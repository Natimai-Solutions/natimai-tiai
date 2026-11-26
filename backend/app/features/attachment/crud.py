"""Attachment queries, the quota and the sweep of the store (C11).

Modelled on ``package/crud.py``: an upload holds the file it stores against
any sweep until its transaction ends (``hold_file``), a sweep deletes a file
only under the same lock taken exclusive without waiting (``_claim_file``),
and asks the database again once it holds it. The locks live in their own
space: holding a package file never stops the sweep of an attachment whose
hash starts alike, nor the other way round.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Integer, cast, delete, func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.attachment import storage
from app.features.attachment.models import InterventionAttachment
from app.features.machine.models import Machine

logger = logging.getLogger(__name__)

# Attachments per line of the journal: a line is not an album.
MAX_PER_INTERVENTION = 10

# Serialises the uploads from the recount to the insertion: the count per
# line and the quota are read and written under it. "tiai-att" in ASCII;
# distinct from ``counter/quota.py:QUOTA_LOCK`` and
# ``user/crud.py:ACCOUNT_MANAGEMENT_LOCK``.
ATTACHMENT_QUOTA_LOCK = 0x746961692D617474

# The two-key form of the per-file advisory locks: this namespace, then the
# first 32 bits of the hash. "TATT" in ASCII; the packages' is "TPKF".
_FILE_LOCK_SPACE = 0x54415454


def _file_lock(sha256: str) -> tuple[Any, Any]:
    key = int(sha256[:8], 16)
    if key >= 1 << 31:
        key -= 1 << 32
    return cast(_FILE_LOCK_SPACE, Integer), cast(key, Integer)


async def hold_file(session: AsyncSession, sha256: str) -> None:
    """Keep the stored file ``sha256`` from any sweep until ``session``'s
    transaction ends. Waits for a sweep that is deleting it. Does not
    commit."""
    await session.exec(select(func.pg_advisory_xact_lock_shared(*_file_lock(sha256))))


async def _claim_file(session: AsyncSession, sha256: str) -> bool:
    """Lock the stored file ``sha256`` for deletion until ``session``'s
    transaction ends; False, at once, when an upload holds it."""
    claimed = await session.exec(
        select(func.pg_try_advisory_xact_lock(*_file_lock(sha256)))
    )
    return bool(claimed.one())


async def lock_quota(session: AsyncSession) -> None:
    """Take ``ATTACHMENT_QUOTA_LOCK`` until the transaction ends."""
    await session.exec(
        select(func.pg_advisory_xact_lock(cast(ATTACHMENT_QUOTA_LOCK, BigInteger)))
    )


async def sha_in_use(session: AsyncSession, sha256: str) -> bool:
    """Whether a row of ``intervention_attachments`` names the file."""
    found = await session.exec(
        select(InterventionAttachment.id)
        .where(col(InterventionAttachment.sha256) == sha256)
        .limit(1)
    )
    return found.first() is not None


async def count_for(session: AsyncSession, intervention_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(InterventionAttachment)
            .where(col(InterventionAttachment.intervention_id) == intervention_id)
        )
        or 0
    )


async def named_on(
    session: AsyncSession, intervention_id: uuid.UUID, sha256: str
) -> bool:
    """Whether this line already has this file."""
    found = await session.exec(
        select(InterventionAttachment.id)
        .where(col(InterventionAttachment.intervention_id) == intervention_id)
        .where(col(InterventionAttachment.sha256) == sha256)
        .limit(1)
    )
    return found.first() is not None


async def used_bytes(session: AsyncSession) -> int:
    """The size of the distinct files the journal names: a file shared by
    two lines counts once."""
    per_file = (
        select(func.max(col(InterventionAttachment.size)).label("size"))
        .group_by(col(InterventionAttachment.sha256))
        .subquery()
    )
    return int(await session.scalar(select(func.sum(per_file.c.size))) or 0)


async def of_interventions(
    session: AsyncSession, intervention_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[InterventionAttachment]]:
    """The attachments of these lines, oldest first, in one query."""
    ids = list(intervention_ids)
    out: dict[uuid.UUID, list[InterventionAttachment]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = await session.exec(
        select(InterventionAttachment)
        .where(col(InterventionAttachment.intervention_id).in_(ids))
        .order_by(
            col(InterventionAttachment.created_at), col(InterventionAttachment.id)
        )
    )
    for a in rows.all():
        out[a.intervention_id].append(a)
    return out


async def shas_of(
    session: AsyncSession, intervention_ids: Iterable[uuid.UUID]
) -> list[str]:
    """The file of each attachment of these lines — one entry per
    attachment, so its length is how many go with the lines."""
    ids = list(intervention_ids)
    if not ids:
        return []
    rows = await session.exec(
        select(col(InterventionAttachment.sha256)).where(
            col(InterventionAttachment.intervention_id).in_(ids)
        )
    )
    return list(rows.all())


async def _remove_if_orphan(session: AsyncSession, sha: str) -> bool:
    """Delete one stored file if nothing names it and no upload holds it.
    Commits (which releases the claim)."""
    if await sha_in_use(session, sha):
        return False
    if not await _claim_file(session, sha):
        return False
    removed = False
    # Asked again under the lock: an upload that held the file until it
    # committed is seen now.
    if not await sha_in_use(session, sha):
        storage.remove_unreferenced(sha)
        removed = True
    await session.commit()
    return removed


async def discard_if_orphan(session: AsyncSession, sha256: str) -> bool:
    """Delete the stored file ``sha256`` at once if nothing names it any
    more: after an upload refused, after an attachment, a line or a visit
    deleted. ``session`` holds no file at that point (called after its
    commit or rollback). Never raises; returns whether the file went."""
    try:
        return await _remove_if_orphan(session, sha256)
    except (OSError, SQLAlchemyError):
        logger.exception("attachment discard failed")
        try:
            await session.rollback()
        except SQLAlchemyError:
            logger.exception("rollback after the attachment discard failed")
        return False


async def sweep_store(session: AsyncSession) -> int:
    """Delete the stored files no attachment names any more, and uploads
    abandoned midway. Returns how many went. Never raises; ends the session's
    transaction after each file it deletes, so ``session`` must hold no file
    itself (``hold_file``) when called.

    Nothing goes when the database knows no poste at all while the store has
    files: that is a new or an emptied database, not orphans."""
    removed = 0
    try:
        shas = storage.stored_shas()
        if shas and (await session.exec(select(Machine.id).limit(1))).first() is None:
            logger.warning(
                "attachment store sweep skipped: %d stored file(s) but no poste in "
                "the database (wrong or empty database?) — nothing deleted",
                len(shas),
            )
            return 0
        for sha in shas:
            if await _remove_if_orphan(session, sha):
                removed += 1
        removed += storage.remove_stale_uploads()
    except (OSError, SQLAlchemyError):
        logger.exception("attachment store sweep failed")
        try:
            await session.rollback()
        except SQLAlchemyError:
            logger.exception("rollback after the attachment store sweep failed")
    return removed


# How often the API process sweeps the store on its own.
SWEEP_INTERVAL_SECONDS = 3600


async def sweep_attachments_periodically(
    session_factory: Callable[[], AsyncSession],
    interval_seconds: float | None = None,
) -> None:
    """Sweep the store every ``interval_seconds`` until cancelled: what
    removes the files of the rows the worker's retention purge deleted — the
    worker has no access to the volume. Run in the API process. Never raises
    but on cancellation."""
    if interval_seconds is None:
        interval_seconds = SWEEP_INTERVAL_SECONDS
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with session_factory() as session:
                await sweep_store(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic attachment store sweep failed")


_PURGE_BATCH = 1000


async def purge_before(session: AsyncSession, cutoff: datetime) -> int:
    """Delete the attachment rows created before ``cutoff``, by batches, and
    return how many. The files are left to the API's sweep. Commits."""
    total = 0
    while True:
        batch = (
            select(col(InterventionAttachment.id))
            .where(col(InterventionAttachment.created_at) < cutoff)
            .limit(_PURGE_BATCH)
        )
        result = await session.exec(
            delete(InterventionAttachment).where(
                col(InterventionAttachment.id).in_(batch.scalar_subquery())
            )
        )
        await session.commit()
        count = result.rowcount or 0
        total += count
        if count < _PURGE_BATCH:
            return total
