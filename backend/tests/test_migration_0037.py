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


def _run_upgrade(conn: sa.Connection) -> None:
    """The migration's own ``upgrade()``, as alembic would run it."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        _migration().upgrade()


async def _before_0037(engine) -> None:
    """The schema as 0036 left it: no index on the names' lower case."""
    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP INDEX ix_groups_name_lower"))


async def _lower_index_is_unique(engine) -> bool:
    async with engine.connect() as conn:
        found = await conn.execute(
            sa.text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'groups' AND indexname = 'ix_groups_name_lower'"
            )
        )
        definition = found.scalar_one_or_none()
    return definition is not None and "UNIQUE" in definition


async def test_the_upgrade_grants_renames_and_builds_the_index(engine, db_session):
    """``upgrade()`` itself, not its helpers one by one: a step dropped from
    it would leave every helper's own test green."""
    from sqlmodel import delete, select

    from app.features.user import crud
    from app.features.user.models import Group, GroupPermission
    from app.features.user.permissions import BuiltinGroup

    await _before_0037(engine)
    await crud.ensure_builtin_groups(db_session)
    techs = await crud.builtin_group(db_session, BuiltinGroup.TECHNICIAN)
    techs_id = techs.id
    await db_session.exec(
        delete(GroupPermission).where(
            GroupPermission.group_id == techs_id,  # type: ignore[arg-type]
            GroupPermission.permission == "package:read",  # type: ignore[arg-type]
        )
    )
    for name in ("Atelier", "ATELIER"):
        db_session.add(Group(name=name))
        await db_session.commit()

    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)

    db_session.expire_all()
    techs = await crud.builtin_group(db_session, BuiltinGroup.TECHNICIAN)
    assert "package:read" in await crud.group_permissions(db_session, techs)
    names = set((await db_session.exec(select(Group.name))).all())
    assert {"Atelier", "ATELIER (2)"} <= names and "ATELIER" not in names
    assert await _lower_index_is_unique(engine)


async def test_twins_are_those_the_database_folds_together(engine, db_session):
    """Verification of v1.2.1, F5: the twins were found with Python's
    ``lower()``, the index is built on PostgreSQL's. The two disagree on a
    few letters — a capital sigma at the end of a word, for one — so two
    names Python told apart collided in the index, and the upgrade aborted
    on ``could not create unique index``. The database's own ``lower()``
    now says which names are twins, and which suffixed name is free."""
    from sqlmodel import select

    from app.features.user.models import Group

    await _before_0037(engine)
    # « ΟΔΟΣ » lower-cased: « οδοσ » for PostgreSQL, « οδος » for Python.
    assert "ΟΔΟΣ".lower() != "οδοσ"
    for name in ("οδοσ", "ΟΔΟΣ", "οδοσ (2)", "ΟΔΟΣ (2)"):
        db_session.add(Group(name=name))
        await db_session.commit()
    # A database whose locale folds ASCII only (``C``) sees no twins here,
    # and has nothing to rename: the test then only shows the upgrade runs.
    folds = (
        await db_session.exec(sa.text("SELECT lower('ΟΔΟΣ') = 'οδοσ'"))  # type: ignore[call-overload]
    ).scalar_one()
    await db_session.commit()

    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)

    db_session.expire_all()
    names = set((await db_session.exec(select(Group.name))).all())
    assert len(names) == 4
    assert await _lower_index_is_unique(engine)
    if folds:
        # The oldest of each pair keeps its name. The suffixed name given
        # to the other is asked of the database too: « ΟΔΟΣ (2) » is free
        # for Python and taken for the index.
        assert names == {"οδοσ", "οδοσ (2)", "ΟΔΟΣ (3)", "ΟΔΟΣ (2) (2)"}


def test_a_suffixed_name_fits_its_column():
    migration = _migration()
    names = migration._suffixed("x" * 100)
    first, second = next(names), next(names)
    assert len(first) == 100 and first.endswith(" (2)")
    assert len(second) == 100 and second.endswith(" (3)")
