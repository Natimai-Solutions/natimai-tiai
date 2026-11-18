"""Migration 0046: the code columns of a command's verdict, added nullable —
an existing row keeps its French text and reads as before (requires
TIAI_TEST_DATABASE_URL)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0046_command_result_codes.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0046", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn: sa.Connection, step: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        getattr(_migration(), step)()


async def _columns(engine) -> dict[str, tuple[str, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'commands' "
                "AND column_name IN ('result_code', 'result_params')"
            )
        )
        return {name: (kind, nullable) for name, kind, nullable in rows.all()}


async def test_the_columns_come_and_go_and_old_rows_keep_their_text(engine, db_session):
    from app.features.machine.models import Machine

    assert _migration().down_revision == "0045_user_language"
    machine = Machine(machine_uuid="m-0046")
    machine_id = machine.id
    db_session.add(machine)
    await db_session.commit()

    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
    assert await _columns(engine) == {}

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO commands (id, machine_id, type, status, created_at, "
                "expires_at, error) VALUES (gen_random_uuid(), :m, 'flush_dns', "
                "'failed', now(), now(), 'Poste fusionné : commande annulée')"
            ),
            {"m": machine_id},
        )
        await conn.run_sync(_run, "upgrade")

    assert await _columns(engine) == {
        "result_code": ("character varying", "YES"),
        "result_params": ("jsonb", "YES"),
    }
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT error, result_code, result_params FROM commands")
            )
        ).one()
    assert tuple(row) == ("Poste fusionné : commande annulée", None, None)
