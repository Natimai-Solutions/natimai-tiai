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
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
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
    if not _SHA256.match(sha256):
        raise ValueError("not a sha256")
    return root() / sha256


async def save(upload: UploadFile, max_bytes: int) -> Stored:
    """Stream an upload to the store, hashing as it goes. A temporary file in
    the same directory, renamed once complete: a half-written file never sits
    under a hash it does not have."""
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
        if final.exists():
            os.unlink(tmp_name)
        else:
            os.replace(tmp_name, final)
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
    return [p.name for p in root().iterdir() if _SHA256.match(p.name) and p.is_file()]


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
