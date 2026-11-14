"""Package queries, and the one rule that keeps signatures honest."""

import base64
import hashlib
import json
import logging
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import contains, utcnow
from app.features.command.models import Command, CommandStatus
from app.features.inventory.models import MachineSoftware, Software
from app.features.package import manifest, storage
from app.features.package.models import Package, PackageFile, PackageKind

logger = logging.getLogger(__name__)

# A deployment that may still download its files.
OPEN_STATUSES = [
    CommandStatus.PENDING.value,
    CommandStatus.DELIVERED.value,
    CommandStatus.RUNNING.value,
]


async def files_of(session: AsyncSession, package_id: uuid.UUID) -> list[PackageFile]:
    rows = await session.exec(
        select(PackageFile)
        .where(col(PackageFile.package_id) == package_id)
        .order_by(col(PackageFile.name))
    )
    return list(rows.all())


async def files_of_many(
    session: AsyncSession, package_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[PackageFile]]:
    ids = list(package_ids)
    out: dict[uuid.UUID, list[PackageFile]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = await session.exec(
        select(PackageFile)
        .where(col(PackageFile.package_id).in_(ids))
        .order_by(col(PackageFile.name))
    )
    for f in rows.all():
        out[f.package_id].append(f)
    return out


async def refresh_manifest(session: AsyncSession, package: Package) -> bool:
    """Rebuild the manifest of a ``files`` package after any change, and void
    the signature if the bytes moved. Returns whether they did.

    The one place the rule lives: a signature is over *these* bytes, so a
    package whose command line or files changed is no longer what the
    administrator signed — and must not keep looking signed in the console.
    """
    if package.kind != PackageKind.FILES:
        return False
    built = manifest.build(package, await files_of(session, package.id))
    if built == package.manifest:
        return False
    package.manifest = built
    package.signature = None
    package.signature_algorithm = None
    package.signer_certificate = None
    package.signer_thumbprint = None
    package.signer_subject = None
    package.signed_at = None
    package.signed_by = None
    package.updated_at = utcnow()
    session.add(package)
    return True


async def installed_count(
    session: AsyncSession, package: Package, machine_where: Any = None
) -> int | None:
    """Postes whose inventory shows the program, within ``machine_where`` (a
    scope's ``machine_ids_clause`` on ``MachineSoftware.machine_id``). None
    when the package says nothing about how it shows up."""
    needle = (package.detect_name or "").strip()
    if not needle:
        return None
    stmt = (
        select(func.count(func.distinct(col(MachineSoftware.machine_id))))
        .select_from(MachineSoftware)
        .join(Software, col(Software.id) == col(MachineSoftware.software_id))
        .where(contains(col(Software.name), needle))
    )
    if machine_where is not None:
        stmt = stmt.where(machine_where)
    return await session.scalar(stmt) or 0


def fingerprint(package: Package, files: Sequence[PackageFile]) -> str:
    """SHA-256 of everything a poste would run for this package: kind, winget
    identifier and version, manifest, signature and certificate, files. Taken
    when a deployment is queued and compared when it is delivered (audit T08)."""
    document = {
        "kind": package.kind,
        "winget_id": package.winget_id,
        "winget_version": package.winget_version,
        "manifest": _b64(package.manifest),
        "signature": _b64(package.signature),
        "signature_algorithm": package.signature_algorithm,
        "certificate": _b64(package.signer_certificate),
        "files": sorted((f.name, f.sha256, f.size) for f in files),
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _b64(value: bytes | None) -> str | None:
    return base64.b64encode(value).decode("ascii") if value is not None else None


async def sha_in_use(session: AsyncSession, sha256: str) -> bool:
    """Whether a stored file is still wanted: named by a package, or by a
    deployment still open, which downloads what it was queued with (audit
    T09) — a pending one included, it has not downloaded yet."""
    found = await session.exec(
        select(PackageFile.package_id).where(col(PackageFile.sha256) == sha256).limit(1)
    )
    if found.first() is not None:
        return True
    held = await session.exec(
        select(Command.id)
        .where(col(Command.status).in_(OPEN_STATUSES))
        .where(col(Command.package_files).contains([sha256]))
        .limit(1)
    )
    return held.first() is not None


async def sweep_store(session: AsyncSession) -> int:
    """Delete the stored files nothing wants any more (audit S09): replaced or
    removed files once no open deployment needs them, uploads of a request
    that failed halfway. Returns how many went. Never raises: a full or
    read-only volume, or a database error, must not fail the request that
    triggered the sweep — which has committed by then.

    A file an upload in progress holds is kept (``storage.pin``, audit T09).
    And nothing goes when the database knows no package at all: packages are
    retired, never deleted, so a store full of files beside an empty catalogue
    means the wrong or an emptied database, not orphans."""
    removed = 0
    try:
        shas = storage.stored_shas()
        if shas and (await session.exec(select(Package.id).limit(1))).first() is None:
            logger.warning(
                "package store sweep skipped: %d stored file(s) but no package in "
                "the database (wrong or empty database?) — nothing deleted",
                len(shas),
            )
            return 0
        for sha in shas:
            mark = storage.pin_mark()
            if storage.pinned_since(sha, mark):
                continue
            if await sha_in_use(session, sha):
                continue
            # No await from this check to the deletion: an upload cannot pin
            # in between, and one that pinned (or committed and unpinned)
            # while the database was being asked shows here.
            if storage.pinned_since(sha, mark):
                continue
            storage.remove_unreferenced(sha)
            removed += 1
        removed += storage.remove_stale_uploads()
    except OSError:
        logger.exception("package store sweep failed")
    except SQLAlchemyError:
        logger.exception("package store sweep failed")
        try:
            await session.rollback()
        except SQLAlchemyError:
            logger.exception("rollback after the package store sweep failed")
    return removed
