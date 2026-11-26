"""deploy/backup/backup.sh: what a backup cycle writes, encrypts and purges.

The script itself is run, unmodified, on a scratch folder (``BACKUP_DIR``),
with a fake ``pg_dump`` and a ``PATH`` holding only the tools it may call:
the test holds the lines the container runs, not a copy of them. It runs
under ``sh`` (dash here) and, when available, under busybox ``sh`` with
busybox's own ``find``, ``stat``, ``du``… — the shell and tools of the
``postgres:16-alpine`` container. The script loops forever (``sleep 86400``,
a builtin in busybox ash): a run is stopped once it prints the line that
closes a cycle.

On a developer's machine the encryption tests are skipped without ``age``, the
busybox variants without ``busybox``. Not in CI (``CI`` set, as GitHub Actions
does): there a missing tool fails the tests that need it — a workflow that
lost its install step would otherwise report the encryption as tested when
none of it ran.
"""

import os
import re
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "backup" / "backup.sh"

# What the fake pg_dump writes: a custom-format dump starts with PGDMP.
DUMP = b"PGDMP fake custom-format dump \x00\x01\x02\xff" * 64

FAKE_PG_DUMP = """#!/bin/sh
# Stands in for pg_dump: records its call, writes DUMP to -f or stdout.
# FAKE_PG_DUMP_FAIL: `start` fails before writing anything, `midway` after
# having written the dump (the server dropping the connection), `killed`
# dies of a SIGKILL after having written it (the kernel short of memory).
: > "$FAKE_PG_DUMP_CALLED"
if [ "${FAKE_PG_DUMP_FAIL:-}" = start ]; then
  echo "pg_dump: error: connection to server failed" >&2
  exit 1
fi
out=""
while [ $# -gt 0 ]; do
  [ "$1" = -f ] && out="$2"
  shift
done
if [ -n "$out" ]; then cat "$FAKE_PG_DUMP_DATA" > "$out"
else cat "$FAKE_PG_DUMP_DATA"; fi
if [ "${FAKE_PG_DUMP_FAIL:-}" = midway ]; then
  echo "pg_dump: error: server closed the connection unexpectedly" >&2
  exit 1
fi
if [ "${FAKE_PG_DUMP_FAIL:-}" = killed ]; then kill -KILL $$; fi
"""

FAKE_AGE = """#!/bin/sh
# Stands in for an age that accepts the recipients (the script's check before
# any dump) and fails while encrypting the dump: the backup disk filling up.
out=""
while [ $# -gt 0 ]; do
  [ "$1" = -o ] && out="$2"
  shift
done
if [ -z "$out" ]; then cat > /dev/null; exit 0; fi
head -c 100 > "$out"
cat > /dev/null
echo "age: error: write: no space left on device" >&2
exit 1
"""

FAKE_PSQL = """#!/bin/sh
# Stands in for psql: records its arguments, then answers FAKE_PSQL_ROWS
# (the attachments the database references), or fails as a database that
# cannot say (`fail`: the table not created yet, the server unreachable).
printf '%s\\n' "$@" > "$FAKE_PSQL_CALLED"
if [ "$FAKE_PSQL_ROWS" = fail ]; then
  echo 'psql: error: relation "intervention_attachments" does not exist' >&2
  exit 1
fi
echo "$FAKE_PSQL_ROWS"
"""

# Tools backup.sh calls (besides pg_dump and age), and the fake pg_dump's own.
TOOLS = ["basename", "cat", "chmod", "cut", "date", "du", "find", "mv", "rm"]
TOOLS += ["sleep", "stat", "head", "cp", "mkdir", "touch"]

DAILY = "tiai-20260101-010203"
OLD_DAILY = [f"{DAILY}.dump", f"{DAILY}.dump.age"]  # purged after a good dump
# Manual dumps, as old as the daily ones the cycle purges: what keeps them is
# their name, not their age.
OLD_MANUAL = [
    "tiai-avant-operation.dump",  # a manual dump (DEPLOYMENT.md)
    "tiai-avant-operation.dump.age",  # the same, encrypted by hand
    "tiai-2026-copie.dump",  # another manual name
    "tiai-20260101-0102030.dump",  # one digit too many: not the script's
]
KEPT = [
    *OLD_MANUAL,
    f"sub/{DAILY}.dump",  # put away in a sub-folder
    f"sub/{DAILY}.dump.age",
    f"{DAILY}.dump.bak",  # not a dump name
    f"{DAILY}.dump.age.bak",
    "tiai-20261116-010203.dump.age",  # recent
    ".tiai-20261116-010203.dump.age.partial",  # in progress elsewhere: < 1 h
]
STALE_PARTIAL = ".tiai-20260101-010203.dump.age.partial"  # > 1 h: removed


