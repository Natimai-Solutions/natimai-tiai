"""machine location + wake-on-lan relay

Revision ID: 0015_location_wol_relay
Revises: 0014_inventory
Create Date: 2026-09-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_location_wol_relay"
down_revision: str | None = "0014_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Where the poste is, as its agent's configuration names it. NULL = none
    # reported, which every agent older than the field — and every agent whose
    # deployment set nothing — leaves it at.
    op.add_column("machines", sa.Column("location", sa.String(), nullable=True))
    op.create_index("ix_machines_location", "machines", ["location"])

    # The poste that emitted (or will emit) a wake on behalf of machine_id.
    # SET NULL rather than CASCADE: retiring the relay must not delete the
    # target's history.
    op.add_column(
        "commands",
        sa.Column(
            "relay_machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Every heartbeat on a relay-enabled parc asks "is a wake waiting for a
    # relay?" — a lookup by type and status over a table that is mostly
    # history. The existing (machine_id, status) index does not serve it.
    op.create_index("ix_commands_type_status", "commands", ["type", "status"])


def downgrade() -> None:
    op.drop_index("ix_commands_type_status", table_name="commands")
    op.drop_column("commands", "relay_machine_id")
    op.drop_index("ix_machines_location", table_name="machines")
    op.drop_column("machines", "location")
