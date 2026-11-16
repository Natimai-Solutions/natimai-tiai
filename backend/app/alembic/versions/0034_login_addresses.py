"""user_login_addresses — audit T06, third pass

What the account lock is guarded by — which addresses failed on an account
lately, which ones opened it — lived in the API process's memory. A restart
(an upgrade is one) forgot it: the lock in the database then refused nobody,
and the owner's usual poste was no longer known, so guesses spread over many
addresses could shut the owner out again. It now lives here.

Revision ID: 0034_login_addresses
Revises: 0033_wol_released_relays
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_login_addresses"
down_revision: str | None = "0033_wol_released_relays"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_login_addresses",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "ip"),
    )
    # The addresses of the sessions still open are their owners' usual postes:
    # known from the first minute, not from each owner's next login.
    op.execute(
        """
        INSERT INTO user_login_addresses (user_id, ip, last_success_at)
        SELECT s.user_id, left(s.ip, 64), max(s.last_used_at)
        FROM auth_sessions s
        WHERE s.revoked_at IS NULL AND s.ip IS NOT NULL AND s.ip <> ''
        GROUP BY s.user_id, left(s.ip, 64)
        """
    )


def downgrade() -> None:
    op.drop_table("user_login_addresses")
