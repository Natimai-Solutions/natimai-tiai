"""users.language: the account's language, for the console and its mail

Phase 6 (bilingual console, ``dev/plan-console-bilingue.md``). Nullable, and
null on every existing account: « follow the browser » in the console, and
DEFAULT_LANGUAGE (French unless set) for the mail sent to it — what an
installation saw before the update.

Revision ID: 0045_user_language
Revises: 0044_accounts_fixes
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_user_language"
down_revision: str | None = "0044_accounts_fixes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("language", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "language")
