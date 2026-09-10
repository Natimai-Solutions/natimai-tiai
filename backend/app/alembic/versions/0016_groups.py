"""groups: permissions composed in the console instead of two fixed roles

Revision ID: 0016_groups
Revises: 0015_location_wol_relay
Create Date: 2026-09-10

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_groups"
down_revision: str | None = "0015_location_wol_relay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors app.features.user.permissions.BUILTIN_GROUP_DEFAULTS at the time of
# this migration — copied rather than imported, so the migration keeps meaning
# the same thing when the module moves on. The administrators' permissions are
# implicit (every one, always) and are not stored.
SUPERVISION_READ = ["command:read", "machine:read", "threat:read"]
BUILTIN = [
    ("admin", "Administrateurs", "Tous les droits, y compris ceux des ressources à venir.", []),
    ("readonly", "Lecture seule", "Consulte le parc sans rien pouvoir y changer.", SUPERVISION_READ),
    (
        "technician",
        "Techniciens",
        "Consulte le parc et exécute les commandes, courantes et à risque.",
        SUPERVISION_READ + ["command:execute", "risky_command:execute"],
    ),
]


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("builtin_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("builtin_key"),
    )
    op.create_table(
        "group_permissions",
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "permission"),
    )
    op.create_table(
        "user_groups",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "group_id"),
    )
    op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"])

    # Seed the built-in groups, then move every account from its role to the
    # group of the same name — admins to Administrateurs, the rest to Lecture
    # seule — so nobody's rights change with the upgrade.
    conn = op.get_bind()
    ids: dict[str, uuid.UUID] = {}
    for key, name, description, permissions in BUILTIN:
        gid = uuid.uuid4()
        ids[key] = gid
        conn.execute(
            sa.text(
                "INSERT INTO groups (id, name, description, builtin_key, created_at, updated_at) "
                "VALUES (:id, :name, :description, :key, now(), now())"
            ),
            {"id": gid, "name": name, "description": description, "key": key},
        )
        for permission in permissions:
            conn.execute(
                sa.text(
                    "INSERT INTO group_permissions (group_id, permission) "
                    "VALUES (:gid, :permission)"
                ),
                {"gid": gid, "permission": permission},
            )
    conn.execute(
        sa.text(
            "INSERT INTO user_groups (user_id, group_id) "
            "SELECT id, :admin FROM users WHERE role = 'admin'"
        ),
        {"admin": ids["admin"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO user_groups (user_id, group_id) "
            "SELECT id, :readonly FROM users WHERE role <> 'admin'"
        ),
        {"readonly": ids["readonly"]},
    )
    op.drop_column("users", "role")


def downgrade() -> None:
    # The role comes back from membership of the administrators' group;
    # everything a composed group granted is lost, which is the point of
    # going back.
    op.add_column(
        "users",
        sa.Column("role", sa.String(), nullable=False, server_default="readonly"),
    )
    op.execute(
        "UPDATE users SET role = 'admin' WHERE id IN ("
        "SELECT ug.user_id FROM user_groups ug "
        "JOIN groups g ON g.id = ug.group_id WHERE g.builtin_key = 'admin')"
    )
    op.alter_column("users", "role", server_default=None)
    op.drop_index("ix_user_groups_group_id", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_table("group_permissions")
    op.drop_table("groups")
