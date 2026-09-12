"""interventions: the journal of a poste

Revision ID: 0019_interventions
Revises: 0018_directory
Create Date: 2026-09-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_interventions"
down_revision: str | None = "0018_directory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interventions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("note", sa.String(length=5000), nullable=True),
        sa.Column("performed_by", sa.String(length=255), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interventions_machine_performed",
        "interventions",
        ["machine_id", "performed_at"],
    )
    # A new resource: readers read the journal, technicians write it. The
    # administrators hold everything implicitly.
    op.execute(
        "INSERT INTO group_permissions (group_id, permission) "
        "SELECT id, 'intervention:read' FROM groups "
        "WHERE builtin_key IN ('readonly', 'technician') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO group_permissions (group_id, permission) "
        "SELECT id, 'intervention:write' FROM groups "
        "WHERE builtin_key = 'technician' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM group_permissions "
        "WHERE permission IN ('intervention:read', 'intervention:write')"
    )
    op.drop_index("ix_interventions_machine_performed", table_name="interventions")
    op.drop_table("interventions")
