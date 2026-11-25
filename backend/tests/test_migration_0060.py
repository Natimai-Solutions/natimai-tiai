"""Migration 0060: the trends' tables and the indexes added for the
indicators (requires TIAI_TEST_DATABASE_URL)."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0060_trends.py"
)

INDEXES = (
    "uq_trend_snapshots_cell",
    "ix_interventions_kind_performed",
    "ix_machine_checks_closed_at",
    "ix_commands_finished_at",
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0060", _PATH)
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


async def test_down_and_up_again_matches_the_models(engine):
    # The schema of the tests is the models' (``create_all``).
    declared = await _index_defs(engine)
    assert all(declared.values())

    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
    assert not await _scalar(engine, "SELECT to_regclass('trend_days') IS NOT NULL")
    assert not await _scalar(
        engine, "SELECT to_regclass('trend_snapshots') IS NOT NULL"
    )
    assert all(v is None for v in (await _index_defs(engine)).values())

    async with engine.begin() as conn:
        await conn.run_sync(_run, "upgrade")
    assert await _index_defs(engine) == declared


async def test_defaults_and_nulls_not_distinct(engine):
    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
        await conn.run_sync(_run, "upgrade")

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO trend_days (day, taken_at, zone) "
                "VALUES ('2026-11-25', now(), 'UTC')"
            )
        )
        await conn.execute(
            sa.text(
                "INSERT INTO trend_snapshots (id, day) "
                "VALUES (gen_random_uuid(), '2026-11-25')"
            )
        )
    assert await _scalar(engine, "SELECT policies::text FROM trend_days") == "{}"
    assert await _scalar(engine, "SELECT counters::text FROM trend_snapshots") == "{}"

    # A second cell with neither site nor room on the same day: refused.
    with pytest.raises(sa.exc.IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO trend_snapshots (id, day) "
                    "VALUES (gen_random_uuid(), '2026-11-25')"
                )
            )

    # Deleting the day takes its cells.
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM trend_days"))
    assert await _scalar(engine, "SELECT count(*) FROM trend_snapshots") == 0