def skip_without(*tools: str, environ=os.environ, which=shutil.which) -> bool:
    """Whether the tests needing ``tools`` are skipped: only when one is
    missing, and never in CI — there they run, and fail on the missing tool."""
    return not all(which(tool) for tool in tools) and not environ.get("CI")


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.fail(
            f"{name} is not installed, and CI is set: the tests of backup.sh "
            "and of the documented restore that need it are run there, not "
            f"skipped — install the package providing {name} in the workflow's "
            "step for the backup tests' tools (.github/workflows/ci.yml)"
        )
    return path


SHELLS = [pytest.param("sh", id="sh")]
if not skip_without("busybox"):
    SHELLS.append(pytest.param("busybox", id="busybox"))

needs_age = pytest.mark.skipif(
    skip_without("age", "age-keygen"), reason="needs age and age-keygen"
)


def test_a_missing_tool_is_a_skip_at_home_and_an_error_in_ci():
    def nothing(tool):
        return None

    def everything(tool):
        return f"/usr/bin/{tool}"

    assert skip_without("age", environ={}, which=nothing) is True
    assert skip_without("age", environ={"CI": ""}, which=nothing) is True
    assert skip_without("age", environ={"CI": "true"}, which=nothing) is False
    assert skip_without("age", environ={}, which=everything) is False
    # One of two is not enough.
    half = {"age": "/usr/bin/age"}.get
    assert skip_without("age", "age-keygen", environ={}, which=half) is True


def _keypair(folder: Path, name: str) -> tuple[Path, str]:
    key = folder / f"{name}.key"
    keygen = _tool("age-keygen")
    subprocess.run([keygen, "-o", str(key)], check=True, capture_output=True)
    public = subprocess.run(
        [keygen, "-y", str(key)], check=True, capture_output=True, text=True
    ).stdout.strip()
    return key, public


class Run:
    def __init__(self, returncode: int, stdout: str, stderr: str, folder: Path):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.folder = folder

    def files(self) -> set[str]:
        return {
            str(p.relative_to(self.folder))
            for p in self.folder.rglob("*")
            if p.is_file() or p.is_symlink()
        }

    def new_dumps(self) -> list[Path]:
        before = set(OLD_DAILY) | set(KEPT) | {STALE_PARTIAL}
        return [
            self.folder / f
            for f in sorted(self.files() - before)
            if not f.startswith("attachments/")
        ]

    def copies(self) -> dict[str, bytes]:
        """The attachments' copy: name → content."""
        copy = self.folder / "attachments"
        if not copy.exists():
            return {}
        return {p.name: p.read_bytes() for p in copy.iterdir()}


