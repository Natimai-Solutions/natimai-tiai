"""slow login attempts, reset budget per address, change budget per session

Audit T06, T34, T07: limits accepted at the third pass, now fixed.

* ``users.slow_failed_login_attempts`` / ``slow_window_started_at`` /
  ``lock_admits_known_only``: failures spaced more than LOGIN_LOCKOUT_MINUTES
  apart never locked an account (four guesses a quarter of an hour, for
  ever). A second counter over LOGIN_SLOW_WINDOW_HOURS now does, and its lock
  admits only the account's usual addresses.
* ``password_reset_tokens.requested_ip``: the « mot de passe oublié » budget
  was the account's, so three requests an hour from a third party left
  nothing for the owner's own. It is now counted per account and requesting
  address, which the link has to remember.
* ``auth_sessions.password_failures``: the five tries of the current password
  on « changer mon mot de passe » were the account's, shared between a stolen
  session and its owner. They are now the session's.

Revision ID: 0039_login_slow_attempts
Revises: 0038_maintenance_journal_links
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_login_slow_attempts"
down_revision: str | None = "0038_maintenance_journal_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "slow_failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("slow_window_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "lock_admits_known_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("users", "slow_failed_login_attempts", server_default=None)
    op.alter_column("users", "lock_admits_known_only", server_default=None)

    op.add_column(
        "password_reset_tokens",
        sa.Column("requested_ip", sa.String(length=64), nullable=True),
    )

    op.add_column(
        "auth_sessions",
        sa.Column(
            "password_failures", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.alter_column("auth_sessions", "password_failures", server_default=None)


def downgrade() -> None:
    op.drop_column("auth_sessions", "password_failures")
    op.drop_column("password_reset_tokens", "requested_ip")
    op.drop_column("users", "lock_admits_known_only")
    op.drop_column("users", "slow_window_started_at")
    op.drop_column("users", "slow_failed_login_attempts")
