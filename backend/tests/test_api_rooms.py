"""Buildings and rooms: the console's placement of the postes, the site a
room inherits from its building, and the mismatch with what the agent says.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid

STRONG = "correct-horse-battery"


async def _login(client, email, password=STRONG):
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user(client, db_session, email, groups):
    from app.features.user import crud

    await crud.create_user(db_session, email=email, password=STRONG, groups=groups)
    return await _login(client, email)


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await _user(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])


async def _machine(db_session, hostname, location=None):
    from app.features.machine.models import Machine

    m = Machine(machine_uuid=str(uuid.uuid4()), hostname=hostname, location=location)
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return str(m.id)


async def _building(client, headers, name, location=None):
    resp = await client.post(
        "/api/v1/buildings",
        headers=headers,
        json={"name": name, "location": location},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _room(client, headers, name, building_id=None, location=None):
    resp = await client.post(
        "/api/v1/rooms",
        headers=headers,
        json={"name": name, "building_id": building_id, "location": location},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _code(resp):
    return resp.json()["error"]["code"]


# --- Buildings --------------------------------------------------------------


async def test_building_name_is_unique_per_site(client, db_session):
    admin = await _admin(client, db_session)
    await _building(client, admin, "Bâtiment B", "Lycée de Taravao")
    # Same name on another site: fine.
    await _building(client, admin, "Bâtiment B", "Collège de Paea")
    resp = await client.post(
        "/api/v1/buildings",
        headers=admin,
        json={"name": " Bâtiment  B ", "location": "Lycée de Taravao"},
    )
    assert resp.status_code == 409
    assert _code(resp) == "building.name.taken"


async def test_room_inherits_its_building_site(client, db_session):
    admin = await _admin(client, db_session)
    b = await _building(client, admin, "Bâtiment B", "Lycée de Taravao")
    room = await _room(client, admin, "B12", b["id"], location="ignored")
    assert room["effective_location"] == "Lycée de Taravao"
    # Its own site is not stored while it sits in a building.
    assert room["location"] is None
    assert room["building"]["name"] == "Bâtiment B"

    # Moved out of the building, it keeps no site until given one.
    resp = await client.patch(
        f"/api/v1/rooms/{room['id']}",
        headers=admin,
        json={"building_id": None, "location": "Collège de Paea"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["building"] is None
    assert resp.json()["effective_location"] == "Collège de Paea"


async def test_deleting_a_building_keeps_its_rooms_and_their_site(client, db_session):
    admin = await _admin(client, db_session)
    b = await _building(client, admin, "Bâtiment B", "Lycée de Taravao")
    room = await _room(client, admin, "B12", b["id"])
    resp = await client.delete(f"/api/v1/buildings/{b['id']}", headers=admin)
    assert resp.status_code == 204
    after = (await client.get(f"/api/v1/rooms/{room['id']}", headers=admin)).json()
    assert after["building"] is None
    assert after["effective_location"] == "Lycée de Taravao"


async def test_room_name_is_unique_per_building(client, db_session):
    admin = await _admin(client, db_session)
    b = await _building(client, admin, "Bâtiment B")
    await _room(client, admin, "B12", b["id"])
    await _room(client, admin, "B12")  # building-less: another namespace
    resp = await client.post(
        "/api/v1/rooms", headers=admin, json={"name": "B12", "building_id": b["id"]}
    )
    assert resp.status_code == 409
    assert _code(resp) == "room.name.taken"
    resp = await client.post("/api/v1/rooms", headers=admin, json={"name": "B12"})
    assert resp.status_code == 409


# --- Placing postes ---------------------------------------------------------


async def test_placing_reports_mismatches_without_refusing(client, db_session):
    admin = await _admin(client, db_session)
    b = await _building(client, admin, "Bâtiment B", "Lycée de Taravao")
    room = await _room(client, admin, "B12", b["id"])
    ok = await _machine(db_session, "PC-OK", "Lycée de Taravao")
    moved = await _machine(db_session, "PC-MOVED", "Collège de Paea")
    silent = await _machine(db_session, "PC-SILENT", None)

    resp = await client.post(
        f"/api/v1/rooms/{room['id']}/machines",
        headers=admin,
        json={"machine_ids": [ok, moved, silent]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved"] == 3
    assert resp.json()["mismatched"] == [moved]

    # The list carries the placement and the finding.
    rows = (await client.get("/api/v1/machines", headers=admin)).json()["items"]
    by_host = {r["hostname"]: r for r in rows}
    assert by_host["PC-OK"]["room_name"] == "B12"
    assert by_host["PC-OK"]["building_name"] == "Bâtiment B"
    assert by_host["PC-OK"]["room_location"] == "Lycée de Taravao"
    assert by_host["PC-OK"]["location_mismatch"] is False
    assert by_host["PC-MOVED"]["location_mismatch"] is True
    assert by_host["PC-SILENT"]["location_mismatch"] is False

    # And the room counts it.
    listed = (await client.get("/api/v1/rooms", headers=admin)).json()
    assert listed[0]["machine_count"] == 3
    assert listed[0]["mismatch_count"] == 1

    # The fiche says the same.
    detail = (await client.get(f"/api/v1/machines/{moved}", headers=admin)).json()
    assert detail["room_name"] == "B12"
    assert detail["location_mismatch"] is True


async def test_list_filters_on_room_building_and_mismatch(client, db_session):
    admin = await _admin(client, db_session)
    b = await _building(client, admin, "Bâtiment B", "Lycée de Taravao")
    b12 = await _room(client, admin, "B12", b["id"])
    b13 = await _room(client, admin, "B13", b["id"])
    loose = await _room(client, admin, "Réserve")
    a = await _machine(db_session, "A", "Lycée de Taravao")
    c = await _machine(db_session, "C", "Collège de Paea")
    d = await _machine(db_session, "D")
    e = await _machine(db_session, "E")
    await client.post(
        f"/api/v1/rooms/{b12['id']}/machines", headers=admin, json={"machine_ids": [a]}
    )
    await client.post(
        f"/api/v1/rooms/{b13['id']}/machines", headers=admin, json={"machine_ids": [c]}
    )
    await client.post(
        f"/api/v1/rooms/{loose['id']}/machines",
        headers=admin,
        json={"machine_ids": [d]},
    )

    async def hosts(**params):
        resp = await client.get("/api/v1/machines", headers=admin, params=params)
        assert resp.status_code == 200, resp.text
        return sorted(r["hostname"] for r in resp.json()["items"])

    assert await hosts(room_id=b12["id"]) == ["A"]
    assert await hosts(building_id=b["id"]) == ["A", "C"]
    assert await hosts(without_room="true") == ["E"]
    assert await hosts(location_mismatch="true") == ["C"]
    assert await hosts(location_mismatch="false") == ["A", "D", "E"]
    # Sorting on the joined columns: room names ascending put the two of
    # Bâtiment B first, the loose room next, the unplaced poste last.
    resp = await client.get(
        "/api/v1/machines",
        headers=admin,
        params={"sort_by": "room", "sort_desc": "false"},
    )
    assert [r["hostname"] for r in resp.json()["items"]] == ["A", "C", "D", "E"]
    resp = await client.get(
        "/api/v1/machines",
        headers=admin,
        params={"sort_by": "building", "sort_desc": "false"},
    )
    # Same building: the tie falls back on freshest contact, so a set.
    assert set([r["hostname"] for r in resp.json()["items"]][:2]) == {"A", "C"}
    assert e in [r["id"] for r in resp.json()["items"]]


async def test_unassign_and_room_deletion_leave_postes_standing(client, db_session):
    admin = await _admin(client, db_session)
    room = await _room(client, admin, "B12")
    a = await _machine(db_session, "A")
    b = await _machine(db_session, "B")
    await client.post(
        f"/api/v1/rooms/{room['id']}/machines",
        headers=admin,
        json={"machine_ids": [a, b]},
    )

    resp = await client.post(
        "/api/v1/rooms/unassign", headers=admin, json={"machine_ids": [a]}
    )
    assert resp.status_code == 200
    assert resp.json()["moved"] == 1

    resp = await client.delete(f"/api/v1/rooms/{room['id']}", headers=admin)
    assert resp.status_code == 204
    rows = (await client.get("/api/v1/machines", headers=admin)).json()["items"]
    assert all(r["room_id"] is None for r in rows)


async def test_unknown_machine_in_placement_is_a_404(client, db_session):
    admin = await _admin(client, db_session)
    room = await _room(client, admin, "B12")
    resp = await client.post(
        f"/api/v1/rooms/{room['id']}/machines",
        headers=admin,
        json={"machine_ids": [str(uuid.uuid4())]},
    )
    assert resp.status_code == 404
    assert _code(resp) == "machine.not_found"


async def test_export_carries_the_placement(client, db_session):
    admin = await _admin(client, db_session)
    b = await _building(client, admin, "Bâtiment B", "Lycée de Taravao")
    room = await _room(client, admin, "B12", b["id"])
    a = await _machine(db_session, "A", "Collège de Paea")
    await _machine(db_session, "Z")
    await client.post(
        f"/api/v1/rooms/{room['id']}/machines", headers=admin, json={"machine_ids": [a]}
    )
    resp = await client.get(
        "/api/v1/machines/export.csv",
        headers=admin,
        params={"columns": "hostname,building,room,location_mismatch"},
    )
    assert resp.status_code == 200, resp.text
    lines = resp.text.strip().splitlines()
    assert lines[1].split(";")[1:] == ["Bâtiment B", "B12", "Oui"] or lines[1].split(
        ","
    )[1:] == ["Bâtiment B", "B12", "Oui"]
    # An unplaced poste exports blanks, not « Non ».
    assert "Z" in lines[2] and "Non" not in lines[2]


# --- Permissions ------------------------------------------------------------


async def test_readonly_reads_rooms_but_cannot_change_them(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await _admin(client, db_session)
    room = await _room(client, admin, "B12")
    ro = await _user(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    assert (await client.get("/api/v1/rooms", headers=ro)).status_code == 200
    assert (await client.get("/api/v1/buildings", headers=ro)).status_code == 200
    resp = await client.post("/api/v1/rooms", headers=ro, json={"name": "B13"})
    assert resp.status_code == 403
    resp = await client.delete(f"/api/v1/rooms/{room['id']}", headers=ro)
    assert resp.status_code == 403


async def test_merge_keeps_the_room_of_the_duplicate(client, db_session):
    admin = await _admin(client, db_session)
    room = await _room(client, admin, "B12")
    kept = await _machine(db_session, "PC-1")
    dup = await _machine(db_session, "PC-1")
    await client.post(
        f"/api/v1/rooms/{room['id']}/machines",
        headers=admin,
        json={"machine_ids": [dup]},
    )
    resp = await client.post(
        f"/api/v1/machines/{kept}/merge", headers=admin, json={"source_id": dup}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["room_name"] == "B12"
