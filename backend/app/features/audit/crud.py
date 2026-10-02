"""Writing and reading audit entries."""

from datetime import datetime
from typing import Any

from sqlalchemy import delete
from sqlmodel import col, desc, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.audit.models import AuditEntry


def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Queue one audit entry on the caller's transaction.

    Deliberately no commit here (same contract as the outbox's queue_email):
    the entry exists exactly when the action it describes does — an action
    rolled back takes its trace down with it, and a trace is never written for
    something that did not happen.
    """
    session.add(
        AuditEntry(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )


async def list_entries(
    session: AsyncSession,
    *,
    action: str | None = None,
    actor: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditEntry], int]:
    """Newest-first page of the log, optionally filtered.

    ``actor`` is a case-insensitive substring — the console types part of an
    e-mail, not the whole address. ``since`` is inclusive and ``until``
    exclusive, so consecutive periods never count an entry twice.
    """
    filters = []
    if action:
        filters.append(col(AuditEntry.action) == action)
    if actor:
        filters.append(col(AuditEntry.actor).ilike(f"%{_escape_like(actor)}%"))
    if resource_type:
        filters.append(col(AuditEntry.resource_type) == resource_type)
    if resource_id:
        filters.append(col(AuditEntry.resource_id) == resource_id)
    if since is not None:
        filters.append(col(AuditEntry.at) >= since)
    if until is not None:
        filters.append(col(AuditEntry.at) < until)

    total_result = await session.exec(
        select(func.count()).select_from(AuditEntry).where(*filters)
    )
    total = total_result.one()

    result = await session.exec(
        select(AuditEntry)
        .where(*filters)
        .order_by(desc(col(AuditEntry.at)))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.all()), total


async def list_actions(session: AsyncSession) -> list[str]:
    """The action slugs present in the log, sorted — the console's filter.

    Read from the table rather than from a list in code: a slug added by a
    later release, or one no longer written, must stay filterable.
    """
    result = await session.exec(
        select(AuditEntry.action).distinct().order_by(col(AuditEntry.action))
    )
    return list(result.all())


async def purge_before(session: AsyncSession, cutoff: datetime) -> int:
    """Drop the entries recorded before ``cutoff``. Commits; returns the count.

    By age alone, whatever the action: a retention that kept some slugs
    longer than others would be a policy nobody could state in one sentence.
    """
    result = await session.exec(delete(AuditEntry).where(col(AuditEntry.at) < cutoff))
    await session.commit()
    return result.rowcount or 0


def _escape_like(value: str) -> str:
    """Make ``%`` and ``_`` typed by the user match themselves."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
