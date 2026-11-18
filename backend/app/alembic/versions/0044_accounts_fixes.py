"""slow lock: its own end, in place of « admits known addresses only »

Verification of v1.2.1 (finding F1 of the accounts review). The lock the
slow counter set (migration 0039) reused ``users.locked_until`` with a flag,
``lock_admits_known_only``: every address the account had never seen was
refused for LOGIN_SLOW_WINDOW_HOURS, so one outside address guessing slowly
shut out a holder without a usual poste — a new account, a holder on a new
address, an account an administrator had just reset.

The slow lock now shuts out the addresses that failed since its window
began, and has its own end, ``users.slow_locked_until``, which a successful
login does not lift (it lifts ``locked_until``, the quick lock's). The flag
goes. A slow lock running under the old rule is not carried over: its
window's start was erased when it was set, so there is nothing to read the
failing addresses since; what is left of it in ``locked_until`` is an
ordinary lock, which shuts out the addresses that failed lately.

Revision ID: 0044_accounts_fixes
Revises: 0043_room_names_unique
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_accounts_fixes"
down_revision: str | None = "0043_room_names_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("slow_locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("users", "lock_admits_known_only")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "lock_admits_known_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("users", "lock_admits_known_only", server_default=None)
    op.drop_column("users", "slow_locked_until")
