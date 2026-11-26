"""Attachments of the journal and procedure notes per model (C11)

``intervention_attachments``: the files joined to a line of a poste's
journal, one row per file and line, the bytes once per SHA-256 under
``ATTACHMENTS_DIR``. ``procedures``: one plain-text note per hardware model.
The built-in technicians' group receives ``procedure:read`` and
``procedure:write``; no other group receives anything.

Revision ID: 0062_attachments_procedures
Revises: 0061_mass_approval
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062_attachments_procedures"
down_revision: str | None = "0061_mass_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = ("procedure:read", "procedure:write")


def grant_technicians_procedures(conn: sa.Connection) -> int:
    """Grant the procedure permissions to the built-in technicians' group —
    found by its key, whatever its name — where it lacks them; returns the
    rows added."""
    added = 0
    for permission in PERMISSIONS:
        result = conn.execute(
            sa.text(
                "INSERT INTO group_permissions (group_id, permission) "
                "SELECT id, :permission FROM groups WHERE builtin_key = 'technician' "
                "ON CONFLICT DO NOTHING"
            ),
            {"permission": permission},
        )
        added += result.rowcount or 0
    return added


def upgrade() -> None:
    op.create_table(
        "intervention_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("intervention_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["intervention_id"], ["interventions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "intervention_id",
            "sha256",
            name="uq_intervention_attachments_intervention_sha",
        ),
    )
    op.create_index(
        "ix_intervention_attachments_intervention",
        "intervention_attachments",
        ["intervention_id", "created_at"],
    )
    op.create_index(
        "ix_intervention_attachments_sha256", "intervention_attachments", ["sha256"]
    )
    op.create_index(
        "ix_intervention_attachments_created_at",
        "intervention_attachments",
        ["created_at"],
    )

    op.create_table(
        "procedures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hw_model", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=5000), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_procedures_hw_model", "procedures", ["hw_model"], unique=True)

    grant_technicians_procedures(op.get_bind())


def downgrade() -> None:
    conn = op.get_bind()
    # The older catalogue would refuse these at the next write of the group.
    conn.execute(
        sa.text(
            "DELETE FROM group_permissions "
            "WHERE permission IN ('procedure:read', 'procedure:write')"
        )
    )
    conn.execute(
        sa.text("DELETE FROM app_settings WHERE key = 'attachments.retention_days'")
    )
    op.drop_index("uq_procedures_hw_model", table_name="procedures")
    op.drop_table("procedures")
    op.drop_index(
        "ix_intervention_attachments_created_at", table_name="intervention_attachments"
    )
    op.drop_index(
        "ix_intervention_attachments_sha256", table_name="intervention_attachments"
    )
    op.drop_index(
        "ix_intervention_attachments_intervention",
        table_name="intervention_attachments",
    )
    # The files of the attachments volume stay: the older version neither
    # reads nor deletes them; a later upgrade sweeps them, unnamed.
    op.drop_table("intervention_attachments")
