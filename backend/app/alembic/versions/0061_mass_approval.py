"""Two-person approval of mass actions (C10)

``approval_requests``: a command at risk above the threshold, or a schedule
at risk, waiting for a second account. ``approval_request_machines``: the
frozen list of postes of a command request. On ``schedules``: who approved
it, when, for which author and how many postes.

Revision ID: 0061_mass_approval
Revises: 0060_trends
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061_mass_approval"
down_revision: str | None = "0060_trends"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column(
            "status",
            sa.String(length=10),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(length=64), nullable=True),
        sa.Column("command_type", sa.String(length=40), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=True),
        sa.Column("package_name", sa.String(length=255), nullable=True),
        sa.Column("package_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "target",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("machine_count", sa.Integer(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("ttl_minutes", sa.Integer(), nullable=True),
        sa.Column("schedule_id", sa.Uuid(), nullable=True),
        sa.Column("schedule_name", sa.String(length=200), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.Column(
            "result_params",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created", sa.Integer(), nullable=True),
        sa.Column("skipped", sa.Integer(), nullable=True),
        sa.Column("left_out", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["schedules.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_approval_requests_status_expires",
        "approval_requests",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_approval_requests_requested_by_status",
        "approval_requests",
        ["requested_by_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_approval_requests_decided_at",
        "approval_requests",
        ["decided_at"],
        unique=False,
    )
    op.create_index(
        "ix_approval_requests_decided_by_id",
        "approval_requests",
        ["decided_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_requests_schedule_id",
        "approval_requests",
        ["schedule_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_requests_package_id",
        "approval_requests",
        ["package_id"],
        unique=False,
    )
    op.create_index(
        "uq_approval_requests_pending_schedule",
        "approval_requests",
        ["schedule_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_approval_requests_pending_key",
        "approval_requests",
        ["request_key"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "approval_request_machines",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"], ["approval_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("request_id", "machine_id"),
    )
    op.create_index(
        "ix_approval_request_machines_machine_id",
        "approval_request_machines",
        ["machine_id"],
        unique=False,
    )

    op.add_column("schedules", sa.Column("approved_by_id", sa.Uuid(), nullable=True))
    op.add_column(
        "schedules", sa.Column("approved_by", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "schedules",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("schedules", sa.Column("approved_for_id", sa.Uuid(), nullable=True))
    op.add_column("schedules", sa.Column("approved_count", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "schedules_approved_by_id_fkey",
        "schedules",
        "users",
        ["approved_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "schedules_approved_for_id_fkey",
        "schedules",
        "users",
        ["approved_for_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_schedules_approved_by_id", "schedules", ["approved_by_id"], unique=False
    )
    op.create_index(
        "ix_schedules_approved_for_id", "schedules", ["approved_for_id"], unique=False
    )


def downgrade() -> None:
    # The code before this revision knows no « to_approve »: such a schedule
    # comes back turned off. One suspended for an approval stays suspended,
    # its code shown raw, and is turned back on like any other.
    op.execute(
        "UPDATE schedules SET state = 'disabled', next_run_at = NULL "
        "WHERE state = 'to_approve'"
    )
    op.drop_index("ix_schedules_approved_for_id", table_name="schedules")
    op.drop_index("ix_schedules_approved_by_id", table_name="schedules")
    op.drop_constraint(
        "schedules_approved_for_id_fkey", "schedules", type_="foreignkey"
    )
    op.drop_constraint("schedules_approved_by_id_fkey", "schedules", type_="foreignkey")
    op.drop_column("schedules", "approved_count")
    op.drop_column("schedules", "approved_for_id")
    op.drop_column("schedules", "approved_at")
    op.drop_column("schedules", "approved_by")
    op.drop_column("schedules", "approved_by_id")
    op.drop_index(
        "ix_approval_request_machines_machine_id",
        table_name="approval_request_machines",
    )
    op.drop_table("approval_request_machines")
    op.drop_index("uq_approval_requests_pending_key", table_name="approval_requests")
    op.drop_index(
        "uq_approval_requests_pending_schedule", table_name="approval_requests"
    )
    op.drop_index("ix_approval_requests_package_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_schedule_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_decided_by_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_decided_at", table_name="approval_requests")
    op.drop_index(
        "ix_approval_requests_requested_by_status", table_name="approval_requests"
    )
    op.drop_index(
        "ix_approval_requests_status_expires", table_name="approval_requests"
    )
    op.drop_table("approval_requests")
