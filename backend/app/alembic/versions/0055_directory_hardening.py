"""Directory readers tied to their domain and SID (relecture du mode relais)

``machines``: the domain a reader was designated in and the SID it reads.
``directory_domains``: one domain per NetBIOS name.

Revision ID: 0055_directory_hardening
Revises: 0054_critical_pending_since
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_directory_hardening"
down_revision: str | None = "0054_critical_pending_since"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "machines",
        sa.Column("directory_reader_domain", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "machines",
        sa.Column("directory_reader_sid", sa.String(length=100), nullable=True),
    )
    # A reader designated before this revision keeps its designation, tied
    # to the domain it declares now.
    op.execute(
        "UPDATE machines SET directory_reader_domain = domain "
        "WHERE directory_reader IS TRUE"
    )
    op.create_index(
        "uq_directory_domains_netbios",
        "directory_domains",
        [sa.text("lower(netbios_name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_directory_domains_netbios", table_name="directory_domains")
    op.drop_column("machines", "directory_reader_sid")
    op.drop_column("machines", "directory_reader_domain")
