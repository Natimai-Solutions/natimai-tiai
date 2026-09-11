"""The journal of a poste: interventions added by hand, read newest first,
edited and deleted with a trace, and carried over by a merge.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import uuid

STRONG = "correct-horse-battery"


async def _user(client, db_session, email, groups):
    from app.features.user import crud

    await crud.create_user(db_session, email=email, password=STRONG, groups=groups)
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await _user(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])


async def _machine(db_session, hostname="PC-1"):
    from app.features.machine.models import Machine

    m = Machine(machine_uuid=str(uuid.uuid4()), hostname=hostname)
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return str(m.id)


async def _add(client, headers, machine_id, **body):
    resp = await client.post(
        f"/api/v1/machines/{machine_id}/interventions", headers=headers, json=body
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _journal(client, headers, machine_id):
    resp = await client.get(
        f"/api/v1/machines/{machine_id}/interventions", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_journal_reads_newest_first_and_accepts_backdating(client, db_session):
    admin = await _admin(client, db_session)
    m = await _machine(db_session)
    old = await _add(
        client,
        admin,
        m,
        kind="maintenance",
        title="  Maintenance annuelle ",
        note="Dépoussiérage",
        performed_at="2025-03-01T08:00:00Z",
    )
    assert old["title"] == "Maintenance annuelle"
    assert old["performed_by"] == "admin@test.local"
    assert old["performed_at"].startswith("2025-03-01T08:00:00")
    new = await _add(client, admin, m, kind="incident", title="Écran noir")
    journal = await _journal(client, admin, m)
    assert journal["total"] == 2
    assert [i["id"] for i in journal["items"]] == [new["id"], old["id"]]
    # Empty strings land as nothing, not as "".
    blank = await _add(client, admin, m, kind="other", title="   ", note="")
    assert blank["title"] is None and blank["note"] is None


async def test_kind_is_a_closed_list(client, db_session):
    admin = await _admin(client, db_session)
    m = await _machine(db_session)
    resp = await client.post(
        f"/api/v1/machines/{m}/interventions", headers=admin, json={"kind": "party"}
    )
    assert resp.status_code == 422
    resp = await client.post(
        f"/api/v1/machines/{uuid.uuid4()}/interventions",
        headers=admin,
        json={"kind": "other"},
    )
    assert resp.status_code == 404


async def test_edit_by_another_and_delete_leave_a_trace(client, db_session):
    from sqlmodel import select

    from app.features.audit.models import AuditEntry
    from app.features.user.permissions import BuiltinGroup

    admin = await _admin(client, db_session)
    tech = await _user(client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN])
    m = await _machine(db_session)
    entry = await _add(client, tech, m, kind="software_install", title="LibreOffice")

    # The author edits: no audit entry — the journal shows the author.
    resp = await client.patch(
        f"/api/v1/interventions/{entry['id']}", headers=tech, json={"note": "24.2"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["note"] == "24.2"
    # Someone else edits: traced.
    resp = await client.patch(
        f"/api/v1/interventions/{entry['id']}",
        headers=admin,
        json={"kind": "upgrade", "title": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "upgrade"
    assert resp.json()["title"] is None
    assert resp.json()["performed_by"] == "tech@test.local"

    resp = await client.delete(f"/api/v1/interventions/{entry['id']}", headers=admin)
    assert resp.status_code == 204
    assert (await _journal(client, admin, m))["total"] == 0
    actions = (
        await db_session.exec(select(AuditEntry.action).order_by(AuditEntry.at))
    ).all()
    assert actions == ["intervention.update", "intervention.delete"]


async def test_readonly_reads_but_cannot_write(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await _admin(client, db_session)
    ro = await _user(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    m = await _machine(db_session)
    entry = await _add(client, admin, m, kind="other")
    assert (await _journal(client, ro, m))["total"] == 1
    resp = await client.post(
        f"/api/v1/machines/{m}/interventions", headers=ro, json={"kind": "other"}
    )
    assert resp.status_code == 403
    resp = await client.delete(f"/api/v1/interventions/{entry['id']}", headers=ro)
    assert resp.status_code == 403


async def test_merge_carries_the_journal_over(client, db_session):
    admin = await _admin(client, db_session)
    kept = await _machine(db_session, "PC-1")
    dup = await _machine(db_session, "PC-1")
    await _add(client, admin, dup, kind="incident", title="Sur le doublon")
    await _add(client, admin, kept, kind="other", title="Sur le conservé")
    resp = await client.post(
        f"/api/v1/machines/{kept}/merge", headers=admin, json={"source_id": dup}
    )
    assert resp.status_code == 200, resp.text
    titles = sorted(i["title"] for i in (await _journal(client, admin, kept))["items"])
    assert titles == ["Sur le conservé", "Sur le doublon"]
