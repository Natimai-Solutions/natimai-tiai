"""Maintenance: the three-level cycle and owner, what is due and for whom, a
recorded visit writing the journal, and the console settings.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid
from datetime import UTC, datetime, timedelta

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


async def _machine(db_session, hostname="PC-1", first_seen_days_ago=0, room_id=None):
    from app.features.machine.models import Machine

    m = Machine(
        machine_uuid=str(uuid.uuid4()),
        hostname=hostname,
        first_seen=datetime.now(UTC) - timedelta(days=first_seen_days_ago),
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


async def _detail(client, headers, machine_id):
    resp = await client.get(f"/api/v1/machines/{machine_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_cycle_and_owner_resolve_over_three_levels(client, db_session):
    admin, admin_id = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    room = await _room(client, admin, "B12")
    m = await _machine(db_session, "PC-1", first_seen_days_ago=100, room_id=room)

    # Nothing set anywhere: the environment's 90 days, no owner — and a poste
    # first seen 100 days ago is overdue.
    res = (await client.get(f"/api/v1/machines/{m}/maintenance", headers=admin)).json()
    assert res["resolved"]["cycle_days"] == 90
    assert res["resolved"]["cycle_origin"] == "global"
    assert res["resolved"]["owner"] is None
    assert res["resolved"]["state"] == "overdue"

    # The console sets a global default owner and a longer cycle.
    resp = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={
            "maintenance_default_cycle_days": 180,
            "maintenance_default_owner_id": admin_id,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["maintenance_default_cycle_days"] == 180
    assert resp.json()["maintenance_default_owner"]["id"] == admin_id
    res = (await client.get(f"/api/v1/machines/{m}/maintenance", headers=admin)).json()[
        "resolved"
    ]
    assert res["cycle_days"] == 180 and res["state"] == "ok"
    assert res["owner"]["id"] == admin_id and res["owner_origin"] == "global"

    # The room overrides: 30 days, Marie.
    resp = await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_cycle_days": 30, "maintenance_owner_id": tech_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["effective_owner"]["name"] == "Marie"
    res = (await client.get(f"/api/v1/machines/{m}/maintenance", headers=admin)).json()[
        "resolved"
    ]
    assert res["cycle_days"] == 30 and res["cycle_origin"] == "room"
    assert res["owner"]["name"] == "Marie" and res["owner_origin"] == "room"
    assert res["state"] == "overdue"

    # The poste overrides the room: excluded (0), and the room's owner kept.
    resp = await client.patch(
        f"/api/v1/machines/{m}/maintenance",
        headers=admin,
        json={"maintenance_cycle_days": 0},
    )
    assert resp.status_code == 200, resp.text
    res = resp.json()["resolved"]
    assert res["state"] == "excluded" and res["due_at"] is None
    assert res["cycle_origin"] == "machine" and res["owner_origin"] == "room"
    # The list and the fiche say the same.
    detail = await _detail(client, admin, m)
    assert detail["maintenance_state"] == "excluded"
    assert detail["maintenance_owner"] == "Marie"


async def test_due_list_groups_by_room_and_filters_by_owner(client, db_session):
    admin, admin_id = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    b12 = await _room(client, admin, "B12")
    b13 = await _room(client, admin, "B13")
    await client.patch(
        f"/api/v1/rooms/{b12}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    await client.patch(
        f"/api/v1/rooms/{b13}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": admin_id},
    )
    a = await _machine(db_session, "A", first_seen_days_ago=100, room_id=b12)  # overdue
    b = await _machine(
        db_session, "B", first_seen_days_ago=80, room_id=b12
    )  # due soon (90 - 14)
    c = await _machine(db_session, "C", first_seen_days_ago=1, room_id=b13)  # ok
    d = await _machine(
        db_session, "D", first_seen_days_ago=200
    )  # loose, overdue, no owner
    # One poste of B12 handed to the admin directly: it leaves Marie's list.
    await client.patch(
        f"/api/v1/machines/{b}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": admin_id},
    )

    mine = (
        await client.get(
            "/api/v1/maintenance/due", headers=tech, params={"owner": "me"}
        )
    ).json()
    assert [r["name"] for r in mine["rooms"]] == ["B12"]
    assert mine["rooms"][0]["overdue"] == 1 and mine["rooms"][0]["due_soon"] == 0
    assert [m["hostname"] for m in mine["rooms"][0]["machines"]] == ["A"]
    assert mine["machines"] == []
    assert mine["overdue"] == 1

    admins = (
        await client.get(
            "/api/v1/maintenance/due", headers=admin, params={"owner": "me"}
        )
    ).json()
    names = {r["name"]: r for r in admins["rooms"]}
    assert set(names) == {"B12", "B13"}
    assert names["B12"]["due_soon"] == 1 and names["B13"]["overdue"] == 0
    assert admins["due_soon"] == 1

    nobody = (
        await client.get(
            "/api/v1/maintenance/due", headers=admin, params={"owner": "none"}
        )
    ).json()
    assert [m["hostname"] for m in nobody["machines"]] == ["D"]
    assert nobody["machines"][0]["state"] == "overdue"

    everybody = (await client.get("/api/v1/maintenance/due", headers=admin)).json()
    assert everybody["overdue"] == 2 and everybody["due_soon"] == 1
    # The room whose poste is due soonest comes first.
    assert everybody["rooms"][0]["name"] == "B12"
    del a, c, d


async def test_rooms_list_names_the_owner_the_policy_resolves(client, db_session):
    """Audit B08 (T17): room owner deactivated, default owner Paul — GET
    /rooms says Paul, like /maintenance/due and the poste's fiche."""
    from app.features.user import crud as user_crud
    from app.features.user.permissions import BuiltinGroup

    admin, _ = await _admin(client, db_session)
    _, marie_id = await _tech(client, db_session)
    _, paul_id = await _user(
        client, db_session, "paul@test.local", [BuiltinGroup.TECHNICIAN], "Paul"
    )
    room = await _room(client, admin, "B12")
    m = await _machine(db_session, "A", first_seen_days_ago=100, room_id=room)
    r = await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": marie_id},
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"maintenance_default_owner_id": paul_id},
    )
    assert r.status_code == 200, r.text
    marie = await user_crud.get_by_email(db_session, "tech@test.local")
    assert marie is not None
    marie.is_active = False
    db_session.add(marie)
    await db_session.commit()

    rooms = (await client.get("/api/v1/rooms", headers=admin)).json()
    assert rooms[0]["effective_owner_name"] == "Paul"
    assert (await _detail(client, admin, m))["maintenance_owner"] == "Paul"


