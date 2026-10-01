"""Console sessions: one row per login, revocable from the server.

A console login used to be a JWT and nothing else, valid for its whole
lifetime whatever happened in between: logging out only forgot it in the
browser, and a token copied off a workstation stayed good for eight hours.
A session row gives the server the last word. The access token names it
(``sid``) and is honoured only while the row is live, so ending the row —
logout, « fermer cette session », a password reset, a deactivation — ends the
access with it, on the next request.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow

# Bounds on what the client tells us about itself. The user agent is only
# there to let a person recognise « Firefox sur Windows » in their session
# list — a header a client controls is not worth more than that much room.
USER_AGENT_MAX_LENGTH = 255
# Long enough for any IPv6 text form, and for the "unknown" placeholder.
IP_MAX_LENGTH = 45


class AuthSession(SQLModel, table=True):
    """One logged-in console session and its current refresh token."""

    __tablename__ = "auth_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # ON DELETE CASCADE: a deleted account takes its sessions down with it,
    # which is also what ends them. Spelled out in the model as well as in the
    # migration so the test schema behaves like the real one.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    # SHA-256 of the refresh token the browser holds now. Rotated on every
    # refresh: a token is good for one use.
    refresh_token_hash: str = Field(max_length=64)
    # The one before it, kept for a short grace period after a rotation (see
    # ``crud.REFRESH_REUSE_GRACE``): two tabs refreshing at the same instant
    # both present the same token, and the slower one must not be taken for a
    # thief. Outside that window, presenting it is exactly that.
    previous_refresh_token_hash: str | None = Field(default=None, max_length=64)
    created_at: datetime = utc_field(default_factory=utcnow)
    # Last time the session bought a new access token — the console's
    # « dernière activité », accurate to an access token's lifetime.
    last_used_at: datetime = utc_field(default_factory=utcnow)
    # When the refresh token stops being accepted: slides forward on every
    # refresh, capped at ``created_at + SESSION_MAX_DAYS``.
    expires_at: datetime = utc_field()
    revoked_at: datetime | None = utc_field(default=None, nullable=True)
    user_agent: str | None = Field(default=None, max_length=USER_AGENT_MAX_LENGTH)
    ip: str | None = Field(default=None, max_length=IP_MAX_LENGTH)
