"""Reading the directory through designated postes (dev/plan-lecture-annuaire.md, relay mode)

``directory_domains`` and ``directory_records``: what the readers read.
``machines``: the object matched to each poste, its verdict, the reading the
rooms are filed by, and the reader designation.

Revision ID: 0053_directory
Revises: 0052_compliance
Create Date: 2026-11-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053_directory"
down_revision: str | None = "0052_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MACHINE_COLUMNS = (
    sa.Column("directory_object_guid", sa.String(length=64), nullable=True),
    sa.Column("directory_status", sa.String(length=16), nullable=True),
    sa.Column("directory_domain_sid", sa.String(length=100), nullable=True),
    sa.Column("dir_distinguished_name", sa.String(), nullable=True),
    sa.Column("dir_ou", sa.String(), nullable=True),
    sa.Column("dir_ou_dn", sa.String(), nullable=True),
    sa.Column("dir_location", sa.String(), nullable=True),
    sa.Column(
        "directory_reader", sa.Boolean(), nullable=False, server_default=sa.false()
    ),
    sa.Column("directory_reader_since", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    for column in _MACHINE_COLUMNS:
        op.add_column("machines", column.copy())

    op.create_table(
        "directory_domains",
        sa.Column("sid", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("netbios_name", sa.String(length=64), nullable=False),
        sa.Column("subnets", postgresql.JSONB(), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reader_id", sa.Uuid(), nullable=True),
        sa.Column("objects_read", sa.Integer(), nullable=False),
        sa.Column("disagreement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disagreement", postgresql.JSONB(), nullable=True),
        sa.Column("pending_moves", postgresql.JSONB(), nullable=True),
        sa.Column("pending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["last_reader_id"], ["machines.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("sid"),
    )
    op.create_table(
        "directory_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("object_guid", sa.String(length=64), nullable=False),
        sa.Column("domain_sid", sa.String(length=100), nullable=False),
        sa.Column("sam_account_name", sa.String(length=256), nullable=False),
        sa.Column("dns_host_name", sa.String(length=255), nullable=True),
        sa.Column("distinguished_name", sa.String(), nullable=True),
        sa.Column("ou", sa.String(), nullable=True),
        sa.Column("ou_dn", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_sid"], ["directory_domains.sid"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "object_guid", name="uq_directory_records_source_guid"
        ),
    )
    op.create_index(
        "ix_directory_records_domain_sam",
        "directory_records",
        ["domain_sid", "sam_account_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_directory_records_domain_sam", table_name="directory_records")
    op.drop_table("directory_records")
    op.drop_table("directory_domains")
    for column in reversed(_MACHINE_COLUMNS):
        op.drop_column("machines", column.name)
