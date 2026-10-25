"""index machines.token_hash and pending_token_hash: every agent call looks the
machine up by one of them

Revision ID: 0026_machine_token_indexes
Revises: 0025_agent_token_rotation
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_machine_token_indexes"
down_revision: str | None = "0025_agent_token_rotation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_machines_token_hash", "machines", ["token_hash"], unique=True
    )
    op.create_index(
        "ix_machines_pending_token_hash",
        "machines",
        ["pending_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_machines_pending_token_hash", table_name="machines")
    op.drop_index("ix_machines_token_hash", table_name="machines")
