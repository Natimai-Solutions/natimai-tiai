import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class CommandType(enum.StrEnum):
    """Supported agent command types (Phase 1: Defender)."""

    QUICK_SCAN = "quick_scan"
    FULL_SCAN = "full_scan"
    UPDATE_SIGNATURES = "update_signatures"


class CommandStatus(enum.StrEnum):
    """Lifecycle of a queued command."""

    PENDING = "pending"
    DELIVERED = "delivered"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class Command(SQLModel, table=True):
    """A command queued for a single machine (one row per target, even in broadcast)."""

    __tablename__ = "commands"
    __table_args__ = (
        Index("ix_commands_machine_status", "machine_id", "status"),
        Index("ix_commands_expires_at", "expires_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    machine_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    )
    # Stored as plain strings; CommandType/CommandStatus are str enums used as
    # constants (members compare/serialize as their values, e.g. "quick_scan").
    type: str
    status: str = Field(default=CommandStatus.PENDING)
    created_by: str | None = None
    created_at: datetime = utc_field(default_factory=utcnow)
    expires_at: datetime = utc_field()
    delivered_at: datetime | None = utc_field(default=None, nullable=True)
    started_at: datetime | None = utc_field(default=None, nullable=True)
    finished_at: datetime | None = utc_field(default=None, nullable=True)
    result_output: str | None = None
    error: str | None = None
