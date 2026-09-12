"""Reading and writing a poste's journal."""

import uuid

from sqlalchemy import func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.intervention.models import Intervention


async def list_for_machine(
    session: AsyncSession, machine_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[list[Intervention], int]:
    """Newest first; ties on the same instant fall back on insertion order."""
    base = select(Intervention).where(col(Intervention.machine_id) == machine_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.exec(
        base.order_by(
            col(Intervention.performed_at).desc(), col(Intervention.created_at).desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.all()), total or 0


async def get(session: AsyncSession, intervention_id: uuid.UUID) -> Intervention | None:
    return await session.get(Intervention, intervention_id)


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """Reattach a poste's journal to another record — a merge. Does not commit."""
    await session.exec(
        update(Intervention)
        .where(col(Intervention.machine_id) == source_id)
        .values(machine_id=target_id)
    )
