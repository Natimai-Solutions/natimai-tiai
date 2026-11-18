"""Migration 0043: the twins it renames before building the unique indexes on
the case-folded names of rooms and buildings, run against a real database
(requires TIAI_TEST_DATABASE_URL)."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0043_room_names_unique.py"
)
_INDEXES = ("ix_rooms_building_name_lower", "ix_buildings_location_name_lower")


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0043", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(conn: sa.Connection) -> None:
    """The migration's own ``upgrade()``, as alembic would run it."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        _migration().upgrade()


async def _before_0043(engine) -> None:
    """The schema as it was: the names unique as typed only."""
    async with engine.begin() as conn:
        for index in _INDEXES:
            await conn.execute(sa.text(f"DROP INDEX {index}"))


async def _unique_indexes(engine) -> dict[str, str]:
    async with engine.connect() as conn:
        found = await conn.execute(
            sa.text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE indexname = ANY(:names)"
            ),
            {"names": list(_INDEXES)},
        )
        return {row[0]: row[1] for row in found.all()}


_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _building(db_session, name, location=None, age=0):
    from app.features.room.models import Building

    row = Building(name=name, location=location, created_at=_T0 + timedelta(days=age))
    db_session.add(row)
    return row


def _room(db_session, name, building_id=None, age=0):
    from app.features.room.models import Room

    row = Room(name=name, building_id=building_id, created_at=_T0 + timedelta(days=age))
    db_session.add(row)
    return row


async def test_the_upgrade_renames_the_twins_and_builds_the_indexes(engine, db_session):
    """Twins under one parent get « (2) », « (3) »… — never the oldest, never
    onto a name some row holds; the same name under another parent is no twin.
    The indexes are then built, unique, NULL parents not distinct."""
    from sqlmodel import select

    from app.features.room.models import Building, Room

    await _before_0043(engine)
    # Buildings: twins on one site, and among those that have none.
    b = _building(db_session, "Bâtiment B", "Site 1", age=0)
    _building(db_session, "bâtiment b", "Site 1", age=1)
    _building(db_session, "BÂTIMENT B", "Site 2", age=2)
    _building(db_session, "Annexe", None, age=3)
    _building(db_session, "ANNEXE", None, age=1)
    other = _building(db_session, "Bâtiment C", "Site 1", age=0)
    await db_session.flush()
    b_id, other_id = b.id, other.id
    # Rooms: three in one building, of which the middle one is the oldest;
    # « a101 (2) » made by hand; the same name in another building.
    _room(db_session, "A101", b_id, age=5)
    _room(db_session, "a101", b_id, age=1)
    _room(db_session, "A101 ", b_id, age=9)  # not a twin: another name
    _room(db_session, "a101 (2)", b_id, age=2)
    _room(db_session, "A101", other_id, age=0)
    # Among the rooms that have no building, three of a name.
    _room(db_session, "Labo", None, age=3)
    _room(db_session, "LABO", None, age=2)
    _room(db_session, "labo", None, age=4)
    # A name as long as the column: the suffix must still fit.
    _room(db_session, "x" * 100, None, age=0)
    _room(db_session, "X" * 100, None, age=1)
    await db_session.commit()

    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)

    db_session.expire_all()
    buildings = (await db_session.exec(select(Building.location, Building.name))).all()
    assert sorted(buildings, key=repr) == sorted(
        [
            ("Site 1", "Bâtiment B"),
            ("Site 1", "bâtiment b (2)"),
            ("Site 2", "BÂTIMENT B"),
            (None, "ANNEXE"),
            (None, "Annexe (2)"),
            ("Site 1", "Bâtiment C"),
        ],
        key=repr,
    )
    rooms = (await db_session.exec(select(Room.building_id, Room.name))).all()
    assert sorted(rooms, key=repr) == sorted(
        [
            (b_id, "a101"),
            (b_id, "a101 (2)"),
            (b_id, "A101 (3)"),
            (b_id, "A101 "),
            (other_id, "A101"),
            (None, "LABO"),
            (None, "Labo (2)"),
            (None, "labo (3)"),
            (None, "x" * 100),
            (None, "X" * 96 + " (2)"),
        ],
        key=repr,
    )
    indexes = await _unique_indexes(engine)
    assert set(indexes) == set(_INDEXES)
    for definition in indexes.values():
        assert "UNIQUE" in definition and "NULLS NOT DISTINCT" in definition
        assert "lower((name)::text)" in definition

    # And they hold: a twin can no longer be written, with or without parent.
    from sqlalchemy.exc import IntegrityError

    for twin in (Room(name="LaBo"), Room(name="A101", building_id=b_id)):
        db_session.add(twin)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()
    db_session.add(Building(name="annexe"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_twins_are_those_the_database_folds_together(engine, db_session):
    """The twins are found, and the free names chosen, with the function the
    index is built on. « ΟΔΟΣ » lower-cased is « οδοσ » for PostgreSQL and
    « οδος » for Python: told apart by Python, the two would have collided
    in the index, and the upgrade aborted on it."""
    from sqlmodel import select

    from app.features.room.models import Room

    await _before_0043(engine)
    assert "ΟΔΟΣ".lower() != "οδοσ"
    for age, name in enumerate(("ΟΔΟΣ", "οδοσ", "ΟΔΟΣ (2)", "οδοσ (2)")):
        _room(db_session, name, None, age=age)
    folds = (
        await db_session.exec(sa.text("SELECT lower('ΟΔΟΣ') = 'οδοσ'"))  # type: ignore[call-overload]
    ).scalar_one()
    await db_session.commit()

    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)

    db_session.expire_all()
    names = set((await db_session.exec(select(Room.name))).all())
    assert len(names) == 4
    assert set(await _unique_indexes(engine)) == set(_INDEXES)
    if folds:
        # A database whose locale folds ASCII only sees no twins here, and
        # the test then only shows that the upgrade runs.
        assert names == {"ΟΔΟΣ", "ΟΔΟΣ (2)", "οδοσ (3)", "οδοσ (2) (2)"}


async def test_a_database_without_twins_is_left_as_it_is(engine, db_session):
    from sqlmodel import select

    from app.features.room.models import Room

    await _before_0043(engine)
    building_id = uuid.uuid4()
    _building(db_session, "Bât. A").id = building_id
    _room(db_session, "A101", building_id)
    _room(db_session, "A101", None)
    await db_session.commit()

    migration = _migration()
    async with engine.begin() as conn:
        assert await conn.run_sync(migration.rename_case_twins, "buildings") == []
        assert await conn.run_sync(migration.rename_case_twins, "rooms") == []
    db_session.expire_all()
    assert sorted((await db_session.exec(select(Room.name))).all()) == ["A101"] * 2
