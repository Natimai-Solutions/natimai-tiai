"""Worker tests.

The scheduling helpers are pure arithmetic and need nothing; the jobs open
their own session on the module-level engine, so the DB-backed tests (require
TIAI_TEST_DATABASE_URL) point that engine at the test database via monkeypatch.
"""

from datetime import UTC, datetime, timedelta

import pytest


async def test_expire_stale_commands_marks_pending(engine, db_session, monkeypatch):
    from sqlmodel import select

    from app.core import worker
    from app.features.command.models import Command, CommandStatus
    from app.features.machine.models import Machine

    monkeypatch.setattr(worker, "engine", engine)

    machine = Machine(machine_uuid="w-expire")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)

    stale = Command(
        machine_id=machine.id,
        type="quick_scan",
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    stale_id = stale.id
    db_session.add(stale)
    await db_session.commit()

    n = await worker.expire_stale_commands()
    assert n == 1

    status = (
        await db_session.exec(select(Command.status).where(Command.id == stale_id))
    ).one()
    assert status == CommandStatus.EXPIRED


async def test_purge_usage_keeps_the_retention_window(engine, db_session, monkeypatch):
    from sqlmodel import select

    from app.core import worker
    from app.core.config import settings
    from app.features.machine.models import Machine
    from app.features.usage.models import MachineUptime

    monkeypatch.setattr(worker, "engine", engine)

    machine = Machine(machine_uuid="w-usage")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    machine_id = machine.id

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    retention = timedelta(days=settings.USAGE_RETENTION_DAYS)
    kept_hour = now - retention + timedelta(hours=1)
    db_session.add_all(
        [
            MachineUptime(
                machine_id=machine_id,
                hour=now - retention - timedelta(hours=1),
                seconds_on=60,
            ),
            MachineUptime(machine_id=machine_id, hour=kept_hour, seconds_on=60),
            MachineUptime(machine_id=machine_id, hour=now, seconds_on=60),
        ]
    )
    await db_session.commit()

    assert await worker.purge_usage() == 1
    hours = (
        await db_session.exec(select(MachineUptime.hour).order_by(MachineUptime.hour))
    ).all()
    assert list(hours) == [kept_hour, now]


# --- scheduling -------------------------------------------------------------


def test_daily_at_aims_for_today_while_the_hour_is_ahead():
    from app.core.worker import daily_at

    now = datetime(2026, 8, 20, 6, 30, tzinfo=UTC)
    assert daily_at(18)(now) == datetime(2026, 8, 20, 18, 0, tzinfo=UTC)


def test_daily_at_rolls_to_tomorrow_once_the_hour_has_passed():
    from app.core.worker import daily_at

    just_ran = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
    late_start = datetime(2026, 8, 20, 18, 5, tzinfo=UTC)
    tomorrow = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)

    # Strictly after: a job that just fired must aim for tomorrow — this is
    # what makes the digest a once-a-day mail rather than one per tick during
    # the whole of its hour.
    assert daily_at(18)(just_ran) == tomorrow
    assert daily_at(18)(late_start) == tomorrow


def test_build_jobs_registers_the_whole_schedule():
    from app.core.config import settings
    from app.core.worker import build_jobs

    now = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)
    jobs = {job.name: job for job in build_jobs(now)}

    assert set(jobs) == {
        "outbox",
        "webhooks",
        "expire_stale_commands",
        "close_unanswered_commands",
        "evaluate_alerts",
        "refresh_compliance",
        "sync_directory",
        "run_schedules",
        "expire_approvals",
        "snapshot_trends",
        "daily_digest",
        "maintenance_reminders",
        "purge_outbox",
        "purge_software",
        "purge_shared_counters",
        "purge_usage",
        "purge_trends",
        "purge_alerts",
        "purge_reports",
        "purge_schedule_runs",
        "purge_sessions",
        "purge_approvals",
        "purge_webhook_deliveries",
        "purge_audit",
        "purge_commands",
        "purge_reset_tokens",
        "purge_login_addresses",
    }
    # The outbox is due immediately: a restarted worker must resume mail
    # delivery on its first tick, not after an arbitrary wait.
    assert jobs["outbox"].next_run == now
    # The trends' photo is hourly, from the start (C9).
    trends = jobs["snapshot_trends"]
    assert trends.next_run == now
    assert trends.schedule(now) == now + timedelta(hours=1)
    # Every retention purge runs in the morning housekeeping slot.
    for name in ("purge_audit", "purge_commands", "purge_reset_tokens", "purge_trends"):
        assert jobs[name].next_run == datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    # The digest fires at the configured hour, on the hour.
    digest = jobs["daily_digest"]
    assert digest.next_run.hour == settings.DIGEST_HOUR_UTC
    assert (digest.next_run.minute, digest.next_run.second) == (0, 0)


