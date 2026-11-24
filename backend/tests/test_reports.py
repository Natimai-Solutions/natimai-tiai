"""Reports (C4) and the richer verifications (require TIAI_TEST_DATABASE_URL):
priority, category and due date; the public form a label opens — off by
default, bounded, telling nothing about the poste; the queue, its scope and
its triage into verifications."""

import uuid
from datetime import date, timedelta

from sqlmodel import col, select

from tests.scope_helpers import machine, two_sites
from tests.test_api_maintenance import _admin, _tech


async def _label(client, headers, machine_id):
    resp = await client.put(
        f"/api/v1/machines/{machine_id}/asset", headers=headers, json={}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["public_token"]


async def _open_form(client, headers):
    resp = await client.patch(
        "/api/v1/settings", headers=headers, json={"reports_enabled": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reports_enabled"] is True


def _report(**over):
    return {"category": "hardware", "text": "L'écran reste noir", **over}


# --- Verifications: priority, category, due date ----------------------------------


async def test_checks_carry_priority_category_and_due_date(client, db_session):
    headers, _ = await _admin(client, db_session)
    ids = {}
    for name, body in (
        ("LOW", {"priority": "low"}),
        ("LATE", {"due_date": str(date.today() + timedelta(days=9))}),
        ("SOON", {"due_date": str(date.today() + timedelta(days=1))}),
        ("URGENT", {"priority": "high", "category": "network"}),
        ("PLAIN", {}),
    ):
        m = await machine(db_session, name)
        resp = await client.post(
            f"/api/v1/machines/{m.id}/check", headers=headers, json=body
        )
        assert resp.status_code == 201, resp.text
        ids[name] = resp.json()["id"]
    body = (await client.get("/api/v1/checks", headers=headers)).json()
    order = [c["machine"]["hostname"] for c in body["items"]]
    # High first; then the nearest due; then the oldest asked; low last.
    assert order == ["URGENT", "SOON", "LATE", "PLAIN", "LOW"]
    urgent = next(c for c in body["items"] if c["machine"]["hostname"] == "URGENT")
    assert (urgent["priority"], urgent["category"]) == ("high", "network")

    resp = await client.patch(
        f"/api/v1/checks/{ids['LOW']}", headers=headers, json={"priority": "high"}
    )
    assert resp.json()["priority"] == "high"
    resp = await client.patch(
        f"/api/v1/checks/{ids['LOW']}", headers=headers, json={"priority": None}
    )
    assert resp.status_code == 422
    resp = await client.patch(
        f"/api/v1/checks/{ids['LOW']}", headers=headers, json={"category": "nope"}
    )
    assert resp.status_code == 422


# --- The public form ----------------------------------------------------------------


async def test_the_form_is_off_by_default_and_says_nothing(client, db_session):
    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    token = await _label(client, headers, m.id)
    resp = await client.get(f"/api/v1/public/reports/{token}")
    assert resp.json() == {"enabled": False, "categories": []}
    # Off: the same answer for a label that does not exist.
    resp = await client.get("/api/v1/public/reports/nope")
    assert resp.json() == {"enabled": False, "categories": []}
    resp = await client.post(f"/api/v1/public/reports/{token}", json=_report())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "report.disabled"


async def test_a_report_is_left_without_an_account(client, db_session):
    from app.features.audit.models import AuditEntry
    from app.features.report.models import Report

    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-SECRET")
    token = await _label(client, headers, m.id)
    await _open_form(client, headers)

    resp = await client.get(f"/api/v1/public/reports/{token}")
    body = resp.json()
    assert body["enabled"] is True and "hardware" in body["categories"]
    assert "PC-SECRET" not in resp.text
    resp = await client.get("/api/v1/public/reports/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "report.label.invalid"

    resp = await client.post(
        f"/api/v1/public/reports/{token}",
        json=_report(contact="  M. Teva, salle B12 ", language="fr"),
    )
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}
    [report] = (await db_session.exec(select(Report))).all()
    assert report.machine_id == m.id
    assert report.contact == "M. Teva, salle B12"
    assert report.status == "new"
    [entry] = (
        await db_session.exec(
            select(AuditEntry).where(col(AuditEntry.action) == "report.create")
        )
    ).all()
    assert entry.actor.startswith("report:")

    for bad in (
        _report(text="x"),
        _report(text="x" * 2001),
        _report(category="nope"),
        _report(contact="x" * 201),
    ):
        resp = await client.post(f"/api/v1/public/reports/{token}", json=bad)
        assert resp.status_code == 422, bad


async def test_the_form_is_bounded_per_address_and_per_label(client, db_session):
    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    token = await _label(client, headers, m.id)
    await _open_form(client, headers)
    statuses = [
        (
            await client.post(f"/api/v1/public/reports/{token}", json=_report())
        ).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [202] * 10
    assert statuses[10] == 429


async def test_a_renewed_label_no_longer_reports(client, db_session):
    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    token = await _label(client, headers, m.id)
    await _open_form(client, headers)
    asset = (await client.get(f"/api/v1/machines/{m.id}/asset", headers=headers)).json()
    await client.post(f"/api/v1/assets/{asset['id']}/token", headers=headers)
    resp = await client.post(f"/api/v1/public/reports/{token}", json=_report())
    assert resp.status_code == 404


# --- The queue ------------------------------------------------------------------------


async def _leave(client, token, **over):
    resp = await client.post(f"/api/v1/public/reports/{token}", json=_report(**over))
    assert resp.status_code == 202, resp.text


async def test_the_queue_is_read_within_the_scope(client, db_session):
    sites = await two_sites(client, db_session)
    await _open_form(client, sites.admin)
    for m in (sites.a, sites.b):
        await _leave(client, await _label(client, sites.admin, m.id))
    body = (await client.get("/api/v1/reports", headers=sites.admin)).json()
    assert body["total"] == 2 and body["new"] == 2 and body["enabled"] is True
    body = (await client.get("/api/v1/reports", headers=sites.scoped)).json()
    assert [r["subject"] for r in body["items"]] == ["PC-A"]
    assert body["new"] == 1
    tech, _ = await _tech(client, db_session)
    resp = await client.get("/api/v1/reports", headers=tech)
    assert resp.status_code == 403


async def test_triage_into_a_verification(client, db_session):
    from app.features.check.models import MachineCheck

    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    token = await _label(client, headers, m.id)
    await _open_form(client, headers)
    await _leave(client, token, category="printing", text="L'imprimante bourre")
    await _leave(client, token, text="Toujours en panne")
    first, second = (await client.get("/api/v1/reports", headers=headers)).json()[
        "items"
    ]

    resp = await client.post(
        f"/api/v1/reports/{first['id']}/convert",
        headers=headers,
        json={"priority": "high", "due_date": str(date.today() + timedelta(days=2))},
    )
    assert resp.status_code == 200, resp.text
    converted = resp.json()
    assert converted["status"] == "converted" and converted["check_id"]
    check = await db_session.get(MachineCheck, uuid.UUID(converted["check_id"]))
    assert (check.priority, check.category) == ("high", "printing")
    assert check.instructions == "L'imprimante bourre"
    checks = (await client.get("/api/v1/checks", headers=headers)).json()["items"]
    assert checks[0]["report_id"] == first["id"]

    # The second: a verification is open — convert refuses, attach links.
    resp = await client.post(
        f"/api/v1/reports/{second['id']}/convert", headers=headers, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "check.already_open"
    queued = (await client.get("/api/v1/reports", headers=headers)).json()["items"]
    assert queued[0]["open_check_id"] == converted["check_id"]
    resp = await client.post(f"/api/v1/reports/{second['id']}/attach", headers=headers)
    assert resp.json()["status"] == "attached"
    assert resp.json()["check_id"] == converted["check_id"]
    # Handled once.
    resp = await client.post(f"/api/v1/reports/{second['id']}/attach", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "report.already_handled"
    body = (await client.get("/api/v1/reports", headers=headers)).json()
    assert body["new"] == 0
    handled = (
        await client.get(
            "/api/v1/reports", headers=headers, params={"state": "handled"}
        )
    ).json()
    assert handled["total"] == 2


async def test_close_reject_and_equipment(client, db_session):
    from app.features.audit.models import AuditEntry

    headers, _ = await _admin(client, db_session)
    resp = await client.post("/api/v1/rooms", headers=headers, json={"name": "A101"})
    room = resp.json()["id"]
    resp = await client.post(
        "/api/v1/assets",
        headers=headers,
        json={"name": "Vidéoprojecteur A101", "kind": "projector", "room_id": room},
    )
    token = resp.json()["public_token"]
    await _open_form(client, headers)
    await _leave(client, token, text="Pas d'image")
    await _leave(client, token, text="Encore")
    first, second = (await client.get("/api/v1/reports", headers=headers)).json()[
        "items"
    ]
    assert first["subject"] == "Vidéoprojecteur A101" and first["room_name"] == "A101"
    resp = await client.post(
        f"/api/v1/reports/{first['id']}/convert", headers=headers, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "report.no_machine"
    resp = await client.post(
        f"/api/v1/reports/{first['id']}/close",
        headers=headers,
        json={"note": "Lampe changée"},
    )
    assert resp.json()["status"] == "closed"
    assert resp.json()["handling_note"] == "Lampe changée"
    resp = await client.post(
        f"/api/v1/reports/{second['id']}/close",
        headers=headers,
        params={"reject": "true"},
        json={},
    )
    assert resp.json()["status"] == "rejected"
    actions = {
        e.action
        for e in (
            await db_session.exec(
                select(AuditEntry).where(col(AuditEntry.resource_type) == "report")
            )
        ).all()
    }
    assert {"report.create", "report.close", "report.reject"} <= actions


async def test_turning_into_a_verification_needs_check_write(client, db_session):
    from tests.scope_helpers import account, group

    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    token = await _label(client, headers, m.id)
    await _open_form(client, headers)
    await _leave(client, token)
    [report] = (await client.get("/api/v1/reports", headers=headers)).json()["items"]
    sorters = await group(
        db_session, "Tri", {"report:read", "report:write", "machine:read"}, None
    )
    sorter = await account(client, db_session, "tri@test.local", [sorters.id])
    resp = await client.post(
        f"/api/v1/reports/{report['id']}/convert", headers=sorter, json={}
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/reports/{report['id']}/close", headers=sorter, json={}
    )
    assert resp.status_code == 200


async def test_merge_and_purge(client, db_session):
    from datetime import UTC, datetime

    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine
    from app.features.report import crud as report_crud
    from app.features.report.models import Report

    headers, _ = await _admin(client, db_session)
    dup = await machine(db_session, "DUP")
    kept = await machine(db_session, "KEPT")
    db_session.add(Report(machine_id=dup.id, category="other", text="x y z"))
    db_session.add(
        Report(
            machine_id=kept.id,
            category="other",
            text="old",
            contact="someone",
            status="closed",
            handled_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()
    await machine_crud.merge_into(
        db_session,
        target=await db_session.get(Machine, kept.id),
        source=await db_session.get(Machine, dup.id),
    )
    await db_session.commit()
    assert (
        await report_crud.purge_before(db_session, datetime(2021, 1, 1, tzinfo=UTC))
        == 1
    )
    db_session.expire_all()
    [left] = (await db_session.exec(select(Report))).all()
    assert left.machine_id == kept.id and left.status == "new"
    assert headers


async def test_a_report_sorted_by_three_accounts_at_once_is_handled_once(
    client, db_session
):
    """Close, convert and reject sent together: one wins, the others meet
    « déjà traité » — not three 200 and a report closed with a verification
    opened beside it."""
    import asyncio

    from app.features.audit.models import AuditEntry
    from app.features.check.models import MachineCheck
    from app.features.report.models import Report
    from app.features.user.permissions import BuiltinGroup
    from tests.test_api_maintenance import _user

    headers, _ = await _admin(client, db_session)
    h2, _ = await _user(client, db_session, "a2@test.local", [BuiltinGroup.ADMIN])
    h3, _ = await _user(client, db_session, "a3@test.local", [BuiltinGroup.ADMIN])
    m = await machine(db_session, "PC-1")
    token = await _label(client, headers, m.id)
    await _open_form(client, headers)
    assert (
        await client.post(f"/api/v1/public/reports/{token}", json=_report())
    ).status_code == 202
    [rep] = (await db_session.exec(select(Report))).all()
    rid = rep.id
    # Warm the pool: on cold connections the requests run one after another
    # and the race does not show.
    for _ in range(2):
        await asyncio.gather(
            *[client.get("/api/v1/reports", headers=h) for h in (headers, h2, h3) * 2]
        )
    answers = await asyncio.gather(
        client.post(
            f"/api/v1/reports/{rid}/close", headers=headers, json={"note": "a"}
        ),
        client.post(f"/api/v1/reports/{rid}/convert", headers=h2, json={}),
        client.post(
            f"/api/v1/reports/{rid}/close?reject=true", headers=h3, json={"note": "b"}
        ),
    )
    codes = sorted(a.status_code for a in answers)
    assert codes == [200, 409, 409], codes
    await db_session.refresh(rep)
    checks = (await db_session.exec(select(MachineCheck))).all()
    assert (rep.status == "converted") == (len(checks) == 1)
    handled = [
        e.action
        for e in (await db_session.exec(select(AuditEntry))).all()
        if e.action in ("report.close", "report.reject", "report.convert")
    ]
    assert len(handled) == 1
    # Its reception is filed under the report's own id.
    created = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "report.create")
        )
    ).one()
    assert created.resource_id == str(rid)
