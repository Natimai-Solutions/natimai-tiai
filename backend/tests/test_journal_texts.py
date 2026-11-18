"""The texts the server stores for the journal and the checks, with their code.

Since the bilingual console (plan ``dev/plan-console-bilingue.md``, lot D),
the title of a line « left out of a maintenance visit » and the note of a
check closed by a merge carry a code — and the title its parameters — beside
their French: the console words them in the reader's language. The French
stays as it was, for an older console and for the rows written before.

``tests/data/journal_texts_fr.json`` holds the cases: this file checks the
server still writes them, ``frontend/src/services/roomsMaintenanceTexts.spec.ts``
that the console writes the same from the codes.

The API tests are DB-backed: they require TIAI_TEST_DATABASE_URL.
"""

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from tests.test_api_maintenance import _admin, _machine, _room

FIXTURE = Path(__file__).parent / "data" / "journal_texts_fr.json"


def _cases() -> list[dict[str, Any]]:
    from app.features.check import crud as check_crud
    from app.features.maintenance import crud as maintenance_crud

    found = []
    for room in ("A101", None):
        text, params = maintenance_crud.skipped_title(room)
        found.append(
            {
                "kind": "intervention_title",
                "code": maintenance_crud.SKIPPED_TITLE_CODE,
                "params": params,
                "text": text,
            }
        )
    found.append(
        {
            "kind": "closing_note",
            "code": check_crud.CLOSED_BY_MERGE,
            "params": {},
            "text": check_crud.CLOSED_BY_MERGE_NOTE,
        }
    )
    return found


def test_the_server_writes_the_shared_cases():
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == _cases()


def test_the_french_is_the_one_written_before_the_codes():
    """An installation updated reads the same journal and the same notes."""
    from app.features.check import crud as check_crud
    from app.features.maintenance import crud as maintenance_crud

    assert maintenance_crud.skipped_title("B12")[0] == "Maintenance non faite — B12"
    assert maintenance_crud.skipped_title(None)[0] == "Maintenance non faite"
    assert (
        check_crud.CLOSED_BY_MERGE_NOTE
        == "Fermée par la fusion du poste dans un autre."
    )


