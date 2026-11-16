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
        "expire_stale_commands",
        "close_unanswered_commands",
        "daily_digest",
        "maintenance_reminders",
        "purge_outbox",
        "purge_software",
        "purge_shared_counters",
        "purge_usage",
        "purge_sessions",
        "purge_audit",
        "purge_commands",
        "purge_reset_tokens",
        "purge_login_addresses",
    }
    # The outbox is due immediately: a restarted worker must resume mail
    # delivery on its first tick, not after an arbitrary wait.
    assert jobs["outbox"].next_run == now
    # Every retention purge runs in the morning housekeeping slot.
    for name in ("purge_audit", "purge_commands", "purge_reset_tokens"):
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
    monkeypatch.setattr(worker, "build_jobs", lambda now, policy=None: [])

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
