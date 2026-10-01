"""Append-only audit log of administrative actions.

Command dispatch already audits itself — every command row carries
``created_by`` and its full lifecycle (command/models.py), wake included. This
table covers the actions that leave *no* row anywhere else: the kill-switch
and its lifting, machine merges (which delete a row), account management —
and, for a command or a wake sent to a set of postes, the request itself
(``command.bulk``, ``machine.wake_bulk``): the target as it was asked, and
what was skipped, which no command row records.
Entries are written inside the caller's transaction — same rule as the e-mail
outbox: the action and its trace commit or roll back together — and are never
updated afterwards. The only deletion is the worker's daily retention purge
(``AUDIT_RETENTION_DAYS``), by age and never by content.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class AuditEntry(SQLModel, table=True):
    """One administrative action, by whom, on what."""

    __tablename__ = "audit_log"
    __table_args__ = (
        # The console reads newest-first; nothing else queries this table.
        Index("ix_audit_log_at", "at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    at: datetime = utc_field(default_factory=utcnow)
    # The acting console account. Its e-mail rather than a foreign key: the
    # trace must survive the account's deletion — which is itself an action
    # this table records.
    actor: str
    # Stable slug ("machine.revoke_token", "user.update", …): countable and
    # filterable, so specifics go in ``details``, never in here.
    action: str = Field(index=True)
    resource_type: str  # "machine" / "user" / "command" …
    # As text, not UUID: it may name a row that no longer exists (a deleted
    # account, a merged machine), and it must still read as what it named.
    resource_id: str
    # What would otherwise be lost: the merged source's identity, the fields
    # an update touched, the hostname behind a machine id.
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))
