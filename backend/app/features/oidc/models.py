"""One sign-in through the directory in flight (C7): what the browser takes
to the provider and must bring back.

The ``state`` travels in the URL and is stored hashed; the browser also holds
a cookie whose hash is stored here: the callback must come back in the same
browser that started it — a link to someone else's callback signs nobody in.
The nonce ties the identity token to this attempt, the PKCE verifier the
authorization code. Valid ten minutes, used once.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class OidcLogin(SQLModel, table=True):
    __tablename__ = "oidc_logins"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    state_hash: str = Field(max_length=64, unique=True)
    browser_hash: str = Field(max_length=64)
    nonce: str = Field(max_length=100)
    code_verifier: str = Field(max_length=128)
    # The console page to land on afterwards: a path of the console only.
    redirect: str | None = Field(default=None, max_length=2000)
    # Set when a signed-in local account links itself from « Mon compte ».
    link_user_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    # The account's password_changed_at when the link started: a password
    # changed since (its owner taking it back) voids the link.
    link_password_changed_at: datetime | None = utc_field(default=None, nullable=True)
    created_at: datetime = utc_field(default_factory=utcnow)
    expires_at: datetime = utc_field()
    used_at: datetime | None = utc_field(default=None, nullable=True)
