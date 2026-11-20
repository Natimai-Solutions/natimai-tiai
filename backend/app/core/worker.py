"""The worker: one asyncio loop, the e-mail outbox and the periodic tasks.

What used to need ARQ and Redis is a single loop over Postgres: every
``POLL_SECONDS`` it drains the outbox (mails queued by the API and by the
digest, sent with retries), and runs whichever periodic jobs have come due —
command expiry every five minutes, the daily digest and housekeeping once a
day — the retention purges of the outbox, the usage counters, the audit log,
the command history and the spent password-reset tokens. One worker process per deployment, which is what the compose runs; the
drain assumes no concurrent drainer.

A job that comes due while the worker is down runs at the next matching time,
not on catch-up — the same semantics the ARQ crons had — with one exception:
the two mail jobs. A worker started after the digest hour (or on the
reminder's day, after its hour) sends that day's mail at once rather than
skipping it: the period recorded in the database (below) is what keeps a
restart after the mail went out from sending it a second time. The outbox
makes the rest safe for mail: a due row is due until sent, so a restart
resumes deliveries within one tick.

The two mail jobs — the daily digest, the weekly reminder — keep in the
database (``app_settings``, ``worker.last_run.*``) the day or the week they
last went out, written in the transaction that queues the mails: neither is
ever sent twice for one period, whatever restarts and schedule changes happen
in between — nor by a second worker started by mistake: the period is
claimed in one statement, under the row's lock. One that fails is tried again
at the next tick, the same day, instead of waiting for tomorrow.

The outbox is drained beside the loop, not in it, and for a bounded time per
drain: a mail server that accepts connections and never answers delays mail,
not the command expiry, the housekeeping and the liveness file.

Run with: python -m app.core.worker
"""

import asyncio
import functools
import logging
import signal
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import assert_not_superuser, engine
from app.features import password_reset_retention
from app.features.audit import crud as audit_crud
from app.features.auth_session import crud as auth_session_crud
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command.models import Command, CommandStatus
from app.features.notification import digest, outbox
from app.features.setting import crud as setting_crud
from app.features.setting.crud import SchedulePolicy
from app.features.setting.models import AppSetting
from app.features.usage import crud as usage_crud
from app.features.user import addresses as login_addresses

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

# At stop, how long a drain in progress is given to finish its mail: under
# the ten seconds ``docker stop`` waits before killing.
STOP_GRACE_SECONDS = 8


# --- Jobs -------------------------------------------------------------------


# How long one drain may keep starting new mails. Below POLL_SECONDS, so that
# a drain stuck on a silent server is over by the time the next one is due.
OUTBOX_BUDGET_SECONDS = 25


async def process_outbox(stop: asyncio.Event | None = None) -> int:
    """Send the due mails; the worker is the outbox's only drainer.

    ``stop`` is the worker's stop event: once set, the drain ends with the
    mail it is sending (``finish_background`` waits for that one)."""
    async with AsyncSession(engine) as session:
        return await outbox.send_pending(
            session, budget_seconds=OUTBOX_BUDGET_SECONDS, stop=stop
        )


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


async def close_unanswered_commands() -> int:
    """Fail the delivered or running commands left without a verdict past
    ``COMMAND_UNANSWERED_HOURS`` (audit B10)."""
    async with AsyncSession(engine) as session:
        closed = await command_crud.close_unanswered(
            session, hours=settings.COMMAND_UNANSWERED_HOURS
        )
        await session.commit()
        return closed


async def purge_software() -> int:
    """Drop the software entries no poste has had for a day (audit S21)."""
    from app.features.inventory import crud as inventory_crud

    async with AsyncSession(engine) as session:
        return await inventory_crud.purge_orphan_software(
            session, utcnow() - timedelta(days=1)
        )


# Where each mail job writes the period it last went out for.
LAST_RUN_KEYS = {
    "daily_digest": "worker.last_run.daily_digest",
    "maintenance_reminders": "worker.last_run.maintenance_reminders",
}


def _day(now: datetime) -> str:
    return now.date().isoformat()


