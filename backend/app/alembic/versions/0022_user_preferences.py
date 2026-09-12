"""per-account console preferences

Revision ID: 0022_user_preferences
Revises: 0021_maintenance
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_user_preferences"
down_revision: str | None = "0021_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One JSONB document per account rather than a column per preference: the
    # keys are the console's (which columns the machine list shows, in what
    # order — and whatever the next page wants remembered), and none of them
    # deserves a migration. NOT NULL with an empty object as the default, so
    # a preference is read with ``.get`` and never with a null check.
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
