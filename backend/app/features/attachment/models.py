"""Attachments of the journal (C11): a photo of a fault, a delivery note.

One row per file joined to one line of ``interventions`` — whatever wrote
the line: by hand, a maintenance visit, the closing of a verification. The
bytes live once per SHA-256 under ``ATTACHMENTS_DIR`` (``storage.py``): two
lines joining the same photo share the file, which goes when no row names it
any more (``crud.sweep_store``, ``crud.discard_if_orphan``).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, ForeignKey, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class InterventionAttachment(SQLModel, table=True):
    __tablename__ = "intervention_attachments"
    __table_args__ = (
        # A page of the journal reads the attachments of its lines.
        Index(
            "ix_intervention_attachments_intervention", "intervention_id", "created_at"
        ),
        # The sweep and the quota ask by file.
        Index("ix_intervention_attachments_sha256", "sha256"),
        # The retention purge.
        Index("ix_intervention_attachments_created_at", "created_at"),
        # The same file once per line: twice would be two identical chips
        # counted twice against the limit.
        UniqueConstraint(
            "intervention_id",
            "sha256",
            name="uq_intervention_attachments_intervention_sha",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # CASCADE: deleting a line deletes its attachments; the file goes at the
    # next sweep, or at once (``crud.discard_if_orphan``).
    intervention_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("interventions.id", ondelete="CASCADE"), nullable=False
        )
    )
    # The file's name in ``ATTACHMENTS_DIR``.
    sha256: str = Field(max_length=64)
    size: int = Field(sa_column=Column(BigInteger, nullable=False))
    # Recognised from the content, never the client's: image/jpeg, image/png,
    # image/webp, application/pdf.
    content_type: str = Field(max_length=40)
    # The name sent, cleaned (``storage.clean_filename``).
    filename: str = Field(max_length=200)
    # The acting account's e-mail, the journal's convention: it outlives the
    # account.
    uploaded_by: str = Field(max_length=255)
    # Also what the retention reads.
    created_at: datetime = utc_field(default_factory=utcnow)
