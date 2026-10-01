"""Opening, refreshing, listing and ending console sessions.

Nothing here commits except the purge: a session is opened, rotated or revoked
inside the transaction of whatever motivates it — a login, a password reset, a
deactivation — so the two commit or roll back together, the same rule as the
audit log and the e-mail outbox.
"""

import enum
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.features.auth_session.models import (
    IP_MAX_LENGTH,
    USER_AGENT_MAX_LENGTH,
    AuthSession,
)
from app.features.base import utcnow

# How long after a rotation the token it replaced is still answered — with an
# access token, never with a new refresh token. The refresh cookie is shared by
# every tab of the browser: two tabs reloaded together each send it, the first
# rotates it, and the second arrives with the token just replaced. Without this
# window that second tab would read as a thief and close the session under the
# operator's feet. Thirty seconds covers a slow network many times over and
# keeps the window a stolen token could slip through as narrow as it can be.
REFRESH_REUSE_GRACE = timedelta(seconds=30)


class RefreshOutcome(enum.Enum):
    """What presenting a refresh token amounted to."""

    # The session's current token: rotated, a new one handed back.
    ROTATED = "rotated"
    # The token rotated away an instant ago (another tab of the same browser
    # won the race): an access token, and the cookie left as the winner set it.
    CONCURRENT = "concurrent"
    # Unknown, malformed, expired, revoked: nothing to give.
    INVALID = "invalid"
    # A stale token of a live session, outside the grace window. Refresh
    # tokens are single-use, so two parties hold copies of this session — the
    # server cannot tell which is the rightful one, and ends it for both.
    REUSED = "reused"


@dataclass(frozen=True)
class RefreshResult:
    outcome: RefreshOutcome
    session: AuthSession | None = None
    # Set on ROTATED only: the clear token, for the cookie.
    refresh_token: str | None = None


def _expiry(created_at: datetime, now: datetime) -> datetime:
    """The refresh token's end: sliding, but never past the session ceiling."""
    sliding = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    ceiling = created_at + timedelta(days=settings.SESSION_MAX_DAYS)
    return min(sliding, ceiling)


def is_live(row: AuthSession, now: datetime | None = None) -> bool:
    """Whether the session still authorizes anything."""
    return row.revoked_at is None and row.expires_at > (now or utcnow())


def _bounded(value: str | None, length: int) -> str | None:
    """A client-supplied string cut to its column, an empty one as absent."""
    return value[:length] if value else None


def _same_hash(token: str, stored: str | None) -> bool:
    return stored is not None and hmac.compare_digest(
        security.hash_token(token), stored
    )


async def open_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    user_agent: str | None,
    ip: str | None,
) -> tuple[AuthSession, str]:
    """Open a session for a login; returns it with its clear refresh token.

    Does not commit. The id is drawn here, before the row exists, because the
    refresh token carries it.
    """
    now = utcnow()
    session_id = uuid.uuid4()
    token = security.generate_refresh_token(session_id)
    row = AuthSession(
        id=session_id,
        user_id=user_id,
        refresh_token_hash=security.hash_token(token),
        created_at=now,
        last_used_at=now,
        expires_at=_expiry(now, now),
        user_agent=_bounded(user_agent, USER_AGENT_MAX_LENGTH),
        ip=_bounded(ip, IP_MAX_LENGTH),
    )
    session.add(row)
    await session.flush()
    return row, token


async def refresh(session: AsyncSession, token: str) -> RefreshResult:
    """Redeem a refresh token. Does not commit.

    The row is read ``FOR UPDATE``: two refreshes of one session are
    serialized, so the second sees the first's rotation and lands in the grace
    window instead of rotating from a token that is no longer current — which
    would leave the browser and the database holding different tokens, and the
    next refresh looking like theft.
    """
    raw_id = security.refresh_token_session_id(token)
    if raw_id is None:
        return RefreshResult(RefreshOutcome.INVALID)
    try:
        session_id = uuid.UUID(raw_id)
    except ValueError:
        return RefreshResult(RefreshOutcome.INVALID)
    row = await session.get(AuthSession, session_id, with_for_update=True)
    now = utcnow()
    if row is None or not is_live(row, now):
        return RefreshResult(RefreshOutcome.INVALID)

    if _same_hash(token, row.refresh_token_hash):
        new_token = security.generate_refresh_token(row.id)
        row.previous_refresh_token_hash = row.refresh_token_hash
        row.refresh_token_hash = security.hash_token(new_token)
        row.last_used_at = now
        row.expires_at = _expiry(row.created_at, now)
        session.add(row)
        return RefreshResult(RefreshOutcome.ROTATED, row, new_token)

    if (
        _same_hash(token, row.previous_refresh_token_hash)
        and now - row.last_used_at <= REFRESH_REUSE_GRACE
    ):
        return RefreshResult(RefreshOutcome.CONCURRENT, row)

    row.revoked_at = now
    session.add(row)
    return RefreshResult(RefreshOutcome.REUSED, row)


async def find_by_refresh_token(
    session: AsyncSession, token: str
) -> AuthSession | None:
    """The live session whose current or just-rotated token this is.

    For logout, which must end the session the browser holds without treating
    a stale cookie as theft — a logout is never an attack worth answering.
    """
    raw_id = security.refresh_token_session_id(token)
    if raw_id is None:
        return None
    try:
        row = await session.get(AuthSession, uuid.UUID(raw_id))
    except ValueError:
        return None
    if row is None or not is_live(row):
        return None
    if _same_hash(token, row.refresh_token_hash) or _same_hash(
        token, row.previous_refresh_token_hash
    ):
        return row
    return None


async def list_live(session: AsyncSession, user_id: uuid.UUID) -> list[AuthSession]:
    """A user's open sessions, most recently active first."""
    result = await session.exec(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            col(AuthSession.revoked_at).is_(None),
            col(AuthSession.expires_at) > utcnow(),
        )
        .order_by(col(AuthSession.last_used_at).desc(), col(AuthSession.id))
    )
    return list(result.all())


def revoke(session: AsyncSession, row: AuthSession) -> None:
    """End one session. Does not commit; a no-op on one already ended."""
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        session.add(row)


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> int:
    """End every open session of a user. Does not commit; returns how many.

    What a password change, a reset and a deactivation call: each is the
    answer to « this account may be in the wrong hands », and an answer that
    left the wrong hands logged in would be none.
    """
    result = await session.exec(
        update(AuthSession)
        .where(
            col(AuthSession.user_id) == user_id,
            col(AuthSession.revoked_at).is_(None),
        )
        .values(revoked_at=utcnow())
        # The rows already loaded in this session (the caller's own, for a
        # self-service password change) must read as revoked too.
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount or 0


async def purge_expired_sessions(session: AsyncSession) -> int:
    """Drop the sessions that can no longer authorize anything. Commits;
    returns the rows gone.

    Expired and revoked alike: a revoked session refuses every token, its own
    and stolen ones, whether its row is there or not — the row has nothing
    left to protect. Meant for the worker's daily housekeeping.
    """
    now = utcnow()
    result = await session.exec(
        delete(AuthSession).where(
            or_(
                col(AuthSession.expires_at) <= now,
                col(AuthSession.revoked_at).is_not(None),
            )
        )
    )
    await session.commit()
    return result.rowcount or 0
