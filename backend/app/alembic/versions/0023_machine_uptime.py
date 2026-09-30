"""hourly usage counters: how long each poste is on

Revision ID: 0023_machine_uptime
Revises: 0022_user_preferences
Create Date: 2026-09-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_machine_uptime"
down_revision: str | None = "0022_user_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Seconds on per poste and per whole UTC hour, fed by the heartbeats
    # (``app.features.usage``). Counting starts with this migration: there is
    # nothing to backfill, a heartbeat already received proves nothing now.
    op.create_table(
        "machine_uptime_hourly",
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hour", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seconds_on", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("machine_id", "hour"),
        # An hour holds 3 600 seconds: past that is a double count.
        sa.CheckConstraint(
            "seconds_on >= 0 AND seconds_on <= 3600",
            name="ck_machine_uptime_hourly_seconds_on",
        ),
    )
    # The fleet-wide sums scan by window; the primary key serves one poste.
    op.create_index(
        "ix_machine_uptime_hourly_hour", "machine_uptime_hourly", ["hour"]
    )


def downgrade() -> None:
    op.drop_index("ix_machine_uptime_hourly_hour", table_name="machine_uptime_hourly")
    op.drop_table("machine_uptime_hourly")