def _iso_week(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


async def _claim_period(session: AsyncSession, key: str, period: str) -> bool:
    """Record ``period`` under ``key`` unless it is already there; whether
    this transaction is the one that recorded it.

    One statement, not a read then a write: two workers started by mistake
    (``--scale worker=2``, a second stack on the same database) both read
    « not sent yet » and both sent. The second now waits on the row the first
    holds until that one commits — and then finds the period there — or
    rolls back, and then takes its turn.
    """
    values = {"value": period, "updated_at": utcnow(), "updated_by": "worker"}
    insert = pg_insert(AppSetting).values(key=key, **values)
    claim = insert.on_conflict_do_update(
        index_elements=[col(AppSetting.key)],
        set_=values,
        where=col(AppSetting.value).is_distinct_from(insert.excluded.value),
    ).returning(col(AppSetting.key))
    return (await session.exec(claim)).first() is not None


async def _once_per_period(
    job_name: str,
    period: str,
    send: Callable[[AsyncSession], Awaitable[int]],
) -> int:
    """Run a mail job unless it already went out for ``period``, recording
    the period in the same transaction as the mails it queues: committed
    together, or not at all — a failed run is not taken for a sent one."""
    key = LAST_RUN_KEYS[job_name]
    async with AsyncSession(engine) as session:
        if not await _claim_period(session, key, period):
            logger.info("Job %s already ran for %s, skipped", job_name, period)
            return 0
        queued = await send(session)
        # The senders commit what they queue; one that had nothing to send
        # returns before its commit, and the period is recorded all the same.
        await session.commit()
        return queued


async def send_daily_digest(now: datetime | None = None) -> int:
    """Queue the daily fleet digest for the accounts that asked for one.

    Runs once a day at the digest hour (page Paramètres, else
    ``DIGEST_HOUR_UTC``). Which accounts hear from it, and on
    which days, is decided per account — see ``features/notification/digest``.

    ``now`` is the tick that decided the run, and the day recorded is its
    day: read off the clock a second time, a run decided a breath before
    midnight recorded the next day, whose own digest was then skipped.
    """
    return await _once_per_period(
        "daily_digest", _day(now or utcnow()), digest.send_daily_digest
    )


async def evaluate_alerts() -> int:
    """Open, refresh and resolve the alerts (``app.features.alert``), queue
    the immediate mails of the new ones, in one transaction. Returns how many
    alerts were opened."""
    from app.features.alert import crud as alert_crud
    from app.features.notification import alert_mail

    async with AsyncSession(engine) as session:
        result = await alert_crud.evaluate(session, utcnow())
        await alert_mail.queue_alert_mails(session, result.opened)
        await session.commit()
    if result.opened or result.resolved:
        logger.info(
            "Alerts: %d opened, %d resolved, %d verification(s) opened",
            len(result.opened),
            result.resolved,
            result.checks_opened,
        )
    return len(result.opened)


async def run_schedules() -> int:
    """Run the schedules come due, then carry the open runs a step further
    (« éteindre ensuite », rings) — ``features.schedule.runner``."""
    from app.features.schedule import runner

    async with AsyncSession(engine) as session:
        ran = await runner.run_due(session, utcnow())
        await runner.follow_runs(session, utcnow())
    return ran


async def purge_schedule_runs() -> int:
    """Drop the schedule runs older than ``SCHEDULE_RUN_RETENTION_DAYS``."""
    from app.features.schedule import runner

    cutoff = utcnow() - timedelta(days=settings.SCHEDULE_RUN_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        return await runner.purge_runs(session, cutoff)


async def purge_reports() -> int:
    """Drop the reports handled more than ``REPORT_RETENTION_DAYS`` ago —
    their contact with them (C4)."""
    from app.features.report import crud as report_crud

    cutoff = utcnow() - timedelta(days=settings.REPORT_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        return await report_crud.purge_before(session, cutoff)


async def purge_alerts() -> int:
    """Drop the alerts resolved more than ``ALERT_RETENTION_DAYS`` ago."""
    from app.features.alert import crud as alert_crud

    cutoff = utcnow() - timedelta(days=settings.ALERT_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        return await alert_crud.purge_before(session, cutoff)


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


async def purge_shared_counters() -> int:
    """Drop the budget counters no window reaches any more (audit T36)."""
    from app.features.counter import quota

    async with AsyncSession(engine) as session:
        return await quota.purge_expired(session)


async def purge_login_addresses() -> int:
    """Drop the login addresses that no longer say anything: no failure
    within the lock window, no success within the known period."""
    async with AsyncSession(engine) as session:
        return await login_addresses.purge_stale(session, utcnow())


# --- Scheduling -------------------------------------------------------------


@dataclass
class Job:
    """A periodic task and when it next runs."""

    name: str
    run: Callable[..., Awaitable[int]]
    next_run: datetime
    # Given the instant a run happened, returns the next due instant.
    schedule: Callable[[datetime], datetime]
    # The settings the schedule was built from, for the two jobs whose hour
    # the console can change (``apply_schedule``); None for the others.
    params: tuple[int, ...] | None = None
    # When the job last ran to the end in this process — what keeps a
    # schedule change from aiming at a period already served (the database
    # record, ``LAST_RUN_KEYS``, is what keeps it from sending it twice).
    last_run: datetime | None = None
    # A mail job (digest, reminder): one that fails is tried again at every
    # tick of the same UTC day, rather than at its next occurrence.
    retry_same_day: bool = False
    # ``run`` is called with the tick's instant — the mail jobs, which record
    # the period of the tick that decided the run.
    takes_now: bool = False
    # Set while such a job is being retried: the day its failed run was due.
    retrying_on: date | None = None
    # Run beside the loop rather than in it (the outbox drain): the next tick
    # does not wait for it, and it is not started again while it runs.
    background: bool = False
    task: "asyncio.Task[None] | None" = None


def every(seconds: int) -> Callable[[datetime], datetime]:
    """Interval schedule, measured from each run (not from a fixed grid)."""

    def _next(now: datetime) -> datetime:
        return now + timedelta(seconds=seconds)

    return _next


def daily_at(hour: int) -> Callable[[datetime], datetime]:
    """The next HH:00 UTC strictly after ``now``.

    Strictly after: a job that just ran at 18:00 must aim for tomorrow. A
    worker started at 18:05 skips today's occurrence for the housekeeping;
    the mail jobs catch it up (``first_run``).
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


async def send_maintenance_reminders(now: datetime | None = None) -> int:
    """Queue the weekly reminder for the owners with a maintenance due —
    once per ISO week, that of ``now``, the tick that decided the run."""
    from app.features.notification import tasks

    return await _once_per_period(
        "maintenance_reminders",
        _iso_week(now or utcnow()),
        tasks.send_maintenance_reminders,
    )


def _digest_params(policy: SchedulePolicy) -> tuple[int, ...]:
    return (policy.digest_hour_utc,)


def _reminder_params(policy: SchedulePolicy) -> tuple[int, ...]:
    return (policy.reminder_weekday, policy.digest_hour_utc)


def first_run(schedule: Callable[[datetime], datetime], now: datetime) -> datetime:
    """When a mail job is first due in a worker started at ``now`` — or
    whose schedule was changed at ``now`` (``apply_schedule``).

    Now, when today's occurrence has already passed — a worker restarted at
    18:05 (deployment, crash, host reboot) still sends the 18:00 digest; the
    period stored by ``_once_per_period`` skips it if it went out before the
    restart. Otherwise the next occurrence. Never a day late: yesterday's
    digest is not sent this morning.
    """
    today = schedule(now - timedelta(days=1))
    if today <= now and today.date() == now.date():
        return now
    return schedule(now)


def _same_period(job_name: str, a: datetime, b: datetime) -> bool:
    """Whether two instants fall in the same period of a mail job: the same
    UTC day for the digest, the same ISO week for the weekly reminder."""
    if job_name == "maintenance_reminders":
        return a.isocalendar()[:2] == b.isocalendar()[:2]
    return a.date() == b.date()


def build_jobs(
    now: datetime,
    policy: SchedulePolicy | None = None,
    stop: asyncio.Event | None = None,
) -> list[Job]:
    """The worker's whole schedule, in one place.

    ``policy`` is the console's schedule (page Paramètres) as read at
    start-up; the environment's values when the database could not be read.
    ``stop`` is the worker's stop event, handed to the outbox drain.
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
        Job(
            "outbox",
            functools.partial(process_outbox, stop),
            now,
            every(POLL_SECONDS),
            background=True,
        ),
        Job("expire_stale_commands", expire_stale_commands, now, every(300)),
        Job("close_unanswered_commands", close_unanswered_commands, now, every(300)),
        # Every five minutes: a disk turning unhealthy is mailed within that,
        # and the rules read what the heartbeats and inventories wrote.
        Job("evaluate_alerts", evaluate_alerts, now, every(300)),
        # Every minute: a schedule set for 18:00 runs by 18:01.
        Job("run_schedules", run_schedules, now, every(60)),
        Job(
            "daily_digest",
            send_daily_digest,
            first_run(digest_hour, now),
            digest_hour,
            params=_digest_params(policy),
            retry_same_day=True,
            takes_now=True,
        ),
        Job(
            "maintenance_reminders",
            send_maintenance_reminders,
            first_run(reminder, now),
            reminder,
            params=_reminder_params(policy),
            retry_same_day=True,
            takes_now=True,
        ),
        Job("purge_outbox", purge_outbox, housekeeping(now), housekeeping),
        Job("purge_software", purge_software, housekeeping(now), housekeeping),
        Job(
            "purge_shared_counters",
            purge_shared_counters,
            housekeeping(now),
            housekeeping,
        ),
        Job("purge_usage", purge_usage, housekeeping(now), housekeeping),
        Job("purge_alerts", purge_alerts, housekeeping(now), housekeeping),
        Job("purge_reports", purge_reports, housekeeping(now), housekeeping),
        Job(
            "purge_schedule_runs",
            purge_schedule_runs,
            housekeeping(now),
            housekeeping,
        ),
        Job("purge_sessions", purge_sessions, housekeeping(now), housekeeping),
        Job("purge_audit", purge_audit, housekeeping(now), housekeeping),
        Job("purge_commands", purge_commands, housekeeping(now), housekeeping),
        Job(
            "purge_reset_tokens",
            purge_reset_tokens,
            housekeeping(now),
            housekeeping,
        ),
        Job(
            "purge_login_addresses",
            purge_login_addresses,
            housekeeping(now),
            housekeeping,
        ),
    ]


def apply_schedule(jobs: list[Job], policy: SchedulePolicy, now: datetime) -> None:
    """Re-aim the two mail jobs when the console changed their hour or day.

    Read on every tick, so a new digest hour applies within thirty seconds,
    without restarting the worker. A job whose settings did not move is left
    alone — its next run stays where it was.

    A change is a restart at that instant, as far as the aim goes
    (``first_run``): an hour moved to one already passed today is due now when
    the day was not served, exactly as if the worker had been restarted with
    the new hour — the two used to disagree, the change skipping the day.

    One guard: moving the hour must not send a period's mail twice. The digest
    sent at 18:00 and an hour then moved to 20:00 aims for 20:00 *tomorrow*,
    not tonight; likewise a reminder already sent this week waits for the
    next. Known here only for runs in this process; the period kept in the
    database (``_once_per_period``) covers the others — a run it skips costs
    one query.

    A retry in progress belongs to the schedule that is replaced: it is
    dropped, and the new aim decides alone.
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
        next_run = first_run(schedule, now)
        if job.last_run is not None and _same_period(job.name, job.last_run, next_run):
            next_run = schedule(next_run)
        logger.info(
            "Job %s rescheduled for %s (settings changed)",
            job.name,
            next_run.isoformat(),
        )
        job.params, job.schedule, job.next_run = params, schedule, next_run
        job.retrying_on = None


async def load_schedule() -> SchedulePolicy | None:
    """The console's schedule, or None when the database cannot be read —
    the worker then keeps the schedule it has rather than stopping."""
    try:
        async with AsyncSession(engine) as session:
            return await setting_crud.schedule_policy(session)
    except Exception:
        logger.warning("Could not read the mail schedule settings", exc_info=True)
        return None


async def _run_logged(job: Job, now: datetime) -> bool:
    """Run one job; whether it went through. Never raises."""
    try:
        result = await (job.run(now) if job.takes_now else job.run())
    except Exception:
        logger.exception("Job %s failed", job.name)
        return False
    job.last_run = now
    if result:
        logger.info("Job %s: %d", job.name, result)
    return True


async def run_due_jobs(jobs: list[Job], now: datetime) -> None:
    """Run every job whose time has come. A failing job never stops the loop."""
    for job in jobs:
        if job.next_run > now:
            continue
        if job.background:
            if job.task is not None and not job.task.done():
                # Still at it: due again as soon as it ends.
                continue
            job.next_run = job.schedule(now)
            job.task = asyncio.create_task(_run_background(job, now))
            continue
        if job.retrying_on is not None and job.retrying_on != now.date():
            # The day of the failed run is over: its mail is not sent late,
            # the job waits for its next occurrence.
            logger.warning("Job %s: gave up retrying %s", job.name, job.retrying_on)
            job.retrying_on = None
            # Unless that occurrence has itself come due since midnight — a
            # digest hour of 0, a failure that lasted the night: it is
            # today's own and runs now. Giving up used to skip it, a whole
            # day (or week) of mail lost to yesterday's failure.
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            due = job.schedule(midnight - timedelta(microseconds=1))
            if due > now:
                job.next_run = due
                continue
        # Rescheduled before running, so a job that raises still moves on
        # rather than being retried on every tick against the same failure —
        # except a mail job, retried the same day: a passing outage at the
        # digest hour must not cost the day's digest.
        job.next_run = job.schedule(now)
        if await _run_logged(job, now):
            job.retrying_on = None
        elif job.retry_same_day:
            job.retrying_on = job.retrying_on or now.date()
            job.next_run = now + timedelta(seconds=POLL_SECONDS)


async def _run_background(job: Job, now: datetime) -> None:
    await _run_logged(job, now)


async def finish_background(jobs: list[Job], timeout: float) -> None:
    """Give the background jobs still running ``timeout`` seconds to end,
    then cancel them — at stop, so that a drain finishes the mail it is
    sending rather than leave it to be sent again. The drain starts no other
    mail once the stop is asked (``outbox.send_pending``): the wait is for
    the mail in flight alone, and only one that outlasts ``timeout`` — a
    server gone silent — is abandoned, still pending."""
    pending = [j.task for j in jobs if j.task is not None and not j.task.done()]
    if not pending:
        return
    _, still = await asyncio.wait(pending, timeout=timeout)
    for task in still:
        task.cancel()
    if still:
        # Let the cancellation land — the drain's session is closed here,
        # not left to the loop's teardown.
        await asyncio.gather(*still, return_exceptions=True)


def mark_alive() -> None:
    """Record that a tick completed. Never fatal: a liveness probe that could
    stop the loop it reports on would be worse than none."""
    try:
        ALIVE_FILE.touch()
    except OSError:
        logger.warning("Could not touch %s", ALIVE_FILE, exc_info=True)


async def main(stop: asyncio.Event) -> None:
    await assert_not_superuser()
    jobs = build_jobs(utcnow(), await load_schedule(), stop=stop)
    logger.info("Worker started: %d jobs, tick %ds", len(jobs), POLL_SECONDS)
    while not stop.is_set():
        policy = await load_schedule()
        # One reading of the clock for the tick: what the schedule is aimed
        # from is what the jobs are run at.
        now = utcnow()
        if policy is not None:
            apply_schedule(jobs, policy, now)
        await run_due_jobs(jobs, now)
        mark_alive()
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass
    await finish_background(jobs, timeout=STOP_GRACE_SECONDS)
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