async def test_a_deactivated_owner_counts_as_none(client, db_session):
    """Audit B08, B35: the postes and requests of an account deactivated
    since go under « À prendre », the forms that still name it can be saved,
    and who may set an owner may list the candidates."""
    from app.features.user import crud as user_crud
    from tests.scope_helpers import group

    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    room = await _room(client, admin, "B12")
    a = await _machine(db_session, "A", first_seen_days_ago=100, room_id=room)
    r = await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    assert r.status_code == 200, r.text
    settings_resp = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"maintenance_default_owner_id": tech_id},
    )
    assert settings_resp.status_code == 200, settings_resp.text
    check = await client.post(
        f"/api/v1/machines/{a}/check", headers=admin, json={"assigned_to_id": tech_id}
    )
    assert check.status_code == 201, check.text

    marie = await user_crud.get_by_email(db_session, "tech@test.local")
    assert marie is not None
    marie.is_active = False
    db_session.add(marie)
    await db_session.commit()

    nobody = (
        await client.get(
            "/api/v1/maintenance/due", headers=admin, params={"owner": "none"}
        )
    ).json()
    assert [r["name"] for r in nobody["rooms"]] == ["B12"]
    to_take = (
        await client.get(
            "/api/v1/checks", headers=admin, params={"assigned_to": "none"}
        )
    ).json()
    assert to_take["total"] == 1

    # The forms that still carry her save their other fields.
    r = await client.patch(
        f"/api/v1/rooms/{room}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id, "maintenance_cycle_days": 60},
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={
            "maintenance_default_owner_id": tech_id,
            "maintenance_default_cycle_days": 120,
        },
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"/api/v1/checks/{check.json()['id']}",
        headers=admin,
        json={"assigned_to_id": tech_id, "instructions": "Écran qui scintille"},
    )
    assert r.status_code == 200, r.text
    # Choosing her anew is still refused.
    r = await client.patch(
        f"/api/v1/machines/{a}/maintenance",
        headers=admin,
        json={"maintenance_owner_id": tech_id},
    )
    assert r.status_code == 404

    # maintenance:write without check:read lists the candidates.
    g = await group(
        db_session,
        "Maintenance seule",
        ["machine:read", "maintenance:read", "maintenance:write", "room:read"],
        None,
    )
    upkeep, _ = await _user(client, db_session, "upkeep@test.local", [g.id])
    listed = await client.get("/api/v1/checks/assignable-users", headers=upkeep)
    assert listed.status_code == 200, listed.text
    # Someone holding none of the three still cannot.
    bare = await group(db_session, "Rien", ["machine:read"], None)
    nothing, _ = await _user(client, db_session, "bare@test.local", [bare.id])
    assert (
        await client.get("/api/v1/checks/assignable-users", headers=nothing)
    ).status_code == 403


