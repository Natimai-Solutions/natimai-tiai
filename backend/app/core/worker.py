"""The worker: one asyncio loop, the e-mail outbox and the periodic tasks.

What used to need ARQ and Redis is a single loop over Postgres: every
``POLL_SECONDS`` it drains the outbox (mails queued by the API and by the
digest, sent with retries), and runs whichever periodic jobs have come due —
command expiry every five minutes, the daily digest and housekeeping once a
day — the retention purges of the outbox, the usage counters, the audit log,
the command history and the spent password-reset tokens. One worker process per deployment, which is what the compose runs; the
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
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import update
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import engine
from app.features import password_reset_retention
from app.features.audit import crud as audit_crud
from app.features.auth_session import crud as auth_session_crud
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command.models import Command, CommandStatus
from app.features.notification import digest, outbox
from app.features.setting import crud as setting_crud
from app.features.setting.crud import SchedulePolicy
from app.features.usage import crud as usage_crud

logger = logging.getLogger(__name__)

# The loop's tick — also the worst-case lag between a mail coming due in the
# outbox and its send attempt.
POLL_SECONDS = 30

# Touched at the end of every tick, so the container's healthcheck can tell a
# worker that is looping from one that is stuck — the worker serves no port to
# probe. A tick normally ends within POLL_SECONDS; the compose healthcheck
# allows several of them before calling the worker unhealthy, because a digest
# or a long outbox drain legitimately stretches one.
ALIVE_FILE = Path(tempfile.gettempdir()) / "tiai-worker.alive"


# --- Jobs -------------------------------------------------------------------


async def process_outbox() -> int:
    """Send the due mails; the worker is the outbox's only drainer."""
    async with AsyncSession(engine) as session:
        return await outbox.send_pending(session)


async def expire_stale_commands() -> int:
    """Mark pending commands past their expires_at as expired."""
    now = utcnow()
    async with AsyncSession(engine) as session:
        result = await session.exec(
            update(Command)
            .where(col(Command.status) == CommandStatus.PENDING)
            .where(col(Command.expires_at) < now)
            .values(status=CommandStatus.EXPIRED)
        )
        await session.commit()
        return result.rowcount or 0


async def send_daily_digest() -> int:
    """Queue the daily fleet digest for the accounts that asked for one.

    Runs once a day at the digest hour (page Paramètres, else
    ``DIGEST_HOUR_UTC``). Which accounts hear from it, and on
    which days, is decided per account — see ``features/notification/digest``.
    """
    async with AsyncSession(engine) as session:
        return await digest.send_daily_digest(session)


async def purge_outbox() -> int:
    """Drop sent/abandoned outbox rows older than the retention window."""
    async with AsyncSession(engine) as session:
        return await outbox.purge_settled(session)


