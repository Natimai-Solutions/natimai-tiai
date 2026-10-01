"""agent token rotation: issue date and token awaiting its first use

Revision ID: 0025_agent_token_rotation
Revises: 0023_machine_uptime
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_agent_token_rotation"
down_revision: str | None = "0023_machine_uptime"  # rechained onto 0024 at integration
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every existing token counts as issued now, not at its real enrollment:
    # backdating it would put the whole parc past AGENT_TOKEN_ROTATE_DAYS at
    # once, and every agent able to rotate would do so on the same morning.
    # Starting the clock here spreads the first rotations over the dates the
    # postes are next seen after N days, like any later ones.
    op.add_column(
        "machines",
        sa.Column(
            "token_issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # The default only served the backfill: the application always writes the
    # issue date itself, and a default left on the column would differ from
    # the model.
    op.alter_column("machines", "token_issued_at", server_default=None)
    op.add_column(
        "machines", sa.Column("pending_token_hash", sa.String(), nullable=True)
    )


def downgrade() -> None:
    # A rotation in flight is dropped with its column. An agent that had not
    # stored the offer yet keeps its current token, still valid; one that had
    # switched to it gets a 401 and re-enrolls by itself — the designed way
    # back for any token the server no longer knows.
    op.drop_column("machines", "pending_token_hash")
    op.drop_column("machines", "token_issued_at")
