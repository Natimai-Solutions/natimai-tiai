"""Where package files live: one file per SHA-256 under ``PACKAGES_DIR``.

Content-addressed so that a file is immutable once written — the hash the
manifest names is the file the agent downloads, whatever happens to the
package row afterwards — and so that two packages carrying the same
installer share it.

Every function takes an optional ``directory``: absent, the store is
``PACKAGES_DIR``, read at each call. The attachments of the journal (C11,
``features/attachment/storage.py``) pass theirs: one code for the atomic
write and the sweep of abandoned uploads, the packages' callers unchanged.
"""

import hashlib
import os
import re
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

# fullmatch, never match + "$": "$" also accepts a trailing newline (S25).
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


class TooLarge(Exception):
    pass


class Unrecognised(Exception):
    """The first bytes of an upload are none of the types ``sniff`` accepts:
    refused before anything is written."""


@dataclass(frozen=True)
class Stored:
    sha256: str
    size: int
    path: Path
    # What ``sniff`` recognised; None when ``save`` was given none.
    content_type: str | None = None


def _base(directory: str | None) -> Path:
    # Read at each call, never at import: the tests redirect the stores.
    return Path(settings.PACKAGES_DIR if directory is None else directory)


def root(directory: str | None = None) -> Path:
    path = _base(directory)
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_for(sha256: str, directory: str | None = None) -> Path:
    if not _SHA256.fullmatch(sha256):
        raise ValueError("not a sha256")
    return root(directory) / sha256


def exists(sha256: str, directory: str | None = None) -> bool:
    """Whether the store holds this file. One ``stat``; creates nothing — it
    is asked for every file of every package the catalogue lists."""
    if not _SHA256.fullmatch(sha256):
        return False
    return (_base(directory) / sha256).is_file()


# --- Held files: stored by an upload not committed yet (audit T09) ------------
#
# ``save`` puts a file under its hash before the request that uploads it has
# committed the row naming it. Until then the store sweep (``crud.sweep_store``,
# run by other requests, in this API process or another) would see an orphan
# and delete it: the upload would answer 200 for a file every deployment then
# gets a 404 on. So ``save`` has the caller hold the hash — a lock in the
# database, until the upload's transaction ends (``crud.hold_file``) — before
# the file can appear under its final name or a blob already there is
# trusted, and the sweep deletes only a file it could lock itself.


async def save(
    upload: UploadFile,
    max_bytes: int,
    hold: Callable[[str], Awaitable[None]],
    *,
    directory: str | None = None,
    sniff: Callable[[bytes], str | None] | None = None,
) -> Stored:
    """Stream an upload to the store, hashing as it goes. A temporary file in
    the same directory, renamed once complete: a half-written file never sits
    under a hash it does not have.

    ``hold`` is awaited with the hash once it is known, before the file is
    put under it or one already there is trusted: it returns once no sweep
    can delete that file until the caller's transaction ends
    (``crud.hold_file``). A sweep that got there first has deleted the file
    or left it by then, and what is there is read after.

    ``sniff``, when given, is called on the first block read (an empty file
    included) and returns the type it recognises, or None: ``Unrecognised``
    is raised then, before any file is created."""
    first = await upload.read(_CHUNK)
    content_type: str | None = None
    if sniff is not None:
        content_type = sniff(first)
        if content_type is None:
            raise Unrecognised
    store = root(directory)
    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=store, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as out:
            chunk = first
            while chunk:
                size += len(chunk)
                if size > max_bytes:
                    raise TooLarge
                digest.update(chunk)
                out.write(chunk)
                chunk = await upload.read(_CHUNK)
        sha = digest.hexdigest()
        final = store / sha
        # Held before the file can be seen under its name, and before
        # trusting one already there.
        await hold(sha)
        if final.exists():
            os.unlink(tmp_name)
        else:
            os.replace(tmp_name, final)
        return Stored(sha256=sha, size=size, path=final, content_type=content_type)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def remove_unreferenced(sha256: str, directory: str | None = None) -> None:
    """Delete a stored file. The caller has checked no package names it."""
    try:
        path_for(sha256, directory).unlink(missing_ok=True)
    except ValueError:
        pass


def stored_shas(directory: str | None = None) -> list[str]:
    """The SHA-256 of every file in the store."""
    return [
        p.name
        for p in root(directory).iterdir()
        if _SHA256.fullmatch(p.name) and p.is_file()
    ]


# An upload in progress writes ``.upload-*``; one older than this was left by
# a process that died mid-request.
_STALE_UPLOAD_SECONDS = 24 * 3600


def remove_stale_uploads(directory: str | None = None) -> int:
    removed = 0
    horizon = time.time() - _STALE_UPLOAD_SECONDS
    for p in root(directory).glob(".upload-*"):
        try:
            if p.stat().st_mtime < horizon:
                p.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed
