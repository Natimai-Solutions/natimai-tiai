"""Where attachment files live: one file per SHA-256 under ``ATTACHMENTS_DIR``.

Thin wrappers over ``package/storage.py`` — the same atomic write and the
same sweep of abandoned uploads — given this store's directory, read from
the settings at each call (never at import: the tests redirect it), and the
content sniffing that decides what may be stored.

What may be stored is recognised from the first bytes, never from the
client's ``Content-Type`` nor the file's extension: JPEG, PNG, WebP and PDF.
SVG, HTML, GIF, HEIC and the rest are refused — the server never serves a
file a browser would interpret.
"""

import os
import unicodedata
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import UploadFile

from app.core.config import settings
from app.features.package import storage as _store
from app.features.package.storage import Stored, TooLarge, Unrecognised

__all__ = [
    "TYPES",
    "Stored",
    "TooLarge",
    "Unrecognised",
    "clean_filename",
    "exists",
    "path_for",
    "remove_stale_uploads",
    "remove_unreferenced",
    "save",
    "sniff",
    "store_available",
    "stored_shas",
]

# The types accepted, and the extension a name must end with for each (the
# first one is added when it does not).
TYPES: dict[str, tuple[str, ...]] = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
    "application/pdf": (".pdf",),
}

FILENAME_MAX = 200
DEFAULT_FILENAME = "piece-jointe"


def directory() -> str:
    return settings.ATTACHMENTS_DIR


def sniff(head: bytes) -> str | None:
    """The type the first bytes of a file say, among ``TYPES``; None for
    anything else — an empty file included."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def clean_filename(name: str | None, content_type: str) -> str:
    """The name to store and to download under: the path dropped (POSIX and
    Windows), control and format characters dropped, at most
    ``FILENAME_MAX`` characters, ``piece-jointe`` when nothing is left, and
    an extension saying the recognised type — ``panne.html`` recognised as
    PNG becomes ``panne.html.png``. Quotes, backslashes and semicolons stay:
    the download header is built by Starlette, which escapes them."""
    base = PureWindowsPath(PurePosixPath(name or "").name).name
    base = "".join(c for c in base if not unicodedata.category(c).startswith("C"))
    base = base.strip()
    if base in ("", ".", ".."):
        base = DEFAULT_FILENAME
    extensions = TYPES.get(content_type, ())
    if extensions and not base.lower().endswith(extensions):
        suffix = extensions[0]
        base = base[: FILENAME_MAX - len(suffix)].rstrip() + suffix
    elif len(base) > FILENAME_MAX:
        # Cut before the extension, which is kept.
        stem, dot, ext = base.rpartition(".")
        keep = FILENAME_MAX - len(dot + ext)
        base = (
            stem[:keep].rstrip() + dot + ext
            if dot and keep > 0
            else base[:FILENAME_MAX]
        )
    return base


def store_available() -> bool:
    """Whether an upload may be written: outside ``ENVIRONMENT=local``,
    ``ATTACHMENTS_DIR`` must be a mount point — the ``attachments`` volume.
    Without it a photo would land in the container's own layer and vanish at
    the next ``up --force-recreate``."""
    if settings.ENVIRONMENT == "local":
        return True
    return os.path.ismount(directory())


async def save(
    upload: UploadFile, max_bytes: int, hold: Callable[[str], Awaitable[None]]
) -> Stored:
    """``package.storage.save`` into this store, the first block sniffed:
    ``Unrecognised`` before anything is written for a type not accepted."""
    return await _store.save(
        upload, max_bytes, hold, directory=directory(), sniff=sniff
    )


def path_for(sha256: str) -> Path:
    return _store.path_for(sha256, directory())


def exists(sha256: str) -> bool:
    return _store.exists(sha256, directory())


def remove_unreferenced(sha256: str) -> None:
    _store.remove_unreferenced(sha256, directory())


def stored_shas() -> list[str]:
    return _store.stored_shas(directory())


def remove_stale_uploads() -> int:
    return _store.remove_stale_uploads(directory())