async def test_a_failing_job_neither_stops_the_loop_nor_spins():
    from app.core.worker import Job, every, run_due_jobs

    calls: list[int] = []

    async def boom() -> int:
        calls.append(1)
        raise RuntimeError("db down")

    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    job = Job("boom", boom, next_run=now, schedule=every(300))

    await run_due_jobs([job], now)  # must not raise

    assert calls == [1]
    # Rescheduled to its normal next slot, not left due — a job failing at
    # every tick would otherwise hammer the same failure every POLL_SECONDS.
    assert job.next_run == now + timedelta(seconds=300)

    # Not due yet: nothing runs on the next pass.
    await run_due_jobs([job], now + timedelta(seconds=30))
    assert calls == [1]


def test_mark_alive_touches_the_liveness_file(tmp_path, monkeypatch):
    from app.core import worker

    alive = tmp_path / "alive"
    monkeypatch.setattr(worker, "ALIVE_FILE", alive)
    worker.mark_alive()
    assert alive.exists()


def test_mark_alive_never_raises(tmp_path, monkeypatch):
    from app.core import worker

    # A directory that does not exist: the touch fails, the loop must not.
    monkeypatch.setattr(worker, "ALIVE_FILE", tmp_path / "missing" / "alive")
    worker.mark_alive()


async def test_main_marks_alive_after_a_tick(tmp_path, monkeypatch):
    import asyncio

    from app.core import worker

    alive = tmp_path / "alive"
    monkeypatch.setattr(worker, "ALIVE_FILE", alive)
    monkeypatch.setattr(worker, "build_jobs", lambda now, policy=None, stop=None: [])

    async def no_schedule():
        return None

    monkeypatch.setattr(worker, "load_schedule", no_schedule)

    async def role_ok() -> None:
        return None

    # The role check reads the database; this test runs without one.
    monkeypatch.setattr(worker, "assert_not_superuser", role_ok)
    stop = asyncio.Event()

    async def stop_after_first_tick() -> None:
        await asyncio.sleep(0)  # let main() run its first tick
        stop.set()

    await asyncio.gather(worker.main(stop), stop_after_first_tick())
    assert alive.exists()


# --- Schedule changed from the console ----------------------------------------


def _policy(hour: int = 18, weekday: int = 0):
    from app.features.setting.crud import SchedulePolicy

    return SchedulePolicy(digest_hour_utc=hour, reminder_weekday=weekday)


def _job(jobs, name):
    return next(j for j in jobs if j.name == name)


def test_build_jobs_follows_the_console_schedule():
    from app.core.worker import build_jobs

    now = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)  # a Thursday
    jobs = build_jobs(now, _policy(hour=9, weekday=4))
    assert _job(jobs, "daily_digest").next_run == datetime(2026, 10, 1, 9, tzinfo=UTC)
    assert _job(jobs, "maintenance_reminders").next_run == datetime(
        2026, 10, 2, 9, tzinfo=UTC
    )


def test_apply_schedule_moves_the_digest_to_the_new_hour():
    from app.core.worker import apply_schedule, build_jobs

    now = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    jobs = build_jobs(now, _policy(hour=18))
    apply_schedule(jobs, _policy(hour=7), now)
    assert _job(jobs, "daily_digest").next_run == datetime(2026, 10, 1, 7, tzinfo=UTC)


def test_apply_schedule_leaves_unchanged_jobs_alone():
    from app.core.worker import apply_schedule, build_jobs

    now = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    jobs = build_jobs(now, _policy(hour=18))
    digest = _job(jobs, "daily_digest")
    digest.next_run = datetime(2026, 10, 1, 18, 0, 5, tzinfo=UTC)  # a marker
    apply_schedule(jobs, _policy(hour=18), now)
    assert digest.next_run == datetime(2026, 10, 1, 18, 0, 5, tzinfo=UTC)


def test_moving_the_hour_later_never_sends_the_same_day_twice():
    from app.core.worker import apply_schedule, build_jobs

    sent = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
    jobs = build_jobs(sent, _policy(hour=18))
    digest = _job(jobs, "daily_digest")
    digest.last_run = sent
    # Changed at 18:30 to 20:00: today's digest is already out.
    apply_schedule(jobs, _policy(hour=20), sent.replace(minute=30))
    assert digest.next_run == datetime(2026, 10, 2, 20, tzinfo=UTC)


def test_moving_the_hour_earlier_keeps_tomorrow():
    from app.core.worker import apply_schedule, build_jobs

    sent = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
    jobs = build_jobs(sent, _policy(hour=18))
    digest = _job(jobs, "daily_digest")
    digest.last_run = sent
    apply_schedule(jobs, _policy(hour=7), sent.replace(minute=30))
    assert digest.next_run == datetime(2026, 10, 2, 7, tzinfo=UTC)


