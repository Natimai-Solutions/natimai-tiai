"""The hourly counters: written by the heartbeat, moved on a merge, purged by
the worker, and read — per poste or across the parc — over a sliding window.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from sqlalchemy import Subquery, and_, case, delete, func, literal
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.machine.models import Machine
from app.features.usage.accounting import hour_start
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


# --- Reading ----------------------------------------------------------------


def window_start(now: datetime, days: int) -> datetime:
    """Where a window of ``days`` begins: ``days`` × 24 whole hours before the
    current one.

    Anchored on the hour rather than on ``now``: the counters are hourly, and
    a cut in the middle of a bucket would count its hour whole or not at all.
    So the window is the last ``days`` × 24 whole hours plus the current hour
    so far — the same boundary for the list, its filter, its sort, the export
    and the dashboard, which is what keeps a card and the list it opens equal.
    """
    return hour_start(now) - timedelta(days=days)


def seconds_by_machine(start: datetime) -> Subquery:
    """``(machine_id, seconds)``: each poste's seconds on since ``start``.

    Grouped by poste, hence one row per poste at most: outer-joined to the
    machine list it never multiplies a row, and the pagination's COUNT stays
    the number of postes. A poste with no hour in the window has no row here;
    ``seconds_on`` reads it as zero.
    """
    return (
        select(
            col(MachineUptime.machine_id).label("machine_id"),
            func.sum(col(MachineUptime.seconds_on)).label("seconds"),
        )
        .where(col(MachineUptime.hour) >= start)
        .group_by(col(MachineUptime.machine_id))
        .subquery("usage")
    )


def join_condition(usage: Subquery) -> ColumnElement[bool]:
    """How ``seconds_by_machine`` hangs off ``machines``."""
    return usage.c.machine_id == col(Machine.id)


def seconds_on(usage: Subquery) -> ColumnElement[Any]:
    """A poste's seconds in the window, zero when it has no hour there.

    Zero and not unknown: the heartbeat writes a row for every hour a poste
    is on, so no row is proof it was off — the very poste the « peu utilisé »
    question is looking for.
    """
    return func.coalesce(usage.c.seconds, 0)


def enrolled_before(start: datetime) -> ColumnElement[bool]:
    """Postes the server knew for the whole window.

    The one absence that is *not* zero: a poste enrolled the day before
    yesterday has not had a week to be used in, and counting it « peu
    utilisé » would send someone to look at a machine that was just unboxed.
    """
    return col(Machine.first_seen) <= start


def usage_hours_expr(usage: Subquery, start: datetime) -> ColumnElement[Any]:
    """Hours on in the window as SQL, NULL for a poste enrolled inside it.

    The sort key: NULL sorts last in both directions, like every other
    absence in the list, while the postes with no hour at all sort together
    at zero.
    """
    return case(
        (enrolled_before(start), seconds_on(usage) / float(SECONDS_PER_HOUR)),
        else_=None,
    )


def usage_clause(
    usage: Subquery,
    start: datetime,
    *,
    hours_below: float | None = None,
    hours_above: float | None = None,
) -> ColumnElement[bool]:
    """Postes on for strictly less than / strictly more than so many hours.

    Both bounds combine: « entre 10 et 30 h ». The lower bound leaves out the
    postes enrolled inside the window (``enrolled_before``); the upper one has
    no reason to — thirty hours in two days is thirty hours.
    """
    seconds = seconds_on(usage)
    clauses: list[ColumnElement[bool]] = []
    if hours_below is not None:
        clauses.append(enrolled_before(start))
        clauses.append(seconds < hours_below * SECONDS_PER_HOUR)
    if hours_above is not None:
        clauses.append(seconds > hours_above * SECONDS_PER_HOUR)
    return and_(*clauses)


def usage_hours(
    seconds: int | None, first_seen: datetime, start: datetime
) -> float | None:
    """The value a row carries, from what the joined query gave.

    ``None`` for a poste enrolled inside the window — the console writes
    « depuis N j » there — otherwise the hours, to the tenth.
    """
    if first_seen > start:
        return None
    return round((seconds or 0) / SECONDS_PER_HOUR, 1)


async def machine_seconds(
    session: AsyncSession, machine_id: uuid.UUID, start: datetime
) -> int:
    """One poste's seconds on since ``start`` — the fiche's figure."""
    total = await session.scalar(
        select(func.coalesce(func.sum(col(MachineUptime.seconds_on)), 0)).where(
            col(MachineUptime.machine_id) == machine_id,
            col(MachineUptime.hour) >= start,
        )
    )
    return int(total or 0)


async def usage_since(session: AsyncSession) -> datetime | None:
    """The first hour ever counted, ``None`` while nothing has been.

    What keeps the first week honest: until the table is a window deep, a
    parc where every poste reads « peu utilisé » is a parc being counted
    since Tuesday, and the console says so.
    """
    return await session.scalar(select(func.min(col(MachineUptime.hour))))


def local_days(now: datetime, days: int, zone: tzinfo) -> tuple[list[date], datetime]:
    """The last ``days`` calendar days in ``zone``, today included, and the
    UTC hour the first of them starts in.

    Days are cut here, at read time and in the reader's zone — the reason the
    counters are hourly. The start is floored to its UTC hour: in a zone off
    UTC by a half hour (the Marquesas, India), a bucket straddles local
    midnight and is filed under the day its hour *starts* in, half an hour
    early at worst.
    """
    today = now.astimezone(zone).date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, time(0), tzinfo=zone).astimezone(UTC)
    return [first + timedelta(days=i) for i in range(days)], hour_start(start)


async def daily_seconds(
    session: AsyncSession,
    machine_id: uuid.UUID,
    now: datetime,
    days: int,
    zone: tzinfo,
) -> list[tuple[date, int]]:
    """One poste's seconds on per local day, oldest first, zeros included.

    A few hundred rows at most (``days`` × 24): grouped in Python rather than
    in SQL, because the grouping is by the reader's calendar, daylight saving
    included, and ``astimezone`` already knows it.
    """
    dates, start = local_days(now, days, zone)
    rows = await session.exec(
        select(col(MachineUptime.hour), col(MachineUptime.seconds_on)).where(
            col(MachineUptime.machine_id) == machine_id,
            col(MachineUptime.hour) >= start,
        )
    )
    totals = dict.fromkeys(dates, 0)
    for hour, seconds in rows.all():
        day = hour.astimezone(zone).date()
        if day in totals:
            totals[day] += seconds
    return list(totals.items())
