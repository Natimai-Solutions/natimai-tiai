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

    from app.features.inventory import budget
    from app.features.inventory.models import Software
    from app.features.machine.models import Machine

    monkeypatch.setattr(budget.software_quota, "units", 3)
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
    assert resp.json() == {
        "placed": 1,
        "unplaced": 0,
        "moved_out": 0,
        "rooms_created": 1,
        "undecided": 0,
        "undecided_rooms": [],
    }
    assert (await _machine(client, headers, a))["room_name"] == "Salle B12"
    assert (await _machine(client, headers, b))["room_id"] is None

    # In manual mode the sync is a no-op that says so.
    room_source("manual")
    resp = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert resp.json() == {
        "placed": 0,
        "unplaced": 0,
        "moved_out": 0,
        "rooms_created": 0,
        "undecided": 0,
        "undecided_rooms": [],
    }


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
    # Nobody was filed, and the answer says so: the two postes are not
    # "placed", they are undecided, and the room is named.
    assert synced.json() == {
        "placed": 0,
        "unplaced": 0,
        "moved_out": 0,
        "rooms_created": 0,
        "undecided": 2,
        "undecided_rooms": ["B12"],
    }
    details = await _last_sync_audit(db_session)
    assert (details["placed"], details["undecided"]) == (0, 2)
    assert details["undecided_rooms"] == ["B12"]


async def _last_sync_audit(db_session) -> dict:
    from sqlmodel import col, select

    from app.features.audit.models import AuditEntry

    rows = await db_session.exec(
        select(AuditEntry)
        .where(AuditEntry.action == "room.sync_directory")
        .order_by(col(AuditEntry.at).desc())
    )
    entry = rows.first()
    assert entry is not None
    return dict(entry.details or {})


async def _flag(db_session, enrolled, **values) -> None:
    from sqlalchemy import update

    from app.features.machine.models import Machine

    await db_session.exec(
        update(Machine)
        .where(Machine.id == uuid.UUID(enrolled["machine_id"]))
        .values(**values)
    )
    await db_session.commit()


async def test_sync_counts_what_it_placed_beside_what_it_left_undecided(
    client, db_session, room_source
):
    """A tie on one room, a clear room beside it: the count of placed postes
    is the clear room's, not every poste that had a key."""
    room_source("manual")
    headers = await _admin(client, db_session)
    await client.post("/api/v1/rooms", headers=headers, json={"name": "B12"})
    f = await _enroll(client, "pc-forged", hostname="F")
    await _report(client, f, _dir(ou="B12", ou_dn=_FORGED))
    h = await _enroll(client, "pc-honest", hostname="H")
    await _report(client, h, _dir(ou="B12", ou_dn=_HONEST))
    clear = await _enroll(client, "pc-clear", hostname="C")
    await _report(client, clear, _dir(ou="C3", ou_dn="OU=C3,DC=lycee,DC=local"))

    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.json() == {
        "placed": 1,
        "unplaced": 0,
        "moved_out": 0,
        "rooms_created": 1,
        "undecided": 2,
        "undecided_rooms": ["B12"],
    }
    assert (await _machine(client, headers, clear))["room_name"] == "C3"


async def test_the_undecided_rooms_are_a_bounded_list(
    client, db_session, room_source, monkeypatch
):
    from app.core.config import settings
    from app.features.room import crud as room_crud

    # Forty-odd enrolments from one address in one test.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    room_source("manual")
    headers = await _admin(client, db_session)
    for n in range(room_crud.UNDECIDED_ROOMS_MAX + 3):
        name = f"Salle {n:02d}"
        await client.post("/api/v1/rooms", headers=headers, json={"name": name})
        for side in ("a", "b"):
            poste = await _enroll(client, f"pc-{n}-{side}")
            await _report(
                client, poste, _dir(ou=name, ou_dn=f"OU={name},OU={side},DC=x")
            )

    room_source("ad_ou")
    body = (await client.post("/api/v1/rooms/sync-directory", headers=headers)).json()
    assert body["placed"] == 0
    assert body["undecided"] == 2 * (room_crud.UNDECIDED_ROOMS_MAX + 3)
    assert body["undecided_rooms"] == [
        f"Salle {n:02d}" for n in range(room_crud.UNDECIDED_ROOMS_MAX)
    ]


