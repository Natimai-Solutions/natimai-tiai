"""Since when a poste has had a critical update pending (C5, relecture)

The compliance check « correctifs » ages on this column rather than on each
update's own ``first_seen``, which a superseding cumulative update resets.
Backfilled from the oldest critical or important update pending now.

Revision ID: 0054_critical_pending_since
Revises: 0053_directory
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_critical_pending_since"
down_revision: str | None = "0053_directory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "machines",
        sa.Column(
            "wu_critical_pending_since", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.execute(
        """
        UPDATE machines AS m
        SET wu_critical_pending_since = w.since
        FROM (
            SELECT machine_id, MIN(first_seen) AS since
            FROM windows_updates
            WHERE type = 'software' AND lower(severity) IN ('critical', 'important')
            GROUP BY machine_id
        ) AS w
        WHERE w.machine_id = m.id
        """
    )


def downgrade() -> None:
    op.drop_column("machines", "wu_critical_pending_since")
