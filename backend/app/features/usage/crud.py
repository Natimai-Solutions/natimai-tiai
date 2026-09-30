"""Writing the hourly counters, moving them on a merge, purging the old ones."""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.usage.models import SECONDS_PER_HOUR, MachineUptime


def _upsert_adding(stmt: Insert) -> Insert:
    """ON CONFLICT on the (poste, hour) key: add, capped at a full hour.

    Adding rather than replacing, because two writers may credit the same
    hour — consecutive heartbeats, or a merge folding one record into
    another. Capped rather than failing on the CHECK: two records of one poste
    overlapping in time must not abort a merge, and an hour cannot hold more
    than an hour whatever was double-counted.
    """
    table = MachineUptime.__table__  # type: ignore[attr-defined]
    return stmt.on_conflict_do_update(
        index_elements=[table.c.machine_id, table.c.hour],
        set_={
            "seconds_on": func.least(
                SECONDS_PER_HOUR, table.c.seconds_on + stmt.excluded.seconds_on
            )
        },
    )


async def record(
    session: AsyncSession,
    machine_id: uuid.UUID,
    credits: Iterable[tuple[datetime, int]],
) -> None:
    """Add a heartbeat's credit to its hourly buckets. Does not commit.

    One statement, an upsert — never read-then-write: the heartbeat is the hot
    path, and a SELECT followed by an UPDATE is the shape that loses a write
    to a concurrent one.
    """
    rows = [
        {"machine_id": machine_id, "hour": hour, "seconds_on": seconds}
        for hour, seconds in credits
    ]
    if not rows:
        return
    await session.exec(_upsert_adding(pg_insert(MachineUptime).values(rows)))


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """Fold a duplicate record's counters into the kept one (machine merge).

    Usage is history, like the journal and the threats, so it follows the
    poste — unlike the pending Windows updates, which are state and are
    dropped. Two records of one poste cover different stretches of time, so
    their hours add up; the cap keeps an overlap from exceeding an hour.
    """
    table = MachineUptime.__table__  # type: ignore[attr-defined]
    source_rows = select(
        literal(target_id, type_=table.c.machine_id.type),
        table.c.hour,
        table.c.seconds_on,
    ).where(table.c.machine_id == source_id)
    await session.exec(
        _upsert_adding(
            pg_insert(MachineUptime).from_select(
                ["machine_id", "hour", "seconds_on"], source_rows
            )
        )
    )
    await session.exec(
        delete(MachineUptime).where(col(MachineUptime.machine_id) == source_id)
    )


async def purge_before(session: AsyncSession, cutoff: datetime) -> int:
    """Drop the hours older than ``cutoff``. Commits; returns the rows gone."""
    result = await session.exec(
        delete(MachineUptime).where(col(MachineUptime.hour) < cutoff)
    )
    await session.commit()
    return result.rowcount or 0
