"""verification requests: "go and look at this poste"

Revision ID: 0020_checks
Revises: 0019_interventions
Create Date: 2026-09-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_checks"
down_revision: str | None = "0019_interventions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "machine_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column(
            "assigned_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("instructions", sa.String(length=5000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(length=255), nullable=True),
        sa.Column("closing_note", sa.String(length=5000), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_machine_checks_machine_id", "machine_checks", ["machine_id"])
    # One open request per poste; the closed ones are history.
    op.create_index(
        "uq_machine_checks_open",
        "machine_checks",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_index(
        "ix_machine_checks_assigned_open",
        "machine_checks",
        ["assigned_to_id", "closed_at"],
    )
    # Closing a request writes the journal: the entry points back at it.
    op.add_column(
        "interventions",
        sa.Column(
            "check_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machine_checks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        "INSERT INTO group_permissions (group_id, permission) "
        "SELECT id, 'check:read' FROM groups "
        "WHERE builtin_key IN ('readonly', 'technician') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO group_permissions (group_id, permission) "
        "SELECT id, 'check:write' FROM groups "
        "WHERE builtin_key = 'technician' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM group_permissions WHERE permission IN ('check:read', 'check:write')"
    )
    op.drop_column("interventions", "check_id")
    op.drop_index("ix_machine_checks_assigned_open", table_name="machine_checks")
    op.drop_index("uq_machine_checks_open", table_name="machine_checks")
    op.drop_index("ix_machine_checks_machine_id", table_name="machine_checks")
    op.drop_table("machine_checks")
