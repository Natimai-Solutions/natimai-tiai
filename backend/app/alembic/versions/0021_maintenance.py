"""maintenance: cycles, owners, sessions, and console settings

Revision ID: 0021_maintenance
Revises: 0020_checks
Create Date: 2026-09-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_maintenance"
down_revision: str | None = "0020_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "maintenances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "room_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rooms.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("room_name", sa.String(length=100), nullable=True),
        sa.Column("performed_by", sa.String(length=255), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=5000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_maintenances_room_performed", "maintenances", ["room_id", "performed_at"]
    )
    op.add_column(
        "interventions",
        sa.Column(
            "maintenance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("maintenances.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_interventions_maintenance_id", "interventions", ["maintenance_id"]
    )
    for table in ("rooms", "machines"):
        op.add_column(table, sa.Column("maintenance_cycle_days", sa.Integer(), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "maintenance_owner_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.add_column(
        "machines",
        sa.Column("last_maintenance_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "INSERT INTO group_permissions (group_id, permission) "
        "SELECT id, 'maintenance:read' FROM groups "
        "WHERE builtin_key IN ('readonly', 'technician') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO group_permissions (group_id, permission) "
        "SELECT id, 'maintenance:write' FROM groups "
        "WHERE builtin_key = 'technician' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM group_permissions WHERE permission IN "
        "('maintenance:read', 'maintenance:write', 'settings:read', 'settings:write')"
    )
    op.drop_column("machines", "last_maintenance_at")
    for table in ("machines", "rooms"):
        op.drop_column(table, "maintenance_owner_id")
        op.drop_column(table, "maintenance_cycle_days")
    op.drop_index("ix_interventions_maintenance_id", table_name="interventions")
    op.drop_column("interventions", "maintenance_id")
    op.drop_index("ix_maintenances_room_performed", table_name="maintenances")
    op.drop_table("maintenances")
    op.drop_table("app_settings")
