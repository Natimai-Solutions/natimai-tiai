"""Reports and richer verifications (dev/plan-evolutions-itil.md, C4)

``machine_checks``: priority (existing requests « normal »), category, due
date. ``reports``: what the postes' users leave through a label's QR code,
sorted by the technicians into verifications.

Revision ID: 0051_reports
Revises: 0050_schedules
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_reports"
down_revision: str | None = "0050_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "machine_checks",
        sa.Column(
            "priority", sa.String(length=10), nullable=False, server_default="normal"
        ),
    )
    op.alter_column("machine_checks", "priority", server_default=None)
    op.add_column(
        "machine_checks", sa.Column("category", sa.String(length=20), nullable=True)
    )
    op.add_column("machine_checks", sa.Column("due_date", sa.Date(), nullable=True))
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "machine_id",
            sa.Uuid(),
            sa.ForeignKey("machines.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("contact", sa.String(length=200), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by", sa.String(length=255), nullable=True),
        sa.Column("handling_note", sa.String(length=2000), nullable=True),
        sa.Column(
            "check_id",
            sa.Uuid(),
            sa.ForeignKey("machine_checks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_asset_id", "reports", ["asset_id"])
    op.create_index("ix_reports_machine_id", "reports", ["machine_id"])
    op.create_index("ix_reports_check_id", "reports", ["check_id"])
    op.create_index("ix_reports_status_created", "reports", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_status_created", table_name="reports")
    op.drop_index("ix_reports_check_id", table_name="reports")
    op.drop_index("ix_reports_machine_id", table_name="reports")
    op.drop_index("ix_reports_asset_id", table_name="reports")
    op.drop_table("reports")
    op.drop_column("machine_checks", "due_date")
    op.drop_column("machine_checks", "category")
    op.drop_column("machine_checks", "priority")