def test_moving_the_reminder_day_waits_for_next_week_once_sent():
    from app.core.worker import apply_schedule, build_jobs

    monday = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)
    jobs = build_jobs(monday, _policy(hour=18, weekday=0))
    reminder = _job(jobs, "maintenance_reminders")
    reminder.last_run = monday
    # Moved to Wednesday the same week: this week's reminder is already out.
    apply_schedule(jobs, _policy(hour=18, weekday=2), monday.replace(hour=19))
    assert reminder.next_run == datetime(2026, 10, 7, 18, tzinfo=UTC)


async def test_run_due_jobs_records_the_last_run():
    from app.core.worker import Job, every, run_due_jobs

    async def noop() -> int:
        return 0

    now = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    job = Job("x", noop, now, every(60))
    await run_due_jobs([job], now)
    assert job.last_run == now


async def test_main_reads_the_schedule_from_the_database(
    engine, db_session, monkeypatch
):
    from app.core import worker
    from app.features.setting import crud

    monkeypatch.setattr(worker, "engine", engine)
    await crud.set_value(db_session, crud.KEY_DIGEST_HOUR, 5, actor="t")
    await crud.set_value(db_session, crud.KEY_REMINDER_WEEKDAY, 3, actor="t")
    await db_session.commit()

    policy = await worker.load_schedule()
    assert policy is not None
    assert (policy.digest_hour_utc, policy.reminder_weekday) == (5, 3)


# --- Acceptance, 2026-11: a stuck drain, a failed digest, a second digest ----------


async def test_a_stuck_drain_holds_neither_the_loop_nor_the_other_jobs():
    """The outbox runs beside the loop: a drain stuck on a silent server
    lets the other jobs run on every tick, and is not started twice."""
    import asyncio

    from app.core.worker import Job, every, finish_background, run_due_jobs

    release = asyncio.Event()
    drains: list[int] = []
    others: list[int] = []

    async def stuck_drain() -> int:
        drains.append(1)
        await release.wait()
        return 0

    async def other() -> int:
        others.append(1)
        return 0

    now = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    jobs = [
        Job("outbox", stuck_drain, now, every(30), background=True),
        Job("expire", other, now, every(30)),
    ]
    await asyncio.wait_for(run_due_jobs(jobs, now), timeout=1)
    await asyncio.sleep(0)
    later = now + timedelta(seconds=30)
    await asyncio.wait_for(run_due_jobs(jobs, later), timeout=1)
    assert drains == [1]
    assert others == [1, 1]
    release.set()
    await finish_background(jobs, timeout=1)
    await asyncio.wait_for(run_due_jobs(jobs, later + timedelta(seconds=30)), 1)
    await finish_background(jobs, timeout=1)
    assert drains == [1, 1]


async def test_a_failed_digest_is_retried_the_same_day_only():
    from app.core.worker import POLL_SECONDS, Job, daily_at, run_due_jobs

    outcomes = [RuntimeError("db down"), RuntimeError("db down"), 3]
    calls: list[datetime] = []

    async def digest() -> int:
        calls.append(datetime.now(UTC))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    at = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
    job = Job("daily_digest", digest, at, daily_at(18), retry_same_day=True)
    await run_due_jobs([job], at)
    assert job.next_run == at + timedelta(seconds=POLL_SECONDS)
    tick = job.next_run
    await run_due_jobs([job], tick)
    await run_due_jobs([job], job.next_run)
    assert len(calls) == 3
    assert job.next_run == datetime(2026, 10, 2, 18, tzinfo=UTC)
    assert job.retrying_on is None

    # Failing until midnight: the next day does not get yesterday's digest
    # at 00:00, it waits for its own hour.
    async def always_down() -> int:
        raise RuntimeError("db down")

    job = Job("daily_digest", always_down, at, daily_at(18), retry_same_day=True)
    await run_due_jobs([job], at)
    midnight = datetime(2026, 10, 2, 0, 0, 10, tzinfo=UTC)
    job.next_run = midnight
    await run_due_jobs([job], midnight)
    assert job.next_run == datetime(2026, 10, 2, 18, tzinfo=UTC)
    assert job.retrying_on is None