async def test_a_skipped_line_carries_its_code_until_its_title_is_retyped(
    client, db_session
):
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "B12")
    a = await _machine(db_session, "A", first_seen_days_ago=100, room_id=room)
    b = await _machine(db_session, "B", first_seen_days_ago=100, room_id=room)
    resp = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={
            "room_id": room,
            "items": [{"machine_id": a}],
            "skipped": [{"machine_id": b, "note": "Absent"}],
        },
    )
    assert resp.status_code == 201, resp.text

    (done,) = (
        await client.get(f"/api/v1/machines/{a}/interventions", headers=admin)
    ).json()["items"]
    # The room's name is data, not the server's words: no code.
    assert done["title"] == "B12"
    assert done["title_code"] is None and done["title_params"] is None

    (line,) = (
        await client.get(f"/api/v1/machines/{b}/interventions", headers=admin)
    ).json()["items"]
    assert line["title"] == "Maintenance non faite — B12"
    assert line["title_code"] == "maintenance.skipped"
    assert line["title_params"] == {"room": "B12"}

    # An edit of the note alone keeps the server's words.
    resp = await client.patch(
        f"/api/v1/interventions/{line['id']}", headers=admin, json={"note": "Malade"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title_code"] == "maintenance.skipped"

    # A title typed by someone is theirs: the code goes.
    resp = await client.patch(
        f"/api/v1/interventions/{line['id']}",
        headers=admin,
        json={"title": "Pas fait : poste éteint"},
    )
    assert resp.status_code == 200, resp.text
    edited = resp.json()
    assert edited["title"] == "Pas fait : poste éteint"
    assert edited["title_code"] is None and edited["title_params"] is None


async def test_a_visit_without_a_room_writes_the_title_without_parameters(
    client, db_session
):
    admin, _ = await _admin(client, db_session)
    a = await _machine(db_session, "A", first_seen_days_ago=100)
    b = await _machine(db_session, "B", first_seen_days_ago=100)
    resp = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={
            "items": [{"machine_id": a}],
            "skipped": [{"machine_id": b, "note": "Absent"}],
        },
    )
    assert resp.status_code == 201, resp.text
    (line,) = (
        await client.get(f"/api/v1/machines/{b}/interventions", headers=admin)
    ).json()["items"]
    assert line["title"] == "Maintenance non faite"
    assert line["title_code"] == "maintenance.skipped"
    assert line["title_params"] == {}


async def test_a_line_typed_by_hand_has_no_code(client, db_session):
    admin, _ = await _admin(client, db_session)
    m = await _machine(db_session, "A")
    resp = await client.post(
        f"/api/v1/machines/{m}/interventions",
        headers=admin,
        json={"kind": "other", "title": "Maintenance non faite"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["title_code"] is None


async def test_a_check_closed_by_a_merge_carries_its_code(client, db_session):
    admin, _ = await _admin(client, db_session)
    kept, dup = await _machine(db_session, "PC-1"), await _machine(db_session, "PC-1")
    for machine, text in ((kept, "sur le conservé"), (dup, "sur le doublon")):
        resp = await client.post(
            f"/api/v1/machines/{machine}/check",
            headers=admin,
            json={"instructions": text},
        )
        assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"/api/v1/machines/{kept}/merge", headers=admin, json={"source_id": dup}
    )
    assert resp.status_code == 200, resp.text

    history = (
        await client.get(f"/api/v1/machines/{kept}/checks", headers=admin)
    ).json()["items"]
    still_open = next(c for c in history if not c["closed_at"])
    assert still_open["closing_note_code"] is None
    closed = next(c for c in history if c["closed_at"])
    assert closed["closing_note"] == "Fermée par la fusion du poste dans un autre."
    assert closed["closing_note_code"] == "check.closed.merged"


async def test_a_check_closed_by_hand_has_no_code(client, db_session):
    admin, _ = await _admin(client, db_session)
    m = await _machine(db_session, "PC-1")
    check = (
        await client.post(f"/api/v1/machines/{m}/check", headers=admin, json={})
    ).json()
    resp = await client.post(
        f"/api/v1/checks/{check['id']}/close", headers=admin, json={"note": "Câble"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["closing_note"] == "Câble"
    assert resp.json()["closing_note_code"] is None


# --- The migration --------------------------------------------------------------

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0047_room_texts.py"
)
_COLUMNS = {
    ("interventions", "title_code"),
    ("interventions", "title_params"),
    ("machine_checks", "closing_note_code"),
}


def _run(step: str):
    def run(conn: sa.Connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        spec = importlib.util.spec_from_file_location("migration_0047", _MIGRATION)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module, step)()

    return run


async def _columns(engine) -> set[tuple[str, str]]:
    async with engine.connect() as conn:
        found = await conn.execute(
            sa.text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE (table_name, column_name) IN "
                "(('interventions', 'title_code'), ('interventions', 'title_params'), "
                "('machine_checks', 'closing_note_code'))"
            )
        )
        return {(row[0], row[1]) for row in found.all()}


async def test_the_migration_adds_the_columns_nullable_and_removes_them(
    engine, db_session
):
    """Every row before it keeps its French: the columns are null on them."""
    from app.features.machine.models import Machine

    machine_id = uuid.uuid4()
    machine = Machine(id=machine_id, machine_uuid=str(uuid.uuid4()), hostname="OLD")
    db_session.add(machine)
    await db_session.commit()
    async with engine.begin() as conn:
        await conn.run_sync(_run("downgrade"))
    assert await _columns(engine) == set()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO interventions (id, machine_id, kind, title, performed_by, "
                "performed_at, created_at, updated_at) VALUES (:id, :m, 'other', "
                "'Maintenance non faite — B12', 'a@b.c', now(), now(), now())"
            ),
            {"id": uuid.uuid4(), "m": machine_id},
        )
        await conn.run_sync(_run("upgrade"))
    assert await _columns(engine) == _COLUMNS
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT title, title_code, title_params FROM interventions")
            )
        ).one()
    assert tuple(row) == ("Maintenance non faite — B12", None, None)