async def test_recording_a_visit_writes_the_journal_and_moves_the_cycle(
    client, db_session
):
    admin, _ = await _admin(client, db_session)
    tech, _ = await _tech(client, db_session)
    room = await _room(client, admin, "B12")
    a = await _machine(db_session, "A", first_seen_days_ago=100, room_id=room)
    b = await _machine(db_session, "B", first_seen_days_ago=100, room_id=room)
    assert (await _detail(client, admin, a))["maintenance_state"] == "overdue"

    resp = await client.post(
        "/api/v1/maintenance",
        headers=tech,
        json={
            "room_id": room,
            "note": "Salle dépoussiérée, un clavier changé",
            "items": [{"machine_id": a, "note": "Clavier changé"}, {"machine_id": b}],
        },
    )
    assert resp.status_code == 201, resp.text
    visit = resp.json()
    assert visit["room_name"] == "B12" and visit["machine_count"] == 2
    assert {i["hostname"]: i["note"] for i in visit["items"]} == {
        "A": "Clavier changé",
        "B": None,
    }

    detail = await _detail(client, admin, a)
    assert detail["maintenance_state"] == "ok"
    assert detail["last_maintenance_at"] is not None
    journal = (
        await client.get(f"/api/v1/machines/{a}/interventions", headers=admin)
    ).json()
    assert journal["items"][0]["kind"] == "maintenance"
    assert journal["items"][0]["title"] == "Maintenance — B12"
    assert journal["items"][0]["note"] == "Clavier changé"
    assert journal["items"][0]["maintenance_id"] == visit["id"]

    # The session reads back with its postes; the room and the poste list it.
    got = (await client.get(f"/api/v1/maintenance/{visit['id']}", headers=admin)).json()
    assert got["note"] == "Salle dépoussiérée, un clavier changé"
    by_room = (
        await client.get("/api/v1/maintenance", headers=admin, params={"room_id": room})
    ).json()
    assert by_room["total"] == 1 and by_room["items"][0]["machine_count"] == 2
    by_machine = (
        await client.get("/api/v1/maintenance", headers=admin, params={"machine_id": b})
    ).json()
    assert by_machine["total"] == 1

    # A backdated visit does not move the cycle back.
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    resp = await client.post(
        "/api/v1/maintenance",
        headers=tech,
        json={"performed_at": old, "items": [{"machine_id": a}]},
    )
    assert resp.status_code == 201
    assert (await _detail(client, admin, a))["maintenance_state"] == "ok"
    rooms = (await client.get("/api/v1/rooms", headers=admin)).json()
    assert rooms[0]["maintenance_overdue"] == 0


