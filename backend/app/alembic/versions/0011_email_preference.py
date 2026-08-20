"""per-account e-mail cadence

Revision ID: 0011_email_preference
Revises: 0010_ip_prefix_length
Create Date: 2026-08-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_email_preference"
down_revision: str | None = "0010_ip_prefix_length"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOT NULL with a server_default, unlike the nullable columns the machine
    # tables use: there is no such thing as "cadence not reported yet" — every
    # account has one, and existing accounts get the same default a new one
    # would. The server_default stays on the column afterwards so a row inserted
    # by anything other than the ORM lands on the same value.
    #
    # A plain VARCHAR and not a PostgreSQL ENUM: adding a fifth cadence later is
    # then a code change, not a migration on a type other tables may reference.
    op.add_column(
        "users",
        sa.Column(
            "email_preference",
            sa.String(length=32),
            nullable=False,
            server_default="digest_daily",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "email_preference")
