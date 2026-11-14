"""commands: the relays whose claim on a wake was released — audit B29 (T35)

Revision ID: 0033_wol_released_relays
Revises: 0032_login_failure_decay
Create Date: 2026-11-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_wol_released_relays"
down_revision: str | None = "0032_login_failure_decay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "commands",
        sa.Column(
            "released_relay_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("commands", "released_relay_ids")
