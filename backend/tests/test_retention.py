"""Retention purges run by the worker: audit log, command history, reset tokens.

The jobs open their own session on the module-level engine, pointed at the
test database by monkeypatch, like the other worker tests. DB-backed tests
require TIAI_TEST_DATABASE_URL.
"""

from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def worker(engine, monkeypatch):
    from app.core import worker as module

    monkeypatch.setattr(module, "engine", engine)
    return module


def _now() -> datetime:
    return datetime.now(UTC)


# --- Audit log ---------------------------------------------------------------


async def _audit_at(db_session, *ages_days: float) -> None:
    from app.features.audit.models import AuditEntry

    for age in ages_days:
        db_session.add(
            AuditEntry(
                actor="admin@test.local",
                action=f"test.age_{age}",
                resource_type="machine",
                resource_id="r",
                at=_now() - timedelta(days=age),
            )
        )
    await db_session.commit()


async def _audit_actions(db_session) -> set[str]:
    from sqlmodel import select

    from app.features.audit.models import AuditEntry

    return set((await db_session.exec(select(AuditEntry.action))).all())


async def test_audit_entries_past_the_retention_are_purged(
    worker, db_session, monkeypatch
):
    monkeypatch.setattr(worker.settings, "AUDIT_RETENTION_DAYS", 730)
    await _audit_at(db_session, 731, 729, 0)

    assert await worker.purge_audit() == 1
    assert await _audit_actions(db_session) == {"test.age_729", "test.age_0"}


async def test_audit_retention_zero_keeps_everything(worker, db_session, monkeypatch):
    monkeypatch.setattr(worker.settings, "AUDIT_RETENTION_DAYS", 0)
    await _audit_at(db_session, 5000, 1)

    assert await worker.purge_audit() == 0
    assert len(await _audit_actions(db_session)) == 2


# --- Command history ------------------------------------------------------------


async def _machine(db_session):
    from app.features.machine.models import Machine

    machine = Machine(machine_uuid="retention")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    return machine.id


async def _command(db_session, machine_id, label: str, status: str, **dates):
    from app.features.command.models import Command

    created_at = dates.pop("created_at")
    db_session.add(
        Command(
            machine_id=machine_id,
            type="quick_scan",
            status=status,
            # The label rides in created_by, so the assertions read as names.
            created_by=label,
            created_at=created_at,
            expires_at=created_at + timedelta(hours=1),
            **dates,
        )
    )


async def _remaining(db_session) -> set[str]:
    from sqlmodel import select

    from app.features.command.models import Command

    return set((await db_session.exec(select(Command.created_by))).all())


async def test_finished_commands_past_the_retention_are_purged(
    worker, db_session, monkeypatch
):
    monkeypatch.setattr(worker.settings, "COMMAND_RETENTION_DAYS", 365)
    machine_id = await _machine(db_session)
    old = _now() - timedelta(days=400)
    recent = _now() - timedelta(days=10)

    # Over, and old: gone.
    await _command(
        db_session,
        machine_id,
        "old-succeeded",
        "succeeded",
        created_at=old,
        finished_at=old,
    )
    await _command(
        db_session, machine_id, "old-failed", "failed", created_at=old, finished_at=old
    )
    await _command(db_session, machine_id, "old-expired", "expired", created_at=old)
    # Delivered to an agent that never answered, a year ago: its verdict is
    # not coming any more.
    await _command(
        db_session,
        machine_id,
        "old-delivered",
        "delivered",
        created_at=old,
        delivered_at=old,
    )
    # Never purged, whatever their age: still owed, or still being executed.
    await _command(db_session, machine_id, "old-pending", "pending", created_at=old)
    await _command(
        db_session,
        machine_id,
        "old-running",
        "running",
        created_at=old,
        delivered_at=old,
        started_at=old,
    )
    # Queued long ago but answered recently: aged from the answer.
    await _command(
        db_session,
        machine_id,
        "late-verdict",
        "succeeded",
        created_at=old,
        delivered_at=old,
        finished_at=recent,
    )
    # Queued long ago, delivered only recently (a long TTL, a poste off for
    # weeks) and not answered yet: aged from the delivery.
    await _command(
        db_session,
        machine_id,
        "late-delivery",
        "delivered",
        created_at=old,
        delivered_at=recent,
    )
    await _command(
        db_session,
        machine_id,
        "recent",
        "succeeded",
        created_at=recent,
        finished_at=recent,
    )
    await db_session.commit()

    assert await worker.purge_commands() == 4
    assert await _remaining(db_session) == {
        "old-pending",
        "old-running",
        "late-verdict",
        "late-delivery",
        "recent",
    }


async def test_command_retention_zero_keeps_the_history(
    worker, db_session, monkeypatch
):
    monkeypatch.setattr(worker.settings, "COMMAND_RETENTION_DAYS", 0)
    machine_id = await _machine(db_session)
    ancient = _now() - timedelta(days=5000)
    await _command(
        db_session,
        machine_id,
        "ancient",
        "succeeded",
        created_at=ancient,
        finished_at=ancient,
    )
    await db_session.commit()

    assert await worker.purge_commands() == 0
    assert await _remaining(db_session) == {"ancient"}


# --- Password-reset tokens -------------------------------------------------------


async def test_spent_reset_tokens_are_purged_after_a_day(worker, db_session):
    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    user = await crud.create_user(db_session, email="reset@test.local", password="pw")
    user_id = user.id  # read before the commit expires it
    await db_session.commit()
    now = _now()

    def token(label: str, *, expires: timedelta, used: timedelta | None = None):
        return PasswordResetToken(
            user_id=user_id,
            token_hash=label,
            expires_at=now + expires,
            used_at=None if used is None else now + used,
            created_at=now - timedelta(days=3),
        )

    db_session.add_all(
        [
            token("expired-two-days", expires=-timedelta(days=2)),
            token("expired-an-hour", expires=-timedelta(hours=1)),
            token(
                "used-two-days",
                expires=-timedelta(days=2) + timedelta(hours=1),
                used=-timedelta(days=2),
            ),
            token(
                "used-an-hour", expires=timedelta(minutes=30), used=-timedelta(hours=1)
            ),
            token("valid", expires=timedelta(minutes=30)),
        ]
    )
    await db_session.commit()

    assert await worker.purge_reset_tokens() == 2
    left = set((await db_session.exec(select(PasswordResetToken.token_hash))).all())
    assert left == {"expired-an-hour", "used-an-hour", "valid"}


async def test_a_long_lived_unused_token_is_kept(worker, db_session):
    """Validity, not age: a deployment with a three-day link keeps it three days."""
    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    user = await crud.create_user(db_session, email="slow@test.local", password="pw")
    user_id = user.id  # read before the commit expires it
    await db_session.commit()
    now = _now()
    db_session.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash="slow",
            created_at=now - timedelta(days=2),
            expires_at=now + timedelta(days=1),
        )
    )
    await db_session.commit()

    assert await worker.purge_reset_tokens() == 0
    assert (await db_session.exec(select(PasswordResetToken.token_hash))).all() == [
        "slow"
    ]


# --- Settings ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AUDIT_RETENTION_DAYS", "-1"),
        ("AUDIT_RETENTION_DAYS", "3651"),
        ("COMMAND_RETENTION_DAYS", "-1"),
        ("COMMAND_RETENTION_DAYS", "3651"),
    ],
)
def test_retention_settings_are_bounded(name, value, monkeypatch):
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError, match=name):
        Settings(_env_file=None)


def test_retention_defaults():
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    assert settings.AUDIT_RETENTION_DAYS == 730
    assert settings.COMMAND_RETENTION_DAYS == 365
