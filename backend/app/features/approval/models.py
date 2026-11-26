"""Two-person approval of mass actions (C10, ``dev/plan-approbation-masse.md``).

Above a number of postes, a command at risk sent by hand is not queued: it
becomes a *request* that a second account — holding the same rights, seeing
every poste it names — approves or rejects. A schedule at risk is approved
once, when it is written, for its author and a number of postes.

What is approved is what runs: a request keeps the exact list of postes it
was counted on (``approval_request_machines``), the package and its
fingerprint, the lifetime of its commands. Approving queues that list, less
the postes deleted or out of the author's scope since — never one more.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class ApprovalKind(enum.StrEnum):
    COMMAND = "command"
    SCHEDULE = "schedule"


class ApprovalStatus(enum.StrEnum):
    """A request is decided once: ``pending`` then one of the others."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    # Its approval was refused by what is checked again then (the author's
    # account or rights, the package, the postes, the clock): closed, with
    # the cause in ``result_code``.
    FAILED = "failed"


class ApprovalRequest(SQLModel, table=True):
    __tablename__ = "approval_requests"
    __table_args__ = (
        # Expiry, the badge.
        Index("ix_approval_requests_status_expires", "status", "expires_at"),
        # « Mes demandes », the limit per author, deleting an account.
        Index("ix_approval_requests_requested_by_status", "requested_by_id", "status"),
        # The purge.
        Index("ix_approval_requests_decided_at", "decided_at"),
        # One pending request per schedule.
        Index(
            "uq_approval_requests_pending_schedule",
            "schedule_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        # The same request sent twice is one request.
        Index(
            "uq_approval_requests_pending_key",
            "request_key",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kind: str = Field(max_length=10)
    status: str = Field(
        default=ApprovalStatus.PENDING,
        max_length=10,
        sa_column_kwargs={"server_default": text("'pending'")},
    )
    # sha256 of what was asked (``crud.request_key``); NULL for a schedule,
    # which is one request at most by ``schedule_id``.
    request_key: str | None = Field(default=None, max_length=64)
    command_type: str = Field(max_length=40)
    package_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("packages.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    # « 7-Zip 23.01 », as it was asked: shown if the package goes.
    package_name: str | None = Field(default=None, max_length=255)
    # ``package_crud.fingerprint`` when asked: a package changed since fails
    # the approval.
    package_digest: str | None = Field(default=None, max_length=64)
    # The target as asked, for the console: ``Target.as_json()``, reduced to
    # ``{"kind": "machines"}`` for a list — the list is the child table.
    target: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB(none_as_null=True), nullable=False)
    )
    # The postes counted against the threshold, and the threshold then.
    machine_count: int
    threshold: int
    # The lifetime of the commands, applied at the approval (NULL: the parc's).
    ttl_minutes: int | None = None
    schedule_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("schedules.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    schedule_name: str | None = Field(default=None, max_length=200)
    # Who asked: the id is what is checked again, the e-mail what is shown.
    requested_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    requested_by: str = Field(max_length=255)
    requested_at: datetime = utc_field(default_factory=utcnow)
    expires_at: datetime = utc_field()
    # Who approved, rejected, or whose approval failed; NULL for a
    # cancellation or an expiry.
    decided_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    decided_by: str | None = Field(default=None, max_length=255)
    # Any close, expiry included.
    decided_at: datetime | None = utc_field(default=None, nullable=True)
    # The reason of a rejection.
    note: str | None = Field(default=None, max_length=500)
    # Why it failed or was closed (``author_inactive``, ``package_changed``,
    # ``schedule_changed``…), with its parameters.
    result_code: str | None = Field(default=None, max_length=64)
    result_params: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    # What the approval queued.
    created: int | None = None
    skipped: int | None = None
    # Postes of the list deleted, out of the author's scope or revoked since.
    left_out: int | None = None


class ApprovalRequestMachine(SQLModel, table=True):
    """The frozen list of a command request: one row per poste. Deleted with
    the poste (it then counts in ``left_out``) or with the request."""

    __tablename__ = "approval_request_machines"

    request_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("approval_requests.id", ondelete="CASCADE"), primary_key=True
        )
    )
    machine_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True, index=True
        )
    )
