"""Migration 0037: the data repairs it makes, run against a real database
(requires TIAI_TEST_DATABASE_URL)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0037_accounts_hardening.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0037", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_technicians_get_package_read_once(engine, db_session):
    """A database migrated before ``package:read`` joined the technicians'
    defaults: the group — renamed since, found by its key — gets it, once."""
    from sqlmodel import delete, select

    from app.features.user import crud
    from app.features.user.models import Group, GroupPermission
    from app.features.user.permissions import BuiltinGroup

    await crud.ensure_builtin_groups(db_session)
    await db_session.commit()
    techs = await crud.builtin_group(db_session, BuiltinGroup.TECHNICIAN)
    techs_id = techs.id
    techs.name = "Équipe terrain"
    db_session.add(techs)
    await db_session.exec(
        delete(GroupPermission).where(
            GroupPermission.group_id == techs_id,  # type: ignore[arg-type]
            GroupPermission.permission == "package:read",  # type: ignore[arg-type]
        )
    )
    await db_session.commit()

    migration = _migration()
    async with engine.begin() as conn:
        assert await conn.run_sync(migration.grant_technicians_package_read) == 1
    async with engine.begin() as conn:
        assert await conn.run_sync(migration.grant_technicians_package_read) == 0

    db_session.expire_all()
    granted = await db_session.exec(
        select(GroupPermission.group_id).where(
            GroupPermission.permission == "package:read"
        )
    )
    assert list(granted.all()) == [techs_id]
    readonly = await crud.builtin_group(db_session, BuiltinGroup.READONLY)
    assert "package:read" not in await crud.group_permissions(db_session, readonly)
    assert (await db_session.get(Group, techs_id)) is not None


async def test_case_twins_are_renamed_before_the_index(engine, db_session):
    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import Group

    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP INDEX ix_groups_name_lower"))
    await crud.ensure_builtin_groups(db_session)
    await db_session.commit()
    for name in ("Atelier", "ATELIER", "atelier (2)", "lecture SEULE"):
        db_session.add(Group(name=name))
        await db_session.commit()

    migration = _migration()
    async with engine.begin() as conn:
        renamed = await conn.run_sync(migration.rename_case_twins)
        await conn.execute(
            sa.text("CREATE UNIQUE INDEX ix_groups_name_lower ON groups (lower(name))")
        )
    assert dict(renamed) == {
        "ATELIER": "ATELIER (3)",
        "lecture SEULE": "lecture SEULE (2)",
    }
    db_session.expire_all()
    names = set((await db_session.exec(select(Group.name))).all())
    # The built-in « Lecture seule » and the oldest « Atelier » keep theirs.
    assert {"Lecture seule", "Atelier", "atelier (2)"} <= names
    assert len({n.lower() for n in names}) == len(names)


def test_a_suffixed_name_fits_its_column():
    migration = _migration()
    name = migration._suffixed("x" * 100, 2, {"x" * 100})
    assert len(name) == 100 and name.endswith(" (2)")
