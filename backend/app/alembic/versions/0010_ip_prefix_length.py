"""subnet mask reported alongside the ip address

Revision ID: 0010_ip_prefix_length
Revises: 0009_mac_address
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_ip_prefix_length"
down_revision: str | None = "0009_mac_address"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no server_default, like the two columns it completes: NULL means
    # "never reported", and a wake then falls back on WOL_SUBNET_PREFIXLEN
    # rather than inventing a mask. Backfilling every row with 24 would have
    # been exactly that invention — and would have looked, in the console, like
    # a value the poste had confirmed.
    op.add_column("machines", sa.Column("ip_prefix_length", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("machines", "ip_prefix_length")
