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


async def get_all(session: AsyncSession) -> dict[str, Any]:
    rows = await session.exec(select(AppSetting))
    return {row.key: row.value for row in rows.all()}


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


async def maintenance_policy(session: AsyncSession) -> MaintenancePolicy:
    """The global defaults: the console's rows where they exist, the
    environment's values otherwise."""
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


async def usage_policy(session: AsyncSession) -> UsagePolicy:
    """The console's rows where they exist, the environment's values
    otherwise — the same precedence as ``maintenance_policy``."""
    values = await get_all(session)
    return UsagePolicy(
        window_days=_int_or(values.get(KEY_USAGE_WINDOW), env.USAGE_WINDOW_DAYS),
        low_hours=_int_or(values.get(KEY_USAGE_LOW), env.USAGE_LOW_HOURS),
        high_hours=_int_or(values.get(KEY_USAGE_HIGH), env.USAGE_HIGH_HOURS),
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
