"""Verification requests: the open one of a poste, the list of a person."""

import uuid

from sqlalchemy import func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.check.models import MachineCheck


async def open_for_machine(
    session: AsyncSession, machine_id: uuid.UUID
) -> MachineCheck | None:
    result = await session.exec(
        select(MachineCheck).where(
            col(MachineCheck.machine_id) == machine_id,
            col(MachineCheck.closed_at).is_(None),
        )
    )
    return result.one_or_none()


async def get(session: AsyncSession, check_id: uuid.UUID) -> MachineCheck | None:
    return await session.get(MachineCheck, check_id)


async def list_checks(
    session: AsyncSession,
    *,
    open_only: bool,
    assigned_to_id: uuid.UUID | None,
    unassigned: bool,
    machine_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[MachineCheck], int]:
    """Open first, oldest open first (the one waiting longest is the one to
    do), then closed newest first."""
    stmt = select(MachineCheck)
    if open_only:
        stmt = stmt.where(col(MachineCheck.closed_at).is_(None))
    if assigned_to_id is not None:
        stmt = stmt.where(col(MachineCheck.assigned_to_id) == assigned_to_id)
    if unassigned:
        stmt = stmt.where(col(MachineCheck.assigned_to_id).is_(None))
    if machine_id is not None:
        stmt = stmt.where(col(MachineCheck.machine_id) == machine_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.exec(
        stmt.order_by(
            col(MachineCheck.closed_at).is_not(None),
            col(MachineCheck.closed_at).desc().nulls_last(),
            col(MachineCheck.created_at),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.all()), total or 0


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge: the source's requests follow it onto the kept record. If both
    carry an open one, the source's is closed as superseded rather than
    violating "one open per poste" — the kept record's is the one somebody
    is already looking at. Does not commit."""
    if await open_for_machine(session, target_id) is not None:
        source_open = await open_for_machine(session, source_id)
        if source_open is not None:
            source_open.closed_at = utcnow()
            source_open.closed_by = "system"
            source_open.closing_note = "Fermée par la fusion du poste dans un autre."
            source_open.updated_at = utcnow()
            session.add(source_open)
            await session.flush()
    await session.exec(
        update(MachineCheck)
        .where(col(MachineCheck.machine_id) == source_id)
        .values(machine_id=target_id)
    )
