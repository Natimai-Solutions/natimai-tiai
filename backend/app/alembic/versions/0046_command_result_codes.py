"""commands.result_code, result_params: a verdict the console words

Phase 6 (bilingual console, ``dev/plan-console-bilingue.md``, I3 and I5). A
verdict the server writes itself (a command lost, cancelled, a wake refused)
or the agent sends with a code is stored as a code and its parameters beside
the French text, which stays. Nullable, and null on every existing row: an
old verdict keeps its text and reads as it always did.

Revision ID: 0046_command_result_codes
Revises: 0045_user_language
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046_command_result_codes"
down_revision: str | None = "0045_user_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "commands", sa.Column("result_code", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "commands",
        sa.Column(
            "result_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("commands", "result_params")
    op.drop_column("commands", "result_code")
