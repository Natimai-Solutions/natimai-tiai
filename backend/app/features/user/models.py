import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


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
    """A console operator authenticating with email + password (JWT).

    What the account may do is not on this row: it is the union of the
    permissions of its groups (``user_groups`` → ``group_permissions``), see
    ``app.features.user.permissions``.
    """

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    hashed_password: str
    full_name: str | None = Field(default=None, max_length=255)
    # A plain string column, the enum being the vocabulary rather than a
    # database type. A PostgreSQL ENUM would need a migration to add a fifth
    # cadence.
    email_preference: str = Field(default=EmailPreference.DIGEST_DAILY)
    # The console's per-account preferences, as one JSON document: which
    # columns the machine list shows and in what order, and whatever the next
    # page wants remembered. Owned by the console (the keys are its
    # vocabulary, see ``app.api.routes.auth``), merged key by key on write,
    # and never read by the server for anything but handing it back.
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    is_active: bool = Field(default=True)
    # Set on every password change. Access tokens issued before this instant are
    # rejected (app.api.deps), so resetting a password ends existing sessions —
    # otherwise a compromised account would stay reachable until token expiry.
    password_changed_at: datetime | None = utc_field(default=None, nullable=True)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)


class Group(SQLModel, table=True):
    """A named set of permissions, composed in the console.

    ``builtin_key`` marks the three groups every installation carries
    (``permissions.BuiltinGroup``): they cannot be deleted, and the
    administrators' one holds every permission implicitly. Everything else
    about them — name, description, and for the other two the permissions —
    is editable like any group's.
    """

    __tablename__ = "groups"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    builtin_key: str | None = Field(default=None, unique=True)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)


class GroupPermission(SQLModel, table=True):
    """One ``"resource:action"`` granted to a group (``permissions.permission_key``)."""

    __tablename__ = "group_permissions"

    group_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    )
    permission: str = Field(primary_key=True, max_length=100)


class UserGroup(SQLModel, table=True):
    """Membership. Deleting either side ends it; nothing else refers to it."""

    __tablename__ = "user_groups"

    user_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    )
    group_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True, index=True
        )
    )


class PasswordResetToken(SQLModel, table=True):
    """A single-use, time-limited "forgot password" token.

    Only the SHA-256 hash is stored, like per-machine agent tokens: a database
    leak must not hand out working reset links.
    """

    __tablename__ = "password_reset_tokens"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # ON DELETE CASCADE spelled out, because the migration has always had it and
    # ``foreign_key="users.id"`` does not: the schema SQLModel builds for the
    # tests and the migrated one used to disagree on what happens to a pending
    # reset link when its account is deleted. ``alembic check`` is what says so.
    #
    # ``nullable`` and ``index`` are explicit for the same reason as in
    # ``utc_field``: with an ``sa_column``, SQLModel stops deriving either from
    # the annotation.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    token_hash: str = Field(unique=True, index=True)
    expires_at: datetime = utc_field()
    used_at: datetime | None = utc_field(default=None, nullable=True)
    created_at: datetime = utc_field(default_factory=utcnow)
