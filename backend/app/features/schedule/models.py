"""Schedules: a command run later, or every week, on a target resolved at the
time it runs (``dev/plan-evolutions-itil.md``, C3).

Not a ``not_before`` column on ``commands``: the target is resolved when the
schedule comes due — a room may have changed in between — a schedule can
repeat, and a wake is the server's to emit, not an agent's to pick up. At
each run the worker creates the commands through the path the console uses
(``command.dispatch``), on behalf of the schedule's author, whose account,
rights and scope are checked again then: planning must not be a way to keep
a right one has since lost.

A run is a row of its own (``ScheduleRun``): what was created, skipped,
woken, shut down — and, for a deployment in rings, which stage it stands at.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class Recurrence(enum.StrEnum):
    ONCE = "once"
    WEEKLY = "weekly"


class ScheduleState(enum.StrEnum):
    """Where a schedule stands. ``suspended`` is the server's doing — the
    author lost a right, their account, the target — and says why
    (``suspended_code``); ``disabled`` is a person's; ``done`` a one-off that
    ran."""

    ACTIVE = "active"
    DISABLED = "disabled"
    SUSPENDED = "suspended"
    DONE = "done"


class RunStatus(enum.StrEnum):
    """A run's life: ``running`` while something is still to do for it (a
    shutdown after, a ring to advance), then one of the others."""

    RUNNING = "running"
    DONE = "done"
    # Nothing was run: the author or the target no longer allowed it.
    SUSPENDED = "suspended"
    # The commands could not be queued (a package that cannot be deployed).
    FAILED = "failed"
    # A deployment in rings stopped on its failure threshold.
    HALTED = "halted"


class Schedule(SQLModel, table=True):
    __tablename__ = "schedules"
    __table_args__ = (Index("ix_schedules_state_next_run", "state", "next_run_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=200)
    command_type: str = Field(max_length=40)
    # A deployment's package. SET NULL: a package deleted leaves the schedule
    # to be suspended at its next run, not gone.
    package_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("packages.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    # The target, as ``command.target.Target.as_json`` writes it: resolved at
    # each run, within the author's scope as it is then.
    target: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    recurrence: str = Field(max_length=10)
    # A one-off: the instant (UTC) it runs.
    run_at: datetime | None = utc_field(default=None, nullable=True)
    # Weekly: ISO weekdays (0 = Monday) and the local time « HH:MM », in the
    # console's zone (``schedule_policy``).
    weekdays: list[int] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    time_of_day: str | None = Field(default=None, max_length=5)
    # How long the commands it creates wait for their poste: a poste woken
    # takes minutes to call in.
    ttl_minutes: int = 180
    wake_first: bool = False
    shutdown_after: bool = False
    # A deployment in rings: ordered stages, each a target, observed for
    # ``ring_observe_hours`` before the next; stopped above
    # ``ring_failure_percent`` of failures. NULL: one stage, the target.
    rings: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    ring_observe_hours: int | None = None
    ring_failure_percent: int | None = None
    state: str = Field(default=ScheduleState.ACTIVE, max_length=12)
    # Why the server suspended it, coded for the console.
    suspended_code: str | None = Field(default=None, max_length=64)
    suspended_at: datetime | None = utc_field(default=None, nullable=True)
    next_run_at: datetime | None = utc_field(default=None, nullable=True)
    last_run_at: datetime | None = utc_field(default=None, nullable=True)
    # On whose behalf it runs. The id is what is checked at each run; the
    # e-mail what the history shows, the account gone.
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    created_by: str = Field(max_length=255)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)


class ScheduleRun(SQLModel, table=True):
    __tablename__ = "schedule_runs"
    __table_args__ = (
        Index("ix_schedule_runs_schedule_started", "schedule_id", "started_at"),
        Index("ix_schedule_runs_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    schedule_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    )
    started_at: datetime = utc_field(default_factory=utcnow)
    finished_at: datetime | None = utc_field(default=None, nullable=True)
    status: str = Field(default=RunStatus.RUNNING, max_length=12)
    # Why it was suspended, failed or halted — coded, with its parameters.
    result_code: str | None = Field(default=None, max_length=64)
    result_params: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # Counts over every stage run so far.
    created: int = 0
    skipped: int = 0
    # Postes left out: token revoked, out of the author's scope.
    left_out: int = 0
    woken: int = 0
    # The postes this run woke — the only ones « éteindre ensuite » may shut
    # down — and those it shut down or left on (a session open).
    woken_ids: list[str] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    shutdown_ids: list[str] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    kept_on_ids: list[str] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # When the wake was emitted: the agent refuses a shutdown in the ten
    # minutes after a boot (``agent/internal/agent/power.go``).
    woken_at: datetime | None = utc_field(default=None, nullable=True)
    # Rings: the stage running (0-based) and since when.
    stage: int = 0
    stage_started_at: datetime | None = utc_field(default=None, nullable=True)
