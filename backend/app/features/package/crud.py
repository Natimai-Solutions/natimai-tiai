"""Package queries, and the one rule that keeps signatures honest."""

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, cast, func, update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import contains, utcnow
from app.features.command import crud as command_crud
from app.features.command.models import Command, CommandStatus, CommandType
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


# What a cancelled installation says in the console (``cancel_pending_installs``).
RETIRED_ERROR = "Paquet retiré : installation annulée"


async def locked(session: AsyncSession, package_id: uuid.UUID) -> Package | None:
    """The package with its row locked (``SELECT … FOR UPDATE``) until the
    transaction ends: what every route that changes a package starts with.

    Two requests changing one package at once would otherwise each rebuild
    the manifest from the files it sees — its own, not the other's — and the
    last commit would keep a manifest missing a file the table holds; two
    uploads of one file name would collide on the primary key. Behind the
    lock the second request reads what the first committed.

    Read again from the database even if the session already holds the row:
    what is locked is what is changed."""
    rows = await session.exec(
        select(Package)
        .where(col(Package.id) == package_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return rows.first()


async def files_named(
    session: AsyncSession, package_id: uuid.UUID, name: str
) -> list[PackageFile]:
    """The files of the package bearing this name, case aside: the one an
    upload replaces — several if rows written before that rule remain."""
    rows = await session.exec(
        select(PackageFile)
        .where(col(PackageFile.package_id) == package_id)
        .where(func.lower(col(PackageFile.name)) == name.lower())
    )
    return list(rows.all())


async def cancel_pending_installs(
    session: AsyncSession, package_id: uuid.UUID, now: datetime
) -> int:
    """Fail the installations of this package no poste has received yet, and
    return how many (audit T08). One statement, on the status as it stands
    when the row is reached: an installation a heartbeat is delivering at
    that moment is left to that heartbeat, which refuses a retired package
    itself. The caller commits."""
    result = await session.exec(
        update(Command)
        .where(col(Command.package_id) == package_id)
        .where(col(Command.type) == CommandType.PACKAGE_INSTALL.value)
        .where(col(Command.status) == CommandStatus.PENDING.value)
        .values(status=CommandStatus.FAILED, error=RETIRED_ERROR, finished_at=now)
    )
    return result.rowcount or 0


# What a pending deployment replaced by a newer one says in the console
# (``supersede_stale_pending``).
SUPERSEDED_ERROR = "Remplacée par un nouveau déploiement"


async def supersede_stale_pending(
    session: AsyncSession,
    *,
    package_id: uuid.UUID,
    command_type: str,
    digest: str,
    machine_ids: Sequence[uuid.UUID],
    now: datetime,
) -> int:
    """Fail the deployments of this package and action still waiting on these
    postes that were queued for another version of it, and return how many.

    Left pending, each would count as « déjà en attente » for the deployment
    being queued — which would then send nothing — and fail at delivery as
    « paquet modifié après la mise en file »: the administrator would have
    redeployed for nothing. One queued for the version as it stands is kept,
    and still counts as already pending. A deployment a poste has received is
    its own: it runs, or fails, to its end. One queued before fingerprints
    existed (no digest) is delivered as the package stands: current too.
    The caller holds the package's lock, and commits."""
    if not machine_ids:
        return 0
    result = await session.exec(
        update(Command)
        .where(col(Command.package_id) == package_id)
        .where(col(Command.type) == command_type)
        .where(col(Command.status) == CommandStatus.PENDING.value)
        .where(col(Command.machine_id).in_(list(machine_ids)))
        .where(col(Command.package_digest).is_not(None))
        .where(col(Command.package_digest) != digest)
        .values(status=CommandStatus.FAILED, error=SUPERSEDED_ERROR, finished_at=now)
    )
    return result.rowcount or 0


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


# --- Held files (audit T09) ----------------------------------------------------
#
# An upload stores a file before the transaction naming it commits, so the
# sweep must not take that file for an orphan. Each stored file has an
# advisory lock in PostgreSQL — seen by every API process, released by the
# database when the transaction holding it ends, a crashed process's
# included, so nothing can stay held for ever. The upload holds it shared
# (``hold_file``) from before the file is under its name until its
# transaction commits or rolls back; uploads do not wait for one another. The
# sweep deletes a file only under the same lock taken exclusive, never
# waiting for it (``_claim_file``), and asks the database again once it holds
# it: the upload that released it had committed by then, and each statement
# sees what was committed before it started. An upload that comes while the
# sweep holds the lock waits, then finds the file deleted or there, and
# stores it again if need be (``storage.save``).

# The two-key form of the advisory locks: this namespace, then the first 32
# bits of the file's hash — two files sharing them only make a sweep skip one
# or an upload wait a moment. "TPKF" in ASCII.
_FILE_LOCK_SPACE = 0x54504B46


def _file_lock(sha256: str) -> tuple[Any, Any]:
    key = int(sha256[:8], 16)
    if key >= 1 << 31:
        key -= 1 << 32
    return cast(_FILE_LOCK_SPACE, Integer), cast(key, Integer)


async def hold_file(session: AsyncSession, sha256: str) -> None:
    """Keep the stored file ``sha256`` from any sweep, in any API process,
    until ``session``'s transaction ends. Waits for a sweep that is deleting
    it. Does not commit."""
    await session.exec(select(func.pg_advisory_xact_lock_shared(*_file_lock(sha256))))


async def _claim_file(session: AsyncSession, sha256: str) -> bool:
    """Lock the stored file ``sha256`` for deletion until ``session``'s
    transaction ends; False, at once, when an upload holds it."""
    claimed = await session.exec(
        select(func.pg_try_advisory_xact_lock(*_file_lock(sha256)))
    )
    return bool(claimed.one())


async def sweep_store(session: AsyncSession) -> int:
    """Delete the stored files nothing wants any more (audit S09): replaced or
    removed files once no open deployment needs them, uploads of a request
    that failed halfway. Returns how many went. Never raises: a full or
    read-only volume, or a database error, must not fail the request that
    triggered the sweep — which has committed by then: the sweep ends the
    session's transaction after each file it deletes, to release its lock.

    A file an upload in progress holds is kept (``hold_file``, audit T09).
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
            if await sha_in_use(session, sha):
                continue
            if not await _claim_file(session, sha):
                continue
            # Asked again under the lock: an upload that held the file until
            # it committed is seen now.
            if not await sha_in_use(session, sha):
                storage.remove_unreferenced(sha)
                removed += 1
            await session.commit()
        removed += storage.remove_stale_uploads()
    except (OSError, SQLAlchemyError):
        logger.exception("package store sweep failed")
        # Also what releases a file the sweep had locked.
        try:
            await session.rollback()
        except SQLAlchemyError:
            logger.exception("rollback after the package store sweep failed")
    return removed


# How often the API process sweeps the store on its own (``sweep_periodically``).
SWEEP_INTERVAL_SECONDS = 3600


async def sweep_periodically(
    session_factory: Callable[[], AsyncSession],
    interval_seconds: float = SWEEP_INTERVAL_SECONDS,
) -> None:
    """Sweep the store every ``interval_seconds``, until cancelled.

    The sweeps the requests trigger — an upload, a verdict, a refusal at
    delivery — miss the files whose last deployment ended without one: it
    expired on a poste that stayed off, or was closed unanswered by the
    worker. On a quiet server those stayed on disk indefinitely. Expired
    deployments are marked first: a pending one past its TTL still holds its
    files until something says it expired. Run in the API process, which has
    the packages volume. Never raises but on cancellation."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with session_factory() as session:
                await command_crud.mark_expired(session)
                await session.commit()
                await sweep_store(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic package store sweep failed")
