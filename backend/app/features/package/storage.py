"""Where package files live: one file per SHA-256 under ``PACKAGES_DIR``.

Content-addressed so that a file is immutable once written — the hash the
manifest names is the file the agent downloads, whatever happens to the
package row afterwards — and so that two packages carrying the same
installer share it.
"""

import hashlib
import os
import re
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

# fullmatch, never match + "$": "$" also accepts a trailing newline (S25).
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


class TooLarge(Exception):
    pass


@dataclass(frozen=True)
class Stored:
    sha256: str
    size: int
    path: Path


def root() -> Path:
    path = Path(settings.PACKAGES_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_for(sha256: str) -> Path:
    if not _SHA256.fullmatch(sha256):
        raise ValueError("not a sha256")
    return root() / sha256


# --- Pins: files stored by an upload not committed yet (audit T09) -------------
#
# ``save`` puts a file under its hash before the request that uploads it has
# committed the row naming it. Until then the store sweep (``crud.sweep_store``,
# run by other requests) would see an orphan and delete it: the upload would
# answer 200 for a file every deployment then gets a 404 on. So ``save`` pins
# the hash before the file can appear under its final name — the reused-blob
# case included — and the upload unpins it once committed or rolled back.
#
# In process memory: the API runs a single uvicorn process (no ``--workers``,
# app/scripts/entrypoint.sh) and the worker never sweeps the store. Serving
# the API from several processes would need this registry in the database.
#
# A sweep checks the database, awaits, then deletes: an upload may pin,
# commit and unpin in between. ``_touched`` records the last pin or unpin of
# each hash on a counter, so that a sweep can tell a hash moved since it
# started looking (``pinned_since``); one entry per distinct file uploaded by
# this process, as small as the store is large.
_pins: Counter[str] = Counter()
_touched: dict[str, int] = {}
_clock = 0


def _touch(sha256: str) -> None:
    global _clock
    _clock += 1
    _touched[sha256] = _clock


def pin(sha256: str) -> None:
    _pins[sha256] += 1
    _touch(sha256)


def unpin(sha256: str) -> None:
    if _pins[sha256] > 1:
        _pins[sha256] -= 1
    else:
        _pins.pop(sha256, None)
    _touch(sha256)


def pin_mark() -> int:
    """Taken by a sweep before it asks the database whether a file is wanted."""
    return _clock


def pinned_since(sha256: str, mark: int) -> bool:
    """Whether an upload holds the file now, or pinned or released it since
    ``mark``: its row may have been committed after the sweep looked."""
    return _pins[sha256] > 0 or _touched.get(sha256, 0) > mark


async def save(upload: UploadFile, max_bytes: int) -> Stored:
    """Stream an upload to the store, hashing as it goes. A temporary file in
    the same directory, renamed once complete: a half-written file never sits
    under a hash it does not have.

    The returned hash is pinned: the caller ``unpin``s it once the row naming
    it is committed or rolled back."""
    directory = root()
    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await upload.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise TooLarge
                digest.update(chunk)
                out.write(chunk)
        sha = digest.hexdigest()
        final = directory / sha
        # Pinned before the file can be seen under its name, and before
        # trusting one already there; nothing awaits between the pin and the
        # rename, so a sweep cannot slip in.
        pin(sha)
        try:
            if final.exists():
                os.unlink(tmp_name)
            else:
                os.replace(tmp_name, final)
        except BaseException:
            unpin(sha)
            raise
        return Stored(sha256=sha, size=size, path=final)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def remove_unreferenced(sha256: str) -> None:
    """Delete a stored file. The caller has checked no package names it."""
    try:
        path_for(sha256).unlink(missing_ok=True)
    except ValueError:
        pass


def stored_shas() -> list[str]:
    """The SHA-256 of every file in the store."""
    return [
        p.name for p in root().iterdir() if _SHA256.fullmatch(p.name) and p.is_file()
    ]


# An upload in progress writes ``.upload-*``; one older than this was left by
# a process that died mid-request.
_STALE_UPLOAD_SECONDS = 24 * 3600


def remove_stale_uploads() -> int:
    removed = 0
    horizon = time.time() - _STALE_UPLOAD_SECONDS
    for p in root().glob(".upload-*"):
        try:
            if p.stat().st_mtime < horizon:
                p.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed
