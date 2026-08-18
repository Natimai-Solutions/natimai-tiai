"""interactive session reported by the agent (presence + optional username)

Revision ID: 0005_session
Revises: 0004_password_reset
Create Date: 2026-08-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_session"
down_revision: str | None = "0004_password_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable, no server_default: NULL means "never reported", which the
    # console renders as "Inconnu" — a real third state, not a missing False.
    op.add_column(
        "machines", sa.Column("session_user_present", sa.Boolean(), nullable=True)
    )
    op.add_column("machines", sa.Column("session_username", sa.String(), nullable=True))
    op.add_column("machines", sa.Column("session_state", sa.String(), nullable=True))
    op.add_column(
        "machines", sa.Column("session_is_remote", sa.Boolean(), nullable=True)
    )
    # No index: nothing filters or sorts on these server-side yet. A future
    # "postes libres" filter wants a partial index (WHERE session_user_present),
    # which belongs with that feature rather than here.


def downgrade() -> None:
    op.drop_column("machines", "session_is_remote")
    op.drop_column("machines", "session_state")
    op.drop_column("machines", "session_username")
    op.drop_column("machines", "session_user_present")