@pytest.fixture
def backups(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir(mode=0o755)
    old = time.time() - 30 * 86400
    two_hours = time.time() - 2 * 3600
    for name in OLD_DAILY + KEPT + [STALE_PARTIAL]:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        path.chmod(0o644)
        when = old if DAILY in name or name in OLD_MANUAL else time.time()
        if name == STALE_PARTIAL:
            when = two_hours
        os.utime(path, (when, when))
    return folder


def run_script(
    shell,
    tmp_path,
    folder,
    *,
    recipient=None,
    with_age=True,
    fail=None,
    tmpdir=None,
    age_fails=False,
    attachments=None,
    cp_fails=False,
    db_rows=None,
):
    """One cycle of backup.sh: returns once it exits or closes its first
    cycle (``sauvegarde OK`` / ``ECHEC de la sauvegarde``). ``fail`` is how
    the fake pg_dump fails (``FAKE_PG_DUMP``); ``tmpdir`` the script's
    ``TMPDIR`` when it is not the test's folder; ``age_fails`` puts
    ``FAKE_AGE`` in place of age; ``attachments`` the attachments volume
    (absent unless given); ``cp_fails`` a ``cp`` that always fails;
    ``db_rows`` what ``FAKE_PSQL`` answers (no psql unless given)."""
    bindir = tmp_path / f"bin-{shell}"
    bindir.mkdir(exist_ok=True)
    for tool in TOOLS:
        target = _tool("busybox") if shell == "busybox" else shutil.which(tool)
        assert target, tool
        link = bindir / tool
        if tool == "cp" and cp_fails:
            link.unlink(missing_ok=True)
            link.write_text(
                "#!/bin/sh\necho 'cp: No space left on device' >&2\nexit 1\n"
            )
            link.chmod(0o755)
        elif not link.exists():
            link.symlink_to(target)
    if age_fails:
        (bindir / "age").write_text(FAKE_AGE)
        (bindir / "age").chmod(0o755)
    elif with_age and shutil.which("age") and not (bindir / "age").exists():
        (bindir / "age").symlink_to(shutil.which("age"))
    pg_dump = bindir / "pg_dump"
    pg_dump.write_text(FAKE_PG_DUMP)
    pg_dump.chmod(0o755)
    psql = bindir / "psql"
    psql.unlink(missing_ok=True)
    if db_rows is not None:
        psql.write_text(FAKE_PSQL)
        psql.chmod(0o755)
    data = tmp_path / "dump-data"
    data.write_bytes(DUMP)

    env = {
        "PATH": str(bindir),
        "TMPDIR": str(tmpdir or tmp_path),
        "POSTGRES_USER": "tiai",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "tiai",
        "BACKUP_KEEP_DAYS": "14",
        "BACKUP_DIR": str(folder),
        "BACKUP_ATTACHMENTS_DIR": str(attachments or tmp_path / "no-attachments"),
        "FAKE_PG_DUMP_DATA": str(data),
        "FAKE_PG_DUMP_CALLED": str(tmp_path / "pg_dump-called"),
        "FAKE_PSQL_ROWS": str(db_rows),
        "FAKE_PSQL_CALLED": str(tmp_path / "psql-called"),
    }
    if recipient is not None:
        env["BACKUP_ENCRYPT_RECIPIENT"] = recipient
    if fail:
        env["FAKE_PG_DUMP_FAIL"] = fail
    command = [_tool("busybox"), "sh"] if shell == "busybox" else ["sh"]
    out, err = tmp_path / "stdout", tmp_path / "stderr"
    with out.open("wb") as o, err.open("wb") as e:
        proc = subprocess.Popen(
            [*command, str(SCRIPT)],
            env=env,
            stdout=o,
            stderr=e,
            start_new_session=True,
            executable=shutil.which(command[0]),
        )
        deadline = time.monotonic() + 30
        try:
            while proc.poll() is None:
                text = out.read_text() + err.read_text()
                if "sauvegarde OK" in text or "ECHEC de la sauvegarde" in text:
                    break
                assert time.monotonic() < deadline, text
                time.sleep(0.05)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            returncode = proc.wait()
    return Run(returncode, out.read_text(), err.read_text(), folder)


def _assert_cycle_kept_and_purged(run: Run) -> None:
    files = run.files()
    for name in OLD_DAILY:
        assert name not in files, f"{name} should be purged"
    assert STALE_PARTIAL not in files
    for name in KEPT:
        assert name in files, f"{name} should be kept"


def _assert_nothing_touched(run: Run) -> None:
    files = run.files()
    for name in OLD_DAILY + KEPT:
        assert name in files, f"{name} should be kept"
    assert run.new_dumps() == [], run.new_dumps()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("shell", SHELLS)
def test_a_clear_dump_without_recipient(shell, tmp_path, backups):
    run = run_script(shell, tmp_path, backups)
    assert "sauvegarde OK : tiai-" in run.stdout, run.stderr
    assert "chiffrée" not in run.stdout
    [dump] = run.new_dumps()
    assert dump.name.startswith("tiai-") and dump.name.endswith(".dump")
    assert dump.read_bytes() == DUMP
    assert _mode(dump) == 0o600
    assert _mode(backups) == 0o700
    # Existing dumps are tightened too.
    assert _mode(backups / "tiai-avant-operation.dump") == 0o600
    assert _mode(backups / "tiai-avant-operation.dump.age") == 0o600
    _assert_cycle_kept_and_purged(run)


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
def test_an_encrypted_dump_decrypts_with_each_private_key(shell, tmp_path, backups):
    key1, public1 = _keypair(tmp_path, "admin")
    key2, public2 = _keypair(tmp_path, "coffre")
    run = run_script(shell, tmp_path, backups, recipient=f" {public1}  {public2} ")
    assert "sauvegarde OK : tiai-" in run.stdout, run.stderr
    assert ", chiffrée)" in run.stdout
    [dump] = run.new_dumps()  # no clear .dump, no .partial left
    assert dump.name.endswith(".dump.age"), dump.name
    assert _mode(dump) == 0o600
    content = dump.read_bytes()
    assert content.startswith(b"age-encryption.org/v1\n")
    assert b"PGDMP" not in content
    for key in (key1, key2):
        clear = subprocess.run(
            ["age", "-d", "-i", str(key), str(dump)], check=True, capture_output=True
        ).stdout
        assert clear == DUMP
    _assert_cycle_kept_and_purged(run)


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "recipient, message",
    [
        # Checksum wrong: only age can tell.
        ("age1" + "q" * 58, "refusé par age"),
        ("age1bogus", "refusé par age"),
        ("not-a-key", "n'est pas une clé publique age"),
        ("age1abc*", "n'est pas une clé publique age"),
        ("AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ", "clé PRIVÉE"),
    ],
)
def test_an_unusable_recipient_stops_before_any_dump(
    shell, tmp_path, backups, recipient, message
):
    run = run_script(shell, tmp_path, backups, recipient=recipient)
    assert run.returncode == 1
    assert message in run.stderr, run.stderr
    assert "aucun dump écrit" in run.stderr
    assert not (tmp_path / "pg_dump-called").exists()
    _assert_nothing_touched(run)  # nothing written, nothing purged
    assert STALE_PARTIAL in run.files()


