"""buildings and rooms: where the postes are, as the console organises it

Revision ID: 0017_rooms
Revises: 0016_groups
Create Date: 2026-09-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_rooms"
down_revision: str | None = "0016_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "buildings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Two buildings of one name on two sites, yes; on the same, no — nor
        # two site-less ones (NULLS NOT DISTINCT, PostgreSQL ≥ 15).
        sa.UniqueConstraint(
            "location",
            "name",
            name="uq_buildings_location_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "building_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("buildings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "building_id",
            "name",
            name="uq_rooms_building_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_rooms_building_id", "rooms", ["building_id"])
    op.add_column(
        "machines",
        sa.Column(
            "room_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rooms.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_machines_room_id", "machines", ["room_id"])

    # A new resource in the catalogue: the two built-in groups that read the
    # parc get to read rooms too. The administrators hold everything
    # implicitly, and a composed group is its operator's to extend.
    op.execute(
        "INSERT INTO group_permissions (group_id, permission) "
        "SELECT id, 'room:read' FROM groups "
        "WHERE builtin_key IN ('readonly', 'technician') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM group_permissions WHERE permission IN ('room:read', 'room:write')")
    op.drop_index("ix_machines_room_id", table_name="machines")
    op.drop_column("machines", "room_id")
    op.drop_index("ix_rooms_building_id", table_name="rooms")
    op.drop_table("rooms")
    op.drop_table("buildings")
