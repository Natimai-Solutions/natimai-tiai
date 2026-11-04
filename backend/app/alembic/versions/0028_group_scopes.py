"""group scopes: restrict a group to sites, buildings or rooms

Revision ID: 0028_group_scopes
Revises: 0027_security_lot1
Create Date: 2026-11-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_group_scopes"
down_revision: str | None = "0027_security_lot1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No row for a group = the whole parc, so every existing group keeps
    # exactly what it sees today. ``value`` is not a foreign key on purpose
    # (``GroupScope``): a deleted room must not widen a group by cascade.
    op.create_table(
        "group_scopes",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "kind", "value"),
    )


def downgrade() -> None:
    op.drop_table("group_scopes")