@pytest.mark.parametrize("shell", SHELLS)
def test_a_recipient_without_age_stops_before_any_dump(shell, tmp_path, backups):
    public = "age1xnwcytrdwqau9aqc5rtru7t3j9g6qz9ws77t6ndhpujrz7eucgyqr58mwg"
    run = run_script(shell, tmp_path, backups, recipient=public, with_age=False)
    assert run.returncode == 1
    assert "age est introuvable" in run.stderr, run.stderr
    assert not (tmp_path / "pg_dump-called").exists()
    _assert_nothing_touched(run)


FAILURES = ["start", "midway", "killed"]


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("fail", FAILURES)
def test_a_failed_encrypted_dump_writes_and_purges_nothing(
    shell, fail, tmp_path, backups
):
    _, public = _keypair(tmp_path, "admin")
    run = run_script(shell, tmp_path, backups, recipient=public, fail=fail)
    assert "ECHEC de la sauvegarde" in run.stderr, run.stderr
    assert "sauvegarde OK" not in run.stdout
    assert (tmp_path / "pg_dump-called").exists()
    _assert_nothing_touched(run)  # neither .dump.age nor .partial; no purge
    assert not list(tmp_path.glob("tiai-backup.*"))  # no flag file left behind


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("fail", FAILURES)
def test_a_failed_encrypted_dump_is_seen_without_a_writable_tmp(
    shell, fail, tmp_path, backups
):
    """pg_dump's failure used to be noted in a file under /tmp, and success
    was the file's absence: where it could not be written — container in
    `read_only`, Docker's disk full, the very event that cuts the dump — a
    truncated dump was encrypted, promoted, announced « sauvegarde OK », and
    the old ones purged."""
    _, public = _keypair(tmp_path, "admin")
    nowhere = tmp_path / "no-such-folder"
    run = run_script(
        shell, tmp_path, backups, recipient=public, fail=fail, tmpdir=nowhere
    )
    assert "ECHEC de la sauvegarde" in run.stderr, run.stderr
    assert "sauvegarde OK" not in run.stdout
    _assert_nothing_touched(run)


