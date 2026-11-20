"""A verification asked of somebody about a poste.

"Go and look at this one": an operator marks a poste, says what to look at,
and optionally who should. The request stays open until whoever handles it
closes it with a note and a date — kept, since the point of a request is
also the trace of what was found. Closing writes the poste's journal too
(``interventions``, kind ``verification``), so the fiche tells it in one
chronology.

Distinct from ``machines.needs_verification``, which is the server's own
doubt about a poste's *identity* (a fingerprint that moved), raised by the
agent's report and cleared by a merge — a machine finding, not a human task.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class MachineCheck(SQLModel, table=True):
    __tablename__ = "machine_checks"
    __table_args__ = (
        # One open request per poste: a second "go and look" on a poste
        # somebody is already asked to look at would be the same request
        # twice. Partial, so the history keeps every closed one.
        Index(
            "uq_machine_checks_open",
            "machine_id",
            unique=True,
            postgresql_where="closed_at IS NULL",
        ),
        # The task page reads "open, assigned to me".
        Index("ix_machine_checks_assigned_open", "assigned_to_id", "closed_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    machine_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    # Who asked, as text — the audit log's convention: the trace outlives the
    # account.
    requested_by: str = Field(max_length=255)
    # Who is asked. SET NULL: an account deleted leaves the request open for
    # anyone, rather than deleting a task nobody did.
    assigned_to_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    instructions: str | None = Field(default=None, max_length=5000)
    # Set when the server opened the request itself, for an alert
    # (``alert.crud``): the console words the instructions from the code and
    # its parameters, in the reader's language; ``instructions`` keeps the
    # French for an older console. NULL on instructions typed by someone.
    instructions_code: str | None = Field(default=None, max_length=64)
    instructions_params: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
    # NULL = still open.
    closed_at: datetime | None = utc_field(default=None, nullable=True)
    closed_by: str | None = Field(default=None, max_length=255)
    closing_note: str | None = Field(default=None, max_length=5000)
    # Set when the server wrote the note itself (``CLOSED_BY_MERGE``): the
    # console words it from the code, in the reader's language, and
    # ``closing_note`` keeps the French for an older console. NULL on a note
    # typed by someone, and on the rows written before (plan console
    # bilingue: they keep their French).
    closing_note_code: str | None = Field(default=None, max_length=64)
