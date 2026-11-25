"""Software licences (C6)

``licenses``: what the établissement bought the right to install — the
programs covered (patterns over the catalogue's names), how many postes,
until when, from whom. Never the key.

Revision ID: 0056_licenses
Revises: 0055_directory_hardening
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056_licenses"
down_revision: str | None = "0055_directory_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "licenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "patterns",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("publisher", sa.String(length=200), nullable=True),
        sa.Column("seats", sa.Integer(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("vendor", sa.String(length=200), nullable=True),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.String(length=5000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_licenses_expires_on", "licenses", ["expires_on"])


def downgrade() -> None:
    op.drop_index("ix_licenses_expires_on", table_name="licenses")
    op.drop_table("licenses")
