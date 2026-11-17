"""shared_counter: the software catalogue budgets in the database — audit T36

Counted per budget, key and minute, so that every API process draws from the
same budgets and a restart hands out no fresh one (they used to live in the
API process's memory). Starts empty: the budgets of the running process are
not carried over, as a restart did before.

Revision ID: 0040_shared_counters
Revises: 0039_login_slow_attempts
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_shared_counters"
down_revision: str | None = "0039_login_slow_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shared_counter",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.CheckConstraint("used >= 0", name="ck_shared_counter_used"),
        sa.PrimaryKeyConstraint("name", "key", "bucket"),
    )
    op.create_index("ix_shared_counter_bucket", "shared_counter", ["bucket"])


def downgrade() -> None:
    op.drop_index("ix_shared_counter_bucket", table_name="shared_counter")
    op.drop_table("shared_counter")