async def purge_usage() -> int:
    """Drop the hourly usage counters past ``USAGE_RETENTION_DAYS``."""
    cutoff = utcnow() - timedelta(days=settings.USAGE_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        return await usage_crud.purge_before(session, cutoff)


async def purge_sessions() -> int:
    """Drop console sessions that have expired or been revoked: they can no
    longer be used, and a row per login for ever would only grow."""
    async with AsyncSession(engine) as session:
        return await auth_session_crud.purge_expired_sessions(session)


async def purge_audit() -> int:
    """Drop audit entries past ``AUDIT_RETENTION_DAYS`` (0 keeps them all)."""
    if settings.AUDIT_RETENTION_DAYS == 0:
        return 0
    cutoff = utcnow() - timedelta(days=settings.AUDIT_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        return await audit_crud.purge_before(session, cutoff)


async def purge_commands() -> int:
    """Drop finished commands past ``COMMAND_RETENTION_DAYS`` (0 keeps them).

    Pending and running rows are never touched — see
    ``command_crud.PURGEABLE_STATUSES``.
    """
    if settings.COMMAND_RETENTION_DAYS == 0:
        return 0
    cutoff = utcnow() - timedelta(days=settings.COMMAND_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        return await command_crud.purge_before(session, cutoff)


async def purge_reset_tokens() -> int:
    """Drop the password-reset tokens expired or used for more than a day."""
    async with AsyncSession(engine) as session:
        return await password_reset_retention.purge_spent_reset_tokens(
            session, utcnow()
        )


# --- Scheduling -------------------------------------------------------------


@dataclass
class Job:
    """A periodic task and when it next runs."""

    name: str
    run: Callable[[], Awaitable[int]]
    next_run: datetime
    # Given the instant a run happened, returns the next due instant.
    schedule: Callable[[datetime], datetime]
    # The settings the schedule was built from, for the two jobs whose hour
    # the console can change (``apply_schedule``); None for the others.
    params: tuple[int, ...] | None = None
    # When the job last ran in this process — what keeps a schedule change
    # from sending the same day's mail twice.
    last_run: datetime | None = None


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


def weekly_at(weekday: int, hour: int) -> Callable[[datetime], datetime]:
    """The next occurrence of ``weekday`` (0 = Monday) at HH:00 UTC strictly
    after ``now``."""

    def _next(now: datetime) -> datetime:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        days_ahead = (weekday - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    return _next


async def send_maintenance_reminders() -> int:
    """Queue the weekly reminder for the owners with a maintenance due."""
    from app.features.notification import tasks

    async with AsyncSession(engine) as session:
        return await tasks.send_maintenance_reminders(session)


def _digest_params(policy: SchedulePolicy) -> tuple[int, ...]:
    return (policy.digest_hour_utc,)


def _reminder_params(policy: SchedulePolicy) -> tuple[int, ...]:
    return (policy.reminder_weekday, policy.digest_hour_utc)


def _same_period(job_name: str, a: datetime, b: datetime) -> bool:
    """Whether two instants fall in the same period of a mail job: the same
    UTC day for the digest, the same ISO week for the weekly reminder."""
    if job_name == "maintenance_reminders":
        return a.isocalendar()[:2] == b.isocalendar()[:2]
    return a.date() == b.date()


def build_jobs(now: datetime, policy: SchedulePolicy | None = None) -> list[Job]:
    """The worker's whole schedule, in one place.

    ``policy`` is the console's schedule (page Paramètres) as read at
    start-up; the environment's values when the database could not be read.
    """
    if policy is None:
        policy = SchedulePolicy(
            digest_hour_utc=settings.DIGEST_HOUR_UTC,
            reminder_weekday=settings.MAINTENANCE_REMINDER_WEEKDAY,
        )
    digest_hour = daily_at(policy.digest_hour_utc)
    reminder = weekly_at(policy.reminder_weekday, policy.digest_hour_utc)
    housekeeping = daily_at(8)
    return [
        # Due immediately: a restart must resume mail delivery within one tick.
        Job("outbox", process_outbox, now, every(POLL_SECONDS)),
        Job("expire_stale_commands", expire_stale_commands, now, every(300)),
        Job(
            "daily_digest",
            send_daily_digest,
            digest_hour(now),
            digest_hour,
            params=_digest_params(policy),
        ),
        Job(
            "maintenance_reminders",
            send_maintenance_reminders,
            reminder(now),
            reminder,
            params=_reminder_params(policy),
        ),
        Job("purge_outbox", purge_outbox, housekeeping(now), housekeeping),
        Job("purge_usage", purge_usage, housekeeping(now), housekeeping),
        Job("purge_sessions", purge_sessions, housekeeping(now), housekeeping),
        Job("purge_audit", purge_audit, housekeeping(now), housekeeping),
        Job("purge_commands", purge_commands, housekeeping(now), housekeeping),
        Job(
            "purge_reset_tokens",
            purge_reset_tokens,
            housekeeping(now),
            housekeeping,
        ),
    ]


def apply_schedule(jobs: list[Job], policy: SchedulePolicy, now: datetime) -> None:
    """Re-aim the two mail jobs when the console changed their hour or day.

    Read on every tick, so a new digest hour applies within thirty seconds,
    without restarting the worker. A job whose settings did not move is left
    alone — its next run stays where it was.

    One guard: moving the hour must not send a period's mail twice. The digest
    sent at 18:00 and an hour then moved to 20:00 aims for 20:00 *tomorrow*,
    not tonight; likewise a reminder already sent this week waits for the
    next. Known only for runs in this process — the restart semantics the
    schedule already has.
    """
    wanted = {
        "daily_digest": (
            _digest_params(policy),
            daily_at(policy.digest_hour_utc),
        ),
        "maintenance_reminders": (
            _reminder_params(policy),
            weekly_at(policy.reminder_weekday, policy.digest_hour_utc),
        ),
    }
    for job in jobs:
        if job.name not in wanted:
            continue
        params, schedule = wanted[job.name]
        if job.params == params:
            continue
        next_run = schedule(now)
        if job.last_run is not None and _same_period(job.name, job.last_run, next_run):
            next_run = schedule(next_run)
        logger.info(
            "Job %s rescheduled for %s (settings changed)",
            job.name,
            next_run.isoformat(),
        )
        job.params, job.schedule, job.next_run = params, schedule, next_run


async def load_schedule() -> SchedulePolicy | None:
    """The console's schedule, or None when the database cannot be read —
    the worker then keeps the schedule it has rather than stopping."""
    try:
        async with AsyncSession(engine) as session:
            return await setting_crud.schedule_policy(session)
    except Exception:
        logger.warning("Could not read the mail schedule settings", exc_info=True)
        return None


async def run_due_jobs(jobs: list[Job], now: datetime) -> None:
    """Run every job whose time has come. A failing job never stops the loop."""
    for job in jobs:
        if job.next_run > now:
            continue
        # Rescheduled before running, so a job that raises still moves on
        # rather than being retried on every tick against the same failure.
        job.next_run = job.schedule(now)
        job.last_run = now
        try:
            result = await job.run()
        except Exception:
            logger.exception("Job %s failed", job.name)
        else:
            if result:
                logger.info("Job %s: %d", job.name, result)


def mark_alive() -> None:
    """Record that a tick completed. Never fatal: a liveness probe that could
    stop the loop it reports on would be worse than none."""
    try:
        ALIVE_FILE.touch()
    except OSError:
        logger.warning("Could not touch %s", ALIVE_FILE, exc_info=True)


async def main(stop: asyncio.Event) -> None:
    jobs = build_jobs(utcnow(), await load_schedule())
    logger.info("Worker started: %d jobs, tick %ds", len(jobs), POLL_SECONDS)
    while not stop.is_set():
        policy = await load_schedule()
        if policy is not None:
            apply_schedule(jobs, policy, utcnow())
        await run_due_jobs(jobs, utcnow())
        mark_alive()
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
