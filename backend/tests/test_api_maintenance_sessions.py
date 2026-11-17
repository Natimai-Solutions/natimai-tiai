"""Maintenance sessions after the acceptance test: a visit read back with its
skipped postes, removed with its journal lines, counted by what it still
maintains; postes of another room refused; the « à échéance » window capped
at half the cycle; the due list grouped by what its postes resolve to; where
a room's owner comes from; the default owner that no longer resolves.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import col, select

STRONG = "correct-horse-battery"


async def _user(client, db_session, email, groups, full_name=None):
    from app.features.user import crud

    user = await crud.create_user(
        db_session, email=email, password=STRONG, groups=groups, full_name=full_name
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, str(user.id)


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await _user(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])


async def _tech(client, db_session, email="tech@test.local", name="Marie"):
    from app.features.user.permissions import BuiltinGroup

    return await _user(client, db_session, email, [BuiltinGroup.TECHNICIAN], name)


async def _machine(db_session, hostname, *, room_id=None, days_ago=100, last=None):
    from app.features.machine.models import Machine

    m = Machine(
        machine_uuid=str(uuid.uuid4()),
        hostname=hostname,
        first_seen=datetime.now(UTC) - timedelta(days=days_ago),
        last_maintenance_at=last,
        room_id=uuid.UUID(room_id) if room_id else None,
    )
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return str(m.id)


async def _room(client, headers, name):
    resp = await client.post("/api/v1/rooms", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _journal(client, headers, machine_id):
    resp = await client.get(
        f"/api/v1/machines/{machine_id}/interventions", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _visit(client, headers, room, done, skipped=(), note="Salle dépoussiérée"):
    resp = await client.post(
        "/api/v1/maintenance",
        headers=headers,
        json={
            "room_id": room,
            "note": note,
            "items": [
                {"machine_id": m, "note": f"note {i}"} for i, m in enumerate(done)
            ],
            "skipped": [{"machine_id": m, "note": "Absent"} for m in skipped],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_a_visit_reads_back_with_its_skipped_postes(client, db_session):
    """Item 1 (C8): the journal line links to its visit, and the visit says
    who was done and who was skipped, each with their note."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    a = await _machine(db_session, "A", room_id=room)
    b = await _machine(db_session, "B", room_id=room)
    visit = await _visit(client, admin, room, [a], skipped=[b])

    got = (await client.get(f"/api/v1/maintenance/{visit['id']}", headers=admin)).json()
    assert got["note"] == "Salle dépoussiérée"
    assert [(i["hostname"], i["note"]) for i in got["items"]] == [("A", "note 0")]
    assert [(i["hostname"], i["note"]) for i in got["skipped"]] == [("B", "Absent")]
    assert got["machine_count"] == 1
    (line,) = await _journal(client, admin, b)
    assert line["maintenance_id"] == visit["id"]
    (line,) = await _journal(client, admin, a)
    assert line["maintenance_id"] == visit["id"]


async def test_the_count_follows_the_remaining_maintenance_lines(client, db_session):
    """Item 6: a line deleted, or turned into « Autre », no longer counts."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    a = await _machine(db_session, "A", room_id=room)
    b = await _machine(db_session, "B", room_id=room)
    c = await _machine(db_session, "C", room_id=room)
    visit = await _visit(client, admin, room, [a, b, c])
    assert visit["machine_count"] == 3

    (line_a,) = await _journal(client, admin, a)
    resp = await client.patch(
        f"/api/v1/interventions/{line_a['id']}", headers=admin, json={"kind": "other"}
    )
    assert resp.status_code == 200, resp.text
    (line_b,) = await _journal(client, admin, b)
    resp = await client.delete(f"/api/v1/interventions/{line_b['id']}", headers=admin)
    assert resp.status_code == 204

    got = (await client.get(f"/api/v1/maintenance/{visit['id']}", headers=admin)).json()
    assert got["machine_count"] == 1
    assert [i["hostname"] for i in got["items"]] == ["C"]
    listed = (
        await client.get(f"/api/v1/maintenance?room_id={room}", headers=admin)
    ).json()
    assert listed["items"][0]["machine_count"] == 1


async def test_a_visit_is_deleted_with_its_lines_and_the_cycle_goes_back(
    client, db_session
):
    """Item 6: DELETE /maintenance/{id} removes the visit and every line it
    wrote, moves the postes' last maintenance back, and is audited."""
    from app.features.audit.models import AuditEntry

    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    earlier = datetime.now(UTC) - timedelta(days=40)
    a = await _machine(db_session, "A", room_id=room)
    b = await _machine(db_session, "B", room_id=room)
    # An older visit of A, which must stay.
    resp = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={
            "room_id": room,
            "performed_at": earlier.isoformat(),
            "items": [{"machine_id": a}],
        },
    )
    assert resp.status_code == 201, resp.text
    visit = await _visit(client, admin, room, [a], skipped=[b])

    resp = await client.delete(f"/api/v1/maintenance/{visit['id']}", headers=admin)
    assert resp.status_code == 204, resp.text
    resp = await client.get(f"/api/v1/maintenance/{visit['id']}", headers=admin)
    assert resp.status_code == 404
    assert len(await _journal(client, admin, a)) == 1
    assert await _journal(client, admin, b) == []
    detail = (await client.get(f"/api/v1/machines/{a}", headers=admin)).json()
    assert detail["last_maintenance_at"] is not None
    assert abs(
        datetime.fromisoformat(detail["last_maintenance_at"]) - earlier
    ) < timedelta(seconds=1)

    rows = await db_session.exec(
        select(AuditEntry).where(col(AuditEntry.action) == "maintenance.delete")
    )
    (entry,) = rows.all()
    assert entry.details["hostnames"] == ["A", "B"]
    assert entry.details["note"] == "Salle dépoussiérée"


