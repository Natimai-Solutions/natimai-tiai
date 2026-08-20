"""Queue and drain the e-mail outbox.

``queue_email`` is what the rest of the application calls: it only adds a row
to the caller's session, so the mail is committed — or rolled back — with the
business change that motivated it. ``send_pending`` and ``purge_settled`` are
the worker's side of the table.

Delivery is at-least-once: the drain commits after the batch, so a worker
killed between a Mailgun accept and the commit re-sends that mail on restart.
The reverse trade — marking rows sent before trying — would lose mail instead,
and a rare duplicate alert is the better failure.
"""

import logging
from datetime import timedelta

from sqlalchemy import delete
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.base import utcnow
from app.features.notification.mailgun import send_email
from app.features.notification.models import EmailOutbox, EmailStatus

logger = logging.getLogger(__name__)

# Backoff between attempts: 1 min doubling to a 1 h ceiling. With the default
# EMAIL_MAX_ATTEMPTS this spans roughly half a day — enough to ride out an
# evening-long proxy or Mailgun outage without keeping rows alive forever.
RETRY_BASE_SECONDS = 60
RETRY_MAX_SECONDS = 3600


def queue_email(session: AsyncSession, *, to: str, subject: str, text: str) -> bool:
    """Add one mail to the outbox, inside the caller's open transaction.

    No commit here: the row must live or die with whatever the caller is about
    to commit (a reset token, a batch of detections). Returns False without
    queueing when Mailgun is not configured — the deployment has said no mail
    leaves this console, and a row nothing will ever send is not a mail, it is
    a backlog.
    """
    if not settings.alerts_enabled or not to:
        return False
    session.add(EmailOutbox(to_address=to, subject=subject, body=text))
    return True


def _retry_delay(attempts: int) -> timedelta:
    return timedelta(
        seconds=min(RETRY_BASE_SECONDS * 2 ** (attempts - 1), RETRY_MAX_SECONDS)
    )


async def send_pending(session: AsyncSession, *, batch_size: int = 50) -> int:
    """Try every due mail once; returns how many went out.

    One commit for the whole batch, *after* the loop: committing inside it
    would expire the remaining instances mid-iteration (sync refresh under
    asyncio — MissingGreenlet). A failure never raises past its own row, so one
    dead address cannot cost the rest of the batch their turn.
    """
    now = utcnow()
    rows = await session.exec(
        select(EmailOutbox)
        .where(col(EmailOutbox.status) == EmailStatus.PENDING)
        .where(col(EmailOutbox.next_attempt_at) <= now)
        .order_by(col(EmailOutbox.created_at))
        .limit(batch_size)
    )
    sent = 0
    for row in rows.all():
        try:
            ok = await send_email(
                subject=row.subject, text=row.body, to=[row.to_address]
            )
            # False means Mailgun is no longer configured — the guard in
            # queue_email was passed once, so treat it like any other failure
            # and let the backoff decide, rather than spinning on every tick.
            error = None if ok else "Mailgun is not configured"
        except Exception as exc:
            ok = False
            error = f"{type(exc).__name__}: {exc}"[:500]

        if ok:
            row.status = EmailStatus.SENT
            row.sent_at = utcnow()
            sent += 1
            continue

        row.attempts += 1
        row.last_error = error
        if row.attempts >= settings.EMAIL_MAX_ATTEMPTS:
            row.status = EmailStatus.ABANDONED
            logger.error(
                "Outbox: giving up on mail to %s after %d attempts (%s)",
                row.to_address,
                row.attempts,
                error,
            )
        else:
            row.next_attempt_at = utcnow() + _retry_delay(row.attempts)
            logger.warning(
                "Outbox: mail to %s failed (attempt %d/%d): %s",
                row.to_address,
                row.attempts,
                settings.EMAIL_MAX_ATTEMPTS,
                error,
            )
    await session.commit()
    return sent


async def purge_settled(session: AsyncSession) -> int:
    """Delete sent and abandoned rows older than the retention window.

    Pending rows are never purged — a mail still owed is not clutter — and the
    window exists so "did the digest of the 12th go out, and to whom?" can be
    answered from the table for a while.
    """
    cutoff = utcnow() - timedelta(days=settings.EMAIL_OUTBOX_RETENTION_DAYS)
    result = await session.execute(
        delete(EmailOutbox)
        .where(col(EmailOutbox.status).in_([EmailStatus.SENT, EmailStatus.ABANDONED]))
        .where(col(EmailOutbox.created_at) < cutoff)
    )
    await session.commit()
    return result.rowcount or 0  # type: ignore[attr-defined]
