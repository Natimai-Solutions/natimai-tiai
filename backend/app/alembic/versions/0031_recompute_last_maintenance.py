"""machines.last_maintenance_at recomputed from the journal — audit T16

Until now the column only ever moved forward: a maintenance entry deleted,
redated or dated in the future left it where it was, and an entry typed in
the journal by hand never moved it. From now on it is the latest maintenance
entry of the journal, and this migration brings every poste in line once.

How many postes change is printed, as the audit asked to know before.

Revision ID: 0031_recompute_last_maintenance
Revises: 0030_command_package_snapshot
Create Date: 2026-11-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_recompute_last_maintenance"
down_revision: str | None = "0030_command_package_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LATEST = """
    SELECT max(i.performed_at) FROM interventions i
    WHERE i.machine_id = machines.id AND i.kind = 'maintenance'
"""


def upgrade() -> None:
    bind = op.get_bind()
    changing = bind.execute(
        sa.text(
            f"SELECT count(*) FROM machines "
            f"WHERE last_maintenance_at IS DISTINCT FROM ({_LATEST})"
        )
    ).scalar_one()
    print(f"0031: last_maintenance_at recomputed from the journal on {changing} postes")
    bind.execute(
        sa.text(
            f"UPDATE machines SET last_maintenance_at = ({_LATEST}) "
            f"WHERE last_maintenance_at IS DISTINCT FROM ({_LATEST})"
        )
    )


def downgrade() -> None:
    # The previous values were the journal's maximum at some earlier time,
    # or a mistake: nothing worth restoring.
    pass
