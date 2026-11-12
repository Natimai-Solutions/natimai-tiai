"""Reading and writing a poste's journal."""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import AfterValidator
from sqlalchemy import func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.intervention.models import Intervention, InterventionKind
from app.features.machine.models import Machine


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


# How far ahead of the server's clock a date may be: a workstation a minute
# fast is not a typo. Beyond, it is refused (audit B06).
FUTURE_TOLERANCE = timedelta(minutes=5)


def not_in_the_future(value: datetime) -> datetime:
    """A journal entry happened, it is not planned: a date in the future
    would push the poste's maintenance due date out of reach, with nothing to
    bring it back (audit B06)."""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if aware > utcnow() + FUTURE_TOLERANCE:
        raise ValueError("la date ne peut pas être dans le futur")
    return value


# A request field holding when something was done.
PastDatetime = Annotated[datetime, AfterValidator(not_in_the_future)]


async def recompute_last_maintenance(
    session: AsyncSession, machine_ids: Iterable[uuid.UUID]
) -> None:
    """Set each poste's ``last_maintenance_at`` to its latest maintenance
    entry in the journal — NULL when there is none any more. Called after any
    change to the journal, so that deleting or redating an entry moves the
    due date with it (audit B06, B17). Flushes, does not commit."""
    ids = list(set(machine_ids))
    if not ids:
        return
    await session.flush()
    latest = (
        select(func.max(col(Intervention.performed_at)))
        .where(col(Intervention.machine_id) == col(Machine.id))
        .where(col(Intervention.kind) == InterventionKind.MAINTENANCE.value)
        .scalar_subquery()
    )
    await session.exec(
        update(Machine)
        .where(col(Machine.id).in_(ids))
        .where(col(Machine.last_maintenance_at).is_distinct_from(latest))
        .values(last_maintenance_at=latest, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    # The rows in the session still hold the old value: read them again.
    for machine_id in ids:
        machine = await session.get(Machine, machine_id)
        if machine is not None:
            await session.refresh(machine, ["last_maintenance_at", "updated_at"])
