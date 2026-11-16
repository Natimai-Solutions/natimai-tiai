"""Queue and drain the e-mail outbox.

``queue_email`` is what the rest of the application calls: it only adds a row
to the caller's session, so the mail is committed — or rolled back — with the
business change that motivated it. ``send_pending`` and ``purge_settled`` are
the worker's side of the table.

Delivery is at-least-once: the drain commits each mail's outcome as soon as
it has one, so a worker killed between a provider's accept and that commit
re-sends that one mail on restart — not the batch. The reverse trade — marking
rows sent before trying — would lose mail instead, and a rare duplicate alert
is the better failure.
"""

import logging
import time
from datetime import timedelta

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.base import utcnow
from app.features.notification.email import send_email
from app.features.notification.models import EmailOutbox, EmailStatus
from app.features.setting.email_policy import current_policy, email_policy

logger = logging.getLogger(__name__)

# Backoff between attempts: 1 min doubling to a 1 h ceiling. With the default
# EMAIL_MAX_ATTEMPTS this spans roughly half a day — enough to ride out an
# evening-long proxy or mail-provider outage without keeping rows alive forever.
RETRY_BASE_SECONDS = 60
RETRY_MAX_SECONDS = 3600


def queue_email(session: AsyncSession, *, to: str, subject: str, text: str) -> bool:
    """Add one mail to the outbox, inside the caller's open transaction.

    No commit here: the row must live or die with whatever the caller is about
    to commit (a reset token, a batch of detections). Returns False without
    queueing when no e-mail provider is configured — the deployment has said no mail
    leaves this console, and a row nothing will ever send is not a mail, it is
    a backlog.

    Synchronous — its callers queue mid-transaction, some of them from code
    that cannot await — so « configured » is read off this process's last
    resolution of the policy (``current_policy``), not the database; see
    ``app.features.setting.email_policy`` for why that is current.
    """
    if not current_policy().enabled or not to:
        return False
    session.add(EmailOutbox(to_address=to, subject=subject, body=text))
    return True


def _retry_delay(attempts: int) -> timedelta:
    return timedelta(
        seconds=min(RETRY_BASE_SECONDS * 2 ** (attempts - 1), RETRY_MAX_SECONDS)
    )


async def send_pending(
    session: AsyncSession,
    *,
    batch_size: int = 50,
    budget_seconds: float | None = None,
) -> int:
    """Try every due mail once; returns how many went out.

    Each mail's outcome is committed as soon as it is known: a worker killed
    mid-drain re-sends at most the one mail it was sending, not every mail of
    the batch delivered before it. The rows are read into plain values first
    and written back by id — a commit expires ORM instances, and reading one
    afterwards would be a lazy load outside the event loop (MissingGreenlet).
    A failure never raises past its own row, so one dead address cannot cost
    the rest of the batch their turn.

    ``budget_seconds``: no new mail is started once that much time has gone
    by. A server that accepts the connection and then stays silent costs a
    full timeout per mail; without a budget, fifty of them held the worker for
    many minutes. What is left waits for the next drain, still due.

    The policy is resolved once per drain, from the database: a provider, a
    server or a password changed in the console applies from the next tick,
    without restarting the worker.
    """
    started = time.monotonic()
    policy = await email_policy(session)
    now = utcnow()
    rows = await session.exec(
        select(EmailOutbox)
        .where(col(EmailOutbox.status) == EmailStatus.PENDING)
        .where(col(EmailOutbox.next_attempt_at) <= now)
        .order_by(col(EmailOutbox.created_at))
        .limit(batch_size)
    )
    due = [(r.id, r.to_address, r.subject, r.body, r.attempts) for r in rows.all()]
    session.expunge_all()
    sent = 0
    for row_id, to_address, subject, body, attempts in due:
        if budget_seconds is not None and time.monotonic() - started >= budget_seconds:
            logger.warning(
                "Outbox: drain stopped after %.0f s, the rest waits for the next tick",
                time.monotonic() - started,
            )
            break
        try:
            ok = await send_email(
                subject=subject, text=body, to=[to_address], policy=policy
            )
            # False means the provider is no longer configured — the guard in
            # queue_email was passed once, so treat it like any other failure
            # and let the backoff decide, rather than spinning on every tick.
            error = None if ok else "E-mail provider is not configured"
        except Exception as exc:
            ok = False
            error = f"{type(exc).__name__}: {exc}"[:500]

        values: dict[str, object]
        if ok:
            values = {"status": EmailStatus.SENT, "sent_at": utcnow()}
            sent += 1
        else:
            attempts += 1
            values = {"attempts": attempts, "last_error": error}
            if attempts >= settings.EMAIL_MAX_ATTEMPTS:
                values["status"] = EmailStatus.ABANDONED
                logger.error(
                    "Outbox: giving up on mail to %s after %d attempts (%s)",
                    to_address,
                    attempts,
                    error,
                )
            else:
                values["next_attempt_at"] = utcnow() + _retry_delay(attempts)
                logger.warning(
                    "Outbox: mail to %s failed (attempt %d/%d): %s",
                    to_address,
                    attempts,
                    settings.EMAIL_MAX_ATTEMPTS,
                    error,
                )
        await session.exec(
            update(EmailOutbox).where(col(EmailOutbox.id) == row_id).values(**values)
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
    result = await session.exec(
        delete(EmailOutbox)
        .where(col(EmailOutbox.status).in_([EmailStatus.SENT, EmailStatus.ABANDONED]))
        .where(col(EmailOutbox.created_at) < cutoff)
    )
    await session.commit()
    return result.rowcount or 0
