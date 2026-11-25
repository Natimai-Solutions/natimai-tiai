"""Second factor (C7): TOTP, backup codes, login challenges, group obligation

``users``: the sealed TOTP secret, when it was confirmed, the last step
accepted (replay), the failure counter and its lock.
``user_backup_codes``: single-use codes, hashed.
``login_challenges``: the step between a right password and the code.
``groups.mfa_required``, ``auth_sessions.auth_method`` and
``auth_sessions.enrolment_only``.

Revision ID: 0057_second_factor
Revises: 0056_licenses
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057_second_factor"
down_revision: str | None = "0056_licenses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_login_challenges_user_id"), "login_challenges", ["user_id"]
    )
    op.create_table(
        "user_backup_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_backup_codes_user_id"), "user_backup_codes", ["user_id"]
    )
    op.add_column(
        "auth_sessions",
        sa.Column(
            "auth_method",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'password'"),
        ),
    )
    op.add_column(
        "auth_sessions",
        sa.Column(
            "enrolment_only", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "groups",
        sa.Column(
            "mfa_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("users", sa.Column("totp_secret", sa.String(length=255)))
    op.add_column(
        "users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True))
    )
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger()))
    op.add_column(
        "users",
        sa.Column(
            "totp_failed_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.alter_column("users", "totp_failed_attempts", server_default=None)
    op.add_column(
        "users", sa.Column("totp_locked_until", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("users", "totp_locked_until")
    op.drop_column("users", "totp_failed_attempts")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_secret")
    op.drop_column("groups", "mfa_required")
    op.drop_column("auth_sessions", "enrolment_only")
    op.drop_column("auth_sessions", "auth_method")
    op.drop_index(op.f("ix_user_backup_codes_user_id"), table_name="user_backup_codes")
    op.drop_table("user_backup_codes")
    op.drop_index(op.f("ix_login_challenges_user_id"), table_name="login_challenges")
    op.drop_table("login_challenges")