async def test_a_mail_job_never_runs_twice_for_one_period(
    engine, db_session, monkeypatch
):
    """The period a mail job went out for is kept in the database, with the
    mails: a restart followed by an hour change does not send the day's
    digest a second time, and a run that failed is not taken for one sent."""
    from app.core import worker
    from app.features.notification import digest
    from app.features.setting import crud

    monkeypatch.setattr(worker, "engine", engine)
    runs: list[int] = []
    fail = [True]

    async def fake_digest(session) -> int:
        runs.append(1)
        if fail[0]:
            raise RuntimeError("smtp down")
        return 2

    monkeypatch.setattr(digest, "send_daily_digest", fake_digest)
    with pytest.raises(RuntimeError):
        await worker.send_daily_digest()
    assert (
        await crud.get_value(db_session, worker.LAST_RUN_KEYS["daily_digest"]) is None
    )

    fail[0] = False
    assert await worker.send_daily_digest() == 2
    # Another process — a restart — with the same day: nothing sent.
    assert await worker.send_daily_digest() == 0
    assert len(runs) == 2
    db_session.expire_all()
    assert (
        await crud.get_value(db_session, worker.LAST_RUN_KEYS["daily_digest"])
        == worker.utcnow().date().isoformat()
    )


async def test_the_weekly_reminder_is_kept_per_iso_week(engine, monkeypatch):
    from app.core import worker
    from app.features.notification import tasks

    monkeypatch.setattr(worker, "engine", engine)
    runs: list[int] = []

    async def fake(session) -> int:
        runs.append(1)
        return 1

    monkeypatch.setattr(tasks, "send_maintenance_reminders", fake)
    assert await worker.send_maintenance_reminders() == 1
    assert await worker.send_maintenance_reminders() == 0
    assert runs == [1]
    assert worker._iso_week(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-W01"


# --- A worker started after the digest hour -----------------------------------


def test_a_worker_started_after_the_hour_sends_that_days_mail():
    """Solidity pass: a worker restarted at 18:05 (deployment, reboot) skipped
    the 18:00 digest until the next day. It is due at once now, the period
    stored in the database keeping it from going out twice."""
    from app.core.worker import build_jobs

    late = datetime(2026, 10, 5, 18, 5, tzinfo=UTC)  # a Monday
    jobs = build_jobs(late, _policy(hour=18, weekday=0))
    assert _job(jobs, "daily_digest").next_run == late
    assert _job(jobs, "maintenance_reminders").next_run == late

    # Before the hour, and on another day of the week: the next occurrence.
    early = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)  # Tuesday morning
    jobs = build_jobs(early, _policy(hour=18, weekday=0))
    assert _job(jobs, "daily_digest").next_run == datetime(2026, 10, 6, 18, tzinfo=UTC)
    assert _job(jobs, "maintenance_reminders").next_run == datetime(
        2026, 10, 12, 18, tzinfo=UTC
    )
    # Never a day late: after midnight, yesterday's digest is not sent.
    after_midnight = datetime(2026, 10, 6, 0, 30, tzinfo=UTC)
    jobs = build_jobs(after_midnight, _policy(hour=18, weekday=0))
    assert _job(jobs, "daily_digest").next_run == datetime(2026, 10, 6, 18, tzinfo=UTC)


# --- Stopping the worker in the middle of a drain ----------------------------------


async def _queue_mails(db_session, monkeypatch, n: int) -> None:
    from app.core.config import settings
    from app.features.notification.outbox import queue_email

    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test.local")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-test")
    for i in range(n):
        queue_email(db_session, to=f"r{i}@test.local", subject="s", text="t")
    await db_session.commit()


async def _outbox_statuses(db_session) -> dict[str, str]:
    from sqlmodel import select

    from app.features.notification.models import EmailOutbox

    db_session.expire_all()
    rows = await db_session.exec(select(EmailOutbox))
    return {r.to_address: r.status for r in rows.all()}


async def test_a_stop_ends_the_drain_after_the_mail_in_flight(
    engine, db_session, monkeypatch, tmp_path
):
    """`docker stop` during a drain: the mail being sent is finished and
    recorded, no other is started. The drain used to go on sending for the
    whole grace, then be cancelled in the middle of a mail — delivered, left
    pending, and sent again at the next start."""
    import asyncio
    import time

    from app.core import worker
    from app.features.notification import outbox
    from app.features.notification.models import EmailStatus

    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "ALIVE_FILE", tmp_path / "alive")
    monkeypatch.setattr(worker, "STOP_GRACE_SECONDS", 0.5)

    async def role_ok() -> None:
        return None

    monkeypatch.setattr(worker, "assert_not_superuser", role_ok)
    await _queue_mails(db_session, monkeypatch, 10)

    built: list[worker.Job] = []
    real_build = worker.build_jobs

    def only_the_outbox(*args, **kwargs):
        built[:] = [j for j in real_build(*args, **kwargs) if j.name == "outbox"]
        return built

    monkeypatch.setattr(worker, "build_jobs", only_the_outbox)
    stop = asyncio.Event()
    delivered: list[str] = []

    async def deliver(subject, text, to, *, policy=None):
        # The server has the mail from here on, whatever becomes of us.
        delivered.append(to[0])
        stop.set()  # SIGTERM while the first mail is being sent
        await asyncio.sleep(0.2)  # … and its answer takes a moment
        return True

    monkeypatch.setattr(outbox, "send_email", deliver)
    started = time.monotonic()
    await asyncio.wait_for(worker.main(stop), timeout=5)
    elapsed = time.monotonic() - started

    # main() waited for the drain: nothing is left running behind it.
    [job] = built
    assert job.background and job.task is not None and job.task.done()
    statuses = await _outbox_statuses(db_session)
    sent = sorted(a for a, s in statuses.items() if s == EmailStatus.SENT)
    # Never delivered *and* still pending.
    assert sent == sorted(delivered)
    # Only the mail in flight: the nine others wait for the next start …
    assert len(delivered) == 1
    assert sum(s == EmailStatus.PENDING for s in statuses.values()) == 9
    # … and the stop did not wait out its grace for them.
    assert elapsed < 0.45