@pytest.mark.parametrize("shell", SHELLS)
def test_an_encryption_that_fails_writes_and_purges_nothing(shell, tmp_path, backups):
    """pg_dump went through and age did not (the backup disk full): no dump
    either. The two outcomes are read apart, and both must be good."""
    public = "age1xnwcytrdwqau9aqc5rtru7t3j9g6qz9ws77t6ndhpujrz7eucgyqr58mwg"
    run = run_script(shell, tmp_path, backups, recipient=public, age_fails=True)
    assert "ECHEC de la sauvegarde" in run.stderr, run.stderr
    assert "sauvegarde OK" not in run.stdout
    assert (tmp_path / "pg_dump-called").exists()
    _assert_nothing_touched(run)


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
def test_an_encrypted_dump_needs_no_writable_tmp(shell, tmp_path, backups):
    """… and a dump that succeeds does not need /tmp either."""
    key, public = _keypair(tmp_path, "admin")
    nowhere = tmp_path / "no-such-folder"
    run = run_script(shell, tmp_path, backups, recipient=public, tmpdir=nowhere)
    assert "sauvegarde OK : tiai-" in run.stdout, run.stderr
    [dump] = run.new_dumps()
    clear = subprocess.run(
        ["age", "-d", "-i", str(key), str(dump)], check=True, capture_output=True
    ).stdout
    assert clear == DUMP
    _assert_cycle_kept_and_purged(run)


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("fail", FAILURES)
def test_a_failed_clear_dump_writes_and_purges_nothing(shell, fail, tmp_path, backups):
    run = run_script(shell, tmp_path, backups, fail=fail)
    assert "ECHEC de la sauvegarde" in run.stderr, run.stderr
    _assert_nothing_touched(run)


@pytest.mark.parametrize("shell", SHELLS)
def test_the_script_parses(shell):
    command = [_tool("busybox"), "sh"] if shell == "busybox" else ["sh"]
    subprocess.run([*command, "-n", str(SCRIPT)], check=True)


# --- Attachments (C11) ------------------------------------------------------------

PHOTO = b"\xff\xd8\xff photo"
SCAN = b"%PDF-1.7 scan"
SHA_PHOTO = "a" * 64
SHA_SCAN = "b" * 64
SHA_GONE = "c" * 64


@pytest.fixture
def volume(tmp_path):
    """The attachments volume: two files named by their hash, and what the
    copy skips — another name, an upload in progress."""
    folder = tmp_path / "attachments-volume"
    folder.mkdir()
    (folder / SHA_PHOTO).write_bytes(PHOTO)
    (folder / SHA_SCAN).write_bytes(SCAN)
    (folder / "README").write_bytes(b"not a hash")
    (folder / ".upload-abc").write_bytes(b"in progress")
    (folder / ("A" * 64)).write_bytes(b"upper case: not one")
    return folder


def _old(path: Path, days: float = 30) -> None:
    when = time.time() - days * 86400
    os.utime(path, (when, when))


@pytest.mark.parametrize("shell", SHELLS)
def test_attachments_are_copied_after_a_good_dump(shell, tmp_path, backups, volume):
    run = run_script(shell, tmp_path, backups, attachments=volume)
    assert "sauvegarde OK" in run.stdout, run.stderr
    assert "pièces jointes : 2 copiée(s), 0 déjà présente(s)" in run.stdout
    assert run.copies() == {SHA_PHOTO: PHOTO, SHA_SCAN: SCAN}
    copy = backups / "attachments"
    assert _mode(copy) == 0o700
    assert {_mode(p) for p in copy.iterdir()} == {0o600}
    _assert_cycle_kept_and_purged(run)


@pytest.mark.parametrize("shell", SHELLS)
def test_a_file_already_copied_is_touched_not_copied_again(
    shell, tmp_path, backups, volume
):
    copy = backups / "attachments"
    copy.mkdir()
    (copy / SHA_PHOTO).write_bytes(b"copied before")
    (copy / f"{SHA_SCAN}.age").write_bytes(b"encrypted before")
    for p in copy.iterdir():
        p.chmod(0o644)
        _old(p, days=20)
    run = run_script(shell, tmp_path, backups, attachments=volume)
    assert "pièces jointes : 0 copiée(s), 2 déjà présente(s)" in run.stdout, run.stderr
    # Under either form: neither copied again nor turned into the other.
    assert run.copies() == {
        SHA_PHOTO: b"copied before",
        f"{SHA_SCAN}.age": b"encrypted before",
    }
    for p in copy.iterdir():
        assert time.time() - p.stat().st_mtime < 3600  # touched: kept
        assert _mode(p) == 0o600


