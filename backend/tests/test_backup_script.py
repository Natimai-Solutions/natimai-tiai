"""deploy/backup/backup.sh: what the daily purge may delete.

The purge's own ``find`` is read out of the script and run against a scratch
folder, ``-delete`` turned into ``-print``: the test holds the line the
container runs, not a copy of it.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "backup" / "backup.sh"


def _purge_command() -> str:
    """The ``find /backups … -mtime … -delete`` command, continuation lines
    joined."""
    text = SCRIPT.read_text(encoding="utf-8").replace("\\\n", " ")
    found = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("find /backups") and "-mtime" in line
    ]
    assert len(found) == 1, found
    command = found[0].split("||")[0].strip()
    assert command.endswith("-delete"), command
    return command


@pytest.mark.skipif(shutil.which("find") is None, reason="needs find(1)")
def test_the_purge_takes_old_daily_dumps_only(tmp_path):
    old = time.time() - 30 * 86400
    names = [
        "tiai-20260101-010203.dump",  # an old daily dump: purged
        "tiai-avant-operation.dump",  # a manual dump (DEPLOYMENT.md): kept
        "tiai-2026-copie.dump",  # another manual name: kept
        "sub/tiai-20260101-010203.dump",  # put away in a sub-folder: kept
        "tiai-20260101-010203.dump.bak",  # not a dump name: kept
    ]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        os.utime(path, (old, old))
    (tmp_path / "tiai-20261116-010203.dump").write_bytes(b"x")  # recent: kept

    command = _purge_command()
    command = re.sub(r"-delete$", "-print", command).replace(
        "find /backups", f"find {tmp_path}", 1
    )
    result = subprocess.run(
        ["sh", "-c", command],
        env={**os.environ, "KEEP_DAYS": "14"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split() == [str(tmp_path / "tiai-20260101-010203.dump")]


def test_the_script_parses():
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)
