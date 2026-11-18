"""Which addresses failed on an account lately, and which ones opened it.

What the account lock is guarded by (audit S03). ``LOGIN_MAX_FAILED_ATTEMPTS``
failures lock an account, but the lock shuts out the addresses that failed on
it within ``LOGIN_LOCKOUT_MINUTES``, not the account: anyone can no longer
keep an administrator out by failing five times from a poste.

That alone gives one guess per address during a lock, which a botnet or an
IPv6 prefix multiplies at will. So once ``LOGIN_SIEGE_ADDRESSES`` distinct
addresses have failed on the account within the window, the lock shuts out
every address but those that opened the account within
``LOGIN_KNOWN_ADDRESS_DAYS`` — its owner's usual postes.

The lock the slow counter sets (guesses spaced out over hours, audit T06)
works the same way over its own, longer window: it shuts out the addresses
that failed on the account since the slow window began — not every address
the account never saw, which let one outside address keep a holder without a
usual poste out for a day — and, once ``LOGIN_SIEGE_ADDRESSES`` of them have,
every address but the usual ones.

All of it is in the database (``user_login_addresses``): a restart of the API
neither lifts a lock nor forgets the usual postes, and several API processes
would share it. Nothing here commits — the caller does.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.user.models import LOGIN_ADDRESS_MAX_LENGTH, LoginAddress

# A session kept alive by its refresh token keeps its address known; written
# at most this often, not on every refresh.
_SUCCESS_REFRESH = timedelta(days=1)


def _address(ip: str | None) -> str:
    """The address as stored: bounded, never empty (one row stands for the
    requests whose address could not be told)."""
    return (ip or "unknown")[:LOGIN_ADDRESS_MAX_LENGTH]


# The same spelling for the other tables that key on a client's address (the
# reset links' ``requested_ip``), so that both compare alike.
stored_address = _address


def _window_start(now: datetime) -> datetime:
    return now - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


def _known_since(now: datetime) -> datetime:
    return now - timedelta(days=settings.LOGIN_KNOWN_ADDRESS_DAYS)


async def shut_out(
    session: AsyncSession,
    user_id: uuid.UUID,
    ip: str | None,
    now: datetime,
    *,
    slow_since: datetime | None = None,
) -> bool:
    """Whether a lock of the account refuses ``ip``.

    Under any lock: it failed on the account within LOGIN_LOCKOUT_MINUTES,
    usual poste or not; or enough addresses did (a siege) and it is not one
    of the usual ones.

    Under the slow lock (audit T06) — ``slow_since`` is the start of the
    slow window that set it — the same two rules over that window: an
    address that failed since then is refused until the lock ends, and the
    siege is counted since then. An address that did not fail is admitted,
    known or not: the lock must not turn one outside address's guesses into
    a day without access for a holder the account has no usual poste for (a
    new account, one an administrator just reset). A usual poste that failed
    is back after LOGIN_LOCKOUT_MINUTES, as under any lock: a typo of its
    holder's must not cost them the day.
    """
    row = await session.get(LoginAddress, (user_id, _address(ip)))
    failed_at = row.last_failure_at if row is not None else None
    quick_since = _window_start(now)
    if failed_at is not None and failed_at > quick_since:
        return True
    if row is not None and row.last_success_at is not None:
        if row.last_success_at > _known_since(now):
            return False
    if slow_since is None:
        siege_since = quick_since
    else:
        if failed_at is not None and failed_at >= slow_since:
            return True
        siege_since = min(quick_since, slow_since)
    return await failing_addresses(session, user_id, siege_since) >= (
        settings.LOGIN_SIEGE_ADDRESSES
    )


async def is_known(
    session: AsyncSession, user_id: uuid.UUID, ip: str | None, now: datetime
) -> bool:
    """Whether ``ip`` opened the account within LOGIN_KNOWN_ADDRESS_DAYS —
    one of its owner's usual postes."""
    row = await session.get(LoginAddress, (user_id, _address(ip)))
    return (
        row is not None
        and row.last_success_at is not None
        and row.last_success_at > _known_since(now)
    )


async def failing_addresses(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> int:
    """How many distinct addresses failed on the account since ``since``
    (and have not opened it after)."""
    count = await session.scalar(
        select(func.count())
        .select_from(LoginAddress)
        .where(col(LoginAddress.user_id) == user_id)
        .where(col(LoginAddress.last_failure_at) >= since)
    )
    return count or 0


async def note_failure(
    session: AsyncSession, user_id: uuid.UUID, ip: str | None, now: datetime
) -> None:
    """``ip`` failed a login on the account."""
    await session.exec(
        insert(LoginAddress)
        .values(user_id=user_id, ip=_address(ip), last_failure_at=now)
        .on_conflict_do_update(
            index_elements=["user_id", "ip"], set_={"last_failure_at": now}
        )
    )


async def note_success(
    session: AsyncSession,
    user_id: uuid.UUID,
    ip: str | None,
    now: datetime,
    *,
    proved: bool = True,
) -> None:
    """``ip`` opened the account: it stays welcome through a lock.

    ``proved`` — a password, or a reset link, was just presented: whatever
    the address failed before is forgotten. False for a session merely
    kept alive (a refresh): the address stays known, written at most once a
    day, and its failures stand.
    """
    values: dict[str, datetime | None] = {"last_success_at": now}
    statement = insert(LoginAddress).values(
        user_id=user_id, ip=_address(ip), last_success_at=now
    )
    if proved:
        values["last_failure_at"] = None
        statement = statement.on_conflict_do_update(
            index_elements=["user_id", "ip"], set_=values
        )
    else:
        last = col(LoginAddress.last_success_at)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id", "ip"],
            set_=values,
            where=or_(last.is_(None), last < now - _SUCCESS_REFRESH),
        )
    await session.exec(statement)


async def forget_failures(session: AsyncSession, user_id: uuid.UUID) -> None:
    """A new password: what was guessed before no longer matters."""
    await session.exec(
        update(LoginAddress)
        .where(col(LoginAddress.user_id) == user_id)
        .where(col(LoginAddress.last_failure_at).is_not(None))
        .values(last_failure_at=None)
    )


async def forget_known(
    session: AsyncSession, user_id: uuid.UUID, *, keep: str | None = None
) -> None:
    """A new password because the old one may be known to someone else: the
    addresses that opened the account with it are no longer its owner's for
    sure. ``keep`` is the address the new password was just chosen from."""
    statement = delete(LoginAddress).where(col(LoginAddress.user_id) == user_id)
    if keep is not None:
        statement = statement.where(col(LoginAddress.ip) != _address(keep))
    await session.exec(statement)


def _failures_kept_since(now: datetime) -> datetime:
    """Before this, a failure says nothing to any lock. The slow lock reads
    the failures since its window began, and outlives the window by at most
    its own duration: twice LOGIN_SLOW_WINDOW_HOURS covers it (and the quick
    window, which the settings keep shorter)."""
    return min(
        _window_start(now), now - timedelta(hours=2 * settings.LOGIN_SLOW_WINDOW_HOURS)
    )


async def purge_stale(session: AsyncSession, now: datetime) -> int:
    """Drop the rows that no longer say anything: no failure a lock could
    still read, no success within the known period. Commits."""
    failure = col(LoginAddress.last_failure_at)
    success = col(LoginAddress.last_success_at)
    result = await session.exec(
        delete(LoginAddress).where(
            and_(
                or_(failure.is_(None), failure <= _failures_kept_since(now)),
                or_(success.is_(None), success <= _known_since(now)),
            )
        )
    )
    await session.commit()
    return result.rowcount or 0
