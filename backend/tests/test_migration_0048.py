"""Migration 0048: the alerts' table, and the date a pending restart is
counted from — a poste already waiting at the upgrade counts from the upgrade,
one that is not stays without (requires TIAI_TEST_DATABASE_URL)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0048_machine_alerts.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0048", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn: sa.Connection, step: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        getattr(_migration(), step)()


async def _has_table(engine, name: str) -> bool:
    async with engine.connect() as conn:
        return bool(
            (
                await conn.execute(
                    sa.text("SELECT to_regclass(:name) IS NOT NULL"),
                    {"name": name},
                )
            ).scalar()
        )


async def test_pending_restarts_count_from_the_upgrade(engine, db_session):
    from app.features.machine.models import Machine

    pending = Machine(machine_uuid="m-pending", wu_reboot_required=True)
    idle = Machine(machine_uuid="m-idle", wu_reboot_required=False)
    db_session.add_all([pending, idle])
    await db_session.commit()

    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
    assert not await _has_table(engine, "machine_alerts")

    async with engine.begin() as conn:
        await conn.run_sync(_run, "upgrade")
    assert await _has_table(engine, "machine_alerts")

    async with engine.connect() as conn:
        rows = dict(
            (
                await conn.execute(
                    sa.text(
                        "SELECT machine_uuid, wu_reboot_required_since IS NOT NULL "
                        "FROM machines"
                    )
                )
            ).all()
        )
    assert rows == {"m-pending": True, "m-idle": False}
