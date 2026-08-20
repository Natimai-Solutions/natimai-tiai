"""ARQ worker job tests (require TIAI_TEST_DATABASE_URL).

The jobs open their own session on the module-level engine, so we point that
engine at the test database via monkeypatch.
"""

from datetime import UTC, datetime, timedelta


async def test_expire_stale_commands_marks_pending(engine, db_session, monkeypatch):
    from sqlmodel import select

    from app.core import arq_worker
    from app.features.command.models import Command, CommandStatus
    from app.features.machine.models import Machine

    monkeypatch.setattr(arq_worker, "engine", engine)

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

    n = await arq_worker.expire_stale_commands({})
    assert n == 1

    status = (
        await db_session.exec(select(Command.status).where(Command.id == stale_id))
    ).one()
    assert status == CommandStatus.EXPIRED


async def test_flag_inactive_machines_counts_stale(engine, db_session, monkeypatch):
    from app.core import arq_worker
    from app.features.machine.models import Machine

    monkeypatch.setattr(arq_worker, "engine", engine)

    db_session.add(
        Machine(
            machine_uuid="w-old",
            last_seen=datetime.now(UTC) - timedelta(days=999),
        )
    )
    db_session.add(Machine(machine_uuid="w-recent"))  # last_seen defaults to now
    await db_session.commit()

    assert await arq_worker.flag_inactive_machines({}) == 1


def test_worker_settings_registers_jobs():
    from app.core.arq_worker import (
        WorkerSettings,
        expire_stale_commands,
        flag_inactive_machines,
        send_daily_digest,
    )

    assert expire_stale_commands in WorkerSettings.functions
    assert flag_inactive_machines in WorkerSettings.functions
    assert send_daily_digest in WorkerSettings.functions
    assert len(WorkerSettings.cron_jobs) == 3


def test_digest_cron_fires_once_a_day():
    """One firing per day, not sixty.

    ARQ crons match on every field left unconstrained, so an hour without a
    minute would run the digest at every minute of that hour — sixty identical
    mails to every operator. This asserts the two constraints that prevent it.
    """
    from app.core.arq_worker import WorkerSettings, send_daily_digest
    from app.core.config import settings

    job = next(j for j in WorkerSettings.cron_jobs if j.coroutine is send_daily_digest)
    assert job.hour == {settings.DIGEST_HOUR_UTC}
    assert job.minute == {0}
