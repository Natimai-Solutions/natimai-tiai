"""rooms, buildings: one name per parent whatever its case, held by the database

The routes refuse « a101 » beside « A101 » in one building, and « bâtiment b »
beside « Bâtiment B » on one site, by reading before they write: two requests
served together both found the name free. A unique index on the case-folded
name now holds the rule — per building for the rooms (and among the rooms
that have none), per site for the buildings (and among those that have none),
as ``uq_rooms_building_name`` and ``uq_buildings_location_name`` do for the
name as typed.

A database that already holds such twins — written before the rule, or by
that race — keeps the oldest name as it is and suffixes the others (« (2) »,
« (3) »…), which an administrator then renames at will: nothing is merged or
dropped. Names are folded by the database's own ``lower()``, the function
the index is built on, so that what the repair leaves the index accepts.

Revision ID: 0043_room_names_unique
Revises: 0042_mail_periods_seed
Create Date: 2026-11-18

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_room_names_unique"
down_revision: str | None = "0042_mail_periods_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

NAME_MAX_LENGTH = 100

# Table → the column a name is unique under.
PARENTS = {"buildings": "location", "rooms": "building_id"}


def rename_case_twins(conn: sa.Connection, table: str) -> list[tuple[str, str]]:
    """Give every row of ``table`` whose name equals another's under the same
    parent, but for the case, a name of its own. The oldest keeps its name.
    Returns ``(old, new)`` for each row renamed."""
    parent = PARENTS[table]
    twins = conn.execute(
        sa.text(
            f"SELECT id, name, parent FROM ("
            f"  SELECT id, name, {parent} AS parent, created_at,"
            f"         row_number() OVER ("
            f"           PARTITION BY {parent}, lower(name) ORDER BY created_at, id"
            f"         ) AS position"
            f"  FROM {table}"
            f") ranked WHERE position > 1 ORDER BY created_at, id"
        )
    ).all()
    # Asked of the database each time, after each rename: a suffixed name
    # must land neither on a name some row keeps (« A101 (2) » made by hand)
    # nor on one given a moment ago, and « free » is the index's own notion.
    taken = sa.text(
        f"SELECT 1 FROM {table} "
        f"WHERE {parent} IS NOT DISTINCT FROM :parent "
        f"AND lower(name) = lower(:name) LIMIT 1"
    ).bindparams(sa.bindparam("parent", type_=_parent_type(table)))
    renamed: list[tuple[str, str]] = []
    for row_id, name, parent_value in twins:
        n = 2
        while True:
            suffix = f" ({n})"
            candidate = name[: NAME_MAX_LENGTH - len(suffix)].rstrip() + suffix
            found = conn.execute(taken, {"parent": parent_value, "name": candidate})
            if found.first() is None:
                break
            n += 1
        conn.execute(
            sa.text(
                f"UPDATE {table} SET name = :name, updated_at = now() WHERE id = :id"
            ),
            {"name": candidate, "id": row_id},
        )
        logger.info(
            "%s: « %s » renamed « %s » (same name, another case)",
            table,
            name,
            candidate,
        )
        renamed.append((name, candidate))
    return renamed


def _parent_type(table: str) -> sa.types.TypeEngine:
    # Typed, so that a NULL parent is sent as a NULL of the column's type.
    return sa.Uuid() if table == "rooms" else sa.String()


def upgrade() -> None:
    conn = op.get_bind()
    # Buildings first, for the order only: a room's parent is its building's
    # id, which a rename does not change.
    rename_case_twins(conn, "buildings")
    rename_case_twins(conn, "rooms")
    op.create_index(
        "ix_buildings_location_name_lower",
        "buildings",
        ["location", sa.text("lower(name)")],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_rooms_building_name_lower",
        "rooms",
        ["building_id", sa.text("lower(name)")],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # The names given stay: they may have been relied upon since, and they
    # do not break the older schema.
    op.drop_index("ix_rooms_building_name_lower", table_name="rooms")
    op.drop_index("ix_buildings_location_name_lower", table_name="buildings")