async def test_deleting_a_visit_takes_maintenance_write(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    a = await _machine(db_session, "A", room_id=room)
    visit = await _visit(client, admin, room, [a])
    reader, _ = await _user(
        client, db_session, "ro@test.local", [BuiltinGroup.READONLY]
    )
    resp = await client.delete(f"/api/v1/maintenance/{visit['id']}", headers=reader)
    assert resp.status_code == 403
    resp = await client.delete(f"/api/v1/maintenance/{uuid.uuid4()}", headers=admin)
    assert resp.status_code == 404


async def test_a_visit_of_a_room_refuses_postes_of_another(client, db_session):
    """Item 12: postes not in ``room_id`` are refused, by name."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    other = await _room(client, admin, "B12")
    a = await _machine(db_session, "A", room_id=room)
    stray = await _machine(db_session, "PC-STRAY", room_id=other)
    loose = await _machine(db_session, "PC-LOOSE")
    resp = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={
            "room_id": room,
            "items": [{"machine_id": a}, {"machine_id": stray}],
            "skipped": [{"machine_id": loose, "note": "pas là"}],
        },
    )
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "maintenance.items.not_in_room"
    assert error["details"]["hostnames"] == ["PC-LOOSE", "PC-STRAY"]
    assert await _journal(client, admin, a) == []
    # Without a room, any poste goes.
    resp = await client.post(
        "/api/v1/maintenance", headers=admin, json={"items": [{"machine_id": stray}]}
    )
    assert resp.status_code == 201, resp.text


async def test_a_short_cycle_is_up_to_date_for_its_first_half(client, db_session):
    """Item 7: cycle 7 days under a 14-day window was « à échéance » forever;
    the window is now at most half the cycle — in the payloads and in the
    SQL filter alike."""
    admin, _ = await _admin(client, db_session)
    resp = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"maintenance_default_cycle_days": 7, "maintenance_due_soon_days": 14},
    )
    assert resp.status_code == 200, resp.text
    now = datetime.now(UTC)
    fresh = await _machine(db_session, "FRESH", last=now - timedelta(days=1))
    near = await _machine(db_session, "NEAR", last=now - timedelta(days=5))
    late = await _machine(db_session, "LATE", last=now - timedelta(days=8))
    expected = {fresh: "ok", near: "due_soon", late: "overdue"}
    for machine_id, state in expected.items():
        res = (
            await client.get(
                f"/api/v1/machines/{machine_id}/maintenance", headers=admin
            )
        ).json()
        assert res["resolved"]["state"] == state, machine_id
    for state in ("ok", "due_soon", "overdue"):
        listed = (
            await client.get(
                f"/api/v1/machines?maintenance_state={state}", headers=admin
            )
        ).json()
        assert {m["id"] for m in listed["items"]} == {
            k for k, v in expected.items() if v == state
        }, state
    # A long cycle keeps the parc's window.
    resp = await client.patch(
        "/api/v1/settings", headers=admin, json={"maintenance_default_cycle_days": 90}
    )
    far = await _machine(db_session, "FAR", last=now - timedelta(days=80))
    res = (
        await client.get(f"/api/v1/machines/{far}/maintenance", headers=admin)
    ).json()
    assert res["resolved"]["state"] == "due_soon"


async def test_due_list_groups_postes_by_what_they_resolve_to(client, db_session):
    """Item 8: a poste whose own owner overrides the room's is a group of its
    own — its header names its owner, and its level says that taking it
    takes the postes, not the room."""
    admin, admin_id = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    room = await _room(client, admin, "A101")
    resp = await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": admin_id},
    )
    assert resp.status_code == 200, resp.text
    a = await _machine(db_session, "A", room_id=room)
    b = await _machine(db_session, "B", room_id=room)
    resp = await client.patch(
        f"/api/v1/machines/{b}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    assert resp.status_code == 200, resp.text

    mine = (await client.get("/api/v1/maintenance/due?owner=me", headers=tech)).json()
    (group,) = mine["rooms"]
    assert group["id"] == room and group["level"] == "machine"
    assert group["owner"]["id"] == tech_id
    assert [m["id"] for m in group["machines"]] == [b]
    assert group["key"] != room

    every = (await client.get("/api/v1/maintenance/due", headers=admin)).json()
    by_level = {g["level"]: g for g in every["rooms"]}
    assert by_level["room"]["key"] == room
    assert by_level["room"]["owner"]["id"] == admin_id
    assert [m["id"] for m in by_level["room"]["machines"]] == [a]
    assert [m["id"] for m in by_level["machine"]["machines"]] == [b]


async def test_the_tasks_mail_names_a_split_room_once(client, db_session):
    """A room whose postes resolve to two cycles is two groups in « Mes
    tâches » (each taken on its own); the mail only counts, and named the
    room twice. One line, with both groups' counts."""
    from app.features.notification import tasks
    from app.features.user.models import User

    admin, admin_id = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": admin_id},
    )
    await _machine(db_session, "A", room_id=room)
    b = await _machine(db_session, "B", room_id=room)
    resp = await client.patch(
        f"/api/v1/machines/{b}/maintenance",
        headers=admin,
        json={"maintenance_cycle_days": 30},
    )
    assert resp.status_code == 200, resp.text
    groups = (
        await client.get("/api/v1/maintenance/due?owner=me", headers=admin)
    ).json()
    assert len(groups["rooms"]) == 2

    user = await db_session.get(User, uuid.UUID(admin_id))
    lines = await tasks.personal_block(db_session, user)
    rooms = [line for line in lines if "A101" in line]
    assert rooms == ["    • A101 — 2 en retard, 0 à échéance"]


