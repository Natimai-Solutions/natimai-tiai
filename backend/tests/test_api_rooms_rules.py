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