@pytest.mark.parametrize(
    "flags", [{"token_revoked": True}, {"needs_verification": True}]
)
async def test_revoked_and_unverified_postes_do_not_vote(
    client, db_session, room_source, flags
):
    """Two readings under an invented OU from postes that are revoked, or
    whose identity is to be confirmed, do not outvote one poste in good
    standing: its key adopts the room, and they are filed after it."""
    room_source("manual")
    headers = await _admin(client, db_session)
    resp = await client.post("/api/v1/rooms", headers=headers, json={"name": "B12"})
    loose_id = resp.json()["id"]
    doubtful = []
    for i in range(2):
        f = await _enroll(client, f"pc-forged-{i}", hostname=f"F{i}")
        await _report(client, f, _dir(ou="B12", ou_dn=_FORGED))
        await _flag(db_session, f, **flags)
        doubtful.append(f)
    h = await _enroll(client, "pc-honest", hostname="H")
    await _report(client, h, _dir(ou="B12", ou_dn=_HONEST))

    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.status_code == 200, synced.text
    rooms = {
        r["id"]: r for r in (await client.get("/api/v1/rooms", headers=headers)).json()
    }
    assert rooms[loose_id]["ad_key"] == _HONEST
    assert (await _machine(client, headers, h))["room_id"] == loose_id
    # Still placed like the others, once the key is decided: in the room
    # their own key gets, beside the adopted one.
    for f in doubtful:
        room_id = (await _machine(client, headers, f))["room_id"]
        assert rooms[room_id]["name"] == "B12 (2)"
    assert synced.json() == {
        "placed": 3,
        "unplaced": 0,
        "moved_out": 0,
        "rooms_created": 1,
        "undecided": 0,
        "undecided_rooms": [],
    }


async def test_a_room_claimed_only_by_postes_that_do_not_vote_stays_undecided(
    client, db_session, room_source
):
    room_source("manual")
    headers = await _admin(client, db_session)
    resp = await client.post("/api/v1/rooms", headers=headers, json={"name": "B12"})
    loose_id = resp.json()["id"]
    f = await _enroll(client, "pc-forged", hostname="F")
    await _report(client, f, _dir(ou="B12", ou_dn=_FORGED))
    await _flag(db_session, f, token_revoked=True)

    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.json()["undecided"] == 1
    assert synced.json()["undecided_rooms"] == ["B12"]
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert [(r["id"], r["ad_key"]) for r in rooms] == [(loose_id, None)]


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


async def test_sync_leaves_a_poste_without_any_reading_where_it_is(
    client, db_session, room_source
):
    """Item 2: the first re-sync took every poste filed by hand without a
    directory reading out of its room (318 of 340). A poste whose agent never
    sent the block is left where it is, as a heartbeat without it does; one
    whose reading names no OU is still taken out."""
    room_source("manual")
    headers = await _admin(client, db_session)
    room = (
        await client.post("/api/v1/rooms", headers=headers, json={"name": "C3"})
    ).json()["id"]
    silent = await _enroll(client, "pc-silent", hostname="S")
    spoken = await _enroll(client, "pc-spoken", hostname="T")
    await _report(client, spoken, {"distinguished_name": "CN=PC,DC=corp"})
    resp = await client.post(
        f"/api/v1/rooms/{room}/machines",
        headers=headers,
        json={"machine_ids": [silent["machine_id"], spoken["machine_id"]]},
    )
    assert resp.status_code == 200, resp.text

    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.status_code == 200, synced.text
    assert synced.json()["unplaced"] == 1
    assert synced.json()["moved_out"] == 1
    assert (await _machine(client, headers, silent))["room_id"] == room
    assert (await _machine(client, headers, spoken))["room_id"] is None


async def test_sync_adopts_a_room_made_by_hand_inside_a_building(
    client, db_session, room_source
):
    """Item 2: a room made by hand in its building is adopted by name, by the
    majority key, like one outside any building — not doubled by a new
    building-less « B12 »."""
    room_source("manual")
    headers = await _admin(client, db_session)
    building = (
        await client.post("/api/v1/buildings", headers=headers, json={"name": "Bât. B"})
    ).json()["id"]
    room = (
        await client.post(
            "/api/v1/rooms",
            headers=headers,
            json={"name": "b12", "building_id": building},
        )
    ).json()["id"]
    honest = []
    for i in range(2):
        h = await _enroll(client, f"pc-h{i}", hostname=f"H{i}")
        await _report(client, h, _dir(ou="B12", ou_dn=_HONEST))
        honest.append(h)
    f = await _enroll(client, "pc-forged", hostname="F")
    await _report(client, f, _dir(ou="B12", ou_dn=_FORGED))

    room_source("ad_ou")
    synced = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert synced.status_code == 200, synced.text
    for h in honest:
        assert (await _machine(client, headers, h))["room_id"] == room
    rooms = {
        r["id"]: r for r in (await client.get("/api/v1/rooms", headers=headers)).json()
    }
    assert rooms[room]["ad_key"] == _HONEST
    assert rooms[room]["building"]["id"] == building
    forged_room = (await _machine(client, headers, f))["room_id"]
    assert forged_room != room and rooms[forged_room]["building"] is None


async def test_two_rooms_made_by_hand_of_one_name_leave_it_undecided(
    client, db_session, room_source
):
    room_source("manual")
    headers = await _admin(client, db_session)
    for name in ("Bât. A", "Bât. B"):
        b = (
            await client.post("/api/v1/buildings", headers=headers, json={"name": name})
        ).json()["id"]
        await client.post(
            "/api/v1/rooms", headers=headers, json={"name": "B12", "building_id": b}
        )
    h = await _enroll(client, "pc-h", hostname="H")
    await _report(client, h, _dir(ou="B12", ou_dn=_HONEST))
    room_source("ad_ou")
    synced = (await client.post("/api/v1/rooms/sync-directory", headers=headers)).json()
    assert (synced["undecided"], synced["undecided_rooms"]) == (1, ["B12"])
    assert synced["rooms_created"] == 0
    assert len((await client.get("/api/v1/rooms", headers=headers)).json()) == 2


