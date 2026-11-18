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

That second connection must never cost a request more than a truncated
answer. It may be refused (``max_connections`` reached: a process opens up
to one per request in flight, beside its pool), it may not open, the lock
may be held by a process that froze: every such failure is ``Unavailable``
— nothing granted, within seconds (``CONNECT_TIMEOUT_SECONDS``,
``LOCK_TIMEOUT_MS``) — which the caller treats as a budget that is spent.
"""

import logging
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from weakref import WeakKeyDictionary

from sqlalchemy import ColumnElement, Engine, delete, func, text, update
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

# How long the side connection may take to open, in seconds: beyond it the
# grant is given up (``Unavailable``) rather than have the request — a
# heartbeat, holding its poste's row — wait for a database that does not
# answer. Two is the least libpq's ``connect_timeout`` honours.
CONNECT_TIMEOUT_SECONDS = 3

# How long a statement of the side connection may wait for a lock, in
# milliseconds: the budgets' advisory lock, held for three short statements
# by whoever is being granted — or for ever by a process that froze while
# holding it, or whose connection is half open. Far above what a busy fleet
# makes a grant wait, far below what a heartbeat can afford.
LOCK_TIMEOUT_MS = 3000

# A failing database fails every grant asked of it: one line when it starts,
# then one per interval while it lasts — with the count of those it stands
# for — not a traceback per poste and per heartbeat.
FAILURE_LOG_INTERVAL_SECONDS = 600.0


class Unavailable(Exception):
    """The budgets could not be asked: nothing was granted, and nothing says
    they are spent. Already logged."""


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
        side = create_async_engine(
            engine.url,
            poolclass=NullPool,
            connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
        )
        _side_engines[engine.sync_engine] = side
    return side


@asynccontextmanager
async def _side_transaction(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A transaction on a side connection, committed on the way out, in
    which no statement waits long for a lock (``LOCK_TIMEOUT_MS``). Said to
    the transaction rather than in the connection's options: whatever the
    database URL carries, or stands behind."""
    async with _side(engine).begin() as conn:
        await conn.execute(
            text("SELECT set_config('lock_timeout', :ms, true)").bindparams(
                ms=str(LOCK_TIMEOUT_MS)
            )
        )
        yield conn


class _Failures:
    """Failures of one kind, logged without flooding: the first one, then
    one line per ``FAILURE_LOG_INTERVAL_SECONDS`` saying how many it stands
    for. Kept for the process: an outage is the database's, not a poste's."""

    def __init__(self) -> None:
        self.logged_at: float | None = None
        self.unsaid = 0

    def report(self, what: str, exc: BaseException) -> None:
        now = time.monotonic()
        if (
            self.logged_at is not None
            and now - self.logged_at < FAILURE_LOG_INTERVAL_SECONDS
        ):
            self.unsaid += 1
            return
        logger.error(
            "%s: %s (and %d more not logged since the last such line; one "
            "line per %d s at most)",
            what,
            exc,
            self.unsaid,
            FAILURE_LOG_INTERVAL_SECONDS,
            exc_info=exc,
        )
        self.logged_at = now
        self.unsaid = 0


_take_failures = _Failures()
_give_back_failures = _Failures()


async def take(
    engine: AsyncEngine, charges: Sequence[tuple[Quota, str]], wanted: int
) -> Grant | None:
    """Grant up to ``wanted`` units, charged to every (budget, key) of
    ``charges``: the smallest of what is left of each. Committed before it
    returns; None when nothing is left to grant.

    Raises ``Unavailable``, and nothing else of what a database does, when
    the budgets could not be asked — no connection, a lock not had in time,
    any error on the way. A commit that failed may have charged the units
    all the same: lost for the window, which errs on the safe side."""
    if wanted <= 0 or not charges:
        return None
    try:
        async with _side_transaction(engine) as conn:
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
    except (SQLAlchemyError, OSError) as exc:
        _take_failures.report(
            "budgets unreachable, nothing granted ("
            + ", ".join(sorted({quota.name for quota, _ in charges}))
            + ")",
            exc,
        )
        raise Unavailable from exc
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
        async with _side_transaction(engine) as conn:
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
    except (SQLAlchemyError, OSError) as exc:
        _give_back_failures.report(
            f"could not give back {grant.units} units to {grant.charges}", exc
        )


async def purge_expired(session: AsyncSession) -> int:
    """Drop the rows no window reaches any more (worker housekeeping)."""
    result = await session.exec(
        delete(SharedCounter).where(col(SharedCounter.bucket) < func.now() - RETENTION)
    )
    await session.commit()
    return result.rowcount or 0
