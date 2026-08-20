"""The worker: one asyncio loop, the e-mail outbox and the periodic tasks.

What used to need ARQ and Redis is a single loop over Postgres: every
``POLL_SECONDS`` it drains the outbox (mails queued by the API and by the
digest, sent with retries), and runs whichever periodic jobs have come due —
command expiry every five minutes, the daily digest and housekeeping once a
day. One worker process per deployment, which is what the compose runs; the
drain assumes no concurrent drainer.

A job that comes due while the worker is down runs at the next matching time,
not on catch-up — the same semantics the ARQ crons had. The outbox is the
exception that makes this safe for mail: a due row is due until sent, so a
restart resumes deliveries within one tick.

Run with: python -m app.core.worker
"""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import engine
from app.features.base import utcnow
from app.features.command.models import Command, CommandStatus
from app.features.machine.models import Machine
from app.features.notification import digest, outbox

logger = logging.getLogger(__name__)

# The loop's tick — also the worst-case lag between a mail coming due in the
# outbox and its send attempt.
POLL_SECONDS = 30


# --- Jobs -------------------------------------------------------------------


async def process_outbox() -> int:
    """Send the due mails; the worker is the outbox's only drainer."""
    async with AsyncSession(engine) as session:
        return await outbox.send_pending(session)


async def expire_stale_commands() -> int:
    """Mark pending commands past their expires_at as expired."""
    now = utcnow()
    async with AsyncSession(engine) as session:
        result = await session.execute(
            update(Command)
            .where(col(Command.status) == CommandStatus.PENDING)
            .where(col(Command.expires_at) < now)
            .values(status=CommandStatus.EXPIRED)
        )
        await session.commit()
        return result.rowcount or 0  # type: ignore[attr-defined]


async def flag_inactive_machines() -> int:
    """Count machines that have not checked in recently (alert candidates)."""
    cutoff = utcnow() - timedelta(days=settings.INACTIVE_AFTER_DAYS)
    async with AsyncSession(engine) as session:
        rows = await session.exec(
            select(Machine).where(col(Machine.last_seen) < cutoff)
        )
        return len(rows.all())


async def send_daily_digest() -> int:
    """Queue the daily fleet digest for the accounts that asked for one.

    Runs once a day at ``DIGEST_HOUR_UTC``. Which accounts hear from it, and on
    which days, is decided per account — see ``features/notification/digest``.
    """
    async with AsyncSession(engine) as session:
        return await digest.send_daily_digest(session)


async def purge_outbox() -> int:
    """Drop sent/abandoned outbox rows older than the retention window."""
    async with AsyncSession(engine) as session:
        return await outbox.purge_settled(session)


# --- Scheduling -------------------------------------------------------------


@dataclass
class Job:
    """A periodic task and when it next runs."""

    name: str
    run: Callable[[], Awaitable[int]]
    next_run: datetime
    # Given the instant a run happened, returns the next due instant.
    schedule: Callable[[datetime], datetime]


def every(seconds: int) -> Callable[[datetime], datetime]:
    """Interval schedule, measured from each run (not from a fixed grid)."""

    def _next(now: datetime) -> datetime:
        return now + timedelta(seconds=seconds)

    return _next


def daily_at(hour: int) -> Callable[[datetime], datetime]:
    """The next HH:00 UTC strictly after ``now``.

    Strictly after: a job that just ran at 18:00 must aim for tomorrow, and a
    worker started at 18:05 skips today's occurrence rather than firing late —
    the semantics the ARQ crons had.
    """

    def _next(now: datetime) -> datetime:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    return _next


def build_jobs(now: datetime) -> list[Job]:
    """The worker's whole schedule, in one place."""
    digest_hour = daily_at(settings.DIGEST_HOUR_UTC)
    housekeeping = daily_at(8)
    return [
        # Due immediately: a restart must resume mail delivery within one tick.
        Job("outbox", process_outbox, now, every(POLL_SECONDS)),
        Job("expire_stale_commands", expire_stale_commands, now, every(300)),
        Job(
            "flag_inactive_machines",
            flag_inactive_machines,
            housekeeping(now),
            housekeeping,
        ),
        Job("daily_digest", send_daily_digest, digest_hour(now), digest_hour),
        Job("purge_outbox", purge_outbox, housekeeping(now), housekeeping),
    ]


async def run_due_jobs(jobs: list[Job], now: datetime) -> None:
    """Run every job whose time has come. A failing job never stops the loop."""
    for job in jobs:
        if job.next_run > now:
            continue
        # Rescheduled before running, so a job that raises still moves on
        # rather than being retried on every tick against the same failure.
        job.next_run = job.schedule(now)
        try:
            result = await job.run()
        except Exception:
            logger.exception("Job %s failed", job.name)
        else:
            if result:
                logger.info("Job %s: %d", job.name, result)


async def main(stop: asyncio.Event) -> None:
    jobs = build_jobs(utcnow())
    logger.info("Worker started: %d jobs, tick %ds", len(jobs), POLL_SECONDS)
    while not stop.is_set():
        await run_due_jobs(jobs, utcnow())
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass
    logger.info("Worker stopped")


async def _run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows dev environment; docker stop / Ctrl+C still end the
            # process, at worst without the "Worker stopped" line.
            pass
    await main(stop)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(_run())
