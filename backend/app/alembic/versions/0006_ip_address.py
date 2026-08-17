"""primary ip address reported by the agent

Revision ID: 0006_ip_address
Revises: 0005_session
Create Date: 2026-08-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_ip_address"
down_revision: str | None = "0005_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no server_default: NULL means "never reported", which the
    # console renders as a dash rather than as an address it does not have.
    #
    # Plain String rather than INET: the value is displayed and searched, never
    # compared as a network, and a text column keeps the column portable (the
    # test suite runs on the same schema) and the ILIKE search below trivial.
    op.add_column("machines", sa.Column("ip_address", sa.String(), nullable=True))
    # No index: the console searches it with a substring ILIKE, which no btree
    # index would serve. An exact-match lookup ("who holds this address?"),
    # should it come, wants its own index — and probably its own filter.


def downgrade() -> None:
    op.drop_column("machines", "ip_address")