# --- The real schedule, as build_jobs hands it to the loop -------------------------


async def test_the_outbox_job_is_a_bounded_drain_beside_the_loop(monkeypatch):
    """What keeps a silent mail server from holding the worker is in how the
    real job is built — beside the loop, with a budget, told of the stop —
    not in a Job a test builds for itself."""
    import asyncio

    from app.core import worker

    calls: list[dict] = []

    async def fake_send_pending(session, **kwargs) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(worker.outbox, "send_pending", fake_send_pending)
    stop = asyncio.Event()
    now = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)
    jobs = {job.name: job for job in worker.build_jobs(now, stop=stop)}

    # The webhooks (C8) drain in the background too, with their own budget.
    assert [name for name, job in jobs.items() if job.background] == [
        "outbox",
        "webhooks",
    ]
    await jobs["outbox"].run()
    assert calls == [{"budget_seconds": worker.OUTBOX_BUDGET_SECONDS, "stop": stop}]
    # Over before the next drain is due, and with room for the tick itself.
    assert 0 < worker.OUTBOX_BUDGET_SECONDS < worker.POLL_SECONDS


async def test_both_mail_jobs_are_retried_the_same_day_and_told_the_tick():
    from app.core.worker import POLL_SECONDS, build_jobs, run_due_jobs

    at = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)  # a Monday, at the hour
    jobs = build_jobs(at - timedelta(hours=1), _policy(hour=18, weekday=0))
    mail = {"daily_digest", "maintenance_reminders"}
    assert {j.name for j in jobs if j.retry_same_day} == mail
    assert {j.name for j in jobs if j.takes_now} == mail

    seen: list[datetime] = []

    async def down(now: datetime) -> int:
        seen.append(now)
        raise RuntimeError("db down")

    for name in sorted(mail):
        job = _job(jobs, name)
        job.run = down
        await run_due_jobs([job], at)
        # Not tomorrow, not next week: at the next tick.
        assert job.next_run == at + timedelta(seconds=POLL_SECONDS), name
        assert job.retrying_on == at.date()
    assert seen == [at, at]


# --- A retry in progress and the schedule (review, 2026-11) ------------------------


async def test_a_stale_retry_never_swallows_the_occurrence_that_is_due():
    """A digest failing at 18:00, its hour then moved to 08:00: the 08:00 run
    of the next day met « gave up retrying » and was rescheduled a day later
    without running. Same for the reminder's weekday, a whole week lost."""
    from app.core.worker import apply_schedule, build_jobs, run_due_jobs

    state = {"fail": True}
    runs: list[datetime] = []

    async def mail(now: datetime) -> int:
        runs.append(now)
        if state["fail"]:
            raise RuntimeError("smtp down")
        return 1

    start = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)  # a Monday
    jobs = build_jobs(start, _policy(hour=18, weekday=0))
    digest, reminder = _job(jobs, "daily_digest"), _job(jobs, "maintenance_reminders")
    digest.run = reminder.run = mail
    both = [digest, reminder]
    at = datetime(2026, 10, 5, 18, 0, 5, tzinfo=UTC)
    await run_due_jobs(both, at)
    assert digest.retrying_on == reminder.retrying_on == at.date()

    # 18:10 — the administrator moves the digest to 08:00, the reminder to
    # Tuesday. Whatever broke is repaired during the night.
    apply_schedule(both, _policy(hour=8, weekday=1), at + timedelta(minutes=10))
    assert digest.retrying_on is None and reminder.retrying_on is None
    assert reminder.next_run == datetime(2026, 10, 6, 8, tzinfo=UTC)
    state["fail"] = False
    runs.clear()
    tuesday = datetime(2026, 10, 6, 8, 0, 5, tzinfo=UTC)
    await run_due_jobs(both, tuesday)
    assert runs == [tuesday, tuesday]  # the digest and the reminder
    assert digest.next_run == datetime(2026, 10, 7, 8, tzinfo=UTC)
    assert reminder.next_run == datetime(2026, 10, 13, 8, tzinfo=UTC)


