"""Trends (C9): the daily photo of the dashboard's counters, by place

``trend_days``: one row per local day photographed, with the thresholds of
the day. ``trend_snapshots``: that day's counters, one row per cell (site of
the agent, room), the room's building and site frozen. Plus three indexes on
existing tables for the indicators read off the history.

Revision ID: 0060_trends
Revises: 0059_webhooks_api_tokens
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060_trends"
down_revision: str | None = "0059_webhooks_api_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trend_days",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("zone", sa.String(length=64), nullable=False),
        sa.Column(
            "policies",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("day"),
    )
    op.create_table(
        "trend_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("room_id", sa.Uuid(), nullable=True),
        sa.Column("building_id", sa.Uuid(), nullable=True),
        sa.Column("site", sa.String(length=255), nullable=True),
        sa.Column(
            "counters",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["day"], ["trend_days.day"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_trend_snapshots_cell",
        "trend_snapshots",
        ["day", "location", "room_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_interventions_kind_performed",
        "interventions",
        ["kind", "performed_at"],
        unique=False,
    )
    op.create_index(
        "ix_machine_checks_closed_at", "machine_checks", ["closed_at"], unique=False
    )
    op.create_index(
        "ix_commands_finished_at", "commands", ["finished_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_commands_finished_at", table_name="commands")
    op.drop_index("ix_machine_checks_closed_at", table_name="machine_checks")
    op.drop_index("ix_interventions_kind_performed", table_name="interventions")
    op.drop_index("uq_trend_snapshots_cell", table_name="trend_snapshots")
    op.drop_table("trend_snapshots")
    op.drop_table("trend_days")
