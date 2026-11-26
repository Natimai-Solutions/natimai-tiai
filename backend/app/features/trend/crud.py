"""Reading the daily photos back (C9, §2.4 and §2.5)."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from sqlalchemy import Integer, and_, cast, false, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.trend.models import TrendDay, TrendSnapshot
from app.features.user.scope import Scope

# The series the console draws when it names none.
DEFAULT_KEYS: tuple[str, ...] = (
    "total",
    "up_to_date",
    "with_active_threats",
    "machines_with_alerts",
    "machines_noncompliant",
    "machines_maintenance_overdue",
    "open_checks",
)


def cell_clause(scope: Scope | None) -> Any:
    """The predicate on ``trend_snapshots`` for an account's scope, or None.

    ``machine_clause`` + ``_room_ids_in`` (``user/scope.py``) read on the
    frozen columns of the photo: the agent's site, the room's effective
    site, its building, the room itself. One difference, deliberate (plan
    §1): a deleted room or building named by the scope still matches the
    cells that carry it — its share of the parc that day.
    """
    if scope is None:
        return None
    conditions: list[Any] = []
    if scope.locations:
        places = sorted(scope.locations)
        conditions.append(col(TrendSnapshot.location).in_(places))
        conditions.append(col(TrendSnapshot.site).in_(places))
    if scope.buildings:
        conditions.append(col(TrendSnapshot.building_id).in_(sorted(scope.buildings)))
    if scope.rooms:
        conditions.append(col(TrendSnapshot.room_id).in_(sorted(scope.rooms)))
    return or_(*conditions) if conditions else false()


def counter_sum(key: str) -> Any:
    """The sum of one counter over the joined cells, 0 when none carries it."""
    if key == "outdated":
        return counter_sum("total") - counter_sum("up_to_date")
    return func.coalesce(
        func.sum(cast(col(TrendSnapshot.counters)[key].astext, Integer)), 0
    )


def months_back(today: date, months: int) -> date:
    """The first day of the month ``months − 1`` months before ``today``'s:
    a period of ``months`` calendar months ending with the current one."""
    index = today.year * 12 + (today.month - 1) - (months - 1)
    return date(index // 12, index % 12 + 1, 1)


def _week_end(day: date) -> date:
    return day + timedelta(days=6 - day.weekday())


async def _sums(
    session: AsyncSession, scope: Scope | None, chosen: Any, keys: list[str]
) -> dict[date, list[int]]:
    """The sums of ``keys`` over the cells of ``scope``, for each day of
    ``chosen`` (a ``SELECT`` of days). Only the keys asked for are read."""
    on = col(TrendSnapshot.day) == col(TrendDay.day)
    clause = cell_clause(scope)
    if clause is not None:
        # In the ON, not the WHERE: a day with no cell in sight must stay,
        # with zeros.
        on = and_(on, clause)
    rows = await session.exec(
        select(col(TrendDay.day), *(counter_sum(k) for k in keys))
        .select_from(TrendDay)
        .outerjoin(TrendSnapshot, on)
        .where(col(TrendDay.day).in_(chosen))
        .group_by(col(TrendDay.day))
    )
    return {row[0]: [int(v) for v in row[1:]] for row in rows.all()}


@dataclass(frozen=True)
class Series:
    days: list[date]
    series: dict[str, list[int | None]]
    provisional_day: date | None
    since: date | None
    policy_changes: list[dict[str, Any]]


async def series(
    session: AsyncSession,
    scope: Scope | None,
    *,
    start: date,
    end: date,
    step: str,
    keys: list[str],
    today: date,
) -> Series:
    """The sums of ``keys`` over the cells of ``scope``, day by day (or week
    by week: the last day photographed of each ISO week) from ``start`` to
    ``end``.

    A point whose day was photographed has a value for every key — 0 when no
    cell of the scope carries it: what the dashboard would have said. A day
    (or week) never photographed is ``None``: a gap, not a zero.
    """
    in_period = and_(col(TrendDay.day) >= start, col(TrendDay.day) <= end)
    if step == "week":
        chosen = (
            select(func.max(col(TrendDay.day)))
            .where(in_period)
            .group_by(func.date_trunc("week", col(TrendDay.day)))
        )
    else:
        chosen = select(col(TrendDay.day)).where(in_period)

    values = await _sums(session, scope, chosen, keys)

    axis: list[date] = []
    points: list[list[int] | None] = []
    if step == "week":
        by_week = {_week_end(d): d for d in values}
        week = _week_end(start)
        while week - timedelta(days=6) <= end:
            found = by_week.get(week)
            axis.append(found if found is not None else min(week, end))
            points.append(values[found] if found is not None else None)
            week += timedelta(days=7)
    else:
        day = start
        while day <= end:
            axis.append(day)
            points.append(values.get(day))
            day += timedelta(days=1)

    out: dict[str, list[int | None]] = {k: [] for k in keys}
    for point in points:
        for i, key in enumerate(keys):
            out[key].append(None if point is None else point[i])

    since = await session.scalar(select(func.min(col(TrendDay.day))))
    return Series(
        days=axis,
        series=out,
        provisional_day=today if today in values else None,
        since=since,
        policy_changes=await policy_changes(session, start, end),
    )


async def policy_changes(
    session: AsyncSession, start: date, end: date
) -> list[dict[str, Any]]:
    """Each threshold that changed between two photographed days of the
    period (the last day before it included as the starting point), with
    its value before and after."""
    previous = await session.scalar(
        select(func.max(col(TrendDay.day))).where(col(TrendDay.day) < start)
    )
    first = previous if previous is not None else start
    rows = await session.exec(
        select(col(TrendDay.day), col(TrendDay.policies))
        .where(col(TrendDay.day) >= first, col(TrendDay.day) <= end)
        .order_by(col(TrendDay.day))
    )
    changes: list[dict[str, Any]] = []
    before: dict[str, Any] | None = None
    for day, policies in rows.all():
        current = policies or {}
        if before is not None:
            for key in sorted(set(before) | set(current)):
                if before.get(key) != current.get(key):
                    changes.append(
                        {
                            "day": day,
                            "key": key,
                            "before": before.get(key),
                            "after": current.get(key),
                        }
                    )
        before = current
    return changes


def last_day_of_month(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


async def month_ends(
    session: AsyncSession,
    scope: Scope | None,
    *,
    start: date,
    end: date,
    keys: list[str],
) -> dict[str, tuple[date, list[int]]]:
    """For the report: per month ``AAAA-MM`` of the period, its last day
    photographed and the sums of ``keys`` on it. A month never photographed
    is absent."""
    in_period = and_(col(TrendDay.day) >= start, col(TrendDay.day) <= end)
    chosen = (
        select(func.max(col(TrendDay.day)))
        .where(in_period)
        .group_by(func.date_trunc("month", col(TrendDay.day)))
    )
    values = await _sums(session, scope, chosen, keys)
    return {day.strftime("%Y-%m"): (day, sums) for day, sums in values.items()}


@dataclass(frozen=True)
class Period:
    """``months`` calendar months ending with the current one, in the
    console's zone: their names, their local days, and the UTC instants
    the timestamped columns are compared with (so that the indexes serve)."""

    zone_name: str
    zone: tzinfo
    today: date
    months: list[str]
    first_day: date
    start: datetime
    end: datetime


async def period(session: AsyncSession, months: int, now: datetime) -> Period:
    from app.features.schedule import windows

    policy = await windows.schedule_policy(session)
    today = now.astimezone(policy.zone).date()
    first_day = months_back(today, months)
    names: list[str] = []
    cursor = first_day
    while cursor <= today:
        names.append(cursor.strftime("%Y-%m"))
        cursor = last_day_of_month(cursor) + timedelta(days=1)
    return Period(
        zone_name=policy.zone_name,
        zone=policy.zone,
        today=today,
        months=names,
        first_day=first_day,
        start=windows.local_to_utc(first_day, time(0, 0), policy.zone),
        end=windows.local_to_utc(cursor, time(0, 0), policy.zone),
    )
