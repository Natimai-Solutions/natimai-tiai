"""The journal of a poste: every human intervention on it, whatever the cause.

One table for every kind of entry — a repair, a software install, an upgrade,
a maintenance visit, a closed verification — rather than one per kind: the
fiche wants *one* chronology, and three forms that differ by a label would
have been three tables to union on every read. The kinds are a closed list
(``InterventionKind``), stored as plain strings like every enum in this
schema so that adding one is a value here and a label in the console, not a
migration.

Later milestones attach an entry to what caused it: a maintenance session
(``maintenance_id``) or a verification request (``check_id``). The columns
arrive with their milestone.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class InterventionKind(enum.StrEnum):
    MAINTENANCE = "maintenance"
    VERIFICATION = "verification"
    INCIDENT = "incident"
    SOFTWARE_INSTALL = "software_install"
    UPGRADE = "upgrade"
    OTHER = "other"


class Intervention(SQLModel, table=True):
    """One entry of a poste's journal."""

    __tablename__ = "interventions"
    __table_args__ = (
        # The fiche reads one poste's journal newest first: this is that read.
        Index("ix_interventions_machine_performed", "machine_id", "performed_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # CASCADE: a poste that no longer exists has no fiche to show its journal
    # on; a merge moves the rows to the kept record before deleting the other.
    machine_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    )
    kind: str = Field(max_length=40)
    # One line, optional: « Remplacement SSD ». The note carries the rest.
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=5000)
    # The acting account's e-mail, as text, the audit log's convention: the
    # entry must outlive the account.
    performed_by: str = Field(max_length=255)
    # When it happened — not when it was typed in. Backdating is allowed and
    # useful: a poste maintained before Tia'i existed can have its journal
    # started from the right date.
    performed_at: datetime = utc_field(default_factory=utcnow)
    # The verification request whose closing wrote this entry, when that is
    # what it is. SET NULL: the entry is the record, the request the cause.
    check_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("machine_checks.id", ondelete="SET NULL"), nullable=True
        ),
    )
    # The maintenance session this entry was written by, for a
    # ``maintenance`` kind: the session holds the visit's global note.
    maintenance_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("maintenances.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
