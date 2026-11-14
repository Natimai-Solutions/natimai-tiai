"""users.last_failed_login_at — audit T06, second pass

The failed-login counter never decayed: four failures a week ago and one typo
today locked the account. From now on a failure older than the lockout window
starts the count over, which needs to know when the last one happened.

Revision ID: 0032_login_failure_decay
Revises: 0031_recompute_last_maintenance
Create Date: 2026-11-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_login_failure_decay"
down_revision: str | None = "0031_recompute_last_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A counter left by the previous version has no date: start it over
    # rather than let old failures count towards the next lock.
    op.execute("UPDATE users SET failed_login_attempts = 0")


def downgrade() -> None:
    op.drop_column("users", "last_failed_login_at")