async def test_a_room_says_where_its_owner_comes_from(client, db_session):
    """Item 4: a room owner deactivated since resolves to the parc's default —
    the room says « global », and names its own owner as inactive."""
    from app.features.user.models import User

    admin, admin_id = await _admin(client, db_session)
    _, tech_id = await _tech(client, db_session)
    room = await _room(client, admin, "A101")
    await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"maintenance_default_owner_id": admin_id},
    )
    resp = await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    assert resp.json()["effective_owner_origin"] == "room"
    assert resp.json()["maintenance_owner"]["active"] is True

    user = await db_session.get(User, uuid.UUID(tech_id))
    user.is_active = False
    db_session.add(user)
    await db_session.commit()
    got = (await client.get(f"/api/v1/rooms/{room}/maintenance", headers=admin)).json()
    assert got["effective_owner"]["id"] == admin_id
    assert got["effective_owner_origin"] == "global"
    assert got["effective_cycle_origin"] == "global"
    assert got["maintenance_owner"] == {
        "id": tech_id,
        "name": "Marie",
        "active": False,
    }


async def test_settings_name_a_default_owner_that_no_longer_resolves(
    client, db_session
):
    """Item 3: the stored default owner, deactivated, is named apart instead
    of vanishing — and a save that leaves it out keeps it."""
    from app.features.user.models import User

    admin, _ = await _admin(client, db_session)
    _, tech_id = await _tech(client, db_session)
    resp = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"maintenance_default_owner_id": tech_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["maintenance_default_owner_unavailable"] is None

    user = await db_session.get(User, uuid.UUID(tech_id))
    user.is_active = False
    db_session.add(user)
    await db_session.commit()
    got = (await client.get("/api/v1/settings", headers=admin)).json()
    assert got["maintenance_default_owner"] is None
    assert got["maintenance_default_owner_unavailable"] == {
        "id": tech_id,
        "name": "Marie",
    }
    resp = await client.patch(
        "/api/v1/settings", headers=admin, json={"maintenance_default_cycle_days": 60}
    )
    assert resp.json()["maintenance_default_owner_unavailable"]["id"] == tech_id


# --- Audit T30: nothing done, and rooms larger than one request ---------------


