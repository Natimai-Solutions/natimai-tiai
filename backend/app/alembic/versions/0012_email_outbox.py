"""e-mail outbox

Revision ID: 0012_email_outbox
Revises: 0011_email_preference
Create Date: 2026-08-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_email_outbox"
down_revision: str | None = "0011_email_preference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every outgoing mail is a row here first, written in the same transaction
    # as whatever motivated it; the worker drains the table with retries. One
    # row per recipient — never a shared To:.
    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_address", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # The drain's exact WHERE: pending rows whose next attempt is due.
    op.create_index(
        "ix_email_outbox_status_next_attempt",
        "email_outbox",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("email_outbox")
