"""Buildings and rooms after the acceptance test: no blank names, one name per
parent whatever its case, the counts of a confined account kept to its scope,
what its scope lets it create, and no deletion of a place a group's scope
names (C11).

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid

import pytest

from app.features.user.permissions import ALL_PERMISSIONS
from app.features.user.scope import Scope
from tests.scope_helpers import account, group, machine

STRONG = "correct-horse-battery"


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await account(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])


async def _post(client, headers, path, body, status=201):
    resp = await client.post(f"/api/v1/{path}", headers=headers, json=body)
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.mark.parametrize("path", ["rooms", "buildings"])
async def test_a_blank_name_is_refused(client, db_session, path):
    """Item 11: «   » was stored as a name ("")."""
    admin = await _admin(client, db_session)
    body = await _post(client, admin, path, {"name": "   "}, status=422)
    assert body["error"]["code"] == "request.validation_error"
    assert body["error"]["details"]["errors"][0]["loc"] == ["body", "name"]
    made = await _post(client, admin, path, {"name": "  Salle   B12 "})
    assert made["name"] == "Salle B12"
    resp = await client.patch(
        f"/api/v1/{path}/{made['id']}", headers=admin, json={"name": " \t "}
    )
    assert resp.status_code == 422, resp.text
    resp = await client.patch(
        f"/api/v1/{path}/{made['id']}", headers=admin, json={"name": " B13 "}
    )
    assert resp.status_code == 200 and resp.json()["name"] == "B13"


async def test_room_names_are_unique_whatever_their_case(client, db_session):
    """Item 11: « A101 » and « a101 » in one building."""
    admin = await _admin(client, db_session)
    b = await _post(client, admin, "buildings", {"name": "Bât. A"})
    await _post(client, admin, "rooms", {"name": "A101", "building_id": b["id"]})
    body = await _post(
        client, admin, "rooms", {"name": "a101", "building_id": b["id"]}, status=409
    )
    assert body["error"]["code"] == "room.name.taken"
    # Another parent: allowed.
    await _post(client, admin, "rooms", {"name": "a101"})
    other = await _post(client, admin, "rooms", {"name": "B12", "building_id": b["id"]})
    resp = await client.patch(
        f"/api/v1/rooms/{other['id']}", headers=admin, json={"name": "A101 "}
    )
    assert resp.status_code == 409
    # The same room may change the case of its own name.
    resp = await client.patch(
        f"/api/v1/rooms/{other['id']}", headers=admin, json={"name": "b12"}
    )
    assert resp.status_code == 200 and resp.json()["name"] == "b12"
    await _post(client, admin, "buildings", {"name": "bât. a"}, status=409)


async def test_building_counts_stay_within_the_scope(client, db_session):
    """Item 14: an account confined to one room of a building is not told how
    many rooms and postes the building holds beyond it."""
    admin = await _admin(client, db_session)
    b = await _post(client, admin, "buildings", {"name": "Bât. A", "location": "X"})
    mine = await _post(client, admin, "rooms", {"name": "A1", "building_id": b["id"]})
    theirs = await _post(client, admin, "rooms", {"name": "A2", "building_id": b["id"]})
    await machine(db_session, "PC-1", room_id=uuid.UUID(mine["id"]))
    await machine(db_session, "PC-2", room_id=uuid.UUID(theirs["id"]))
    await machine(db_session, "PC-3", room_id=uuid.UUID(theirs["id"]))
    g = await group(
        db_session,
        "Salle A1",
        ALL_PERMISSIONS,
        Scope(rooms=frozenset({uuid.UUID(mine["id"])})),
    )
    scoped = await account(client, db_session, "tech@test.local", [g.id])

    (seen,) = (await client.get("/api/v1/buildings", headers=scoped)).json()
    assert (seen["room_count"], seen["machine_count"]) == (1, 1)
    (full,) = (await client.get("/api/v1/buildings", headers=admin)).json()
    assert (full["room_count"], full["machine_count"]) == (2, 3)


async def test_what_a_scope_lets_create(client, db_session):
    """Item 14: the console hides « Nouvelle salle » / « Nouveau bâtiment »
    when every use would be refused."""
    admin = await _admin(client, db_session)
    b = await _post(client, admin, "buildings", {"name": "Bât. A", "location": "X"})
    room = await _post(client, admin, "rooms", {"name": "A1", "building_id": b["id"]})
    cases = {
        "rooms": (Scope(rooms=frozenset({uuid.UUID(room["id"])})), False, False),
        "buildings": (Scope(buildings=frozenset({uuid.UUID(b["id"])})), True, False),
        "site": (Scope(locations=frozenset({"X"})), True, True),
    }
    assert (await client.get("/api/v1/rooms/creation", headers=admin)).json() == {
        "rooms": True,
        "buildings": True,
    }
    for name, (scope, rooms, buildings) in cases.items():
        g = await group(db_session, name, ALL_PERMISSIONS, scope)
        headers = await account(client, db_session, f"{name}@test.local", [g.id])
        got = (await client.get("/api/v1/rooms/creation", headers=headers)).json()
        assert got == {"rooms": rooms, "buildings": buildings}, name
        # What it says matches what the creation routes answer.
        resp = await client.post(
            "/api/v1/rooms",
            headers=headers,
            json={"name": f"N-{name}", "building_id": b["id"]},
        )
        assert (resp.status_code == 201) is rooms, (name, resp.text)
        resp = await client.post(
            "/api/v1/buildings",
            headers=headers,
            json={"name": f"B-{name}", "location": "X"},
        )
        assert (resp.status_code == 201) is buildings, (name, resp.text)


async def test_a_place_in_a_group_scope_cannot_be_deleted(client, db_session):
    """C11: deleting a room or a building a group's scope names is refused,
    with the groups named — it used to leave a dangling scope row."""
    admin = await _admin(client, db_session)
    b = await _post(client, admin, "buildings", {"name": "Bât. A", "location": "X"})
    room = await _post(client, admin, "rooms", {"name": "A1", "building_id": b["id"]})
    await group(
        db_session,
        "Techniciens A1",
        ["room:read"],
        Scope(rooms=frozenset({uuid.UUID(room["id"])})),
    )
    await group(
        db_session,
        "Bâtiment A",
        ["room:read"],
        Scope(buildings=frozenset({uuid.UUID(b["id"])})),
    )
    resp = await client.delete(f"/api/v1/rooms/{room['id']}", headers=admin)
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "room.in_group_scope"
    assert error["details"] == {"groups": ["Techniciens A1"]}
    resp = await client.delete(f"/api/v1/buildings/{b['id']}", headers=admin)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["details"] == {"groups": ["Bâtiment A"]}
    # Out of every scope, it goes.
    free = await _post(client, admin, "rooms", {"name": "A2", "building_id": b["id"]})
    resp = await client.delete(f"/api/v1/rooms/{free['id']}", headers=admin)
    assert resp.status_code == 204


@pytest.mark.parametrize("path", ["rooms", "buildings"])
async def test_one_name_created_several_times_at_once_is_created_once(
    client, db_session, path
):
    """The name rule is a read before the write: requests served together
    all found the name free. The database now holds the rule — one name per
    parent whatever its case — and the losers get the 409 the read would
    have answered, not a 500."""
    import asyncio

    admin = await _admin(client, db_session)
    for names in (("Twin", "twin", "TWIN", "tWin"), ("Same",) * 4):
        answers = await asyncio.gather(
            *[
                client.post(f"/api/v1/{path}", headers=admin, json={"name": name})
                for name in names
            ]
        )
        assert sorted(r.status_code for r in answers) == [201, 409, 409, 409], [
            r.text[:200] for r in answers
        ]
        code = "room.name.taken" if path == "rooms" else "building.name.taken"
        assert {r.json()["error"]["code"] for r in answers if r.status_code == 409} == {
            code
        }
    listed = (await client.get(f"/api/v1/{path}", headers=admin)).json()
    assert sorted(row["name"].lower() for row in listed) == ["same", "twin"]


@pytest.mark.parametrize("path", ["rooms", "buildings"])
async def test_a_name_taken_while_the_request_is_served_is_a_409(
    client, db_session, engine, path
):
    """A twin written by a request still in its transaction: no read sees it.
    A creation and a rename to that name wait on the index, and answer 409
    once the twin is committed."""
    import asyncio

    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.room.models import Building, Room

    admin = await _admin(client, db_session)
    mine = await _post(client, admin, path, {"name": "A101"})
    async with AsyncSession(engine) as other:
        other.add((Room if path == "rooms" else Building)(name="LABO"))
        await other.flush()
        rename = asyncio.create_task(
            client.patch(
                f"/api/v1/{path}/{mine['id']}", headers=admin, json={"name": "Labo"}
            )
        )
        create = asyncio.create_task(
            client.post(f"/api/v1/{path}", headers=admin, json={"name": "labo"})
        )
        await asyncio.sleep(0.5)
        waiting = not rename.done() and not create.done()
        await other.commit()
    answers = [await rename, await create]
    assert waiting, [r.text[:200] for r in answers]
    assert [r.status_code for r in answers] == [409, 409], [
        r.text[:200] for r in answers
    ]
    code = "room.name.taken" if path == "rooms" else "building.name.taken"
    assert {r.json()["error"]["code"] for r in answers} == {code}
    listed = (await client.get(f"/api/v1/{path}", headers=admin)).json()
    assert sorted(row["name"] for row in listed) == ["A101", "LABO"]


@pytest.mark.parametrize("path", ["rooms", "buildings"])
async def test_names_are_compared_as_the_database_folds_them(client, db_session, path):
    """« İ » lower-cases to one character for PostgreSQL and to two for
    Python: compared across the two, the name was found free, and its exact
    twin then met the table's own constraint (a 500)."""
    admin = await _admin(client, db_session)
    await _post(client, admin, path, {"name": "İle"})
    body = await _post(client, admin, path, {"name": "İle"}, status=409)
    assert body["error"]["code"].endswith(".name.taken")