@pytest.mark.parametrize("shell", SHELLS)
def test_a_copy_the_volume_lost_goes_after_the_retention(
    shell, tmp_path, backups, volume
):
    copy = backups / "attachments"
    copy.mkdir()
    (copy / SHA_GONE).write_bytes(b"gone from the volume")
    _old(copy / SHA_GONE, days=30)
    (copy / f"{SHA_GONE[:-1]}d").write_bytes(b"gone, but recently")
    _old(copy / f"{SHA_GONE[:-1]}d", days=3)
    (copy / SHA_PHOTO).write_bytes(PHOTO)
    _old(copy / SHA_PHOTO, days=30)  # still in the volume: touched, kept
    run = run_script(shell, tmp_path, backups, attachments=volume)
    assert "sauvegarde OK" in run.stdout, run.stderr
    assert sorted(run.copies()) == sorted([SHA_PHOTO, SHA_SCAN, f"{SHA_GONE[:-1]}d"])


def _empty_volume_and_old_copies(tmp_path, backups) -> Path:
    """An empty volume, and a copy of three files untouched for 30 days and
    one for 3: the volume lost them, or never had them back."""
    empty = tmp_path / "empty-volume"
    empty.mkdir()
    (empty / "README").write_bytes(b"not a hash")  # not an attachment
    copy = backups / "attachments"
    copy.mkdir()
    (copy / SHA_PHOTO).write_bytes(PHOTO)
    (copy / f"{SHA_SCAN}.age").write_bytes(b"encrypted")
    (copy / f"{SHA_GONE}.tmp").write_bytes(b"interrupted")
    (copy / SHA_GONE).write_bytes(b"recent")
    for p in copy.iterdir():
        _old(p, days=3 if p.name == SHA_GONE else 30)
    return empty


OLD_COPIES = {
    SHA_PHOTO: PHOTO,
    f"{SHA_SCAN}.age": b"encrypted",
    f"{SHA_GONE}.tmp": b"interrupted",
    SHA_GONE: b"recent",
}


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("rows", ["2", "fail", None])
def test_an_empty_volume_the_database_still_needs_purges_no_copy(
    shell, rows, tmp_path, backups
):
    """The volume lost its files while the database still references them
    (``2``: a lost volume, a database restored before « Remettre les pièces
    jointes »), or the database cannot say (``fail``: no table yet, ``None``:
    no psql): the copy is all that is left of the files, nothing goes."""
    empty = _empty_volume_and_old_copies(tmp_path, backups)
    run = run_script(shell, tmp_path, backups, attachments=empty, db_rows=rows)
    assert "sauvegarde OK" in run.stdout, run.stderr
    said = (
        "volume vide, 2 référencée(s)" if rows == "2" else "volume vide et base muette"
    )
    assert said in run.stdout, run.stdout
    assert run.copies() == OLD_COPIES
    _assert_cycle_kept_and_purged(run)  # the dumps' own purge still runs


@pytest.mark.parametrize("shell", SHELLS)
def test_an_empty_volume_nothing_references_purges_as_usual(shell, tmp_path, backups):
    """The last attachment was deleted: the database references none, and the
    copies of the deleted photos (personal data, EXIF) go after the
    retention like any other, instead of staying for ever."""
    empty = _empty_volume_and_old_copies(tmp_path, backups)
    run = run_script(shell, tmp_path, backups, attachments=empty, db_rows="0")
    assert "sauvegarde OK" in run.stdout, run.stderr
    assert "pièces jointes : 0 copiée(s), 0 déjà présente(s)" in run.stdout
    assert run.copies() == {SHA_GONE: b"recent"}
    asked = (tmp_path / "psql-called").read_text().split("\n")
    assert asked[:4] == ["-h", "db", "-U", "tiai"]
    assert "SELECT count(*) FROM intervention_attachments" in asked


def test_the_script_counts_the_attachments_table():
    from app.features.attachment.models import InterventionAttachment

    table = InterventionAttachment.__tablename__
    assert f"SELECT count(*) FROM {table}" in SCRIPT.read_text(encoding="utf-8")


