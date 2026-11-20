"""Compliance of the postes and third-party updates (dev/plan-evolutions-itil.md, C5)

``machines``: the firewall's three profiles, the local Administrators, when
winget packages were last reported, and the compliance summary the worker
keeps. ``inventory_winget_packages``: what winget would upgrade, per poste.

Revision ID: 0052_compliance
Revises: 0051_reports
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052_compliance"
down_revision: str | None = "0051_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("firewall_domain", sa.Boolean(), nullable=True))
    op.add_column(
        "machines", sa.Column("firewall_private", sa.Boolean(), nullable=True)
    )
    op.add_column("machines", sa.Column("firewall_public", sa.Boolean(), nullable=True))
    op.add_column(
        "machines",
        sa.Column("local_admins", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "machines",
        sa.Column("winget_reported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "machines", sa.Column("compliance_passed", sa.Integer(), nullable=True)
    )
    op.add_column(
        "machines", sa.Column("compliance_total", sa.Integer(), nullable=True)
    )
    op.add_column(
        "machines",
        sa.Column("compliance_failed", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "inventory_winget_packages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("winget_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("available", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "winget_id", name="uq_inv_winget_machine_id"),
    )
    op.create_index(
        "ix_inv_winget_winget_id", "inventory_winget_packages", ["winget_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_inv_winget_winget_id", table_name="inventory_winget_packages")
    op.drop_table("inventory_winget_packages")
    for column in (
        "compliance_failed",
        "compliance_total",
        "compliance_passed",
        "winget_reported_at",
        "local_admins",
        "firewall_public",
        "firewall_private",
        "firewall_domain",
    ):
        op.drop_column("machines", column)
