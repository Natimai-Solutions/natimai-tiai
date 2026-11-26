"""Outbound webhooks (C8): where the console tells another tool what
happened, and the queue of what it still owes them.

A delivery row is added in the transaction of the change it reports — a
threat recorded, an alert opened — and sent by the worker, with retries:
the same guarantee as the mail outbox (``notification/outbox.py``).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, false, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class WebhookEvent(enum.StrEnum):
    """The closed catalogue of what can be sent."""

    THREAT_DETECTED = "threat.detected"
    ALERT_OPENED = "alert.opened"
    ALERT_RESOLVED = "alert.resolved"
    CHECK_CREATED = "check.created"
    CHECK_CLOSED = "check.closed"
    COMMAND_FAILED = "command.failed"
    # A mass action waits for a second account's approval (C10).
    APPROVAL_REQUESTED = "approval.requested"
    # Sent by « Envoyer un essai » only; never subscribed to.
    TEST = "test"


SUBSCRIBABLE: tuple[WebhookEvent, ...] = tuple(
    e for e in WebhookEvent if e is not WebhookEvent.TEST
)


class WebhookFormat(enum.StrEnum):
    # The structured body, signed: for a script, an automation, a ticket tool.
    JSON = "json"
    # A text, in the webhook's language, as the chat tools take it.
    TEAMS = "teams"
    MATTERMOST = "mattermost"


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Webhook(SQLModel, table=True):
    __tablename__ = "webhooks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100)
    url: str = Field(max_length=2000)
    format: str = Field(default=WebhookFormat.JSON, max_length=20)
    # The language of the texts of the chat formats.
    language: str = Field(default="fr", max_length=8)
    events: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB(none_as_null=True), nullable=False),
    )
    # The signing secret, sealed (``secretbox``): shown at creation and at
    # each renewal, never again.
    secret: str = Field(max_length=500)
    enabled: bool = Field(default=True, sa_column_kwargs={"server_default": false()})
    created_by: str = Field(max_length=255)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
    last_success_at: datetime | None = utc_field(default=None, nullable=True)
    last_failure_at: datetime | None = utc_field(default=None, nullable=True)
    last_error: str | None = Field(default=None, max_length=500)
    consecutive_failures: int = Field(
        default=0, sa_column_kwargs={"server_default": text("0")}
    )


class WebhookDelivery(SQLModel, table=True):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        # The worker reads « pending, due »; the history reads per webhook.
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
        Index("ix_webhook_deliveries_webhook_created", "webhook_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    webhook_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False)
    )
    event: str = Field(max_length=40)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB(none_as_null=True), nullable=False)
    )
    status: str = Field(default=DeliveryStatus.PENDING, max_length=20)
    attempts: int = Field(default=0)
    next_attempt_at: datetime = utc_field(default_factory=utcnow)
    last_error: str | None = Field(default=None, max_length=500)
    response_status: int | None = None
    created_at: datetime = utc_field(default_factory=utcnow)
    sent_at: datetime | None = utc_field(default=None, nullable=True)
