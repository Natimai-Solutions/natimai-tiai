"""groups: names unique whatever their case; « Techniciens » reads packages

Two repairs on the accounts' data, found by the acceptance test of 2026-11.

* « Lecture seule » and « lecture SEULE » could live side by side: the name was
  unique as typed only. A unique index on ``lower(name)`` makes it the rule,
  as for the accounts' addresses. A database that already holds such twins
  keeps the oldest name as it is and suffixes the others (« (2) », « (3) »…),
  which an administrator then renames at will: nothing is merged or dropped.
* The built-in technicians' group gained ``package:read`` (to pick the package
  a deployment installs) in ``BUILTIN_GROUP_DEFAULTS`` after migration 0016
  had created it: databases older than that never got it. Granted here when
  missing. The group is found by its ``builtin_key``, which its name may have
  lost since — an administrator can rename it.

Revision ID: 0037_accounts_hardening
Revises: 0036_verdict_signature_age
Create Date: 2026-11-16

"""

from collections.abc import Iterator, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_accounts_hardening"
down_revision: str | None = "0036_verdict_signature_age"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME_MAX_LENGTH = 100


def grant_technicians_package_read(conn: sa.Connection) -> int:
    """Grant ``package:read`` to the built-in technicians' group if it lacks
    it; returns the rows added (0 or 1)."""
    result = conn.execute(
        sa.text(
            "INSERT INTO group_permissions (group_id, permission) "
            "SELECT id, 'package:read' FROM groups WHERE builtin_key = 'technician' "
            "ON CONFLICT DO NOTHING"
        )
    )
    return result.rowcount or 0


def _suffixed(name: str) -> Iterator[str]:
    """``name (2)``, ``name (3)``… each cut to the column."""
    n = 2
    while True:
        suffix = f" ({n})"
        yield name[: NAME_MAX_LENGTH - len(suffix)].rstrip() + suffix
        n += 1


def rename_case_twins(conn: sa.Connection) -> list[tuple[str, str]]:
    """Give every group whose name equals another's but for the case a name
    of its own. The built-in groups, then the oldest, keep theirs. Returns
    ``(old, new)`` for each renamed group.

    « But for the case » is what the index will say, so it is asked of the
    database: its ``lower()`` and Python's disagree on a few letters (a
    capital sigma ending a word, a dotted capital I), and twins found with
    Python's left names the index then refused — the upgrade aborted.
    """
    rows = conn.execute(
        sa.text(
            "SELECT id, name, lower(name) FROM groups "
            "ORDER BY builtin_key IS NULL, created_at, id"
        )
    ).all()
    # Every name some group keeps is reserved first, so that a suffixed name
    # never lands on one of them (« Atelier (2) » created by hand).
    keepers: dict[str, object] = {}
    for group_id, _name, folded in rows:
        keepers.setdefault(folded, group_id)
    taken = set(keepers)
    renamed: list[tuple[str, str]] = []
    for group_id, name, folded in rows:
        if keepers[folded] == group_id:
            continue
        for new in _suffixed(name):
            new_folded = conn.execute(
                sa.text("SELECT lower(CAST(:name AS text))"), {"name": new}
            ).scalar_one()
            if new_folded not in taken:
                break
        taken.add(new_folded)
        conn.execute(
            sa.text("UPDATE groups SET name = :name WHERE id = :id"),
            {"name": new, "id": group_id},
        )
        renamed.append((name, new))
    return renamed


def upgrade() -> None:
    conn = op.get_bind()
    grant_technicians_package_read(conn)
    rename_case_twins(conn)
    op.create_index(
        "ix_groups_name_lower", "groups", [sa.text("lower(name)")], unique=True
    )


def downgrade() -> None:
    # The permission granted and the names given stay: either may have been
    # relied upon since, and neither breaks the older schema.
    op.drop_index("ix_groups_name_lower", table_name="groups")
