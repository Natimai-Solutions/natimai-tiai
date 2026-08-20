import enum
import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class Role(enum.StrEnum):
    """Console roles (Phase 1).

    Coarse-grained for now. Fine-grained per-resource grants (read/write by
    table, per user) are layered on later in app.features.user.permissions
    without changing route call sites.
    """

    ADMIN = "admin"  # read + write + execute remote commands
    READONLY = "readonly"  # read only


class EmailPreference(enum.StrEnum):
    """What this account wants to receive by e-mail.

    One axis with four positions rather than a set of independent switches: the
    real question an operator answers is "how much do I want to hear from
    Tia'i", and the four answers below are ordered from silence to a message
    every morning. Switches would let you ask for a digest of nothing, or for
    nothing plus a digest.
    """

    # Nothing at all. Account mail (password reset) is not covered by this: it
    # answers a request the user just made, and is not a notification.
    NONE = "none"
    # One mail per newly detected threat, as it is reported. No daily summary —
    # this is the setting for someone who wants to hear only when it burns.
    IMMEDIATE = "immediate"
    # One mail a day, and only on a day that has something to report.
    DIGEST_EVENTS = "digest_events"
    # One mail a day, whatever happened. The default: a fleet whose console
    # nobody opens is the case this product exists for, and "no mail today"
    # then reads as "nothing broke" rather than as "the digest is broken".
    DIGEST_DAILY = "digest_daily"


class User(SQLModel, table=True):
    """A console operator authenticating with email + password (JWT)."""

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    hashed_password: str
    full_name: str | None = Field(default=None, max_length=255)
    # Stored as a plain string; Role is a str enum used as a constant.
    role: str = Field(default=Role.READONLY)
    # Same treatment as ``role``: a plain string column, the enum being the
    # vocabulary rather than a database type. A PostgreSQL ENUM would need a
    # migration to add a fifth cadence.
    email_preference: str = Field(default=EmailPreference.DIGEST_DAILY)
    is_active: bool = Field(default=True)
    # Set on every password change. Access tokens issued before this instant are
    # rejected (app.api.deps), so resetting a password ends existing sessions —
    # otherwise a compromised account would stay reachable until token expiry.
    password_changed_at: datetime | None = utc_field(default=None, nullable=True)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)


class PasswordResetToken(SQLModel, table=True):
    """A single-use, time-limited "forgot password" token.

    Only the SHA-256 hash is stored, like per-machine agent tokens: a database
    leak must not hand out working reset links.
    """

    __tablename__ = "password_reset_tokens"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(unique=True, index=True)
    expires_at: datetime = utc_field()
    used_at: datetime | None = utc_field(default=None, nullable=True)
    created_at: datetime = utc_field(default_factory=utcnow)
