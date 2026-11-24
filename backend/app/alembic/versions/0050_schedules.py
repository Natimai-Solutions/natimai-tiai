"""Schedules (dev/plan-evolutions-itil.md, C3)

``schedules``: a command run later or every week, on a target resolved when
it runs, on behalf of its author; ``schedule_runs``: each run, what it
created, woke and shut down, and the stage of a deployment in rings;
``commands.schedule_run_id`` / ``schedule_stage``: the run a command came
from.

Revision ID: 0050_schedules
Revises: 0049_assets
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0050_schedules"
down_revision: str | None = "0049_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("command_type", sa.String(length=40), nullable=False),
        sa.Column(
            "package_id",
            sa.Uuid(),
            sa.ForeignKey("packages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target", JSONB(), nullable=False),
        sa.Column("recurrence", sa.String(length=10), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weekdays", JSONB(), nullable=True),
        sa.Column("time_of_day", sa.String(length=5), nullable=True),
        sa.Column("ttl_minutes", sa.Integer(), nullable=False),
        sa.Column("wake_first", sa.Boolean(), nullable=False),
        sa.Column("shutdown_after", sa.Boolean(), nullable=False),
        sa.Column("rings", JSONB(), nullable=True),
        sa.Column("ring_observe_hours", sa.Integer(), nullable=True),
        sa.Column("ring_failure_percent", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("suspended_code", sa.String(length=64), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedules_package_id", "schedules", ["package_id"])
    op.create_index(
        "ix_schedules_state_next_run", "schedules", ["state", "next_run_at"]
    )
    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "schedule_id",
            sa.Uuid(),
            sa.ForeignKey("schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.Column("result_params", JSONB(), nullable=True),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("left_out", sa.Integer(), nullable=False),
        sa.Column("woken", sa.Integer(), nullable=False),
        sa.Column("woken_ids", JSONB(), nullable=True),
        sa.Column("shutdown_ids", JSONB(), nullable=True),
        sa.Column("kept_on_ids", JSONB(), nullable=True),
        sa.Column("woken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("stage_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_schedule_runs_schedule_started",
        "schedule_runs",
        ["schedule_id", "started_at"],
    )
    op.create_index("ix_schedule_runs_status", "schedule_runs", ["status"])
    op.add_column(
        "commands",
        sa.Column(
            "schedule_run_id",
            sa.Uuid(),
            sa.ForeignKey("schedule_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("commands", sa.Column("schedule_stage", sa.Integer(), nullable=True))
    op.create_index("ix_commands_schedule_run_id", "commands", ["schedule_run_id"])


def downgrade() -> None:
    op.drop_index("ix_commands_schedule_run_id", table_name="commands")
    op.drop_column("commands", "schedule_stage")
    op.drop_column("commands", "schedule_run_id")
    op.drop_index("ix_schedule_runs_status", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_schedule_started", table_name="schedule_runs")
    op.drop_table("schedule_runs")
    op.drop_index("ix_schedules_state_next_run", table_name="schedules")
    op.drop_index("ix_schedules_package_id", table_name="schedules")
    op.drop_table("schedules")
