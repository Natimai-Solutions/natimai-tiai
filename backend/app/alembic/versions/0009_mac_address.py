"""mac address of the adapter holding the reported ip

Revision ID: 0009_mac_address
Revises: 0008_windows_update
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_mac_address"
down_revision: str | None = "0008_windows_update"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no server_default, exactly like ip_address in 0006: NULL means
    # "never reported", which the console renders as a dash — and, here, as a
    # wake button that says why it cannot fire rather than one that fires into
    # the void.
    #
    # Plain String rather than MACADDR: the value is displayed and compared as
    # text, never as a network type, and a text column keeps this schema
    # identical to the one the test suite builds from the models. The canonical
    # form (upper case, colon-separated) is enforced on the way in, at the
    # heartbeat, so the column holds one shape and not five.
    op.add_column("machines", sa.Column("mac_address", sa.String(), nullable=True))
    # No index: nothing looks a machine up by its MAC. The console reads it on a
    # machine it already has, and the wake endpoint likewise.


def downgrade() -> None:
    op.drop_column("machines", "mac_address")
