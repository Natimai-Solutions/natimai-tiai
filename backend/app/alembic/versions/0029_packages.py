"""software deployment: packages, their files, commands.package_id

Revision ID: 0029_packages
Revises: 0028_group_scopes
Create Date: 2026-11-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_packages"
down_revision: str | None = "0028_group_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("winget_id", sa.String(length=128), nullable=True),
        sa.Column("winget_version", sa.String(length=64), nullable=True),
        sa.Column("install_run", sa.String(length=255), nullable=True),
        sa.Column("install_args", postgresql.JSONB(), nullable=False),
        sa.Column("uninstall_run", sa.String(length=255), nullable=True),
        sa.Column("uninstall_args", postgresql.JSONB(), nullable=False),
        sa.Column("success_codes", postgresql.JSONB(), nullable=False),
        sa.Column("detect_name", sa.String(length=200), nullable=True),
        sa.Column("manifest", sa.LargeBinary(), nullable=True),
        sa.Column("signature", sa.LargeBinary(), nullable=True),
        sa.Column("signature_algorithm", sa.String(length=40), nullable=True),
        sa.Column("signer_certificate", sa.LargeBinary(), nullable=True),
        sa.Column("signer_thumbprint", sa.String(length=64), nullable=True),
        sa.Column("signer_subject", sa.String(length=500), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_by", sa.String(), nullable=True),
        sa.Column("publisher_name", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "package_files",
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("publisher_name", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("package_id", "name"),
    )
    op.create_index("ix_package_files_sha256", "package_files", ["sha256"])
    op.add_column(
        "commands",
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "commands_package_id_fkey",
        "commands",
        "packages",
        ["package_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_commands_package_id", "commands", ["package_id"])


def downgrade() -> None:
    op.drop_index("ix_commands_package_id", table_name="commands")
    op.drop_constraint("commands_package_id_fkey", "commands", type_="foreignkey")
    op.drop_column("commands", "package_id")
    op.drop_index("ix_package_files_sha256", table_name="package_files")
    op.drop_table("package_files")
    op.drop_table("packages")