async def test_the_cycle_follows_the_journal(client, db_session):
    """Audit B06, B17: an entry typed in the journal moves the cycle, a
    deleted or redated one moves it back, and a date in the future is
    refused — at the visit as in the journal."""
    admin, _ = await _admin(client, db_session)
    a = await _machine(db_session, "A", first_seen_days_ago=100)
    assert (await _detail(client, admin, a))["maintenance_state"] == "overdue"

    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    refused = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={"performed_at": future, "items": [{"machine_id": a}]},
    )
    assert refused.status_code == 422
    refused = await client.post(
        f"/api/v1/machines/{a}/interventions",
        headers=admin,
        json={"kind": "maintenance", "performed_at": future},
    )
    assert refused.status_code == 422
    assert "performed_at" in refused.text

    # Typed in the journal: the cycle moves.
    entry = await client.post(
        f"/api/v1/machines/{a}/interventions",
        headers=admin,
        json={"kind": "maintenance", "title": "Nettoyage"},
    )
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["id"]
    assert (await _detail(client, admin, a))["maintenance_state"] == "ok"

    # Redated far back: the cycle moves back with it.
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    redated = await client.patch(
        f"/api/v1/interventions/{entry_id}",
        headers=admin,
        json={"performed_at": old},
    )
    assert redated.status_code == 200, redated.text
    assert (await _detail(client, admin, a))["maintenance_state"] == "overdue"
    redated = await client.patch(
        f"/api/v1/interventions/{entry_id}",
        headers=admin,
        json={"performed_at": future},
    )
    assert redated.status_code == 422

    # A visit, then its line deleted: back to what the journal says.
    visit = await client.post(
        "/api/v1/maintenance", headers=admin, json={"items": [{"machine_id": a}]}
    )
    assert visit.status_code == 201
    assert (await _detail(client, admin, a))["maintenance_state"] == "ok"
    line = visit.json()["items"][0]["intervention_id"]
    gone = await client.delete(f"/api/v1/interventions/{line}", headers=admin)
    assert gone.status_code == 204
    detail = await _detail(client, admin, a)
    assert detail["maintenance_state"] == "overdue"
    assert detail["last_maintenance_at"].startswith(old[:10])

    # Nothing left in the journal: no last maintenance at all.
    await client.delete(f"/api/v1/interventions/{entry_id}", headers=admin)
    assert (await _detail(client, admin, a))["last_maintenance_at"] is None


async def test_a_future_line_never_becomes_a_maintenance(client, db_session):
    """Audit B06, B17 (T16): a check closed in the future is refused, and a
    journal line already dated in the future cannot be turned into a
    maintenance by changing its kind alone — the cycle would be pushed out."""
    from app.features.intervention.models import Intervention

    admin, _ = await _admin(client, db_session)
    a = await _machine(db_session, "A", first_seen_days_ago=100)
    future = datetime.now(UTC) + timedelta(days=400)

    check = await client.post(f"/api/v1/machines/{a}/check", headers=admin, json={})
    assert check.status_code == 201, check.text
    refused = await client.post(
        f"/api/v1/checks/{check.json()['id']}/close",
        headers=admin,
        json={"closed_at": future.isoformat()},
    )
    assert refused.status_code == 422
    assert "closed_at" in refused.text
    # Still open, nothing written in the journal.
    journal = await client.get(f"/api/v1/machines/{a}/interventions", headers=admin)
    assert journal.json()["total"] == 0

    # A line dated in the future from before the fix (or written directly).
    line = Intervention(
        machine_id=uuid.UUID(a),
        kind="verification",
        performed_by="admin@test.local",
        performed_at=future,
    )
    db_session.add(line)
    await db_session.commit()
    await db_session.refresh(line)
    refused = await client.patch(
        f"/api/v1/interventions/{line.id}",
        headers=admin,
        json={"kind": "maintenance"},
    )
    assert refused.status_code == 422
    body = refused.json()["error"]
    assert body["code"] == "request.validation_error"
    assert body["details"]["errors"][0]["loc"] == ["body", "performed_at"]
    detail = await _detail(client, admin, a)
    assert detail["last_maintenance_at"] is None
    assert detail["maintenance_state"] == "overdue"

    # Redated to the past in the same request: accepted, the cycle follows.
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    ok = await client.patch(
        f"/api/v1/interventions/{line.id}",
        headers=admin,
        json={"kind": "maintenance", "performed_at": past},
    )
    assert ok.status_code == 200, ok.text
    assert (await _detail(client, admin, a))["maintenance_state"] == "ok"


