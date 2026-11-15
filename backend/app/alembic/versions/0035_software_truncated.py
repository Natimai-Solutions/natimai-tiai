"""machines: when the software list last applied was cut short — audit S21 (T36)

Revision ID: 0035_software_truncated
Revises: 0034_login_addresses
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_software_truncated"
down_revision: str | None = "0034_login_addresses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL for every poste already there: nothing says their list was cut,
    # and a list cut from now on sets it.
    op.add_column(
        "machines",
        sa.Column("software_truncated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("machines", "software_truncated_at")
