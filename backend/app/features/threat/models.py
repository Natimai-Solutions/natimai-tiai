import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field


class Threat(SQLModel, table=True):
    """A Defender detection reported by an agent.

    Deduplicated on (machine_id, detection_id) so the same detection reported
    on several heartbeats yields a single row.
    """

    __tablename__ = "threats"
    __table_args__ = (
        UniqueConstraint(
            "machine_id", "detection_id", name="uq_threats_machine_detection"
        ),
        Index("ix_threats_machine_id", "machine_id"),
        Index("ix_threats_detected_at", "detected_at"),
        Index("ix_threats_status", "status"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    machine_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    )
    detection_id: str | None = None  # unique Defender DetectionID
    threat_name: str | None = None
    severity: str | None = None
    category: str | None = None
    status: str | None = None  # active / quarantined / removed / allowed
    action_taken: str | None = None
    detected_at: datetime | None = utc_field(default=None, nullable=True)
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))
