"""console sessions; e-mail addresses unique whatever their case

Revision ID: 0024_auth_sessions
Revises: 0023_machine_uptime
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_auth_sessions"
down_revision: str | None = "0023_machine_uptime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The stored form of an address (``app.features.user.models.normalize_email``),
# in SQL. Spelled once so the duplicate check and the rewrite cannot disagree.
_NORMALIZED = "lower(btrim(email))"


def upgrade() -> None:
    # --- E-mail addresses: one account per mailbox, whatever the case ---------
    #
    # Two accounts whose addresses differ only by case are one person with two
    # logins, or two people sharing a mailbox — either way a decision about
    # which account survives, with its groups and its audit trail, that is not
    # a migration's to take. Refuse, name them, and let an administrator merge
    # or rename by hand before upgrading again.
    bind = op.get_bind()
    clashes = bind.execute(
        sa.text(
            f"SELECT {_NORMALIZED} AS address, string_agg(email, ', ' ORDER BY email) "
            f"AS spellings FROM users GROUP BY {_NORMALIZED} "
            f"HAVING count(*) > 1 ORDER BY 1"
        )
    ).all()
    if clashes:
        listed = "; ".join(f"{row.address} ({row.spellings})" for row in clashes)
        raise RuntimeError(
            "Migration 0024 interrompue : des comptes de la console ne diffèrent "
            "que par la casse de leur adresse e-mail, qui devient insensible à la "
            f"casse — {listed}. Renommez ou supprimez les doublons (page "
            "Utilisateurs de la version précédente, ou en base : UPDATE users "
            "SET email = '…' WHERE id = '…'), puis relancez la migration. Rien "
            "n'a été modifié."
        )
    op.execute(f"UPDATE users SET email = {_NORMALIZED} WHERE email <> {_NORMALIZED}")
    # The plain unique index is replaced, not kept beside the new one: every
    # lookup now goes through lower(email), and the expression index enforces
    # a strictly stronger rule.
    op.drop_index("ix_users_email", table_name="users")
    op.create_index(
        "ix_users_email_lower", "users", [sa.text("lower(email)")], unique=True
    )

    # --- Console sessions ------------------------------------------------------
    # Nothing to backfill: the tokens issued before this migration carry no
    # session, are refused from now on, and every operator logs in once more.
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_refresh_token_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # « Mes sessions » and the mass revocation of an account both read by user.
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    # The addresses stay lower-cased: the original capitalisation is gone, and
    # the case-sensitive index accepts them as they are.
    op.drop_index("ix_users_email_lower", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True)
