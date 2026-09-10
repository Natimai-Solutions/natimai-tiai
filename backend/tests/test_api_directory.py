"""The directory block of the inventory, and ROOM_SOURCE: postes filed by
their OU or by their AD location, rooms created on the way, manual placement
locked, and the re-sync from stored readings.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import pytest

STRONG = "correct-horse-battery"


async def _admin(client, db_session):
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="admin@test.local",
        password=STRONG,
        groups=[BuiltinGroup.ADMIN],
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "admin@test.local", "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _enroll(client, machine_uuid, **fields):
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, **fields},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _report(client, enrolled, directory, hash_="h1"):
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {enrolled['token']}"},
        json={"inventory": {"hash": hash_, "directory": directory}},
    )
    assert resp.status_code == 200, resp.text


def _dir(
    ou="Salle B12", ou_dn="OU=Salle B12,OU=Postes,DC=lycee,DC=local", location=None
):
    return {
        "distinguished_name": f"CN=PC,{ou_dn}",
        "ou": ou,
        "ou_dn": ou_dn,
        "ad_location": location,
    }


async def _machine(client, headers, enrolled):
    resp = await client.get(
        f"/api/v1/machines/{enrolled['machine_id']}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def room_source(monkeypatch):
    from app.core.config import settings

    def set_source(value):
        monkeypatch.setattr(settings, "ROOM_SOURCE", value)

    return set_source


# --- Manual mode: stored, shown, not acted on --------------------------------


async def test_directory_is_stored_and_shown_but_files_nothing_by_hand(
    client, db_session, room_source
):
    room_source("manual")
    headers = await _admin(client, db_session)
    enrolled = await _enroll(client, "pc-1", hostname="PC-1")
    await _report(client, enrolled, _dir(location="Bât. B"))

    m = await _machine(client, headers, enrolled)
    assert m["ad_ou"] == "Salle B12"
    assert m["ad_ou_dn"] == "OU=Salle B12,OU=Postes,DC=lycee,DC=local"
    assert m["ad_location"] == "Bât. B"
    assert m["ad_distinguished_name"].startswith("CN=PC,")
    assert m["room_id"] is None
    assert (await client.get("/api/v1/rooms", headers=headers)).json() == []
    config = (await client.get("/api/v1/rooms/config", headers=headers)).json()
    assert config == {"source": "manual", "manual": True}


# --- OU mode ------------------------------------------------------------------


async def test_ou_mode_creates_the_room_and_files_the_poste(
    client, db_session, room_source
):
    room_source("ad_ou")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    b = await _enroll(client, "pc-b", hostname="B")
    await _report(client, a, _dir())
    await _report(client, b, _dir())

    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert len(rooms) == 1
    assert rooms[0]["name"] == "Salle B12"
    assert rooms[0]["ad_key"] == "OU=Salle B12,OU=Postes,DC=lycee,DC=local"
    assert rooms[0]["machine_count"] == 2
    assert (await _machine(client, headers, a))["room_name"] == "Salle B12"


async def test_ou_move_changes_room_and_rename_keeps_the_key(
    client, db_session, room_source
):
    room_source("ad_ou")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    await _report(client, a, _dir())
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    room_id = rooms[0]["id"]

    # The room is renamed in the console: the key, not the name, is what the
    # directory files by, so the next report lands in the same room.
    resp = await client.patch(
        f"/api/v1/rooms/{room_id}", headers=headers, json={"name": "B12 (info)"}
    )
    assert resp.status_code == 200
    await _report(client, a, _dir(), hash_="h2")
    assert (await _machine(client, headers, a))["room_name"] == "B12 (info)"

    # Moved to another OU: another room, the old one left standing, empty.
    await _report(
        client,
        a,
        _dir(ou="Salle B13", ou_dn="OU=Salle B13,OU=Postes,DC=lycee,DC=local"),
        hash_="h3",
    )
    rooms = {
        r["name"]: r
        for r in (await client.get("/api/v1/rooms", headers=headers)).json()
    }
    assert rooms["Salle B13"]["machine_count"] == 1
    assert rooms["B12 (info)"]["machine_count"] == 0

    # Out of any OU: unfiled.
    await _report(
        client, a, {"distinguished_name": "CN=PC,DC=lycee,DC=local"}, hash_="h4"
    )
    assert (await _machine(client, headers, a))["room_id"] is None


async def test_ou_mode_adopts_a_loose_room_of_the_same_name(
    client, db_session, room_source
):
    """A parc that filed by hand before turning the directory on already has
    a « Salle B12 »: the OU takes it over rather than creating « Salle B12 (2) »."""
    room_source("manual")
    headers = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/rooms", headers=headers, json={"name": "Salle B12"}
    )
    assert resp.status_code == 201
    loose_id = resp.json()["id"]

    room_source("ad_ou")
    a = await _enroll(client, "pc-a", hostname="A")
    await _report(client, a, _dir())
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert len(rooms) == 1
    assert rooms[0]["id"] == loose_id
    assert rooms[0]["ad_key"] is not None


async def test_two_ous_of_one_name_get_two_rooms(client, db_session, room_source):
    room_source("ad_ou")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    b = await _enroll(client, "pc-b", hostname="B")
    await _report(client, a, _dir(ou="B12", ou_dn="OU=B12,OU=Nord,DC=corp"))
    await _report(client, b, _dir(ou="B12", ou_dn="OU=B12,OU=Sud,DC=corp"))
    names = sorted(
        r["name"] for r in (await client.get("/api/v1/rooms", headers=headers)).json()
    )
    assert names == ["B12", "B12 (2)"]


# --- Location mode ------------------------------------------------------------


async def test_location_mode_files_by_the_attribute(client, db_session, room_source):
    room_source("ad_location")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    b = await _enroll(client, "pc-b", hostname="B")
    await _report(client, a, _dir(location="Bât. B — salle 12"))
    await _report(client, b, _dir(location=None))  # no attribute: unfiled
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert [r["name"] for r in rooms] == ["Bât. B — salle 12"]
    assert rooms[0]["ad_key"] == "Bât. B — salle 12"
    assert (await _machine(client, headers, b))["room_id"] is None


# --- Lock and re-sync ---------------------------------------------------------


async def test_directory_mode_locks_manual_placement(client, db_session, room_source):
    room_source("ad_ou")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    await _report(client, a, _dir())
    room_id = (await client.get("/api/v1/rooms", headers=headers)).json()[0]["id"]

    resp = await client.post(
        f"/api/v1/rooms/{room_id}/machines",
        headers=headers,
        json={"machine_ids": [a["machine_id"]]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "room.placement.locked"
    resp = await client.post(
        "/api/v1/rooms/unassign",
        headers=headers,
        json={"machine_ids": [a["machine_id"]]},
    )
    assert resp.status_code == 409
    # The room itself stays editable: its building, its name, its notes.
    resp = await client.patch(
        f"/api/v1/rooms/{room_id}", headers=headers, json={"notes": "Info"}
    )
    assert resp.status_code == 200


async def test_sync_refiles_the_parc_from_stored_readings(
    client, db_session, room_source
):
    """The mode was switched after the agents reported: nothing moves until
    the console asks for a re-sync, which then files every poste at once."""
    room_source("manual")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    b = await _enroll(client, "pc-b", hostname="B")
    await _report(client, a, _dir(location="Bât. B"))
    await _report(client, b, {"distinguished_name": "CN=PC,DC=corp"})
    assert (await client.get("/api/v1/rooms", headers=headers)).json() == []

    room_source("ad_ou")
    resp = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"placed": 1, "unplaced": 0, "rooms_created": 1}
    assert (await _machine(client, headers, a))["room_name"] == "Salle B12"
    assert (await _machine(client, headers, b))["room_id"] is None

    # In manual mode the sync is a no-op that says so.
    room_source("manual")
    resp = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert resp.json() == {"placed": 0, "unplaced": 0, "rooms_created": 0}
