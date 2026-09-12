"""directory: what the domain says about a poste, and rooms keyed by it

Revision ID: 0018_directory
Revises: 0017_rooms
Create Date: 2026-09-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_directory"
down_revision: str | None = "0017_rooms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Read by the agent on its inventory cycle: the computer object's DN, the
    # OU holding it, the object's "location" attribute. NULL = never reported.
    op.add_column("machines", sa.Column("ad_distinguished_name", sa.String(), nullable=True))
    op.add_column("machines", sa.Column("ad_ou", sa.String(), nullable=True))
    op.add_column("machines", sa.Column("ad_ou_dn", sa.String(), nullable=True))
    op.add_column("machines", sa.Column("ad_location", sa.String(), nullable=True))
    # What the directory names a room by when ROOM_SOURCE created it. Unique:
    # one OU, one room, whatever the room was renamed to since.
    op.add_column("rooms", sa.Column("ad_key", sa.String(length=500), nullable=True))
    op.create_unique_constraint("uq_rooms_ad_key", "rooms", ["ad_key"])


def downgrade() -> None:
    op.drop_constraint("uq_rooms_ad_key", "rooms", type_="unique")
    op.drop_column("rooms", "ad_key")
    op.drop_column("machines", "ad_location")
    op.drop_column("machines", "ad_ou_dn")
    op.drop_column("machines", "ad_ou")
    op.drop_column("machines", "ad_distinguished_name")
