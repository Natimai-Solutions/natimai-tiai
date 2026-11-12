"""commands: the package as approved (digest and files) — audit T08, T09

Revision ID: 0030_command_package_snapshot
Revises: 0029_packages
Create Date: 2026-11-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_command_package_snapshot"
down_revision: str | None = "0029_packages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "commands",
        sa.Column("package_digest", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "commands",
        sa.Column(
            "package_files", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("commands", "package_files")
    op.drop_column("commands", "package_digest")
