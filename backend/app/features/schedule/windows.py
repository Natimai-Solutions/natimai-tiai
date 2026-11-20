"""The console's clock: its zone, the forbidden windows, and when a schedule
next runs.

One zone for the whole console (decision 7 of the plan): Tahiti is UTC−10,
and an hour in UTC means nothing to whoever plans « mercredi à 18 h ». It is a
setting (``schedules.timezone``), its initial value ``CONSOLE_TIMEZONE``.

Forbidden windows: weekly ranges, in that zone, when nothing at risk is to
run on several postes at once — the class hours. A schedule that would run
in one is refused when it is written; a risky command sent by hand to
several postes asks for a confirmation more. A command on one poste stays
free: that is troubleshooting.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as env
from app.core.errors import AppError, ErrorCode

KEY_TIMEZONE = "schedules.timezone"
KEY_FORBIDDEN = "schedules.forbidden_windows"

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def valid_time(value: str) -> bool:
    return bool(_HHMM.match(value))


def zone_of(name: str | None) -> tzinfo:
    """The zone ``name`` names; the environment's, then UTC, otherwise."""
    for candidate in (name, env.CONSOLE_TIMEZONE, "UTC"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


@dataclass(frozen=True)
class Window:
    """A forbidden range, every listed weekday (0 = Monday), from ``start``
    to ``end`` local — ``end`` after ``start``, within the day."""

    days: tuple[int, ...]
    start: str
    end: str

    def contains(self, local: datetime) -> bool:
        if local.weekday() not in self.days:
            return False
        moment = local.time().replace(second=0, microsecond=0)
        return _parse_time(self.start) <= moment < _parse_time(self.end)

    def as_json(self) -> dict[str, Any]:
        return {"days": list(self.days), "start": self.start, "end": self.end}


def parse_windows(value: Any) -> list[Window]:
    """The stored windows; what does not read is dropped, never fatal."""
    out: list[Window] = []
    if not isinstance(value, list):
        return out
    for item in value:
        if not isinstance(item, dict):
            continue
        days = item.get("days")
        start, end = item.get("start"), item.get("end")
        if (
            isinstance(days, list)
            and days
            and all(isinstance(d, int) and 0 <= d <= 6 for d in days)
            and isinstance(start, str)
            and isinstance(end, str)
            and valid_time(start)
            and valid_time(end)
            and start < end
        ):
            out.append(Window(tuple(sorted(set(days))), start, end))
    return out


@dataclass(frozen=True)
class SchedulePolicy:
    zone_name: str
    zone: tzinfo
    forbidden: tuple[Window, ...]

    def forbidden_at(self, instant: datetime) -> Window | None:
        local = instant.astimezone(self.zone)
        return next((w for w in self.forbidden if w.contains(local)), None)


async def schedule_policy(
    session: AsyncSession, values: dict[str, Any] | None = None
) -> SchedulePolicy:
    from app.features.setting import crud as setting_crud

    if values is None:
        values = await setting_crud.get_all(session)
    name = values.get(KEY_TIMEZONE)
    zone_name = (
        name if isinstance(name, str) and valid_zone(name) else env.CONSOLE_TIMEZONE
    )
    if not valid_zone(zone_name):
        zone_name = "UTC"
    return SchedulePolicy(
        zone_name=zone_name,
        zone=zone_of(zone_name),
        forbidden=tuple(parse_windows(values.get(KEY_FORBIDDEN))),
    )


def window_details(window: Window) -> dict[str, Any]:
    """A window as an error's details: the console words it."""
    return {"window": window.as_json()}


async def require_outside_forbidden(
    session: AsyncSession, now: datetime, *, confirmed: bool
) -> None:
    """A risky command for several postes, sent by hand: refused inside a
    forbidden window unless the person confirmed (``confirmed``)."""
    if confirmed:
        return
    window = (await schedule_policy(session)).forbidden_at(now)
    if window is not None:
        raise AppError(
            code=ErrorCode.COMMAND_FORBIDDEN_WINDOW,
            status_code=409,
            message="Inside a forbidden window: confirm to send it anyway",
            details=window_details(window),
        )


# --- When a schedule runs -----------------------------------------------------


def local_to_utc(day: date, at: time, zone: tzinfo) -> datetime:
    """``day`` at ``at`` in ``zone``, as a UTC instant. A time skipped by a
    clock change reads as the same wall time after it (``fold`` 0)."""
    from datetime import UTC

    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC)


def next_weekly(
    weekdays: list[int], time_of_day: str, zone: tzinfo, after: datetime
) -> datetime | None:
    """The first occurrence strictly after ``after`` of one of ``weekdays``
    at ``time_of_day``, local to ``zone``."""
    if not weekdays or not valid_time(time_of_day):
        return None
    at = _parse_time(time_of_day)
    local_day = after.astimezone(zone).date()
    for offset in range(0, 8):
        day = local_day + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        candidate = local_to_utc(day, at, zone)
        if candidate > after:
            return candidate
    return None


def weekly_in_forbidden(
    weekdays: list[int], time_of_day: str, policy: SchedulePolicy
) -> Window | None:
    """The forbidden window one of the weekly occurrences falls in, if any."""
    at = _parse_time(time_of_day).replace(second=0)
    for window in policy.forbidden:
        for day in weekdays:
            if day in window.days and (
                _parse_time(window.start) <= at < _parse_time(window.end)
            ):
                return window
    return None
