"""interventions: skipped postes linked to their visit, titles without the kind

Two corrections to the journal lines the console itself wrote:

* A poste left out of a maintenance visit got a line « Maintenance non faite
  — <salle> » with no link to the visit, so the visit could not show who was
  skipped. The line is now written with ``maintenance_id``; the old ones are
  linked here when exactly one visit has the same author, instant and room.
* The lines of a visit were titled « Maintenance — <salle> » and those of a
  closed check « Vérification »: the journal prefixes the kind, and read
  « Maintenance — Maintenance — A101 », « Vérification — Vérification ». The
  title now holds the room alone (or nothing). Only lines linked to a visit
  or a check are touched: a title typed by hand is left as it is.

Revision ID: 0038_maintenance_journal_links
Revises: 0037_accounts_hardening
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_maintenance_journal_links"
down_revision: str | None = "0037_accounts_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The visit a « Maintenance non faite » line was written by: same author,
# same instant, same room in the title — and only one such visit.
_SKIPPED_MATCH = """
    i.maintenance_id IS NULL
    AND i.kind = 'other'
    AND i.performed_by = m.performed_by
    AND i.performed_at = m.performed_at
    AND i.title = 'Maintenance non faite' || COALESCE(' — ' || m.room_name, '')
    AND (
        SELECT count(*) FROM maintenances m2
        WHERE m2.performed_by = m.performed_by
          AND m2.performed_at = m.performed_at
          AND m2.room_name IS NOT DISTINCT FROM m.room_name
    ) = 1
"""

_PREFIX = "Maintenance — "


def upgrade() -> None:
    bind = op.get_bind()
    linked = bind.execute(
        sa.text(
            f"UPDATE interventions i SET maintenance_id = m.id "
            f"FROM maintenances m WHERE {_SKIPPED_MATCH}"
        )
    ).rowcount
    retitled = bind.execute(
        sa.text(
            "UPDATE interventions SET title = NULL "
            "WHERE kind = 'verification' AND check_id IS NOT NULL "
            "AND title = 'Vérification'"
        )
    ).rowcount
    retitled += bind.execute(
        sa.text(
            "UPDATE interventions "
            "SET title = NULLIF(btrim(substr(title, :start)), '') "
            "WHERE kind = 'maintenance' AND maintenance_id IS NOT NULL "
            "AND left(title, :n) = :prefix"
        ),
        {"start": len(_PREFIX) + 1, "n": len(_PREFIX), "prefix": _PREFIX},
    ).rowcount
    retitled += bind.execute(
        sa.text(
            "UPDATE interventions SET title = NULL "
            "WHERE kind = 'maintenance' AND maintenance_id IS NOT NULL "
            "AND title = 'Maintenance'"
        )
    ).rowcount
    print(
        f"0038: {linked} skipped line(s) linked to their visit, "
        f"{retitled} title(s) without the kind"
    )


def downgrade() -> None:
    # The links and the shorter titles are what the code writes from now on;
    # the previous state was the defect.
    pass
