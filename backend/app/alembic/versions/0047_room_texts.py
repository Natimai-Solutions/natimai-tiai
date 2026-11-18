"""Codes beside the texts the server stores for the journal and the checks

Phase 6 (bilingual console, ``dev/plan-console-bilingue.md``). The server
writes two texts itself, kept and shown later: the title of a line « left out
of a maintenance visit » (« Maintenance non faite — A101 ») and the note of a
check closed by a merge (« Fermée par la fusion du poste dans un autre. »).
From now on each carries a code — and the title its parameters — that the
console words in the reader's language; the French stays beside it for an
older console.

* ``interventions.title_code``, ``interventions.title_params`` (JSONB),
* ``machine_checks.closing_note_code``.

All nullable, and null on every existing row: the lines and notes written
before keep their French and are shown as they are.

Revision ID: 0047_room_texts
Revises: 0045_user_language
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0047_room_texts"
down_revision: str | None = "0045_user_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interventions", sa.Column("title_code", sa.String(length=64), nullable=True)
    )
    op.add_column("interventions", sa.Column("title_params", JSONB, nullable=True))
    op.add_column(
        "machine_checks",
        sa.Column("closing_note_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("machine_checks", "closing_note_code")
    op.drop_column("interventions", "title_params")
    op.drop_column("interventions", "title_code")