@pytest.mark.parametrize("shell", SHELLS)
def test_a_volume_with_files_does_not_ask_the_database(
    shell, tmp_path, backups, volume
):
    run = run_script(shell, tmp_path, backups, attachments=volume, db_rows="fail")
    assert "sauvegarde OK" in run.stdout, run.stderr
    assert not (tmp_path / "psql-called").exists()


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("fail", FAILURES)
def test_nothing_is_copied_nor_purged_when_the_dump_fails(
    shell, fail, tmp_path, backups, volume
):
    copy = backups / "attachments"
    copy.mkdir()
    (copy / SHA_GONE).write_bytes(b"old")
    _old(copy / SHA_GONE)
    run = run_script(shell, tmp_path, backups, attachments=volume, fail=fail)
    assert "ECHEC de la sauvegarde" in run.stderr, run.stderr
    assert run.copies() == {SHA_GONE: b"old"}


@pytest.mark.parametrize("shell", SHELLS)
def test_a_failed_copy_is_said_and_purges_nothing(shell, tmp_path, backups, volume):
    copy = backups / "attachments"
    copy.mkdir()
    (copy / SHA_GONE).write_bytes(b"old")
    _old(copy / SHA_GONE)
    run = run_script(shell, tmp_path, backups, attachments=volume, cp_fails=True)
    assert "ECHEC de la copie des pièces jointes" in run.stderr, run.stderr
    # The dump itself stands, and closes the cycle.
    assert "sauvegarde OK" in run.stdout
    [dump] = run.new_dumps()
    assert dump.read_bytes() == DUMP
    assert run.copies() == {SHA_GONE: b"old"}  # no .tmp left, nothing purged


@pytest.mark.parametrize("shell", SHELLS)
def test_without_the_volume_the_dump_alone(shell, tmp_path, backups):
    run = run_script(shell, tmp_path, backups)
    assert "non copiées" in run.stdout, run.stderr
    assert "sauvegarde OK" in run.stdout
    assert run.returncode != 1
    assert not (backups / "attachments").exists()
    _assert_cycle_kept_and_purged(run)


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
def test_attachments_are_encrypted_with_the_dumps(shell, tmp_path, backups, volume):
    key, public = _keypair(tmp_path, "admin")
    run = run_script(shell, tmp_path, backups, recipient=public, attachments=volume)
    assert "sauvegarde OK" in run.stdout, run.stderr
    copies = run.copies()
    assert sorted(copies) == [f"{SHA_PHOTO}.age", f"{SHA_SCAN}.age"]
    for name, clear in ((SHA_PHOTO, PHOTO), (SHA_SCAN, SCAN)):
        path = backups / "attachments" / f"{name}.age"
        assert PHOTO not in path.read_bytes() and SCAN not in path.read_bytes()
        assert _mode(path) == 0o600
        out = subprocess.run(
            ["age", "-d", "-i", str(key), str(path)], check=True, capture_output=True
        ).stdout
        assert out == clear


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
def test_turning_encryption_on_replaces_the_clear_copies(
    shell, tmp_path, backups, volume
):
    key, public = _keypair(tmp_path, "admin")
    copy = backups / "attachments"
    copy.mkdir()
    (copy / SHA_PHOTO).write_bytes(PHOTO)
    run = run_script(shell, tmp_path, backups, recipient=public, attachments=volume)
    assert "sauvegarde OK" in run.stdout, run.stderr
    assert sorted(run.copies()) == [f"{SHA_PHOTO}.age", f"{SHA_SCAN}.age"]
    out = subprocess.run(
        ["age", "-d", "-i", str(key), str(copy / f"{SHA_PHOTO}.age")],
        check=True,
        capture_output=True,
    ).stdout
    assert out == PHOTO


# --- The documented restore (DEPLOYMENT.md, « Restaurer ») -----------------

DEPLOYMENT = SCRIPT.parents[2] / "DEPLOYMENT.md"
PG_TOOLS = ("psql", "pg_dump", "pg_restore")
PROBE_APP = "tiai_restore_probe_app"


def documented_restore() -> str:
    """The script DEPLOYMENT.md has the operator run in ``db-backup``: the
    single-quoted ``sh -c`` argument of the first ``docker compose exec
    db-backup`` after the « Restaurer » heading."""
    text = DEPLOYMENT.read_text(encoding="utf-8")
    section = text[text.index("### Restaurer") :]
    start = section.index("docker compose exec db-backup sh -c \\\n")
    body = section[start:].split("'", 2)
    assert len(body) == 3, "the restore command is no longer a sh -c '…'"
    return body[1]