async def test_giving_up_yesterdays_retry_runs_the_occurrence_already_due():
    """The give-up itself, whatever left the retry behind: when the job's own
    occurrence has come due since midnight, it runs — with a digest hour of
    0 and a failure lasting until midnight, the new day's digest was never
    attempted."""
    from app.core.worker import POLL_SECONDS, Job, daily_at, run_due_jobs

    runs: list[datetime] = []

    async def down() -> int:
        runs.append(datetime.now(UTC))
        raise RuntimeError("down")

    at = datetime(2026, 10, 1, 0, 0, 5, tzinfo=UTC)
    job = Job("daily_digest", down, at, daily_at(0), retry_same_day=True)
    await run_due_jobs([job], at)
    last = datetime(2026, 10, 1, 23, 59, 50, tzinfo=UTC)
    job.next_run = last
    await run_due_jobs([job], last)
    assert len(runs) == 2
    # 00:00:20 on the 2nd: the 1st is given up, the 2nd's own digest is due.
    tick = last + timedelta(seconds=POLL_SECONDS)
    await run_due_jobs([job], tick)
    assert len(runs) == 3
    assert job.retrying_on == tick.date()  # … and retried on its own day
    assert job.next_run == tick + timedelta(seconds=POLL_SECONDS)

    # A stale retry met at a real occurrence (an hour moved meanwhile).
    job = Job(
        "daily_digest",
        down,
        datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
        daily_at(8),
        retry_same_day=True,
        retrying_on=datetime(2026, 10, 1, tzinfo=UTC).date(),
    )
    await run_due_jobs([job], datetime(2026, 10, 2, 8, 0, 5, tzinfo=UTC))
    assert len(runs) == 4


def test_an_hour_moved_to_one_already_passed_is_due_now_like_a_restart():
    """10:05, the digest set from 18:00 to 09:00, nothing sent today: the
    change skipped the day, when a worker restarted at that instant with the
    same settings sends it at once."""
    from app.core.worker import apply_schedule, build_jobs

    morning = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)  # a Monday
    changed = morning + timedelta(minutes=5)
    jobs = build_jobs(morning, _policy(hour=18, weekday=3))
    new = _policy(hour=9, weekday=0)
    apply_schedule(jobs, new, changed)
    restarted = build_jobs(changed, new)
    for name in ("daily_digest", "maintenance_reminders"):
        assert _job(jobs, name).next_run == changed, name
        assert _job(restarted, name).next_run == changed, name

    # Served today already (in this process): tomorrow, next week.
    jobs = build_jobs(morning, _policy(hour=18, weekday=3))
    for name in ("daily_digest", "maintenance_reminders"):
        _job(jobs, name).last_run = morning
    apply_schedule(jobs, new, changed)
    assert _job(jobs, "daily_digest").next_run == datetime(2026, 10, 6, 9, tzinfo=UTC)
    assert _job(jobs, "maintenance_reminders").next_run == datetime(
        2026, 10, 12, 9, tzinfo=UTC
    )


# --- The period a mail job records ---------------------------------------------------


async def test_the_period_recorded_is_that_of_the_tick(engine, db_session, monkeypatch):
    """A catch-up decided at 23:59:59.9 and run a few milliseconds later, on
    the next day by the clock: it recorded the next day, whose own digest was
    then skipped as already sent."""
    from app.core import worker
    from app.features.notification import digest, tasks
    from app.features.setting import crud

    monkeypatch.setattr(worker, "engine", engine)
    tick = datetime(2026, 10, 4, 23, 59, 59, 900000, tzinfo=UTC)  # a Sunday
    monday = datetime(2026, 10, 5, 0, 0, 0, 50000, tzinfo=UTC)
    jobs = worker.build_jobs(tick, _policy(hour=18, weekday=6))
    mail = [_job(jobs, "daily_digest"), _job(jobs, "maintenance_reminders")]
    assert [j.next_run for j in mail] == [tick, tick]  # Sunday's, caught up
    runs: list[str] = []

    async def fake_digest(session) -> int:
        runs.append("digest")
        return 1

    async def fake_reminder(session) -> int:
        runs.append("reminder")
        return 1

    monkeypatch.setattr(digest, "send_daily_digest", fake_digest)
    monkeypatch.setattr(tasks, "send_maintenance_reminders", fake_reminder)
    monkeypatch.setattr(worker, "utcnow", lambda: monday)
    await worker.run_due_jobs(mail, tick)
    assert runs == ["digest", "reminder"]
    keys = worker.LAST_RUN_KEYS
    assert await crud.get_value(db_session, keys["daily_digest"]) == "2026-10-04"
    assert await crud.get_value(db_session, keys["maintenance_reminders"]) == "2026-W40"

    # Monday's own digest, at its hour, is not taken for sent.
    at = datetime(2026, 10, 5, 18, 0, 5, tzinfo=UTC)
    await worker.run_due_jobs(mail, at)
    assert runs == ["digest", "reminder", "digest"]


