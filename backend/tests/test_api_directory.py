"""The directory block of the inventory, and ROOM_SOURCE: postes filed by
their OU or by their AD location, rooms created on the way, manual placement
locked, and the re-sync from stored readings.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid

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
    # One agent's report does not take over a room made by hand (audit S20):
    # the poste waits, unfiled, and no « Salle B12 (2) » appears.
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert len(rooms) == 1 and rooms[0]["ad_key"] is None
    assert (await _machine(client, headers, a))["room_id"] is None

    # The administrator's re-sync does adopt it.
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.status_code == 200, synced.text
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert len(rooms) == 1
    assert rooms[0]["id"] == loose_id
    assert rooms[0]["ad_key"] is not None
    assert (await _machine(client, headers, a))["room_id"] == loose_id


async def test_an_ou_the_dn_is_not_in_is_not_taken(client, db_session, room_source):
    """Audit S20: an agent naming another OU than its own DN's is not filed."""
    room_source("ad_ou")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    forged = _dir()
    forged["distinguished_name"] = "CN=PC,OU=Ailleurs,DC=lycee,DC=local"
    await _report(client, a, forged)
    assert (await client.get("/api/v1/rooms", headers=headers)).json() == []
    assert (await _machine(client, headers, a))["room_id"] is None


async def test_a_heartbeat_loop_is_cut_per_poste(client, db_session, monkeypatch):
    """Audit S21: a token in a loop gets 429, other postes are not."""
    from app.core import ratelimit

    monkeypatch.setattr(ratelimit.heartbeat_limiter, "max_attempts", 3)
    a = await _enroll(client, "pc-a", hostname="A")
    b = await _enroll(client, "pc-b", hostname="B")
    codes = []
    for _ in range(4):
        r = await client.post(
            "/api/v1/agent/heartbeat",
            headers={"Authorization": f"Bearer {a['token']}"},
            json={},
        )
        codes.append(r.status_code)
    assert codes == [200, 200, 200, 429]
    other = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {b['token']}"},
        json={},
    )
    assert other.status_code == 200


async def test_a_poste_creates_a_bounded_number_of_catalogue_entries(
    client, db_session, monkeypatch
):
    """Audit S21: the new catalogue entries one poste may create per day are
    budgeted, whatever the number of heartbeats; known entries cost nothing,
    and a cut-short inventory does not store its hash (sent again, it is
    applied again)."""
    from sqlmodel import func, select

    from app.core import ratelimit
    from app.features.inventory.models import Software
    from app.features.machine.models import Machine

    monkeypatch.setattr(ratelimit.software_quota, "units", 3)
    a = await _enroll(client, "pc-a", hostname="A")
    b = await _enroll(client, "pc-b", hostname="B")

    async def send(enrolled, names, hash_):
        resp = await client.post(
            "/api/v1/agent/heartbeat",
            headers={"Authorization": f"Bearer {enrolled['token']}"},
            json={
                "inventory": {
                    "hash": hash_,
                    "software": [{"name": n, "version": "1"} for n in names],
                }
            },
        )
        assert resp.status_code == 200, resp.text

    async def catalogue():
        return await db_session.scalar(select(func.count()).select_from(Software))

    await send(a, ["s1", "s2", "s3", "s4", "s5"], "h1")
    assert await catalogue() == 3
    machine = await db_session.get(Machine, uuid.UUID(a["machine_id"]))
    assert machine.inventory_hash is None
    # The budget is spent: another hash, other names, nothing new.
    await send(a, [f"x{i}" for i in range(50)], "h2")
    assert await catalogue() == 3
    # Another poste: the known entries are free, the rest on its own budget.
    await send(b, ["s1", "s2", "s3", "s4", "s5"], "h1")
    assert await catalogue() == 5
    other = await db_session.get(Machine, uuid.UUID(b["machine_id"]))
    await db_session.refresh(other)
    assert other.inventory_hash == "h1"


async def test_software_nobody_has_is_purged(client, db_session):
    from datetime import timedelta

    from sqlmodel import select

    from app.features.base import utcnow
    from app.features.inventory import crud
    from app.features.inventory.models import Software

    db_session.add(Software(name="Orphelin", first_seen=utcnow() - timedelta(days=3)))
    db_session.add(Software(name="Récent"))
    await db_session.commit()
    assert (
        await crud.purge_orphan_software(db_session, utcnow() - timedelta(days=1)) == 1
    )
    names = {s.name for s in (await db_session.exec(select(Software))).all()}
    assert names == {"Récent"}


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


