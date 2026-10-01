"""Reading and writing console settings, and the typed views over them."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as env
from app.features.base import utcnow
from app.features.setting.models import AppSetting

KEY_CYCLE = "maintenance.default_cycle_days"
KEY_OWNER = "maintenance.default_owner_id"
KEY_DUE_SOON = "maintenance.due_soon_days"
KEY_USAGE_WINDOW = "usage.window_days"
KEY_USAGE_LOW = "usage.low_hours"
KEY_USAGE_HIGH = "usage.high_hours"
# Parc thresholds and rhythms: decisions about how this parc is run, not about
# how the server is installed — the environment gives their initial value, the
# console's row wins once written (page Paramètres).
KEY_SIGNATURE_MAX_AGE = "fleet.signature_max_age_days"
KEY_INACTIVE_AFTER = "fleet.inactive_after_days"
KEY_LOW_DISK = "fleet.low_disk_free_percent"
KEY_HARDWARE_AGING = "fleet.hardware_aging_years"
KEY_AGENT_VERSION = "fleet.agent_expected_version"
KEY_COMMAND_TTL = "commands.default_ttl_minutes"
KEY_DIGEST_HOUR = "notifications.digest_hour_utc"
KEY_REMINDER_WEEKDAY = "maintenance.reminder_weekday"


async def get_all(session: AsyncSession) -> dict[str, Any]:
    rows = await session.exec(select(AppSetting))
    return {row.key: row.value for row in rows.all()}


async def get_value(session: AsyncSession, key: str) -> Any:
    """One stored value, or None when the console never wrote it — a primary
    key lookup, for the hot paths that need a single setting (the heartbeat)."""
    row = await session.get(AppSetting, key)
    return None if row is None else row.value


async def set_value(session: AsyncSession, key: str, value: Any, *, actor: str) -> None:
    """Write one setting. Does not commit."""
    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
    row.value = value
    row.updated_at = utcnow()
    row.updated_by = actor
    session.add(row)


@dataclass(frozen=True)
class MaintenancePolicy:
    """The parc-wide maintenance defaults, as resolved right now."""

    cycle_days: int
    owner_id: uuid.UUID | None
    due_soon_days: int


async def maintenance_policy(
    session: AsyncSession, values: dict[str, Any] | None = None
) -> MaintenancePolicy:
    """The global defaults: the console's rows where they exist, the
    environment's values otherwise. ``values`` is the table already read,
    for a caller that resolves several policies from one round trip."""
    if values is None:
        values = await get_all(session)
    cycle = values.get(KEY_CYCLE)
    due_soon = values.get(KEY_DUE_SOON)
    owner = values.get(KEY_OWNER)
    return MaintenancePolicy(
        cycle_days=int(cycle)
        if isinstance(cycle, int)
        else env.MAINTENANCE_DEFAULT_CYCLE_DAYS,
        owner_id=uuid.UUID(owner) if isinstance(owner, str) and owner else None,
        due_soon_days=(
            int(due_soon)
            if isinstance(due_soon, int)
            else env.MAINTENANCE_DUE_SOON_DAYS
        ),
    )


@dataclass(frozen=True)
class UsagePolicy:
    """How the usage statistics read the hourly counters, as resolved now:
    the window they look back over and the two thresholds that make a poste
    « peu utilisé » or « toujours allumé »."""

    window_days: int
    low_hours: int
    high_hours: int


def _int_or(value: Any, default: int) -> int:
    # ``bool`` is an ``int`` to Python; a stored true is not a threshold.
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


async def usage_policy(
    session: AsyncSession, values: dict[str, Any] | None = None
) -> UsagePolicy:
    """The console's rows where they exist, the environment's values
    otherwise — the same precedence as ``maintenance_policy``."""
    if values is None:
        values = await get_all(session)
    return UsagePolicy(
        window_days=_int_or(values.get(KEY_USAGE_WINDOW), env.USAGE_WINDOW_DAYS),
        low_hours=_int_or(values.get(KEY_USAGE_LOW), env.USAGE_LOW_HOURS),
        high_hours=_int_or(values.get(KEY_USAGE_HIGH), env.USAGE_HIGH_HOURS),
    )


@dataclass(frozen=True)
class FleetPolicy:
    """The thresholds that decide what the console says about a poste, as
    resolved now: when its antivirus base is « périmée », when it is
    « inactif », when its disk is nearly full, when it is due for renewal,
    which agent version it should run, and how long a queued command waits
    for it."""

    signature_max_age_days: int
    inactive_after_days: int
    low_disk_free_percent: int
    hardware_aging_years: int
    # None = no pinned version: the reference is the highest one the parc
    # reports (``agent_version.fleet_versions``).
    agent_expected_version: str | None
    command_default_ttl_minutes: int


def _agent_version_or(value: Any, default: str | None) -> str | None:
    """A stored agent version, where "" is a decision and not an absence.

    The console stores "" to say « automatique », and that must win over an
    ``AGENT_EXPECTED_VERSION`` pinned in the environment — otherwise a version
    pinned at installation could never be unpinned from the page. Only a
    missing row (or a cleared one, None) hands the setting back to the
    environment.
    """
    if isinstance(value, str):
        return value.strip() or None
    return default


async def fleet_policy(
    session: AsyncSession, values: dict[str, Any] | None = None
) -> FleetPolicy:
    """The console's rows where they exist, the environment's values
    otherwise — the same precedence as the other policies."""
    if values is None:
        values = await get_all(session)
    return FleetPolicy(
        signature_max_age_days=_int_or(
            values.get(KEY_SIGNATURE_MAX_AGE), env.SIGNATURE_MAX_AGE_DAYS
        ),
        inactive_after_days=_int_or(
            values.get(KEY_INACTIVE_AFTER), env.INACTIVE_AFTER_DAYS
        ),
        low_disk_free_percent=_int_or(
            values.get(KEY_LOW_DISK), env.LOW_DISK_FREE_PERCENT
        ),
        hardware_aging_years=_int_or(
            values.get(KEY_HARDWARE_AGING), env.HARDWARE_AGING_YEARS
        ),
        agent_expected_version=_agent_version_or(
            values.get(KEY_AGENT_VERSION), env.AGENT_EXPECTED_VERSION or None
        ),
        command_default_ttl_minutes=_int_or(
            values.get(KEY_COMMAND_TTL), env.COMMAND_DEFAULT_TTL_MINUTES
        ),
    )


async def signature_max_age_days(session: AsyncSession) -> int:
    """The one threshold the heartbeat needs, by primary key: the heartbeat
    runs every minute on every poste, and the whole table would be a read too
    many on that path."""
    return _int_or(
        await get_value(session, KEY_SIGNATURE_MAX_AGE), env.SIGNATURE_MAX_AGE_DAYS
    )


@dataclass(frozen=True)
class SchedulePolicy:
    """When the worker's mails go out, as resolved now: the hour of the daily
    digest (UTC) and the weekday of the maintenance reminder (0 = Monday),
    sent at that same hour."""

    digest_hour_utc: int
    reminder_weekday: int


async def schedule_policy(
    session: AsyncSession, values: dict[str, Any] | None = None
) -> SchedulePolicy:
    """Same precedence as the other policies. Read by the worker on every
    tick, so a new hour applies without restarting it."""
    if values is None:
        values = await get_all(session)
    return SchedulePolicy(
        digest_hour_utc=_int_or(values.get(KEY_DIGEST_HOUR), env.DIGEST_HOUR_UTC),
        reminder_weekday=_int_or(
            values.get(KEY_REMINDER_WEEKDAY), env.MAINTENANCE_REMINDER_WEEKDAY
        ),
    )


@dataclass(frozen=True)
class Policies:
    """Every parc-wide policy a request may need, resolved from one read."""

    maintenance: MaintenancePolicy
    usage: UsagePolicy
    fleet: FleetPolicy


async def policies(session: AsyncSession) -> Policies:
    """Every policy off a single SELECT of ``app_settings``: the machine
    list, the exports, the fiche and the dashboard need them at once, and
    the table is small enough that reading it twice would be the only cost."""
    values = await get_all(session)
    return Policies(
        maintenance=await maintenance_policy(session, values),
        usage=await usage_policy(session, values),
        fleet=await fleet_policy(session, values),
    )


async def user_names(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Display names of accounts, for the places that show an owner."""
    from app.features.user.models import User

    if not ids:
        return {}
    rows = await session.exec(select(User).where(col(User.id).in_(ids)))
    return {u.id: u.full_name or u.email for u in rows.all()}
