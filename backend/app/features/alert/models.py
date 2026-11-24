"""An alert: a rule of the catalogue that holds for a poste, dated.

The dashboard already *counts* the postes whose disk is nearly full or whose
volume is not encrypted, but a count is a figure to go and read: it says
neither since when, nor that it changed. An alert is the same finding made
into a row — opened the first time the worker sees the rule hold, resolved by
the worker itself the first time it no longer does. One open alert at most
per (poste, rule); the closed ones stay as the poste's history.

The rules are a closed catalogue in the code (``AlertRule``), like the
commands: there is no rule engine to write in the console, only rules to turn
on or off and thresholds to set (``setting.crud.alert_policy``).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class AlertRule(enum.StrEnum):
    """The catalogue. A value is stored as a plain string: adding a rule is a
    value here and a function in ``rules.py``, never a migration."""

    # The system volume below the parc's free-space threshold — the one the
    # dashboard's card already uses (``fleet.low_disk_free_percent``).
    DISK_LOW = "disk_low"
    # A physical drive whose health is reported as anything but « Healthy ».
    # The one rule mailed at once: a day of delay can cost data.
    DISK_UNHEALTHY = "disk_unhealthy"
    # The system volume read as not fully encrypted (never on a status that
    # was not read: an unknown is not a finding).
    VOLUME_UNENCRYPTED = "volume_unencrypted"
    # A restart Windows Update asked for, pending for more than N days.
    REBOOT_PENDING = "reboot_pending"
    # A Windows version past its end of support (``os_support.py``).
    OS_UNSUPPORTED = "os_unsupported"
    # A program of the console's « logiciels interdits » list installed.
    FORBIDDEN_SOFTWARE = "forbidden_software"
    # No contact for longer than the inactivity window.
    INACTIVE = "inactive"
    # The warranty of a poste's asset ends within N days (``assets``).
    WARRANTY_ENDING = "warranty_ending"


ALL_RULES: tuple[AlertRule, ...] = tuple(AlertRule)


class MachineAlert(SQLModel, table=True):
    __tablename__ = "machine_alerts"
    __table_args__ = (
        # One open alert per (poste, rule): a rule holds or it does not.
        # Partial, so the history keeps every resolved one — and the
        # evaluation's INSERT … ON CONFLICT DO NOTHING leans on it to stay
        # safe against a second evaluator.
        Index(
            "uq_machine_alerts_open",
            "machine_id",
            "rule",
            unique=True,
            postgresql_where="resolved_at IS NULL",
        ),
        # The list page and the dashboard read "open, by rule".
        Index("ix_machine_alerts_rule_resolved", "rule", "resolved_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    machine_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    rule: str = Field(max_length=40)
    opened_at: datetime = utc_field(default_factory=utcnow)
    # NULL = still holds.
    resolved_at: datetime | None = utc_field(default=None, nullable=True)
    # What made it hold, as values the console words in its reader's
    # language: a percentage, a volume letter, a program name. Refreshed while
    # the alert is open, so the fiche reads today's figure.
    detail: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # The verification the worker opened for it, when the rule asks for one.
    # SET NULL: a check deleted with its poste's merge leaves the alert.
    check_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("machine_checks.id", ondelete="SET NULL"), nullable=True
        ),
    )
