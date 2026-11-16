"""deploy/backup/backup.sh: what a backup cycle writes, encrypts and purges.

The script itself is run, unmodified, on a scratch folder (``BACKUP_DIR``),
with a fake ``pg_dump`` and a ``PATH`` holding only the tools it may call:
the test holds the lines the container runs, not a copy of them. It runs
under ``sh`` (dash here) and, when available, under busybox ``sh`` with
busybox's own ``find``, ``stat``, ``du``… — the shell and tools of the
``postgres:16-alpine`` container. The script loops forever (``sleep 86400``,
a builtin in busybox ash): a run is stopped once it prints the line that
closes a cycle.
"""

import os
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
: > "$FAKE_PG_DUMP_CALLED"
if [ -n "${FAKE_PG_DUMP_FAIL:-}" ]; then
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
"""

# Tools backup.sh calls (besides pg_dump and age), and the fake pg_dump's own.
TOOLS = ["basename", "cat", "chmod", "cut", "date", "du", "find", "mv", "rm"]
TOOLS += ["sleep", "stat"]

DAILY = "tiai-20260101-010203"
OLD_DAILY = [f"{DAILY}.dump", f"{DAILY}.dump.age"]  # purged after a good dump
KEPT = [
    "tiai-avant-operation.dump",  # a manual dump (DEPLOYMENT.md)
    "tiai-avant-operation.dump.age",  # the same, encrypted by hand
    "tiai-2026-copie.dump",  # another manual name
    f"sub/{DAILY}.dump",  # put away in a sub-folder
    f"sub/{DAILY}.dump.age",
    f"{DAILY}.dump.bak",  # not a dump name
    f"{DAILY}.dump.age.bak",
    "tiai-20261116-010203.dump.age",  # recent
    ".tiai-20261116-010203.dump.age.partial",  # in progress elsewhere: < 1 h
]
STALE_PARTIAL = ".tiai-20260101-010203.dump.age.partial"  # > 1 h: removed

SHELLS = [pytest.param("sh", id="sh")]
if shutil.which("busybox"):
    SHELLS.append(pytest.param("busybox", id="busybox"))

needs_age = pytest.mark.skipif(
    not (shutil.which("age") and shutil.which("age-keygen")),
    reason="needs age and age-keygen",
)


def _keypair(folder: Path, name: str) -> tuple[Path, str]:
    key = folder / f"{name}.key"
    subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
    public = subprocess.run(
        ["age-keygen", "-y", str(key)], check=True, capture_output=True, text=True
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
        return [self.folder / f for f in sorted(self.files() - before)]


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
        when = old if DAILY in name else time.time()
        if name == STALE_PARTIAL:
            when = two_hours
        os.utime(path, (when, when))
    return folder


def run_script(shell, tmp_path, folder, *, recipient=None, with_age=True, fail=False):
    """One cycle of backup.sh: returns once it exits or closes its first
    cycle (``sauvegarde OK`` / ``ECHEC de la sauvegarde``)."""
    bindir = tmp_path / f"bin-{shell}"
    bindir.mkdir(exist_ok=True)
    for tool in TOOLS:
        target = shutil.which("busybox") if shell == "busybox" else shutil.which(tool)
        assert target, tool
        link = bindir / tool
        if not link.exists():
            link.symlink_to(target)
    if with_age and shutil.which("age") and not (bindir / "age").exists():
        (bindir / "age").symlink_to(shutil.which("age"))
    pg_dump = bindir / "pg_dump"
    pg_dump.write_text(FAKE_PG_DUMP)
    pg_dump.chmod(0o755)
    data = tmp_path / "dump-data"
    data.write_bytes(DUMP)

    env = {
        "PATH": str(bindir),
        "TMPDIR": str(tmp_path),
        "POSTGRES_USER": "tiai",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "tiai",
        "BACKUP_KEEP_DAYS": "14",
        "BACKUP_DIR": str(folder),
        "FAKE_PG_DUMP_DATA": str(data),
        "FAKE_PG_DUMP_CALLED": str(tmp_path / "pg_dump-called"),
    }
    if recipient is not None:
        env["BACKUP_ENCRYPT_RECIPIENT"] = recipient
    if fail:
        env["FAKE_PG_DUMP_FAIL"] = "1"
    command = [shutil.which("busybox"), "sh"] if shell == "busybox" else ["sh"]
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


@needs_age
@pytest.mark.parametrize("shell", SHELLS)
def test_a_failed_encrypted_dump_writes_and_purges_nothing(shell, tmp_path, backups):
    _, public = _keypair(tmp_path, "admin")
    run = run_script(shell, tmp_path, backups, recipient=public, fail=True)
    assert "ECHEC de la sauvegarde" in run.stderr, run.stderr
    assert "sauvegarde OK" not in run.stdout
    assert (tmp_path / "pg_dump-called").exists()
    _assert_nothing_touched(run)  # neither .dump.age nor .partial; no purge
    assert not list(tmp_path.glob("tiai-backup.*"))  # failure flag cleaned up


@pytest.mark.parametrize("shell", SHELLS)
def test_a_failed_clear_dump_writes_and_purges_nothing(shell, tmp_path, backups):
    run = run_script(shell, tmp_path, backups, fail=True)
    assert "ECHEC de la sauvegarde" in run.stderr, run.stderr
    _assert_nothing_touched(run)


@pytest.mark.parametrize("shell", SHELLS)
def test_the_script_parses(shell):
    command = [shutil.which("busybox"), "sh"] if shell == "busybox" else ["sh"]
    subprocess.run([*command, "-n", str(SCRIPT)], check=True)
