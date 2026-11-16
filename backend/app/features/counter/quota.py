"""Budgets of units over a sliding window, counted in PostgreSQL.

Where a rate limiter counts requests, a budget counts what they create — the
software catalogue entries a poste adds, say, whatever the number of
heartbeats they ride (audit S21). ``take`` grants what is left, possibly less
than asked, from several budgets at once (a poste's and the fleet's), and
``give_back`` returns a grant whose work was rolled back.

In the database rather than in the API process (audit T36): every process
draws from the same budget, and a restart hands out no fresh one.

A grant is taken in a transaction of its own, on a connection of its own,
committed at once: two requests in flight — in one process or in two — must
not both be granted the same units, and the request's own transaction may
run a while longer; holding the budget's lock until it ends would make every
request that creates something wait for the others. The connection comes
from a pool-less engine beside the application's: a request holding one of
the application pool's connections never waits for a second one from the
same pool. So the grant is spent whatever becomes of the request; the
caller gives it back when the request's transaction does not commit
(``app.features.inventory.crud``). A process that dies in between loses that
grant for the window — a budget that errs on the safe side.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from weakref import WeakKeyDictionary

from sqlalchemy import ColumnElement, Engine, delete, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.counter.models import SharedCounter

logger = logging.getLogger(__name__)

# The grain of the window: a grant is charged to the minute it was made in,
# and counts until that minute has left the window — the window and at most
# one minute more.
BUCKET_SECONDS = 60

# Rows older than this are purged by the worker's housekeeping
# (``purge_expired``). Longer than any window plus its bucket.
RETENTION = timedelta(days=2)

# The key of the transaction-scoped advisory lock every grant takes before
# reading what is left: both budgets move together, and two grants never read
# the same remainder. One lock for every budget: a grant holds it for three
# short statements. Spells "tiai-qta" in ASCII, to read as what it is in
# ``pg_locks``.
QUOTA_LOCK = 0x746961692D717461


@dataclass
class Quota:
    """A budget: at most ``units`` per key over ``window_seconds``."""

    name: str
    units: int
    window_seconds: int

    def __post_init__(self) -> None:
        if timedelta(seconds=self.window_seconds + BUCKET_SECONDS) > RETENTION:
            raise ValueError(f"{self.name}: window longer than the retention")


@dataclass(frozen=True)
class Grant:
    """Units taken from each (budget name, key) of ``charges`` in ``bucket``."""

    charges: tuple[tuple[str, str], ...]
    units: int
    bucket: datetime


def _counted(quota: Quota, key: str) -> list[ColumnElement[bool]]:
    """The rows still in the window of ``quota`` for ``key``."""
    since = func.now() - timedelta(seconds=quota.window_seconds + BUCKET_SECONDS)
    return [
        col(SharedCounter.name) == quota.name,
        col(SharedCounter.key) == key,
        col(SharedCounter.bucket) > since,
    ]


async def used(db: AsyncSession | AsyncConnection, quota: Quota, key: str) -> int:
    """Units of ``quota`` granted to ``key`` within the window."""
    total = await db.scalar(
        select(func.coalesce(func.sum(SharedCounter.used), 0)).where(
            *_counted(quota, key)
        )
    )
    return int(total or 0)


async def remaining(db: AsyncSession | AsyncConnection, quota: Quota, key: str) -> int:
    """What ``key`` could still be granted from ``quota``, taking nothing."""
    return max(0, quota.units - await used(db, quota, key))


def engine_of(session: AsyncSession) -> AsyncEngine:
    """The engine a session's connections come from."""
    bind = session.bind
    if isinstance(bind, AsyncConnection):
        return bind.engine
    if isinstance(bind, AsyncEngine):
        return bind
    raise RuntimeError("the session is not bound to an engine")


_side_engines: WeakKeyDictionary[Engine, AsyncEngine] = WeakKeyDictionary()


def _side(engine: AsyncEngine) -> AsyncEngine:
    """A pool-less engine on the same database as ``engine``: one connection
    per grant, opened and closed with it (see the module's docstring)."""
    side = _side_engines.get(engine.sync_engine)
    if side is None:
        side = create_async_engine(engine.url, poolclass=NullPool)
        _side_engines[engine.sync_engine] = side
    return side


async def take(
    engine: AsyncEngine, charges: Sequence[tuple[Quota, str]], wanted: int
) -> Grant | None:
    """Grant up to ``wanted`` units, charged to every (budget, key) of
    ``charges``: the smallest of what is left of each. Committed before it
    returns; None when nothing could be granted."""
    if wanted <= 0 or not charges:
        return None
    async with _side(engine).begin() as conn:
        await conn.execute(select(func.pg_advisory_xact_lock(QUOTA_LOCK)))
        left = min([await remaining(conn, quota, key) for quota, key in charges])
        granted = min(wanted, left)
        if granted <= 0:
            return None
        bucket = (
            await conn.execute(select(func.date_trunc("minute", func.now())))
        ).scalar_one()
        for quota, key in charges:
            stmt = pg_insert(SharedCounter).values(
                name=quota.name, key=key, bucket=bucket, used=granted
            )
            await conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["name", "key", "bucket"],
                    set_={"used": col(SharedCounter.used) + stmt.excluded.used},
                )
            )
    return Grant(
        charges=tuple((quota.name, key) for quota, key in charges),
        units=granted,
        bucket=bucket,
    )


async def give_back(engine: AsyncEngine, grant: Grant) -> None:
    """Return a grant whose work was rolled back, to every budget it was
    charged to. Never raises: a give-back that fails leaves the units spent
    for the window, which errs on the safe side."""
    try:
        async with _side(engine).begin() as conn:
            for name, key in grant.charges:
                await conn.execute(
                    update(SharedCounter)
                    .where(col(SharedCounter.name) == name)
                    .where(col(SharedCounter.key) == key)
                    .where(col(SharedCounter.bucket) == grant.bucket)
                    .values(
                        used=func.greatest(col(SharedCounter.used) - grant.units, 0)
                    )
                )
    except (SQLAlchemyError, OSError):
        logger.exception(
            "could not give back %d units to %s", grant.units, grant.charges
        )


async def purge_expired(session: AsyncSession) -> int:
    """Drop the rows no window reaches any more (worker housekeeping)."""
    result = await session.exec(
        delete(SharedCounter).where(col(SharedCounter.bucket) < func.now() - RETENTION)
    )
    await session.commit()
    return result.rowcount or 0