async def test_two_workers_send_one_period_once(engine, db_session, monkeypatch):
    """Two workers on one database by mistake (`--scale worker=2`, a second
    stack): both read « not sent for today » and both queued the digest. The
    second now waits for the first, and sends only if that one failed."""
    import asyncio

    from app.core import worker
    from app.features.notification import digest
    from app.features.setting import crud
    from app.features.setting.models import AppSetting

    monkeypatch.setattr(worker, "engine", engine)
    key = worker.LAST_RUN_KEYS["daily_digest"]
    now = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)

    for first_fails, yesterday in ((False, None), (False, "2026-10-04"), (True, None)):
        # With no record at all (the first run) and with yesterday's.
        row = await db_session.get(AppSetting, key)
        if row is not None:
            await db_session.delete(row)
        if yesterday is not None:
            await crud.set_value(db_session, key, yesterday, actor="t")
        await db_session.commit()
        inside: list[int] = []
        release = asyncio.Event()

        async def building(
            session, inside=inside, release=release, fails=first_fails
        ) -> int:
            inside.append(1)
            await release.wait()
            if fails and len(inside) == 1:
                raise RuntimeError("smtp down")
            return 1

        monkeypatch.setattr(digest, "send_daily_digest", building)
        both = [asyncio.create_task(worker.send_daily_digest(now)) for _ in range(2)]
        await asyncio.sleep(0.3)
        assert len(inside) == 1, "both workers are building the same digest"
        release.set()
        results = await asyncio.gather(*both, return_exceptions=True)
        if first_fails:
            # The first one's failure is not taken for a sent digest.
            assert sorted(map(repr, results)) == ["1", "RuntimeError('smtp down')"]
            assert len(inside) == 2
        else:
            assert sorted(results) == [0, 1]
            assert len(inside) == 1
        db_session.expire_all()
        assert await crud.get_value(db_session, key) == "2026-10-05"


# --- The day of the upgrade (migration 0042) -----------------------------------------


def _migration_0042():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "app/alembic/versions/0042_mail_periods_seed.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0042", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _seed(engine, now: datetime) -> dict[str, str]:
    migration = _migration_0042()
    async with engine.begin() as conn:
        return await conn.run_sync(migration.seed_mail_periods, now)


async def _an_account(db_session) -> None:
    from app.features.user import crud as user_crud

    await user_crud.create_user(
        db_session, email="admin@test.local", password="correct-horse-battery"
    )
    await db_session.commit()


async def test_the_upgrade_day_does_not_send_the_digest_again(
    engine, db_session, monkeypatch
):
    """v1.2.0 sent the 18:00 digest; the server is upgraded at 19:00. The new
    worker, with no record of it, sent that day's digest a second time — and
    the reminder, on its day. The migration records what was served."""
    from app.core import worker
    from app.core.config import settings
    from app.features.notification import digest, tasks

    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(settings, "DIGEST_HOUR_UTC", 18)
    monkeypatch.setattr(settings, "MAINTENANCE_REMINDER_WEEKDAY", 0)
    await _an_account(db_session)
    late = datetime(2026, 10, 5, 19, 0, tzinfo=UTC)  # a Monday

    assert await _seed(engine, late) == {
        "worker.last_run.daily_digest": "2026-10-05",
        "worker.last_run.maintenance_reminders": "2026-W41",
    }
    assert await _seed(engine, late) == {}  # run twice: nothing more

    runs: list[str] = []

    async def fake(session) -> int:
        runs.append("sent")
        return 1

    monkeypatch.setattr(digest, "send_daily_digest", fake)
    monkeypatch.setattr(tasks, "send_maintenance_reminders", fake)
    jobs = worker.build_jobs(late, _policy(hour=18, weekday=0))
    mail = [_job(jobs, "daily_digest"), _job(jobs, "maintenance_reminders")]
    assert [j.next_run for j in mail] == [late, late]  # both caught up at start
    await worker.run_due_jobs(mail, late)
    assert runs == []
    # Tomorrow's digest and next week's reminder go out as usual.
    await worker.run_due_jobs(mail, datetime(2026, 10, 6, 18, 0, 5, tzinfo=UTC))
    await worker.run_due_jobs(mail, datetime(2026, 10, 12, 18, 0, 5, tzinfo=UTC))
    assert runs == ["sent", "sent", "sent"]


