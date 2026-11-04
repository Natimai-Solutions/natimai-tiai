"""Package queries, and the one rule that keeps signatures honest."""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.inventory.models import MachineSoftware, Software
from app.features.package import manifest
from app.features.package.models import Package, PackageFile, PackageKind


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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        .where(col(Software.name).ilike(f"%{_escape_like(needle)}%", escape="\\"))
    )
    if machine_where is not None:
        stmt = stmt.where(machine_where)
    return await session.scalar(stmt) or 0


async def sha_in_use(session: AsyncSession, sha256: str) -> bool:
    found = await session.exec(
        select(PackageFile.package_id).where(col(PackageFile.sha256) == sha256).limit(1)
    )
    return found.first() is not None
