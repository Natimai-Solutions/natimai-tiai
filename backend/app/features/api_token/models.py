"""Personal API tokens (C8): a script acting on behalf of an account.

The clear token (``tiai_pat_…``) is shown once; the row keeps its SHA-256
and its first characters, to recognise it in a list. It acts with at most
its account's rights and scope at the time of each call, read-only unless
made otherwise, and stops working at its end, at its revocation, or with its
account.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, false
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow

TOKEN_PREFIX = "tiai_pat_"


class ApiToken(SQLModel, table=True):
    __tablename__ = "api_tokens"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    name: str = Field(max_length=100)
    token_hash: str = Field(max_length=64, unique=True)
    # The first characters of the clear token, to tell tokens apart.
    prefix: str = Field(max_length=20)
    # Read-only unless asked: a token acts with the account's ``:read``
    # rights only.
    can_write: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    expires_at: datetime = utc_field()
    created_at: datetime = utc_field(default_factory=utcnow)
    last_used_at: datetime | None = utc_field(default=None, nullable=True)
    last_used_ip: str | None = Field(default=None, max_length=45)
    revoked_at: datetime | None = utc_field(default=None, nullable=True)