@pytest.mark.parametrize("path", ["rooms", "buildings"])
@pytest.mark.parametrize(
    "name",
    [
        "​",  # zero-width space
        "​ ⁠﻿",  # with a word joiner and a byte-order mark
        "­‍",  # soft hyphen, zero-width joiner
        "‎‮",  # direction marks
        "ㅤ",  # Hangul filler: a letter that draws nothing
        "⠀ ͏",  # blank Braille pattern, combining grapheme joiner
        "\x1f",  # a control character
    ],
)
async def test_a_name_made_of_invisible_characters_is_blank(
    client, db_session, path, name
):
    """A name nobody can see is no name: it listed as an empty row that could
    not be told from another."""
    admin = await _admin(client, db_session)
    body = await _post(client, admin, path, {"name": name}, status=422)
    assert body["error"]["code"] == "request.validation_error"
    assert body["error"]["details"]["errors"][0]["loc"] == ["body", "name"]
    made = await _post(client, admin, path, {"name": "Salle"})
    resp = await client.patch(
        f"/api/v1/{path}/{made['id']}", headers=admin, json={"name": name}
    )
    assert resp.status_code == 422, resp.text


async def test_an_invisible_character_inside_a_name_is_kept(client, db_session):
    """Only the name made of nothing else is refused: a joiner inside a word
    is part of how some scripts are written."""
    admin = await _admin(client, db_session)
    made = await _post(client, admin, "rooms", {"name": "Salle‍A"})
    assert made["name"] == "Salle‍A"