async def test_a_dry_run_says_what_the_sync_would_do_and_writes_nothing(
    client, db_session, room_source
):
    """C9: ``dry_run=true`` answers the counts of the real run — with
    ``moved_out``, the postes that would leave their room — and changes
    nothing: no room, no move, no audit entry."""
    from sqlmodel import select

    from app.features.audit.models import AuditEntry

    room_source("manual")
    headers = await _admin(client, db_session)
    room = (
        await client.post("/api/v1/rooms", headers=headers, json={"name": "Réserve"})
    ).json()["id"]
    a = await _enroll(client, "pc-a", hostname="A")
    await _report(client, a, _dir(ou="C3", ou_dn="OU=C3,DC=lycee,DC=local"))
    await client.post(
        f"/api/v1/rooms/{room}/machines",
        headers=headers,
        json={"machine_ids": [a["machine_id"]]},
    )

    room_source("ad_ou")
    preview = await client.post(
        "/api/v1/rooms/sync-directory?dry_run=true", headers=headers
    )
    assert preview.status_code == 200, preview.text
    expected = {
        "placed": 1,
        "unplaced": 0,
        "moved_out": 1,
        "rooms_created": 1,
        "undecided": 0,
        "undecided_rooms": [],
    }
    assert preview.json() == expected
    assert (await _machine(client, headers, a))["room_id"] == room
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert [r["name"] for r in rooms] == ["Réserve"]
    audits = await db_session.exec(
        select(AuditEntry).where(AuditEntry.action == "room.sync_directory")
    )
    assert audits.all() == []

    real = await client.post("/api/v1/rooms/sync-directory", headers=headers)
    assert real.json() == expected
    assert (await _machine(client, headers, a))["room_name"] == "C3"


async def test_a_resync_beside_heartbeats_filing_the_same_postes_does_not_deadlock(
    client, db_session, room_source
):
    """A re-sync (its dry run, then the real one) while the postes report
    their directory block: the heartbeat holds its poste and goes on to the
    room its OU names, the sync used to hold that room — created a moment
    earlier, not committed — and go on to the poste. One of the two died of
    the deadlock: a 500 for the administrator when it was the sync. The sync
    now takes its postes first, like the heartbeat."""
    import asyncio

    headers = await _admin(client, db_session)
    enrolled = [await _enroll(client, f"pc-{i}", hostname=f"H{i}") for i in range(30)]

    def reading(i):
        return _dir(ou=f"R{i % 10}", ou_dn=f"OU=R{i % 10},DC=lycee,DC=local")

    # Stored in manual mode: nothing is filed yet, every room is to create.
    room_source("manual")
    for i, e in enumerate(enrolled):
        await _report(client, e, reading(i))
    room_source("ad_ou")

    async def beat(i, e):
        return await client.post(
            "/api/v1/agent/heartbeat",
            headers={"Authorization": f"Bearer {e['token']}"},
            json={"inventory": {"hash": "h2", "directory": reading(i)}},
        )

    answers = await asyncio.gather(
        client.post("/api/v1/rooms/sync-directory?dry_run=true", headers=headers),
        *[beat(i, e) for i, e in enumerate(enrolled)],
        client.post("/api/v1/rooms/sync-directory?dry_run=true", headers=headers),
        client.post("/api/v1/rooms/sync-directory", headers=headers),
    )
    assert [r.status_code for r in answers] == [200] * len(answers), [
        r.text[:300] for r in answers if r.status_code != 200
    ]
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert sorted(r["name"] for r in rooms) == [f"R{i}" for i in range(10)]
    assert sum(r["machine_count"] for r in rooms) == 30


async def test_postes_reporting_a_new_ou_at_the_same_time_are_all_filed(
    client, db_session, room_source
):
    """Thirty postes report ten OUs that have no room yet, together. One
    request creates each room; the others, which had not seen it either,
    used to fail on the room's unique key — the heartbeat went through, the
    poste stayed unfiled until its next inventory. They now take the room
    the first one created."""
    import asyncio

    headers = await _admin(client, db_session)
    enrolled = [await _enroll(client, f"pc-{i}", hostname=f"H{i}") for i in range(30)]
    room_source("ad_ou")
    answers = await asyncio.gather(
        *[
            client.post(
                "/api/v1/agent/heartbeat",
                headers={"Authorization": f"Bearer {e['token']}"},
                json={
                    "inventory": {
                        "hash": "h1",
                        "directory": _dir(
                            ou=f"R{i % 10}", ou_dn=f"OU=R{i % 10},DC=lycee,DC=local"
                        ),
                    }
                },
            )
            for i, e in enumerate(enrolled)
        ]
    )
    assert {r.status_code for r in answers} == {200}
    rooms = (await client.get("/api/v1/rooms", headers=headers)).json()
    assert sorted((r["name"], r["machine_count"]) for r in rooms) == [
        (f"R{i}", 3) for i in range(10)
    ]
