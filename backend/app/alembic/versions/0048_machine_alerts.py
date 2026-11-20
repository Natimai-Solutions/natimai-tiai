"""Alerts (dev/plan-evolutions-itil.md, C1)

* ``machine_alerts``: one row per (poste, rule) opened by the worker, resolved
  by it; at most one open per (poste, rule) — a partial unique index;
* ``machines.wu_reboot_required_since``: since when a restart has been
  pending. The postes already pending at the upgrade start counting from it;
  nobody knows since when they were;
* ``machine_checks.instructions_code`` / ``instructions_params``: the
  instructions of a verification the server opened for an alert, coded.

Revision ID: 0048_machine_alerts
Revises: 0047_room_texts
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0048_machine_alerts"
down_revision: str | None = "0047_room_texts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "machine_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "machine_id",
            sa.Uuid(),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule", sa.String(length=40), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column(
            "check_id",
            sa.Uuid(),
            sa.ForeignKey("machine_checks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_machine_alerts_machine_id", "machine_alerts", ["machine_id"]
    )
    op.create_index(
        "ix_machine_alerts_rule_resolved", "machine_alerts", ["rule", "resolved_at"]
    )
    op.create_index(
        "uq_machine_alerts_open",
        "machine_alerts",
        ["machine_id", "rule"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.add_column(
        "machines",
        sa.Column(
            "wu_reboot_required_since", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.execute(
        "UPDATE machines SET wu_reboot_required_since = now() "
        "WHERE wu_reboot_required"
    )
    op.add_column(
        "machine_checks",
        sa.Column("instructions_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "machine_checks", sa.Column("instructions_params", JSONB, nullable=True)
    )


def downgrade() -> None:
    op.drop_column("machine_checks", "instructions_params")
    op.drop_column("machine_checks", "instructions_code")
    op.drop_column("machines", "wu_reboot_required_since")
    op.drop_index("uq_machine_alerts_open", table_name="machine_alerts")
    op.drop_index("ix_machine_alerts_rule_resolved", table_name="machine_alerts")
    op.drop_index("ix_machine_alerts_machine_id", table_name="machine_alerts")
    op.drop_table("machine_alerts")
