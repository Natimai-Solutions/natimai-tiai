"""Personal API tokens (C8): made, found, revoked."""

import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.features.api_token.models import TOKEN_PREFIX, ApiToken
from app.features.base import utcnow
from app.features.user.models import User

MAX_ACTIVE = 20
MAX_DAYS = 365
DEFAULT_DAYS = 90
# How often the last use is written: a script polling every second must not
# write the row every second.
LAST_USED_EVERY = timedelta(minutes=1)


def is_token(value: str) -> bool:
    return value.startswith(TOKEN_PREFIX)


def live(token: ApiToken, now: datetime) -> bool:
    return token.revoked_at is None and token.expires_at > now


async def active_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    now = utcnow()
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ApiToken)
            .where(
                col(ApiToken.user_id) == user_id,
                col(ApiToken.revoked_at).is_(None),
                col(ApiToken.expires_at) > now,
            )
        )
        or 0
    )


def create(
    session: AsyncSession, user_id: uuid.UUID, *, name: str, can_write: bool, days: int
) -> tuple[ApiToken, str]:
    """A new token; returns it with its clear value, shown once. Does not
    commit."""
    clear = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = utcnow()
    row = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=security.hash_token(clear),
        prefix=clear[: len(TOKEN_PREFIX) + 4],
        can_write=can_write,
        created_at=now,
        expires_at=now + timedelta(days=days),
    )
    session.add(row)
    return row, clear


async def resolve(session: AsyncSession, clear: str) -> tuple[ApiToken, User] | None:
    """The live token and its active account behind a clear value, or None."""
    row = (
        await session.exec(
            select(ApiToken, User)
            .join(User, col(User.id) == col(ApiToken.user_id))
            .where(col(ApiToken.token_hash) == security.hash_token(clear))
        )
    ).one_or_none()
    if row is None:
        return None
    token, user = row
    if not live(token, utcnow()) or not user.is_active:
        return None
    return token, user


async def note_use(session: AsyncSession, token: ApiToken, ip: str | None) -> None:
    """Record the last use, at most once a minute — in a session of its own:
    the request's own transaction is the route's, and a read-only route
    never commits it."""
    now = utcnow()
    if token.last_used_at is not None and now - token.last_used_at < LAST_USED_EVERY:
        return
    async with AsyncSession(session.bind) as own:
        await own.exec(
            update(ApiToken)
            .where(col(ApiToken.id) == token.id)
            .values(last_used_at=now, last_used_ip=(ip or "")[:45] or None)
        )
        await own.commit()


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> int:
    """End every token of an account (its password reset by an administrator,
    its second factor reset, its deactivation). Does not commit."""
    result = await session.exec(
        update(ApiToken)
        .where(col(ApiToken.user_id) == user_id, col(ApiToken.revoked_at).is_(None))
        .values(revoked_at=utcnow())
    )
    return result.rowcount or 0