async def test_a_visit_with_nothing_done_is_recorded_when_it_says_why(
    client, db_session
):
    """A visit where every poste was left out, each with its reason, is
    recorded: one « Maintenance non faite » line per poste, no maintenance
    counted, and no poste's last maintenance moved."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    a = await _machine(db_session, "A", room_id=room)
    b = await _machine(db_session, "B", room_id=room)
    visit = await _visit(client, admin, room, [], skipped=[a, b])
    assert visit["machine_count"] == 0
    assert visit["items"] == []
    assert sorted(i["hostname"] for i in visit["skipped"]) == ["A", "B"]
    for m in (a, b):
        (line,) = await _journal(client, admin, m)
        assert line["kind"] == "other"
        assert line["title"] == "Maintenance non faite — A101"
        detail = (await client.get(f"/api/v1/machines/{m}", headers=admin)).json()
        assert detail["last_maintenance_at"] is None
    listed = (
        await client.get(f"/api/v1/maintenance?room_id={room}", headers=admin)
    ).json()
    assert [v["machine_count"] for v in listed["items"]] == [0]


async def test_a_room_visit_with_only_its_global_note_is_recorded(client, db_session):
    """The room was closed: no poste line at all, the global note says why."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    a = await _machine(db_session, "A", room_id=room)
    resp = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={"room_id": room, "note": "Salle fermée (examens)", "items": []},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["note"], body["machine_count"], body["room_name"]) == (
        "Salle fermée (examens)",
        0,
        "A101",
    )
    assert await _journal(client, admin, a) == []
    got = await client.get(f"/api/v1/maintenance/{body['id']}", headers=admin)
    assert got.status_code == 200, got.text


async def test_a_visit_with_nothing_done_and_no_reason_is_refused(client, db_session):
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101")
    a = await _machine(db_session, "A", room_id=room)
    for payload in (
        {"room_id": room, "items": []},
        # A blank reason is no reason: the skipped poste is not written.
        {"room_id": room, "items": [], "skipped": [{"machine_id": a, "note": " "}]},
        # A note about no room and no poste is about nothing.
        {"note": "RAS", "items": []},
        {"items": []},
    ):
        resp = await client.post("/api/v1/maintenance", headers=admin, json=payload)
        assert resp.status_code == 422, (payload, resp.text)
        assert resp.json()["error"]["code"] == "maintenance.session.empty"
    assert await _journal(client, admin, a) == []
    listed = (await client.get("/api/v1/maintenance", headers=admin)).json()
    assert listed["total"] == 0


async def test_a_large_room_is_sent_in_parts_as_one_visit(client, db_session):
    """More postes than one request takes: the first part creates the visit,
    the next ones are added to it — same date, same title, one visit."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "Amphi")
    a = await _machine(db_session, "A", room_id=room)
    b = await _machine(db_session, "B", room_id=room)
    c = await _machine(db_session, "C", room_id=room)
    when = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)
    resp = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={
            "room_id": room,
            "performed_at": when.isoformat(),
            "note": "Tout l'amphi",
            "items": [{"machine_id": a}],
        },
    )
    assert resp.status_code == 201, resp.text
    visit_id = resp.json()["id"]
    part = {"items": [{"machine_id": b}], "skipped": [{"machine_id": c, "note": "HS"}]}
    resp = await client.post(
        f"/api/v1/maintenance/{visit_id}/lines", headers=admin, json=part
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["machine_count"] == 2
    assert [i["hostname"] for i in body["items"]] == ["A", "B"]
    assert [i["hostname"] for i in body["skipped"]] == ["C"]
    # Sent twice (an answer lost on the way): nothing written twice.
    resp = await client.post(
        f"/api/v1/maintenance/{visit_id}/lines", headers=admin, json=part
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["machine_count"] == 2
    (line,) = await _journal(client, admin, b)
    assert line["maintenance_id"] == visit_id
    assert line["title"] == "Amphi"
    assert datetime.fromisoformat(line["performed_at"]) == when
    detail = (await client.get(f"/api/v1/machines/{b}", headers=admin)).json()
    assert datetime.fromisoformat(detail["last_maintenance_at"]) == when
    (line,) = await _journal(client, admin, c)
    assert line["title"] == "Maintenance non faite — Amphi"
    listed = (await client.get("/api/v1/maintenance", headers=admin)).json()
    assert listed["total"] == 1

    # The room's own postes only, and its author only.
    other = await _room(client, admin, "B12")
    stray = await _machine(db_session, "STRAY", room_id=other)
    resp = await client.post(
        f"/api/v1/maintenance/{visit_id}/lines",
        headers=admin,
        json={"items": [{"machine_id": stray}]},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "maintenance.items.not_in_room"
    tech, _ = await _tech(client, db_session)
    d = await _machine(db_session, "D", room_id=room)
    resp = await client.post(
        f"/api/v1/maintenance/{visit_id}/lines",
        headers=tech,
        json={"items": [{"machine_id": d}]},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "maintenance.session.not_author"
    resp = await client.post(
        f"/api/v1/maintenance/{uuid.uuid4()}/lines",
        headers=admin,
        json={"items": [{"machine_id": d}]},
    )
    assert resp.status_code == 404
    # One request stays bounded.
    resp = await client.post(
        f"/api/v1/maintenance/{visit_id}/lines",
        headers=admin,
        json={"items": [{"machine_id": d}] * 1001},
    )
    assert resp.status_code == 422
