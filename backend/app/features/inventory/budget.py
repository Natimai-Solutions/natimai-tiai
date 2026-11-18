"""The software catalogue budgets: new entries per poste and for the whole
fleet, per 24 hours (audit S21, T36).

A first inventory names at most MAX_SOFTWARE (2,000) entries, and on a parc
whose catalogue already exists nearly all of them are known; a token in a
loop used to add 2,000 new names per heartbeat. The per-poste budget
(``SOFTWARE_NEW_ENTRIES_PER_DAY``) bounds one token; it does not bound the
postes the enrollment secret can forge, each with a budget of its own —
twenty-nine of them added 58,000 rows in under a minute. The fleet's
(``SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET``) does: one key, since there is one
catalogue. A poste is granted the smaller of what is left of both.

Counted in PostgreSQL (``app.features.counter``): the same budgets for every
API process, and across a restart.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.counter import quota
from app.features.counter.quota import Grant, Quota

_DAY = 24 * 3600

software_quota = Quota(
    name="software_entries",
    units=settings.SOFTWARE_NEW_ENTRIES_PER_DAY,
    window_seconds=_DAY,
)
software_fleet_quota = Quota(
    name="software_entries_fleet",
    units=settings.SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET,
    window_seconds=_DAY,
)
FLEET = "fleet"


async def poste_budget_left(session: AsyncSession, machine_key: str) -> int:
    """New catalogue entries this poste's own budget still allows."""
    return await quota.remaining(session, software_quota, machine_key)


async def fleet_budget_left(session: AsyncSession) -> int:
    """New catalogue entries the postes together may still create."""
    return await quota.remaining(session, software_fleet_quota, FLEET)


async def budget_left(session: AsyncSession, machine_key: str) -> int:
    """New catalogue entries this poste could be granted right now: the
    smaller of what is left of its own budget and of the fleet's."""
    return min(
        await poste_budget_left(session, machine_key),
        await fleet_budget_left(session),
    )


# The budgets could not be asked (``quota.take``): to be read as nothing
# granted, never as a failure of the request.
Unavailable = quota.Unavailable


async def reserve(session: AsyncSession, machine_key: str, wanted: int) -> Grant | None:
    """Take up to ``wanted`` new catalogue entries from both budgets at once,
    committed apart from ``session``'s transaction. To be given back with
    ``release`` when the transaction that was to create them does not
    commit. None when the budgets have nothing left; ``Unavailable`` when
    they could not be asked."""
    return await quota.take(
        quota.engine_of(session),
        [(software_quota, machine_key), (software_fleet_quota, FLEET)],
        wanted,
    )


release = quota.give_back
