"""Sign-in through the directory (C7): OpenID Connect

``users``: where the account comes from (``auth_source``) and the directory
identity it answers to. ``oidc_logins``: the sign-ins in flight.
``group_idp_links``: the directory groups each Tia'i group stands for.

Revision ID: 0058_oidc
Revises: 0057_second_factor
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058_oidc"
down_revision: str | None = "0057_second_factor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_idp_links",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("idp_group_id", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "idp_group_id"),
    )
    op.create_table(
        "oidc_logins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=100), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("redirect", sa.String(length=2000), nullable=True),
        sa.Column("link_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "link_password_changed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["link_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        op.f("ix_oidc_logins_link_user_id"), "oidc_logins", ["link_user_id"]
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_source",
            sa.String(length=20),
            server_default=sa.text("'local'"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("oidc_issuer", sa.String(length=255)))
    op.add_column("users", sa.Column("oidc_subject", sa.String(length=255)))
    op.create_index(
        "uq_users_oidc_identity",
        "users",
        ["oidc_issuer", "oidc_subject"],
        unique=True,
        postgresql_where=sa.text("oidc_subject IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_users_oidc_identity",
        table_name="users",
        postgresql_where=sa.text("oidc_subject IS NOT NULL"),
    )
    op.drop_column("users", "oidc_subject")
    op.drop_column("users", "oidc_issuer")
    op.drop_column("users", "auth_source")
    op.drop_index(op.f("ix_oidc_logins_link_user_id"), table_name="oidc_logins")
    op.drop_table("oidc_logins")
    op.drop_table("group_idp_links")