@pytest.mark.parametrize("minute", [0, 30])
async def test_an_upgrade_during_the_digest_hour_records_it(
    engine, db_session, monkeypatch, minute
):
    """v1.2.0 sends at HH:00 sharp: upgraded at 18:00 or 18:30 with an 18:00
    digest, the day's digest — and on its day the week's reminder — is
    already out. Recorded only from 19:00, the new worker's first run would
    send them again. (At 17:59 nothing is recorded: the test above.)"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DIGEST_HOUR_UTC", 18)
    monkeypatch.setattr(settings, "MAINTENANCE_REMINDER_WEEKDAY", 0)
    await _an_account(db_session)
    monday = datetime(2026, 10, 5, 18, minute, tzinfo=UTC)
    assert await _seed(engine, monday) == {
        "worker.last_run.daily_digest": "2026-10-05",
        "worker.last_run.maintenance_reminders": "2026-W41",
    }


async def test_the_migration_seeds_when_it_is_run(engine, db_session, monkeypatch):
    """`alembic upgrade` itself, on the clock: with a schedule of Monday
    00:00, every instant of the week is past both the digest's hour and the
    reminder's day."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.core import worker
    from app.core.config import settings
    from app.features.setting import crud

    monkeypatch.setattr(settings, "DIGEST_HOUR_UTC", 0)
    monkeypatch.setattr(settings, "MAINTENANCE_REMINDER_WEEKDAY", 0)
    await _an_account(db_session)
    migration = _migration_0042()

    def upgrade(conn) -> None:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()

    before = worker.utcnow()
    async with engine.begin() as conn:
        await conn.run_sync(upgrade)
    after = worker.utcnow()

    keys = worker.LAST_RUN_KEYS
    assert await crud.get_value(db_session, keys["daily_digest"]) in {
        worker._day(before),
        worker._day(after),
    }
    assert await crud.get_value(db_session, keys["maintenance_reminders"]) in {
        worker._iso_week(before),
        worker._iso_week(after),
    }


async def test_the_seed_reads_the_schedule_as_the_worker_does(
    engine, db_session, monkeypatch
):
    from app.core import worker
    from app.core.config import settings
    from app.features.setting import crud
    from app.features.setting.models import AppSetting

    monkeypatch.setattr(settings, "DIGEST_HOUR_UTC", 18)
    monkeypatch.setattr(settings, "MAINTENANCE_REMINDER_WEEKDAY", 0)
    keys = worker.LAST_RUN_KEYS

    # A new installation — no account yet: nothing was ever sent.
    assert await _seed(engine, datetime(2026, 10, 5, 19, 0, tzinfo=UTC)) == {}
    await _an_account(db_session)

    # Before the hour (environment: 18:00, Monday): today's digest is still
    # to come, and the worker will send it — nothing recorded.
    assert await _seed(engine, datetime(2026, 10, 5, 17, 59, tzinfo=UTC)) == {}
    # Wednesday morning: Monday's reminder is behind, the day's digest not.
    assert await _seed(engine, datetime(2026, 10, 7, 9, 0, tzinfo=UTC)) == {
        keys["maintenance_reminders"]: "2026-W41"
    }

    # The console's schedule wins over the environment's: 08:00, Thursday.
    await crud.set_value(db_session, crud.KEY_DIGEST_HOUR, 8, actor="t")
    await crud.set_value(db_session, crud.KEY_REMINDER_WEEKDAY, 3, actor="t")
    await db_session.delete(
        await db_session.get_one(AppSetting, keys["maintenance_reminders"])
    )
    await db_session.commit()
    policy = await crud.schedule_policy(db_session)
    assert (policy.digest_hour_utc, policy.reminder_weekday) == (8, 3)
    wednesday = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
    assert await _seed(engine, wednesday) == {keys["daily_digest"]: "2026-10-07"}

    # A record already there — the worker's own — is never overwritten.
    await crud.set_value(db_session, keys["daily_digest"], "2026-10-01", actor="worker")
    await db_session.commit()
    assert await _seed(engine, datetime(2026, 10, 8, 9, 0, tzinfo=UTC)) == {
        keys["maintenance_reminders"]: "2026-W41"
    }
    db_session.expire_all()
    assert await crud.get_value(db_session, keys["daily_digest"]) == "2026-10-01"


async def test_a_drain_that_outlasts_the_grace_is_cancelled_and_over():
    """A mail in flight on a server gone silent: past the grace the drain is
    cancelled, and has ended — its session closed — when the worker says it
    stopped."""
    import asyncio

    from app.core.worker import Job, every, finish_background, run_due_jobs

    closed: list[str] = []

    async def stuck() -> int:
        try:
            await asyncio.sleep(60)
        finally:
            closed.append("session")
        return 0

    now = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    job = Job("outbox", stuck, now, every(30), background=True)
    await run_due_jobs([job], now)
    await asyncio.sleep(0)
    await asyncio.wait_for(finish_background([job], timeout=0.05), timeout=2)
    assert job.task is not None and job.task.cancelled()
    assert closed == ["session"]
