"""Migration 0061: the approval requests, their lists, the schedules'
approval columns, and the way down for a schedule waiting for its approval
(requires TIAI_TEST_DATABASE_URL)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0061_mass_approval.py"
)

INDEXES = (
    "ix_approval_requests_status_expires",
    "ix_approval_requests_requested_by_status",
    "ix_approval_requests_decided_at",
    "ix_approval_requests_decided_by_id",
    "ix_approval_requests_schedule_id",
    "ix_approval_requests_package_id",
    "uq_approval_requests_pending_schedule",
    "uq_approval_requests_pending_key",
    "ix_approval_request_machines_machine_id",
    "ix_schedules_approved_by_id",
    "ix_schedules_approved_for_id",
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0061", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn: sa.Connection, step: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        getattr(_migration(), step)()


async def _scalar(engine, sql: str, **params):
    async with engine.connect() as conn:
        return (await conn.execute(sa.text(sql), params)).scalar()


async def _index_defs(engine) -> dict[str, str | None]:
    return {
        name: await _scalar(
            engine,
            "SELECT indexdef FROM pg_indexes WHERE indexname = :name",
            name=name,
        )
        for name in INDEXES
    }


async def _seed(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO schedules (id, name, command_type, target, recurrence, "
                "run_at, ttl_minutes, wake_first, shutdown_after, state, next_run_at, "
                "created_by, created_at, updated_at) VALUES "
                "(gen_random_uuid(), 'À approuver', 'reboot', '{\"kind\": \"all\"}', "
                "'once', now() + interval '1 day', 180, false, false, 'to_approve', "
                "NULL, 'a@test.local', now(), now()), "
                "(gen_random_uuid(), 'Active', 'quick_scan', '{\"kind\": \"all\"}', "
                "'once', now() + interval '1 day', 180, false, false, 'active', "
                "now() + interval '1 day', 'a@test.local', now(), now())"
            )
        )
        await conn.execute(
            sa.text(
                "INSERT INTO approval_requests (id, kind, command_type, target, "
                "machine_count, threshold, requested_by, requested_at, expires_at, "
                "schedule_id) SELECT gen_random_uuid(), 'schedule', 'reboot', "
                "'{\"kind\": \"all\"}', 45, 40, 'a@test.local', now(), "
                "now() + interval '1 day', id FROM schedules WHERE state = 'to_approve'"
            )
        )


async def test_down_with_a_schedule_waiting_and_up_again(engine):
    # The schema of the tests is the models' (``create_all``).
    declared = await _index_defs(engine)
    assert all(declared.values())
    await _seed(engine)
    # A pending request takes the server's default status.
    assert await _scalar(engine, "SELECT status FROM approval_requests") == "pending"

    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
    assert not await _scalar(
        engine, "SELECT to_regclass('approval_requests') IS NOT NULL"
    )
    assert not await _scalar(
        engine, "SELECT to_regclass('approval_request_machines') IS NOT NULL"
    )
    assert not await _scalar(
        engine,
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'schedules' AND column_name LIKE 'approved_%'",
    )
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text("SELECT name, state, next_run_at FROM schedules")
        )
        rows = {name: (state, next_run) for name, state, next_run in result.all()}
    assert rows["À approuver"] == ("disabled", None)
    assert rows["Active"][0] == "active" and rows["Active"][1] is not None

    async with engine.begin() as conn:
        await conn.run_sync(_run, "upgrade")
    assert await _index_defs(engine) == declared


async def test_one_pending_request_per_schedule_and_per_key(engine):
    import pytest

    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
        await conn.run_sync(_run, "upgrade")
    await _seed(engine)
    insert = (
        "INSERT INTO approval_requests (id, kind, command_type, target, "
        "machine_count, threshold, requested_by, requested_at, expires_at, "
        "schedule_id, request_key, status) SELECT gen_random_uuid(), 'schedule', "
        "'reboot', '{}', 45, 40, 'a', now(), now(), id, :key, :status "
        "FROM schedules WHERE state = 'to_approve'"
    )
    # A second pending one for the same schedule: refused; a closed one: fine.
    async with engine.begin() as conn:
        await conn.execute(sa.text(insert), {"key": None, "status": "cancelled"})
    with pytest.raises(sa.exc.IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(sa.text(insert), {"key": None, "status": "pending"})
    # Deleting the schedule takes its requests.
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM schedules WHERE state = 'to_approve'"))
    assert await _scalar(engine, "SELECT count(*) FROM approval_requests") == 0
