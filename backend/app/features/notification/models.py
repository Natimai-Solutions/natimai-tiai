"""The e-mail outbox: every mail is a row before it is a request.

Nothing in this application calls Mailgun during the transaction that decides a
mail must exist. The caller writes a row here — inside that same transaction —
and the worker drains the table, retrying on failure. A Mailgun or proxy outage
therefore delays a mail instead of losing it, and a rolled-back transaction
takes its mail down with it.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class EmailStatus(enum.StrEnum):
    """Lifecycle of a queued mail."""

    PENDING = "pending"
    SENT = "sent"
    # Given up after EMAIL_MAX_ATTEMPTS failures. Kept, not deleted: the row and
    # its last_error are the only trace that someone was *not* told something.
    ABANDONED = "abandoned"


class EmailOutbox(SQLModel, table=True):
    """One mail to one recipient.

    One row per recipient even for a digest sent to many: each address succeeds,
    retries and gives up on its own, and a shared row would put every operator's
    address in one place a single send could leak.
    """

    __tablename__ = "email_outbox"
    __table_args__ = (
        # The drain's exact WHERE: pending rows whose next attempt is due.
        Index("ix_email_outbox_status_next_attempt", "status", "next_attempt_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    to_address: str
    subject: str
    body: str
    # Stored as a plain string; EmailStatus is a str enum used as constants.
    status: str = Field(default=EmailStatus.PENDING)
    attempts: int = Field(default=0)
    created_at: datetime = utc_field(default_factory=utcnow)
    next_attempt_at: datetime = utc_field(default_factory=utcnow)
    sent_at: datetime | None = utc_field(default=None, nullable=True)
    last_error: str | None = None
