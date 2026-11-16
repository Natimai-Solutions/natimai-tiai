"""commands: who closed a command; machines: when the signature age was reported

Revision ID: 0036_verdict_signature_age
Revises: 0035_software_truncated
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_verdict_signature_age"
down_revision: str | None = "0035_software_truncated"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "commands",
        sa.Column("agent_verdict_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A success is only ever written by a poste — except a wake the server
    # emitted itself, which is written closed and has no poste to answer. A
    # failure can be either side's, and is left NULL: a late verdict may still
    # replace it, which is what happened to every failure until now.
    op.execute(
        "UPDATE commands SET agent_verdict_at = finished_at "
        "WHERE status = 'succeeded' AND type <> 'wake_on_lan'"
    )
    op.add_column(
        "machines",
        sa.Column("signature_reported_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The last heartbeat is the best date there is for the age already stored:
    # the agent sends its Defender block on every heartbeat it can read it.
    op.execute(
        "UPDATE machines SET signature_reported_at = last_seen "
        "WHERE signature_age_days IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("machines", "signature_reported_at")
    op.drop_column("commands", "agent_verdict_at")