@pytest.mark.parametrize("path", ["rooms", "buildings"])
async def test_invisible_characters_at_the_ends_of_a_name_are_dropped(
    client, db_session, path
):
    """« Labo 3 » with a zero-width space before or after it reads « Labo 3 »:
    stored as typed, it was another row nobody could tell from the first."""
    admin = await _admin(client, db_session)
    made = await _post(client, admin, path, {"name": "​Labo‍3 ⁠"})
    assert made["name"] == "Labo‍3"
    await _post(client, admin, path, {"name": "Labo 3"})
    for twin in ("Labo 3​", "​Labo 3", "labo 3⁠", "﻿LABO 3 ‎"):
        body = await _post(client, admin, path, {"name": twin}, status=409)
        assert body["error"]["code"].endswith(".name.taken")
    resp = await client.patch(
        f"/api/v1/{path}/{made['id']}", headers=admin, json={"name": "​Salle 9"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Salle 9"
    listed = (await client.get(f"/api/v1/{path}", headers=admin)).json()
    assert sorted(row["name"] for row in listed) == ["Labo 3", "Salle 9"]


async def test_a_building_deleted_while_a_twin_of_its_room_is_created(
    client, db_session, engine
):
    """The building's « A100 » goes building-less while a building-less
    « a100 » is being written: the renaming read the name free, and the ON
    DELETE SET NULL then met the name's index — a 500 from the DELETE. The
    deletion now waits for the twin, sees it, and renames its room."""
    import asyncio

    from sqlalchemy import text
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.room.models import Room

    admin = await _admin(client, db_session)
    b = await _post(client, admin, "buildings", {"name": "Bât B"})
    await _post(client, admin, "rooms", {"name": "A100", "building_id": b["id"]})

    async def lock_waiters() -> int:
        async with engine.connect() as conn:
            return await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )

    async with AsyncSession(engine) as other:
        other.add(Room(name="a100"))
        await other.flush()
        deleting = asyncio.create_task(
            client.delete(f"/api/v1/buildings/{b['id']}", headers=admin)
        )
        # The deletion has run into the twin's uncommitted index entry.
        for _ in range(200):
            if await lock_waiters():
                break
            await asyncio.sleep(0.05)
        else:
            deleting.cancel()
            pytest.fail("the deletion never waited on the twin")
        await other.commit()
    resp = await deleting
    assert resp.status_code == 204, resp.text
    listed = (await client.get("/api/v1/rooms", headers=admin)).json()
    assert sorted(row["name"] for row in listed) == ["A100 (Bât B)", "a100"]
    assert all(row["building"] is None for row in listed)
