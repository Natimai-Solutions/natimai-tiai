"""Which addresses failed on an account lately, and which ones opened it.

What the account lock is guarded by (audit S03). ``LOGIN_MAX_FAILED_ATTEMPTS``
failures lock an account, but the lock shuts out the addresses that failed on
it within ``LOGIN_LOCKOUT_MINUTES``, not the account: anyone can no longer
keep an administrator out by failing five times from a poste.

That alone gives one guess per address during a lock, which a botnet or an
IPv6 prefix multiplies at will. So once ``LOGIN_SIEGE_ADDRESSES`` distinct
addresses have failed on the account within the window, the lock shuts out
every address but those that opened the account within
``LOGIN_KNOWN_ADDRESS_DAYS`` — its owner's usual postes. The lock the slow
counter sets (guesses spaced out over hours, audit T06) does the same from
the start.

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
    known_only: bool = False,
) -> bool:
    """Whether the lock of the account refuses ``ip``: it failed on the
    account within the window, or the lock admits only the usual addresses
    and it is not one of them. A lock admits only those when enough addresses
    failed on the account (a siege), or when ``known_only`` — the lock the
    slow counter sets (audit T06), whose guesser spaced the failures out so
    that no address failed lately."""
    row = await session.get(LoginAddress, (user_id, _address(ip)))
    window = _window_start(now)
    if row is not None and row.last_failure_at is not None:
        if row.last_failure_at > window:
            return True
    if row is not None and row.last_success_at is not None:
        if row.last_success_at > _known_since(now):
            return False
    if known_only:
        return True
    return await failing_addresses(session, user_id, now) >= (
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
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> int:
    """How many distinct addresses failed on the account within the window."""
    count = await session.scalar(
        select(func.count())
        .select_from(LoginAddress)
        .where(col(LoginAddress.user_id) == user_id)
        .where(col(LoginAddress.last_failure_at) > _window_start(now))
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


async def purge_stale(session: AsyncSession, now: datetime) -> int:
    """Drop the rows that no longer say anything: no failure within the
    window, no success within the known period. Commits."""
    failure = col(LoginAddress.last_failure_at)
    success = col(LoginAddress.last_success_at)
    result = await session.exec(
        delete(LoginAddress).where(
            and_(
                or_(failure.is_(None), failure <= _window_start(now)),
                or_(success.is_(None), success <= _known_since(now)),
            )
        )
    )
    await session.commit()
    return result.rowcount or 0
