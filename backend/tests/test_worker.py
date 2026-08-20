"""Worker tests.

The scheduling helpers are pure arithmetic and need nothing; the jobs open
their own session on the module-level engine, so the DB-backed tests (require
TIAI_TEST_DATABASE_URL) point that engine at the test database via monkeypatch.
"""

from datetime import UTC, datetime, timedelta


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


async def test_flag_inactive_machines_counts_stale(engine, db_session, monkeypatch):
    from app.core import worker
    from app.features.machine.models import Machine

    monkeypatch.setattr(worker, "engine", engine)

    db_session.add(
        Machine(
            machine_uuid="w-old",
            last_seen=datetime.now(UTC) - timedelta(days=999),
        )
    )
    db_session.add(Machine(machine_uuid="w-recent"))  # last_seen defaults to now
    await db_session.commit()

    assert await worker.flag_inactive_machines() == 1


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
        "flag_inactive_machines",
        "daily_digest",
        "purge_outbox",
    }
    # The outbox is due immediately: a restarted worker must resume mail
    # delivery on its first tick, not after an arbitrary wait.
    assert jobs["outbox"].next_run == now
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
