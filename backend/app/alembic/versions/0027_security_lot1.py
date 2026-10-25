"""account lockout, audit source address, re-enrollment held for approval

Revision ID: 0027_security_lot1
Revises: 0026_machine_token_indexes
Create Date: 2026-10-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_security_lot1"
down_revision: str | None = "0026_machine_token_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Consecutive failed logins and the lock they set. The default only fills
    # the existing accounts: the application always writes the counter itself.
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.alter_column("users", "failed_login_attempts", server_default=None)
    op.add_column(
        "users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    # Where each administrative action came from. NULL for the entries written
    # before, and for what no request carried (the worker's own jobs).
    op.add_column("audit_log", sa.Column("ip", sa.String(length=64), nullable=True))
    # A re-enrollment held because the poste still had a live token.
    op.add_column(
        "machines",
        sa.Column("reenroll_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "machines",
        sa.Column("reenroll_requested_ip", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("machines", "reenroll_requested_ip")
    op.drop_column("machines", "reenroll_requested_at")
    op.drop_column("audit_log", "ip")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
