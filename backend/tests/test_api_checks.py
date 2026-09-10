"""Verification requests: asked, assigned, listed as tasks, closed with a note
that writes the journal — and one open per poste.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid

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


async def _machine(db_session, hostname="PC-1"):
    from app.features.machine.models import Machine

    m = Machine(machine_uuid=str(uuid.uuid4()), hostname=hostname)
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return str(m.id)


async def _ask(client, headers, machine_id, **body):
    resp = await client.post(
        f"/api/v1/machines/{machine_id}/check", headers=headers, json=body
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_ask_assign_and_close_writes_the_journal(client, db_session):
    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    m = await _machine(db_session)

    check = await _ask(
        client,
        admin,
        m,
        assigned_to_id=tech_id,
        instructions="Vérifier le câble réseau",
    )
    assert check["requested_by"] == "admin@test.local"
    assert check["assigned_to"] == {"id": tech_id, "name": "Marie"}
    assert check["machine"]["hostname"] == "PC-1"

    # The fiche and the list carry it.
    detail = (await client.get(f"/api/v1/machines/{m}", headers=admin)).json()
    assert detail["check_open"] is True
    assert detail["check_assigned_to"] == "Marie"
    assert detail["open_check"]["instructions"] == "Vérifier le câble réseau"
    rows = (
        await client.get(
            "/api/v1/machines", headers=admin, params={"check_open": "true"}
        )
    ).json()
    assert [r["id"] for r in rows["items"]] == [m]
    assert rows["items"][0]["check_assigned_to"] == "Marie"

    # It is the technician's task.
    mine = (
        await client.get("/api/v1/checks", headers=tech, params={"assigned_to": "me"})
    ).json()
    assert mine["total"] == 1

    # A second request on the same poste is refused while one is open.
    resp = await client.post(f"/api/v1/machines/{m}/check", headers=admin, json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "check.already_open"

    # Closed with a note: the request keeps it, the journal gets it.
    resp = await client.post(
        f"/api/v1/checks/{check['id']}/close",
        headers=tech,
        json={"note": "Câble remplacé"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["closed_by"] == "tech@test.local"
    assert resp.json()["closing_note"] == "Câble remplacé"
    detail = (await client.get(f"/api/v1/machines/{m}", headers=admin)).json()
    assert detail["check_open"] is False and detail["open_check"] is None
    journal = (
        await client.get(f"/api/v1/machines/{m}/interventions", headers=admin)
    ).json()
    assert journal["total"] == 1
    assert journal["items"][0]["kind"] == "verification"
    assert journal["items"][0]["note"] == "Câble remplacé"
    assert journal["items"][0]["check_id"] == check["id"]
    # Closing twice is refused; the history keeps the closed one.
    resp = await client.post(
        f"/api/v1/checks/{check['id']}/close", headers=tech, json={}
    )
    assert resp.status_code == 409
    history = (await client.get(f"/api/v1/machines/{m}/checks", headers=admin)).json()
    assert history["total"] == 1 and history["items"][0]["closed_at"]
    # And a new one can be opened.
    await _ask(client, admin, m)


async def test_task_lists_mine_unassigned_and_all(client, db_session):
    admin, admin_id = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    a, b, c = [await _machine(db_session, f"PC-{i}") for i in "ABC"]
    await _ask(client, admin, a, assigned_to_id=tech_id)
    await _ask(client, admin, b)
    await _ask(client, admin, c, assigned_to_id=admin_id)

    async def hosts(headers, **params):
        resp = await client.get("/api/v1/checks", headers=headers, params=params)
        assert resp.status_code == 200, resp.text
        return sorted(i["machine"]["hostname"] for i in resp.json()["items"])

    assert await hosts(tech, assigned_to="me") == ["PC-A"]
    assert await hosts(tech, assigned_to="none") == ["PC-B"]
    assert await hosts(tech) == ["PC-A", "PC-B", "PC-C"]
    assert await hosts(tech, assigned_to=admin_id) == ["PC-C"]
    resp = await client.get(
        "/api/v1/checks", headers=tech, params={"assigned_to": "bob"}
    )
    assert resp.status_code == 422

    # Reassigned to nobody, then reworded.
    check_id = (
        await client.get("/api/v1/checks", headers=tech, params={"assigned_to": "me"})
    ).json()["items"][0]["id"]
    resp = await client.patch(
        f"/api/v1/checks/{check_id}",
        headers=admin,
        json={"assigned_to_id": None, "instructions": "Regarder l'écran"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned_to"] is None
    assert resp.json()["instructions"] == "Regarder l'écran"
    assert await hosts(tech, assigned_to="none") == ["PC-A", "PC-B"]


async def test_bulk_skips_postes_already_asked(client, db_session):
    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    a, b = await _machine(db_session, "A"), await _machine(db_session, "B")
    await _ask(client, admin, a)
    resp = await client.post(
        "/api/v1/checks/bulk",
        headers=admin,
        json={
            "machine_ids": [a, b],
            "assigned_to_id": tech_id,
            "instructions": "Tour de salle",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"created": 1, "skipped": 1}
    resp = await client.post(
        "/api/v1/checks/bulk", headers=admin, json={"machine_ids": [str(uuid.uuid4())]}
    )
    assert resp.status_code == 404


async def test_assignable_users_and_permissions(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin, _ = await _admin(client, db_session)
    tech, _ = await _tech(client, db_session)
    ro, _ = await _user(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    m = await _machine(db_session)

    names = sorted(
        u["name"]
        for u in (
            await client.get("/api/v1/checks/assignable-users", headers=tech)
        ).json()
    )
    assert names == ["Marie", "admin@test.local", "ro@test.local"]
    # A deactivated account cannot be assigned.
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    ro_id = next(u["id"] for u in users if u["email"] == "ro@test.local")
    await client.patch(
        f"/api/v1/users/{ro_id}", headers=admin, json={"is_active": False}
    )
    resp = await client.post(
        f"/api/v1/machines/{m}/check", headers=tech, json={"assigned_to_id": ro_id}
    )
    assert resp.status_code == 404

    # Read-only reads the lists but asks for nothing.
    ro2, _ = await _user(client, db_session, "ro2@test.local", [BuiltinGroup.READONLY])
    assert (await client.get("/api/v1/checks", headers=ro2)).status_code == 200
    resp = await client.post(f"/api/v1/machines/{m}/check", headers=ro2, json={})
    assert resp.status_code == 403


async def test_merge_keeps_one_open_request(client, db_session):
    admin, _ = await _admin(client, db_session)
    kept, dup = await _machine(db_session, "PC-1"), await _machine(db_session, "PC-1")
    await _ask(client, admin, kept, instructions="sur le conservé")
    await _ask(client, admin, dup, instructions="sur le doublon")
    resp = await client.post(
        f"/api/v1/machines/{kept}/merge", headers=admin, json={"source_id": dup}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["open_check"]["instructions"] == "sur le conservé"
    history = (
        await client.get(f"/api/v1/machines/{kept}/checks", headers=admin)
    ).json()
    assert history["total"] == 2
    closed = next(c for c in history["items"] if c["closed_at"])
    assert closed["closed_by"] == "system"


async def test_dashboard_counts_open_requests_and_export_carries_them(
    client, db_session
):
    admin, _ = await _admin(client, db_session)
    tech, tech_id = await _tech(client, db_session)
    m = await _machine(db_session)
    await _ask(client, admin, m, assigned_to_id=tech_id, instructions="Écran")
    stats = (await client.get("/api/v1/stats/overview", headers=admin)).json()
    assert stats["open_checks"] == 1
    resp = await client.get(
        "/api/v1/machines/export.csv",
        headers=admin,
        params={"columns": "hostname,check_open,check_assigned_to,check_instructions"},
    )
    assert resp.status_code == 200
    assert "Oui" in resp.text and "Marie" in resp.text and "Écran" in resp.text