def test_the_documented_restore_resets_the_schema_first():
    script = documented_restore()
    assert "pg_restore" in script
    assert script.index("DROP SCHEMA public CASCADE") < script.index("pg_restore")


@pytest.mark.skipif(
    skip_without(*PG_TOOLS) or not os.environ.get("TIAI_TEST_DATABASE_URL"),
    reason="needs psql, pg_dump, pg_restore and TIAI_TEST_DATABASE_URL",
)
def test_the_documented_restore_puts_back_a_dump_older_than_the_schema(tmp_path):
    """A dump taken before a migration added a table holding a foreign key
    to one of the dump's (0062: intervention_attachments → interventions),
    restored with the documented command after the upgrade: the dump's rows
    come back, the newer table is gone (Alembic recreates it), the objects
    belong to the application role. ``pg_restore --clean`` alone fails here:
    the foreign key keeps the old table, its rows and the new table."""
    from sqlalchemy.engine import make_url

    for tool in PG_TOOLS:
        _tool(tool)
    url = make_url(os.environ["TIAI_TEST_DATABASE_URL"])
    db = f"{url.database}_restore_probe"
    # Roles are the server's, not a database's: one per test database, so
    # that two runs on one server do not drop each other's.
    probe_app = re.sub(r"[^a-z0-9_]", "_", f"{PROBE_APP}_{url.database}".lower())[:63]
    env = {
        "PATH": os.environ["PATH"],
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "",
        "PGPASSWORD": url.password or "",
    }

    def psql(database: str, *sql: str) -> str:
        args = [a for q in sql for a in ("-c", q)]
        return subprocess.run(
            ["psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-d", database] + args,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    psql("postgres", f'DROP DATABASE IF EXISTS "{db}"', f'CREATE DATABASE "{db}"')
    try:
        psql(
            db,
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE "
            f"rolname = '{probe_app}') THEN CREATE ROLE {probe_app}; END IF; END $$",
            f"ALTER SCHEMA public OWNER TO {probe_app}",
            "CREATE TABLE interventions (id int PRIMARY KEY)",
            "INSERT INTO interventions VALUES (1)",
            f"ALTER TABLE interventions OWNER TO {probe_app}",
        )
        dump = tmp_path / "tiai-20260101-010203.dump"
        subprocess.run(
            ["pg_dump", "-d", db, "-Fc", "-f", str(dump)],
            env=env,
            check=True,
            capture_output=True,
        )
        # The upgrade, then a day of work.
        psql(
            db,
            "CREATE TABLE intervention_attachments (id int PRIMARY KEY, "
            "intervention_id int REFERENCES interventions (id))",
            f"ALTER TABLE intervention_attachments OWNER TO {probe_app}",
            "INSERT INTO interventions VALUES (2)",
            "INSERT INTO intervention_attachments VALUES (1, 2)",
        )
        script = (
            documented_restore()
            .replace("-h db", "")
            .replace("/backups/tiai-AAAAMMJJ-HHMMSS.dump", str(dump))
        )
        run_env = {
            **env,
            "POSTGRES_USER": env["PGUSER"],
            "POSTGRES_PASSWORD": env["PGPASSWORD"],
            "POSTGRES_DB": db,
            "POSTGRES_APP_USER": probe_app,
        }
        done = subprocess.run(
            ["sh", "-c", script], env=run_env, capture_output=True, text=True
        )
        assert done.returncode == 0, done.stderr
        assert psql(db, "SELECT id FROM interventions ORDER BY id") == "1\n"
        assert psql(db, "SELECT to_regclass('intervention_attachments')") == "\n"
        owners = psql(
            db,
            "SELECT tableowner FROM pg_tables WHERE schemaname = 'public'",
            "SELECT nspowner::regrole FROM pg_namespace WHERE nspname = 'public'",
        )
        assert owners.split() == [probe_app, probe_app]
    finally:
        psql(
            "postgres",
            f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)',
            f"DROP ROLE IF EXISTS {probe_app}",
        )
