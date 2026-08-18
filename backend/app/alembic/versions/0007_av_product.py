"""third-party antivirus registered with the windows security center

Revision ID: 0007_av_product
Revises: 0006_ip_address
Create Date: 2026-08-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_av_product"
down_revision: str | None = "0006_ip_address"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable, no server_default. NULL means "never reported", which the
    # console renders as unknown rather than as a claim about the machine: an
    # agent older than the feature, or a host with no Security Center at all
    # (Windows Server ships none, so the namespace simply does not exist there).
    #
    # An *empty* av_product_name is a different answer: the registry was read
    # and holds nothing, i.e. the machine runs no antivirus. Worth storing and
    # worth showing, hence the deliberate distinction from NULL.
    op.add_column("machines", sa.Column("av_product_name", sa.String(), nullable=True))
    op.add_column("machines", sa.Column("av_product_enabled", sa.Boolean(), nullable=True))
    op.add_column(
        "machines",
        sa.Column("av_product_signatures_up_to_date", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "machines", sa.Column("av_product_is_defender", sa.Boolean(), nullable=True)
    )
    # Defender's own execution mode (AMRunningMode), which is what says "passive
    # because a third party took over" rather than "protection disabled".
    op.add_column("machines", sa.Column("running_mode", sa.String(), nullable=True))
    # No index on av_product_name: the console searches it with a substring
    # ILIKE and groups it for the filter dropdown, neither of which a btree on a
    # low-cardinality column would help. Should an exact-match lookup appear, it
    # wants its own index and probably its own filter.


def downgrade() -> None:
    op.drop_column("machines", "running_mode")
    op.drop_column("machines", "av_product_is_defender")
    op.drop_column("machines", "av_product_signatures_up_to_date")
    op.drop_column("machines", "av_product_enabled")
    op.drop_column("machines", "av_product_name")
