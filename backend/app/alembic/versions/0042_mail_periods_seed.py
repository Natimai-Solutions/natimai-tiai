"""app_settings: the mail jobs' periods, seeded on the day of the upgrade

Since v1.2.1 the worker keeps the day the digest last went out for, and the
week of the maintenance reminder (``worker.last_run.*``), and a worker started
after the digest hour sends that day's mail at once unless the record says it
went out. A server upgraded from v1.2.0 has no record: upgraded after the
hour — 18:00 UTC by default, 08:00 where the parc is, so any morning upgrade —
its new worker sent again the digest v1.2.0 had sent that same day, and the
reminder on its day.

So the periods already served are written here, read off the clock and the
schedule the worker itself would read (the console's row, else the
environment): today, when the digest hour has passed; this week, when the
reminder's day and hour have. An existing record is left alone, and so is a
database with no account yet — a new installation, where nothing was ever
sent.

The cost, accepted: a server upgraded in the very minute of its digest, the
old worker stopped before it could send, has no digest that day.

Revision ID: 0042_mail_periods_seed
Revises: 0041_enrollment_token_unused
Create Date: 2026-11-18

"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0042_mail_periods_seed"
down_revision: str | None = "0041_enrollment_token_unused"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The keys as they are at this revision (``setting.crud``, ``core.worker``).
KEY_DIGEST_HOUR = "notifications.digest_hour_utc"
KEY_REMINDER_WEEKDAY = "maintenance.reminder_weekday"
KEY_LAST_DIGEST = "worker.last_run.daily_digest"
KEY_LAST_REMINDER = "worker.last_run.maintenance_reminders"


def _int_or(value: Any, default: int) -> int:
    # As ``setting.crud`` reads a stored schedule: an integer, or the default.
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def seed_mail_periods(
    conn: sa.Connection, now: datetime | None = None
) -> dict[str, str]:
    """Record the periods whose mail the previous version has sent by
    ``now``; returns what was written."""
    from app.core.config import settings

    now = now or datetime.now(UTC)
    if not conn.execute(sa.text("SELECT EXISTS (SELECT 1 FROM users)")).scalar():
        return {}
    stored = dict(
        conn.execute(
            sa.text("SELECT key, value FROM app_settings WHERE key IN (:hour, :day)"),
            {"hour": KEY_DIGEST_HOUR, "day": KEY_REMINDER_WEEKDAY},
        )
        .tuples()
        .all()
    )
    hour = _int_or(stored.get(KEY_DIGEST_HOUR), settings.DIGEST_HOUR_UTC)
    weekday = _int_or(
        stored.get(KEY_REMINDER_WEEKDAY), settings.MAINTENANCE_REMINDER_WEEKDAY
    )

    served: dict[str, str] = {}
    if now.hour >= hour:
        served[KEY_LAST_DIGEST] = now.date().isoformat()
    if (now.weekday(), now.hour) >= (weekday, hour):
        year, week, _ = now.isocalendar()
        served[KEY_LAST_REMINDER] = f"{year}-W{week:02d}"

    written: dict[str, str] = {}
    for key, period in served.items():
        inserted = conn.execute(
            sa.text(
                "INSERT INTO app_settings (key, value, updated_at, updated_by) "
                "VALUES (:key, CAST(:value AS jsonb), :at, 'migration') "
                "ON CONFLICT (key) DO NOTHING RETURNING key"
            ),
            {"key": key, "value": json.dumps(period), "at": now},
        ).first()
        if inserted is not None:
            written[key] = period
    return written


def upgrade() -> None:
    seed_mail_periods(op.get_bind())


def downgrade() -> None:
    # Nothing to undo: the rows are the worker's own record, which it writes
    # at every digest whatever the revision.
    pass
