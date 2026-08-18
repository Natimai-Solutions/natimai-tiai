"""windows update state: pending updates per machine + reboot flag

Revision ID: 0008_windows_update
Revises: 0007_av_product
Create Date: 2026-08-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_windows_update"
down_revision: str | None = "0007_av_product"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL on the count means "never reported" — an agent older than the feature,
    # or a host whose Windows Update service could not be searched — which the
    # console renders as unknown rather than as "nothing to install". The reboot
    # flag is the exception: a machine that never reported is not pending a
    # reboot, so false is the honest default and NOT NULL costs nothing.
    op.add_column(
        "machines", sa.Column("wu_pending_count", sa.Integer(), nullable=True)
    )
    op.add_column(
        "machines",
        sa.Column(
            "wu_reboot_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "machines",
        sa.Column("wu_last_search", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "machines",
        sa.Column("wu_last_install", sa.DateTime(timezone=True), nullable=True),
    )
    # No index on wu_pending_count / wu_reboot_required: the only server-side
    # readers are two fleet-wide COUNTs on the dashboard, which scan this table
    # whatever we build. A "postes en attente de MAJ" filter would want its own
    # index, and it belongs with that filter.

    # The *pending* set, not a history: a row disappears when the update is
    # installed (see features/windows_update/crud.replace_pending). The unique
    # constraint is what the upsert keys on.
    op.create_table(
        "windows_updates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("update_id", sa.String(), nullable=False),
        sa.Column("kb", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False, server_default="software"),
        sa.Column("categories", sa.String(), nullable=True),
        sa.Column(
            "is_downloaded", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("size_mb", sa.Float(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "machine_id", "update_id", name="uq_windows_updates_machine_update"
        ),
    )
    op.create_index("ix_windows_updates_machine_id", "windows_updates", ["machine_id"])


def downgrade() -> None:
    op.drop_index("ix_windows_updates_machine_id", table_name="windows_updates")
    op.drop_table("windows_updates")
    op.drop_column("machines", "wu_last_install")
    op.drop_column("machines", "wu_last_search")
    op.drop_column("machines", "wu_reboot_required")
    op.drop_column("machines", "wu_pending_count")
