"""Migration 0062: the attachments and procedures tables, the procedure
rights of the built-in technicians, and the way down
(requires TIAI_TEST_DATABASE_URL)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0062_attachments_procedures.py"
)

INDEXES = (
    "ix_intervention_attachments_intervention",
    "ix_intervention_attachments_sha256",
    "ix_intervention_attachments_created_at",
    "uq_intervention_attachments_intervention_sha",
    "uq_procedures_hw_model",
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0062", _PATH)
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


async def _groups(engine) -> None:
    """The built-in groups, the technicians' renamed, and one of the
    operator's."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO groups (id, name, builtin_key, created_at, updated_at) VALUES "
                "(gen_random_uuid(), 'Équipe terrain', 'technician', now(), now()), "
                "(gen_random_uuid(), 'Lecture seule', 'readonly', now(), now()), "
                "(gen_random_uuid(), 'Administrateurs', 'admin', now(), now()), "
                "(gen_random_uuid(), 'Mes techniciens', NULL, now(), now())"
            )
        )


async def _granted(engine) -> dict[str, list[str]]:
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text(
                "SELECT g.name, p.permission FROM group_permissions p "
                "JOIN groups g ON g.id = p.group_id "
                "WHERE p.permission LIKE 'procedure:%' ORDER BY g.name, p.permission"
            )
        )
        out: dict[str, list[str]] = {}
        for name, permission in result.all():
            out.setdefault(name, []).append(permission)
        return out


async def test_down_and_up_again(engine):
    # The schema of the tests is the models' (``create_all``).
    declared = await _index_defs(engine)
    assert all(declared.values())
    await _groups(engine)
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO app_settings (key, value, updated_at) VALUES "
                "('attachments.retention_days', '30', now())"
            )
        )
        # Already granted by hand: no duplicate, no failure.
        await conn.execute(
            sa.text(
                "INSERT INTO group_permissions (group_id, permission) "
                "SELECT id, 'procedure:read' FROM groups WHERE builtin_key = 'technician'"
            )
        )
    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
    for table in ("intervention_attachments", "procedures"):
        assert not await _scalar(engine, f"SELECT to_regclass('{table}') IS NOT NULL")
    assert await _granted(engine) == {}
    assert not await _scalar(
        engine,
        "SELECT count(*) FROM app_settings WHERE key = 'attachments.retention_days'",
    )

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO group_permissions (group_id, permission) "
                "SELECT id, 'procedure:read' FROM groups WHERE builtin_key = 'technician'"
            )
        )
        await conn.run_sync(_run, "upgrade")
    assert await _index_defs(engine) == declared
    # The technicians only — by their key, whatever their name.
    assert await _granted(engine) == {
        "Équipe terrain": ["procedure:read", "procedure:write"]
    }


async def test_deleting_a_line_deletes_its_attachments(engine):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.machine.models import Machine

    async with engine.begin() as conn:
        await conn.run_sync(_run, "downgrade")
        await conn.run_sync(_run, "upgrade")
    async with AsyncSession(engine) as session:
        session.add(Machine(machine_uuid="u-1", hostname="PC-1"))
        await session.commit()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO interventions (id, machine_id, kind, performed_by, "
                "performed_at, created_at, updated_at) SELECT gen_random_uuid(), id, "
                "'incident', 'a', now(), now(), now() FROM machines"
            )
        )
        await conn.execute(
            sa.text(
                "INSERT INTO intervention_attachments (id, intervention_id, sha256, "
                "size, content_type, filename, uploaded_by, created_at) SELECT "
                "gen_random_uuid(), id, repeat('a', 64), 1, 'image/png', 'a.png', "
                "'a', now() FROM interventions"
            )
        )
    import pytest

    # The same file twice on the line: refused.
    with pytest.raises(sa.exc.IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO intervention_attachments (id, intervention_id, "
                    "sha256, size, content_type, filename, uploaded_by, created_at) "
                    "SELECT gen_random_uuid(), id, repeat('a', 64), 1, 'image/png', "
                    "'b.png', 'a', now() FROM interventions"
                )
            )
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM interventions"))
    assert await _scalar(engine, "SELECT count(*) FROM intervention_attachments") == 0