async def test_a_long_location_is_cut_to_a_room_name(client, db_session, room_source):
    """Audit S07: AD allows 1024 characters, the room name 100 — the heartbeat
    must not fail, and two long names sharing their first 100 characters get
    two rooms whose suffixed names still fit."""
    room_source("ad_location")
    headers = await _admin(client, db_session)
    long_a = "Bâtiment administratif Nord — 2e étage — " * 4 + "salle 214"
    long_b = "Bâtiment administratif Nord — 2e étage — " * 4 + "salle 215"
    a = await _enroll(client, "pc-a", hostname="A")
    b = await _enroll(client, "pc-b", hostname="B")
    await _report(client, a, _dir(location=long_a))
    await _report(client, b, _dir(location=long_b))
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    names = sorted(r["name"] for r in rooms)
    assert len(names) == 2 and all(len(n) <= 100 for n in names)
    assert sum(n.endswith(" (2)") for n in names) == 1
    assert {r["ad_key"] for r in rooms} == {long_a[:200], long_b[:200]}


async def test_a_failed_placement_does_not_fail_the_heartbeat(
    client, db_session, room_source, monkeypatch
):
    """Whatever goes wrong while filing the poste, the rest of the heartbeat
    (its commands, its threats) goes through."""
    from sqlalchemy import text

    from app.features.room import crud as room_crud

    async def broken(session, machine, source, **_kwargs):
        await session.exec(text("SELECT 1/0"))

    monkeypatch.setattr(room_crud, "place_from_directory", broken)
    room_source("ad_ou")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    await _report(client, a, _dir())
    machine = await _machine(client, headers, a)
    assert machine["room_id"] is None


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


_HONEST = "OU=B12,OU=Postes,DC=lycee,DC=local"
_FORGED = "OU=invente"


@pytest.mark.parametrize("forged_first", [True, False])
async def test_sync_adopts_a_manual_room_for_the_majority_key_only(
    client, db_session, room_source, forged_first
):
    """Audit S20 (T36): one forged reading naming « B12 » under an invented
    OU does not capture the room made by hand, whatever the row order: the
    key most postes report adopts it, the forged one gets « B12 (2) »."""
    room_source("manual")
    headers = await _admin(client, db_session)
    resp = await client.post("/api/v1/rooms", headers=headers, json={"name": "B12"})
    loose_id = resp.json()["id"]

    async def forged():
        f = await _enroll(client, "pc-forged", hostname="F")
        await _report(client, f, _dir(ou="B12", ou_dn=_FORGED))
        return f

    f = await forged() if forged_first else None
    honest = []
    for i in range(3):
        h = await _enroll(client, f"pc-h{i}", hostname=f"H{i}")
        await _report(client, h, _dir(ou="B12", ou_dn=_HONEST))
        honest.append(h)
    if f is None:
        f = await forged()

    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.status_code == 200, synced.text
    for h in honest:
        assert (await _machine(client, headers, h))["room_id"] == loose_id
    rooms = {
        r["id"]: r for r in (await client.get("/api/v1/rooms", headers=headers)).json()
    }
    assert rooms[loose_id]["ad_key"] == _HONEST
    forged_room = (await _machine(client, headers, f))["room_id"]
    assert forged_room != loose_id
    assert rooms[forged_room]["name"] == "B12 (2)"


async def test_sync_adopts_nothing_on_a_tie(client, db_session, room_source):
    room_source("manual")
    headers = await _admin(client, db_session)
    resp = await client.post("/api/v1/rooms", headers=headers, json={"name": "B12"})
    loose_id = resp.json()["id"]
    f = await _enroll(client, "pc-forged", hostname="F")
    await _report(client, f, _dir(ou="B12", ou_dn=_FORGED))
    h = await _enroll(client, "pc-honest", hostname="H")
    await _report(client, h, _dir(ou="B12", ou_dn=_HONEST))

    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.status_code == 200, synced.text
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert [(r["id"], r["ad_key"]) for r in rooms] == [(loose_id, None)]
    assert (await _machine(client, headers, f))["room_id"] is None
    assert (await _machine(client, headers, h))["room_id"] is None


async def test_sync_applies_the_dn_rule_of_the_heartbeat(
    client, db_session, room_source
):
    """Audit S20 (T36): a stored OU the poste's DN is not in is not filed by
    the re-sync either."""
    room_source("manual")
    headers = await _admin(client, db_session)
    a = await _enroll(client, "pc-a", hostname="A")
    await _report(
        client,
        a,
        {
            "distinguished_name": "CN=PC,OU=Ailleurs,DC=lycee,DC=local",
            "ou": "Salle B12",
            "ou_dn": "OU=Salle B12,OU=Postes,DC=lycee,DC=local",
        },
    )
    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.status_code == 200, synced.text
    assert synced.json()["placed"] == 0
    assert (await _machine(client, headers, a))["room_id"] is None
    assert (await client.get("/api/v1/rooms", headers=headers)).json() == []
