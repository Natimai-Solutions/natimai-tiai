"""machines: whether the enrollment's token was ever used, as a stored fact

The lost-enrollment retry read « never used » off two timestamps
(``last_seen <= token_issued_at``), which a token rotation promoted by a
command verdict made true again for an established poste. Every poste that
exists when this runs counts as *used* (false): the worst case is a poste
enrolled minutes before the upgrade whose answer was lost, which then waits
for an approval instead of being answered a second time.

Revision ID: 0041_enrollment_token_unused
Revises: 0040_shared_counters
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_enrollment_token_unused"
down_revision: str | None = "0040_shared_counters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "machines",
        sa.Column(
            "enrollment_token_unused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("machines", "enrollment_token_unused")
