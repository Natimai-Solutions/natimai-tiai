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