async def test_list_filters_and_sorts_on_maintenance(client, db_session):
    admin, _ = await _admin(client, db_session)
    a = await _machine(db_session, "A", first_seen_days_ago=100)
    b = await _machine(db_session, "B", first_seen_days_ago=80)
    c = await _machine(db_session, "C", first_seen_days_ago=1)
    x = await _machine(db_session, "X", first_seen_days_ago=500)
    await client.patch(
        f"/api/v1/machines/{x}/maintenance",
        headers=admin,
        json={"maintenance_cycle_days": 0},
    )

    async def hosts(**params):
        resp = await client.get("/api/v1/machines", headers=admin, params=params)
        assert resp.status_code == 200, resp.text
        return [r["hostname"] for r in resp.json()["items"]]

    assert await hosts(maintenance_state="overdue") == ["A"]
    assert await hosts(maintenance_state="due_soon") == ["B"]
    assert await hosts(maintenance_state="ok") == ["C"]
    assert await hosts(maintenance_state="excluded") == ["X"]
    assert await hosts(sort_by="maintenance_due_at", sort_desc="false") == [
        "A",
        "B",
        "C",
        "X",
    ]
    stats = (await client.get("/api/v1/stats/overview", headers=admin)).json()
    assert stats["machines_maintenance_overdue"] == 1
    assert stats["machines_maintenance_due_soon"] == 1
    resp = await client.get(
        "/api/v1/machines/export.csv",
        headers=admin,
        params={"columns": "hostname,maintenance_state,maintenance_due_at"},
    )
    assert resp.status_code == 200, resp.text
    assert "En retard" in resp.text and "Exclu" in resp.text
    del a, b, c


async def test_settings_are_admin_material_and_reject_a_dead_owner(client, db_session):
    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    assert (await client.get("/api/v1/settings", headers=tech)).status_code == 403
    got = (await client.get("/api/v1/settings", headers=admin)).json()
    assert got["maintenance_default_cycle_days"] == 90
    assert got["env_default_cycle_days"] == 90
    assert got["room_source"] == "manual"
    # The environment overview rides along: grouped, keyed by variable name,
    # and never a secret.
    groups = {
        g["label"]: {i["key"]: i["value"] for i in g["items"]}
        for g in got["environment"]
    }
    assert groups["Salles"]["ROOM_SOURCE"].startswith("manual")
    assert groups["Postes et seuils"]["SIGNATURE_MAX_AGE_DAYS"] == "3"
    listed = {key for items in groups.values() for key in items}
    assert not listed & {
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "MAILGUN_API_KEY",
        "SMTP_PASSWORD",
    }
    resp = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={"maintenance_default_owner_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    # Read-only reads what is due, writes nothing.
    from app.features.user.permissions import BuiltinGroup

    ro, _ = await _user(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    assert (await client.get("/api/v1/maintenance/due", headers=ro)).status_code == 200
    m = await _machine(db_session)
    resp = await client.post(
        "/api/v1/maintenance", headers=ro, json={"items": [{"machine_id": m}]}
    )
    assert resp.status_code == 403
    resp = await client.patch(
        f"/api/v1/machines/{m}/maintenance",
        headers=ro,
        json={"maintenance_cycle_days": 10},
    )
    assert resp.status_code == 403
    # A technician transfers an owner: the same write, audited.
    resp = await client.patch(
        f"/api/v1/machines/{m}/maintenance",
        headers=tech,
        json={"maintenance_owner_id": tech_id},
    )
    assert resp.status_code == 200


async def test_a_skipped_poste_keeps_why_and_excluded_ones_are_not_listed(
    client, db_session
):
    """Audit U20: the reason a poste was not done lands in its journal, its
    cycle untouched. Audit B09: an excluded poste is counted, not listed."""
    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "B12")
    a = await _machine(db_session, "A", first_seen_days_ago=100, room_id=room)
    b = await _machine(db_session, "B", first_seen_days_ago=100, room_id=room)
    server = await _machine(db_session, "SRV", first_seen_days_ago=100, room_id=room)
    r = await client.patch(
        f"/api/v1/machines/{server}/maintenance",
        headers=admin,
        json={"maintenance_cycle_days": 0},
    )
    assert r.status_code == 200, r.text

    due = (await client.get("/api/v1/maintenance/due", headers=admin)).json()
    (entry,) = due["rooms"]
    assert sorted(m["hostname"] for m in entry["machines"]) == ["A", "B"]
    assert entry["excluded"] == 1

    resp = await client.post(
        "/api/v1/maintenance",
        headers=admin,
        json={
            "room_id": room,
            "items": [{"machine_id": a}],
            "skipped": [{"machine_id": b, "note": "Absent de la salle"}],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["machine_count"] == 1
    journal = (
        await client.get(f"/api/v1/machines/{b}/interventions", headers=admin)
    ).json()
    (line,) = journal["items"]
    assert line["kind"] == "other" and line["note"] == "Absent de la salle"
    assert line["title"] == "Maintenance non faite — B12"
    assert (await _detail(client, admin, b))["maintenance_state"] == "overdue"
