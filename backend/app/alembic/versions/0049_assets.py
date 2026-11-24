"""Assets (dev/plan-evolutions-itil.md, C2)

``assets``: purchase, warranty, status and loan of a poste (``machine_id``,
one asset per poste at most) or of equipment without an agent (a projector,
a printer), with the opaque token its QR label carries.

Revision ID: 0049_assets
Revises: 0048_machine_alerts
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_assets"
down_revision: str | None = "0048_machine_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "machine_id",
            sa.Uuid(),
            sa.ForeignKey("machines.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "room_id",
            sa.Uuid(),
            sa.ForeignKey("rooms.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("manufacturer", sa.String(length=200), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("serial_number", sa.String(length=200), nullable=True),
        sa.Column("inventory_number", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("supplier", sa.String(length=200), nullable=True),
        sa.Column("order_reference", sa.String(length=200), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("borrower", sa.String(length=200), nullable=True),
        sa.Column("loan_due", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=5000), nullable=True),
        sa.Column("public_token", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_room_id", "assets", ["room_id"])
    op.create_index("ix_assets_status", "assets", ["status"])
    op.create_index("ix_assets_warranty_end", "assets", ["warranty_end"])
    op.create_index(
        "uq_assets_inventory_number",
        "assets",
        ["inventory_number"],
        unique=True,
        postgresql_where=sa.text("inventory_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_assets_inventory_number", table_name="assets")
    op.drop_index("ix_assets_warranty_end", table_name="assets")
    op.drop_index("ix_assets_status", table_name="assets")
    op.drop_index("ix_assets_room_id", table_name="assets")
    op.drop_table("assets")
