"""A report: what somebody in front of a poste, without an account, says is
wrong with it (``dev/plan-evolutions-itil.md``, C4).

Left by the QR code of the poste's label (C2), when the console allows it
(off by default). It is *not* a verification: it lands in a queue, and a
technician turns it into one, attaches it to the one already open, or
closes it — otherwise anybody could take up the poste's single open
verification. The contact is optional, said so on the form, and purged
with the report.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class ReportStatus(enum.StrEnum):
    NEW = "new"
    # Turned into a verification, or attached to the one already open.
    CONVERTED = "converted"
    ATTACHED = "attached"
    # Looked at and closed without a verification: equipment without an
    # agent seen to, a duplicate, nothing to do.
    CLOSED = "closed"
    REJECTED = "rejected"


class Report(SQLModel, table=True):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_status_created", "status", "created_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # The labelled asset, and its poste when it has one. SET NULL: a poste or
    # an asset deleted leaves the report readable in the queue.
    asset_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    machine_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("machines.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    category: str = Field(max_length=20)
    text: str = Field(max_length=2000)
    # Optional: a name, a room, an e-mail — whatever lets the technician
    # come back to the person. Purged with the report.
    contact: str | None = Field(default=None, max_length=200)
    # The form's language, for whoever reads it back.
    language: str | None = Field(default=None, max_length=5)
    status: str = Field(default=ReportStatus.NEW, max_length=12)
    created_at: datetime = utc_field(default_factory=utcnow)
    handled_at: datetime | None = utc_field(default=None, nullable=True)
    handled_by: str | None = Field(default=None, max_length=255)
    # Why it was closed or rejected, typed by the technician.
    handling_note: str | None = Field(default=None, max_length=2000)
    # The verification it became or was attached to.
    check_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("machine_checks.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
