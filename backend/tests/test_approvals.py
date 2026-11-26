"""Two-person approval of mass actions (C10): commands sent by hand.

The threshold, the request in place of the commands (202), duplicates and
the limit per author, who may approve, everything checked again at the
approval and the failures recorded before the answer, rejection,
cancellation, expiry, the list and the badge, the mails, the webhook, the
settings, the merge and the purge (require TIAI_TEST_DATABASE_URL)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import col, select

from app.core.config import settings
from app.features.user.permissions import BuiltinGroup
from app.features.user.scope import Scope
from tests.scope_helpers import SITE_A, SITE_B, STRONG, account, group, machine

API = "/api/v1/approvals"
RISKY = {
    "command:execute",
    "command:read",
    "risky_command:execute",
    "machine:read",
}


@pytest.fixture
def mail(monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key")
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test")
    monkeypatch.setattr(settings, "CONSOLE_BASE_URL", "https://tiai.test")


async def _enable(db_session, threshold=2, ttl_hours=24, enabled=True):
    from app.features.setting import crud

    await crud.set_value(db_session, crud.KEY_APPROVAL_ENABLED, enabled, actor="t")
    await crud.set_value(db_session, crud.KEY_APPROVAL_THRESHOLD, threshold, actor="t")
    await crud.set_value(db_session, crud.KEY_APPROVAL_TTL_HOURS, ttl_hours, actor="t")
    await db_session.commit()


async def _admins(client, db_session):
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    other = await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    return author, other


async def _postes(db_session, n, **fields):
    return [await machine(db_session, f"PC-{i:02}", **fields) for i in range(n)]


async def _send(client, headers, ids, type_="reboot", status=202, **fields):
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": type_, "machine_ids": [str(i) for i in ids], **fields},
    )
    assert resp.status_code == status, resp.text
    return resp.json()


async def _request(db_session, approval_id):
    from app.features.approval.models import ApprovalRequest

    db_session.expire_all()
    return await db_session.get(ApprovalRequest, uuid.UUID(str(approval_id)))


async def _commands(db_session, **where):
    from app.features.command.models import Command

    db_session.expire_all()
    stmt = select(Command)
    for name, value in where.items():
        stmt = stmt.where(getattr(Command, name) == value)
    return list((await db_session.exec(stmt)).all())


async def _audit(db_session, action):
    from app.features.audit.models import AuditEntry

    db_session.expire_all()
    return list(
        (
            await db_session.exec(
                select(AuditEntry)
                .where(col(AuditEntry.action) == action)
                .order_by(col(AuditEntry.at))
            )
        ).all()
    )


async def _outbox(db_session, to=None):
    from app.features.notification.models import EmailOutbox

    db_session.expire_all()
    stmt = select(EmailOutbox)
    if to is not None:
        stmt = stmt.where(col(EmailOutbox.to_address) == to)
    return list((await db_session.exec(stmt)).all())


async def _approve(client, headers, approval_id, status=200, **body):
    resp = await client.post(f"{API}/{approval_id}/approve", headers=headers, json=body)
    assert resp.status_code == status, resp.text
    return resp.json()


def _code(resp):
    return resp.json()["error"]["code"]


async def _hook(db_session):
    from app.features.webhook.models import Webhook

    db_session.add(
        Webhook(
            name="Canal",
            url="https://hooks.example.test/in",
            events=["approval.requested"],
            secret="x",
            created_by="t",
        )
    )
    await db_session.commit()


async def _package(db_session, name="7-Zip", **fields):
    from app.features.package.models import Package

    package = Package(kind="winget", name=name, winget_id="7zip.7zip", **fields)
    package_id = package.id
    db_session.add(package)
    await db_session.commit()
    return package_id


# --- The threshold ----------------------------------------------------------------


async def test_the_threshold_turns_a_send_into_a_request(client, db_session):
    from app.features.approval.models import ApprovalRequestMachine
    from app.main import app

    author, _ = await _admins(client, db_session)
    postes = await _postes(db_session, 4)
    ids = [p.id for p in postes]
    # Off: as before.
    out = await _send(client, author, ids, status=200)
    assert out["count"] == 4 and out.get("approval_id") is None

    await _enable(db_session, threshold=3)
    out = await _send(client, author, ids[:3], type_="shutdown", status=200)
    assert out["count"] == 3
    out = await _send(client, author, ids, type_="wu_reset")
    assert out["count"] == 0 and out["created"] == []
    assert out["pending_approval"] == 4 and out["approval_id"]
    assert out["approval_expires_at"]
    assert await _commands(db_session, type="wu_reset") == []
    request = await _request(db_session, out["approval_id"])
    assert request.status == "pending" and request.machine_count == 4
    assert request.threshold == 3 and request.target == {"kind": "machines"}
    rows = (
        await db_session.exec(
            select(ApprovalRequestMachine).where(
                col(ApprovalRequestMachine.request_id) == request.id
            )
        )
    ).all()
    assert {r.machine_id for r in rows} == set(ids)
    [entry] = await _audit(db_session, "approval.request")
    assert entry.details["count"] == 4 and entry.details["threshold"] == 3
    assert entry.details["target"] == "machines"
    bulk = await _audit(db_session, "command.bulk")
    assert all(e.details["command_type"] != "wu_reset" for e in bulk)

    responses = app.openapi()["paths"]["/api/v1/commands"]["post"]["responses"]
    assert "202" in responses


async def test_what_is_counted(client, db_session):
    from app.features.command.models import Command, CommandType

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    a = await _postes(db_session, 2, location=SITE_A)
    revoked = await machine(db_session, "PC-R", location=SITE_A, token_revoked=True)
    # Two postes plus a revoked one: two counted, sent.
    out = await _send(
        client, author, [*(p.id for p in a), revoked.id], status=200, type_="reboot"
    )
    assert out["count"] == 2 and out["revoked"] == 1

    # « Tout le parc » from an account confined to site A is site A.
    await _postes(db_session, 0)
    for i in range(3):
        await machine(db_session, f"PC-B{i}", location=SITE_B)
    site_a = await group(
        db_session, "Site A", RISKY, Scope(locations=frozenset({SITE_A}))
    )
    tech = await account(client, db_session, "tech@test.local", [site_a.id])
    resp = await client.post(
        "/api/v1/commands",
        headers=tech,
        json={"type": "shutdown", "target_all": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 2

    # A poste that already has the command open still counts.
    third = await machine(db_session, "PC-A3", location=SITE_A)
    db_session.add(
        Command(
            machine_id=third.id,
            type=CommandType.WU_INSTALL,
            created_by="x",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()
    out = await _send(client, author, [a[0].id, a[1].id, third.id], type_="wu_install")
    assert out["pending_approval"] == 3


async def test_which_commands_ask_for_it(client, db_session):
    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 5)]
    out = await _send(client, author, ids, type_="quick_scan", status=200)
    assert out["count"] == 5
    # One poste: never.
    out = await _send(client, author, ids[:1], type_="reboot", status=200)
    assert out["count"] == 1
    package_id = await _package(db_session)
    for type_ in ("package_install", "package_uninstall"):
        out = await _send(client, author, ids, type_=type_, package_id=str(package_id))
        request = await _request(db_session, out["approval_id"])
        assert request.package_digest and request.package_id == package_id
        assert request.package_name == "7-Zip"


async def test_a_forbidden_window_is_confirmed_at_the_request(client, db_session):
    from app.features.schedule import windows
    from app.features.setting.crud import set_value

    await _enable(db_session, threshold=2)
    await set_value(
        db_session,
        windows.KEY_FORBIDDEN,
        [{"days": list(range(7)), "start": "00:00", "end": "23:59"}],
        actor="t",
    )
    await db_session.commit()
    author, _ = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    resp = await client.post(
        "/api/v1/commands",
        headers=author,
        json={"type": "reboot", "machine_ids": [str(i) for i in ids]},
    )
    assert resp.status_code == 409 and _code(resp) == "command.forbidden_window"
    out = await _send(client, author, ids, confirm_forbidden_window=True)
    assert out["approval_id"]


# --- Duplicates, the limit -------------------------------------------------------


async def test_the_same_request_twice_is_one(client, db_session, mail):
    from app.features.webhook.models import WebhookDelivery

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    await _hook(db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    first = await _send(client, author, ids)
    again = await _send(client, author, list(reversed(ids)))
    assert first["approval_id"] == again["approval_id"]
    assert len(await _outbox(db_session, "second@test.local")) == 1
    assert len(await _audit(db_session, "approval.request")) == 1
    deliveries = (await db_session.exec(select(WebhookDelivery))).all()
    assert len([d for d in deliveries if d.event == "approval.requested"]) == 1


async def test_a_duplicate_of_a_request_past_its_time_asks_afresh(client, db_session):
    from datetime import datetime as dt

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    first = await _send(client, author, ids)
    # Past its time, not yet expired by the job.
    request = await _request(db_session, first["approval_id"])
    request.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.add(request)
    await db_session.commit()

    again = await _send(client, author, ids)
    assert again["approval_id"] != first["approval_id"]
    assert dt.fromisoformat(again["approval_expires_at"]) > datetime.now(UTC)
    assert (await _request(db_session, first["approval_id"])).status == "expired"
    assert (await _request(db_session, again["approval_id"])).status == "pending"
    assert len(await _audit(db_session, "approval.expire")) == 1
    assert len(await _audit(db_session, "approval.request")) == 2


async def _wait_for_a_lock_wait(db_session):
    """Until a connection waits on a row lock (the send held behind ``holder``)."""
    from sqlalchemy import text

    for _ in range(200):
        waiting = await db_session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )
        await db_session.commit()
        if waiting:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the send never waited on the request's lock")


async def _resend_while_held(client, db_session, engine, change):
    """A request past its time; ``change`` closes it in another transaction
    that holds its row while the identical send runs, then commits."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.approval.models import ApprovalRequest

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    first = await _send(client, author, ids)
    request = await _request(db_session, first["approval_id"])
    request.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.add(request)
    await db_session.commit()

    async with AsyncSession(engine) as holder:
        held = (
            await holder.exec(
                select(ApprovalRequest)
                .where(col(ApprovalRequest.id) == uuid.UUID(first["approval_id"]))
                .with_for_update()
            )
        ).one()
        await change(holder, held)
        await holder.flush()
        send = asyncio.create_task(_send(client, author, ids))
        await _wait_for_a_lock_wait(db_session)
        await holder.commit()
        again = await send
    return first, again


async def test_a_resend_past_its_time_leaves_an_approval_made_meanwhile(
    client, db_session, engine
):
    # Approved just before its time, while the identical send reads it
    # pending: the approval stands, and the send asks afresh.
    from app.features.approval.models import ApprovalStatus

    async def approve(holder, held):
        held.status = ApprovalStatus.APPROVED
        held.decided_at = datetime.now(UTC)
        holder.add(held)

    first, again = await _resend_while_held(client, db_session, engine, approve)
    assert again["approval_id"] != first["approval_id"]
    assert (await _request(db_session, first["approval_id"])).status == "approved"
    assert (await _request(db_session, again["approval_id"])).status == "pending"
    assert await _audit(db_session, "approval.expire") == []


async def test_a_resend_past_its_time_expires_it_once_beside_the_job(
    client, db_session, engine, mail
):
    # The job expires it while the identical send reads it pending: one
    # ``approval.expire``, one mail to the author.
    from app.features.approval import crud

    async def job(holder, held):
        await crud.expire(holder, held, datetime.now(UTC))

    first, again = await _resend_while_held(client, db_session, engine, job)
    assert again["approval_id"] != first["approval_id"]
    assert (await _request(db_session, first["approval_id"])).status == "expired"
    assert (await _request(db_session, again["approval_id"])).status == "pending"
    assert len(await _audit(db_session, "approval.expire")) == 1
    assert len(await _outbox(db_session, "auteur@test.local")) == 1


async def test_turned_on_by_the_environment_with_one_approver(
    client, db_session, monkeypatch
):
    # The two-approver check is the settings page's: the environment's
    # value applies as it is, and a single approver means nothing at risk
    # above the threshold goes out until the page turns it off.
    monkeypatch.setattr(settings, "APPROVAL_ENABLED", True)
    monkeypatch.setattr(settings, "APPROVAL_THRESHOLD", 2)
    admin = await account(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])
    ids = [p.id for p in await _postes(db_session, 3)]
    body = (await client.get("/api/v1/settings", headers=admin)).json()
    assert body["approval_enabled"] is True and body["approval_eligible"] == 1
    resp = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={"type": "reboot", "machine_ids": [str(i) for i in ids]},
    )
    assert resp.status_code == 409 and _code(resp) == "approval.no_approver"
    assert await _commands(db_session, type="reboot") == []

    resp = await client.patch(
        "/api/v1/settings", headers=admin, json={"approval_enabled": False}
    )
    assert resp.status_code == 200, resp.text
    out = await _send(client, admin, ids, status=200)
    assert out["count"] == 3


async def test_simultaneous_identical_requests_make_one(client, db_session):
    from app.features.approval.models import ApprovalRequest

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    ids = [str(p.id) for p in await _postes(db_session, 3)]
    body = {"type": "reboot", "machine_ids": ids}
    a, b = await asyncio.gather(
        client.post("/api/v1/commands", headers=author, json=body),
        client.post("/api/v1/commands", headers=author, json=body),
    )
    assert a.status_code == b.status_code == 202
    assert a.json()["approval_id"] == b.json()["approval_id"]
    db_session.expire_all()
    rows = (await db_session.exec(select(ApprovalRequest))).all()
    assert len(rows) == 1


async def test_at_most_twenty_pending_per_author(client, db_session):
    from app.features.approval.models import ApprovalRequest

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    for ttl in range(1, 20):
        await _send(client, author, ids, ttl_minutes=ttl)
    # The twentieth and twenty-first at once: one passes.
    a, b = await asyncio.gather(
        client.post(
            "/api/v1/commands",
            headers=author,
            json={
                "type": "reboot",
                "machine_ids": [str(i) for i in ids],
                "ttl_minutes": 50,
            },
        ),
        client.post(
            "/api/v1/commands",
            headers=author,
            json={
                "type": "reboot",
                "machine_ids": [str(i) for i in ids],
                "ttl_minutes": 51,
            },
        ),
    )
    assert sorted([a.status_code, b.status_code]) == [202, 409]
    refused = a if a.status_code == 409 else b
    assert _code(refused) == "approval.too_many_pending"
    db_session.expire_all()
    assert len((await db_session.exec(select(ApprovalRequest))).all()) == 20


async def test_no_request_nobody_else_could_approve(client, db_session):
    await _enable(db_session, threshold=2)
    admin = await account(client, db_session, "seul@test.local", [BuiltinGroup.ADMIN])
    ids = [p.id for p in await _postes(db_session, 3, location=SITE_A)]
    resp = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={"type": "reboot", "machine_ids": [str(i) for i in ids]},
    )
    assert resp.status_code == 409 and _code(resp) == "approval.no_approver"

    # A second account confined to site B does not cover site A's postes.
    site_b = await group(
        db_session, "Site B", RISKY, Scope(locations=frozenset({SITE_B}))
    )
    await account(client, db_session, "tech-b@test.local", [site_b.id])
    resp = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={"type": "reboot", "machine_ids": [str(i) for i in ids]},
    )
    assert resp.status_code == 409 and _code(resp) == "approval.no_approver"
    assert await _audit(db_session, "approval.request") == []


# --- Approving -------------------------------------------------------------------


async def test_approved_by_another_account(client, db_session, mail):
    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    out = await _send(client, author, ids)
    # Not by its author.
    resp = await client.post(
        f"{API}/{out['approval_id']}/approve", headers=author, json={}
    )
    assert resp.status_code == 403 and _code(resp) == "approval.own_request"

    approved = await _approve(client, other, out["approval_id"])
    assert approved["status"] == "approved" and approved["created"] == 3
    assert approved["decided_by"] == "second@test.local"
    commands = await _commands(db_session, type="reboot")
    assert len(commands) == 3
    assert {c.created_by for c in commands} == {"auteur@test.local"}
    [bulk] = await _audit(db_session, "command.bulk")
    assert bulk.actor == "auteur@test.local"
    assert bulk.details["approval_id"] == out["approval_id"]
    assert bulk.details["approved_by"] == "second@test.local"
    [entry] = await _audit(db_session, "approval.approve")
    assert entry.actor == "second@test.local" and entry.details["created"] == 3
    [told] = await _outbox(db_session, "auteur@test.local")
    assert "approuvée" in told.subject
    assert "PC-" not in told.body
    # Decided once.
    resp = await client.post(
        f"{API}/{out['approval_id']}/approve", headers=other, json={}
    )
    assert resp.status_code == 409 and _code(resp) == "approval.not_pending"


async def test_who_may_not_approve(client, db_session):
    await _enable(db_session, threshold=2)
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    ids_a = [p.id for p in await _postes(db_session, 2, location=SITE_A)]
    b = await machine(db_session, "PC-B", location=SITE_B)
    await account(client, db_session, "admin2@test.local", [BuiltinGroup.ADMIN])
    out = await _send(client, author, [*ids_a, b.id])

    # Without the risky right.
    plain = await group(
        db_session, "Courants", {"command:execute", "command:read"}, None
    )
    no_risky = await account(client, db_session, "plain@test.local", [plain.id])
    resp = await client.post(
        f"{API}/{out['approval_id']}/approve", headers=no_risky, json={}
    )
    assert resp.status_code == 403 and _code(resp) == "auth.permission.denied"

    # Seeing only part of the postes: not theirs to decide.
    site_a = await group(
        db_session, "Site A", RISKY, Scope(locations=frozenset({SITE_A}))
    )
    partial = await account(client, db_session, "tech-a@test.local", [site_a.id])
    resp = await client.post(
        f"{API}/{out['approval_id']}/approve", headers=partial, json={}
    )
    assert resp.status_code == 404 and _code(resp) == "approval.not_found"
    resp = await client.get(f"{API}/{out['approval_id']}", headers=partial)
    assert resp.status_code == 404


async def test_a_token_cannot_decide_but_can_cancel(client, db_session):
    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    out = await _send(client, author, ids)

    async def write_token(headers):
        resp = await client.post(
            "/api/v1/auth/api-tokens",
            headers=headers,
            json={"name": "Script", "current_password": STRONG, "can_write": True},
        )
        assert resp.status_code == 201, resp.text
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    token = await write_token(other)
    for action, body in (("approve", {}), ("reject", {"note": "non"})):
        resp = await client.post(
            f"{API}/{out['approval_id']}/{action}", headers=token, json=body
        )
        assert resp.status_code == 403 and _code(resp) == "api_token.forbidden_here"
    # A token may send the request, and cancel it.
    author_token = await write_token(author)
    resp = await client.post(
        "/api/v1/commands",
        headers=author_token,
        json={"type": "shutdown", "machine_ids": [str(i) for i in ids]},
    )
    assert resp.status_code == 202
    resp = await client.post(
        f"{API}/{resp.json()['approval_id']}/cancel", headers=author_token
    )
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"


# --- Failures recorded before the answer -----------------------------------------


async def _failed(client, db_session, headers, approval_id, code, cause):
    resp = await client.post(f"{API}/{approval_id}/approve", headers=headers, json={})
    assert resp.status_code in (404, 409, 422), resp.text
    assert _code(resp) == code
    request = await _request(db_session, approval_id)
    assert request.status == "failed" and request.result_code == cause
    entries = [
        e
        for e in await _audit(db_session, "approval.fail")
        if e.resource_id == str(approval_id)
    ]
    assert len(entries) == 1 and entries[0].details["cause"] == cause
    # The close was committed: a retry finds it decided.
    resp = await client.post(f"{API}/{approval_id}/approve", headers=headers, json={})
    assert resp.status_code == 409 and _code(resp) == "approval.not_pending"
    return resp


async def test_a_changed_package_fails_the_request(client, db_session, mail):
    from app.features.package.models import Package

    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    package_id = await _package(db_session)
    out = await _send(
        client, author, ids, type_="package_install", package_id=str(package_id)
    )
    package = await db_session.get(Package, package_id)
    package.winget_version = "24.0"
    db_session.add(package)
    await db_session.commit()
    await _failed(
        client,
        db_session,
        other,
        out["approval_id"],
        "approval.package_changed",
        "package_changed",
    )
    [told] = await _outbox(db_session, "auteur@test.local")
    assert "échoué" in told.subject and "modifié" in told.body
    assert await _commands(db_session, type="package_install") == []


async def test_a_retired_or_deleted_package(client, db_session):
    from app.features.package.models import Package

    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    retired = await _package(db_session, name="Ancien")
    out = await _send(
        client, author, ids, type_="package_install", package_id=str(retired)
    )
    package = await db_session.get(Package, retired)
    package.retired_at = datetime.now(UTC)
    db_session.add(package)
    await db_session.commit()
    await _failed(
        client,
        db_session,
        other,
        out["approval_id"],
        "package.retired",
        "package.retired",
    )

    gone = await _package(db_session, name="Supprimé")
    out = await _send(
        client, author, ids, type_="package_install", package_id=str(gone)
    )
    await db_session.delete(await db_session.get(Package, gone))
    await db_session.commit()
    await _failed(
        client,
        db_session,
        other,
        out["approval_id"],
        "approval.package_gone",
        "package_gone",
    )


async def test_an_author_who_may_no_longer_send_it(client, db_session):
    from app.features.user import crud as user_crud
    from app.features.user.models import Group, User

    await _enable(db_session, threshold=2)
    other = await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    ids = [p.id for p in await _postes(db_session, 3)]
    techs = await group(db_session, "Techs", RISKY, None)

    async def author_and_request(email, ttl):
        headers = await account(client, db_session, email, [techs.id])
        out = await _send(client, headers, ids, ttl_minutes=ttl)
        return out["approval_id"]

    # Deactivated.
    first = await author_and_request("inactif@test.local", 10)
    user = await user_crud.get_by_email(db_session, "inactif@test.local")
    user.is_active = False
    db_session.add(user)
    await db_session.commit()
    await _failed(
        client,
        db_session,
        other,
        first,
        "approval.author_not_allowed",
        "author_inactive",
    )

    # Deprived of risky_command:execute.
    second = await author_and_request("prive@test.local", 11)
    g = await db_session.get(Group, techs.id)
    await user_crud.set_group_permissions(
        db_session, g, {"command:execute", "command:read", "machine:read"}
    )
    await db_session.commit()
    resp = await client.post(f"{API}/{second}/approve", headers=other, json={})
    assert resp.status_code == 409 and _code(resp) == "approval.author_not_allowed"
    assert resp.json()["error"]["details"]["cause"] == "permission_lost"
    assert (await _request(db_session, second)).result_code == "permission_lost"

    # Deleted.
    g = await db_session.get(Group, techs.id)
    await user_crud.set_group_permissions(db_session, g, RISKY)
    await db_session.commit()
    third = await author_and_request("parti@test.local", 12)
    gone = await user_crud.get_by_email(db_session, "parti@test.local")
    await db_session.delete(gone)
    await db_session.commit()
    resp = await client.post(f"{API}/{third}/approve", headers=other, json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["cause"] == "author_gone"
    assert (await _request(db_session, third)).status == "failed"
    assert await db_session.get(User, uuid.uuid4()) is None


async def test_nothing_left_and_what_is_left_out(client, db_session):
    from app.features.machine.models import Machine

    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    postes = await _postes(db_session, 5)
    ids = [p.id for p in postes]
    out = await _send(client, author, ids)
    # One deleted, one revoked since.
    await db_session.delete(await db_session.get(Machine, ids[0]))
    revoked = await db_session.get(Machine, ids[1])
    revoked.token_revoked = True
    db_session.add(revoked)
    await db_session.commit()
    approved = await _approve(client, other, out["approval_id"])
    assert approved["created"] == 3 and approved["left_out"] == 2

    out = await _send(client, author, ids[2:], type_="shutdown")
    for machine_id in ids[2:]:
        await db_session.delete(await db_session.get(Machine, machine_id))
    await db_session.commit()
    await _failed(
        client,
        db_session,
        other,
        out["approval_id"],
        "approval.nothing_left",
        "nothing_left",
    )


async def test_postes_out_of_the_authors_scope_since_are_left_out(client, db_session):
    from app.features.machine.models import Machine

    await _enable(db_session, threshold=2)
    other = await account(client, db_session, "second@test.local", [BuiltinGroup.ADMIN])
    site_a = await group(
        db_session, "Site A", RISKY, Scope(locations=frozenset({SITE_A}))
    )
    author = await account(client, db_session, "tech-a@test.local", [site_a.id])
    ids = [p.id for p in await _postes(db_session, 3, location=SITE_A)]
    out = await _send(client, author, ids)
    moved = await db_session.get(Machine, ids[0])
    moved.location = SITE_B
    db_session.add(moved)
    await db_session.commit()
    approved = await _approve(client, other, out["approval_id"])
    assert approved["created"] == 2 and approved["left_out"] == 1
    assert {c.machine_id for c in await _commands(db_session)} == set(ids[1:])


async def test_a_forbidden_window_at_the_approval(client, db_session):
    from app.features.schedule import windows
    from app.features.setting.crud import set_value

    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    out = await _send(client, author, [p.id for p in await _postes(db_session, 3)])
    await set_value(
        db_session,
        windows.KEY_FORBIDDEN,
        [{"days": list(range(7)), "start": "00:00", "end": "23:59"}],
        actor="t",
    )
    await db_session.commit()
    resp = await client.post(
        f"{API}/{out['approval_id']}/approve", headers=other, json={}
    )
    assert resp.status_code == 409 and _code(resp) == "command.forbidden_window"
    assert (await _request(db_session, out["approval_id"])).status == "pending"
    approved = await _approve(
        client, other, out["approval_id"], confirm_forbidden_window=True
    )
    assert approved["status"] == "approved"


# --- Races ---------------------------------------------------------------------------


async def test_two_approvals_at_once_queue_once(client, db_session):
    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    third = await account(client, db_session, "trois@test.local", [BuiltinGroup.ADMIN])
    out = await _send(client, author, [p.id for p in await _postes(db_session, 3)])
    url = f"{API}/{out['approval_id']}/approve"
    a, b = await asyncio.gather(
        client.post(url, headers=other, json={}),
        client.post(url, headers=third, json={}),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    assert len(await _commands(db_session, type="reboot")) == 3

    ids = [p.id for p in await _postes(db_session, 3)]
    out = await _send(client, author, ids, type_="shutdown")
    a, b = await asyncio.gather(
        client.post(f"{API}/{out['approval_id']}/approve", headers=other, json={}),
        client.post(f"{API}/{out['approval_id']}/cancel", headers=author),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    status = (await _request(db_session, out["approval_id"])).status
    created = len(await _commands(db_session, type="shutdown"))
    assert (status, created) in (("approved", 3), ("cancelled", 0))


async def test_expiry_skips_a_request_held_by_an_approver(client, db_session, engine):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.approval import crud
    from app.features.approval.models import ApprovalRequest

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    out = await _send(client, author, [p.id for p in await _postes(db_session, 3)])
    later = datetime.now(UTC) + timedelta(days=2)
    async with AsyncSession(engine) as holder:
        await holder.exec(
            select(ApprovalRequest)
            .where(col(ApprovalRequest.id) == uuid.UUID(out["approval_id"]))
            .with_for_update()
        )
        async with AsyncSession(engine) as worker:
            assert await crud.mark_expired(worker, later) == 0
        await holder.rollback()
    assert (await _request(db_session, out["approval_id"])).status == "pending"


# --- Rejecting, cancelling, expiring -----------------------------------------------


async def test_rejected_with_a_reason(client, db_session, mail):
    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    out = await _send(client, author, [p.id for p in await _postes(db_session, 3)])
    resp = await client.post(
        f"{API}/{out['approval_id']}/reject",
        headers=other,
        json={"note": "Pas pendant les examens"},
    )
    assert resp.status_code == 200 and resp.json()["status"] == "rejected"
    [told] = await _outbox(db_session, "auteur@test.local")
    assert "refusée" in told.subject and "Pas pendant les examens" in told.body
    [entry] = await _audit(db_session, "approval.reject")
    assert entry.details["note"] == "Pas pendant les examens"
    resp = await client.post(
        f"{API}/{out['approval_id']}/reject", headers=other, json={}
    )
    assert resp.status_code == 409 and _code(resp) == "approval.not_pending"


async def test_cancelled_by_its_author_alone(client, db_session):
    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    out = await _send(client, author, [p.id for p in await _postes(db_session, 3)])
    resp = await client.post(f"{API}/{out['approval_id']}/cancel", headers=other)
    assert resp.status_code == 404 and _code(resp) == "approval.not_found"
    resp = await client.post(f"{API}/{out['approval_id']}/cancel", headers=author)
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    [entry] = await _audit(db_session, "approval.cancel")
    assert entry.actor == "auteur@test.local"
    resp = await client.post(
        f"{API}/{out['approval_id']}/approve", headers=other, json={}
    )
    assert resp.status_code == 409


async def test_expiry_by_the_job_by_a_read_and_at_the_approval(
    client, db_session, engine, mail, monkeypatch
):
    from app.core import worker
    from app.features.approval.models import ApprovalRequest

    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]

    async def aged(out):
        request = await _request(db_session, out["approval_id"])
        request.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db_session.add(request)
        await db_session.commit()

    # The job.
    first = await _send(client, author, ids, ttl_minutes=10)
    await aged(first)
    monkeypatch.setattr(worker, "engine", engine)
    assert await worker.expire_approvals() == 1
    assert (await _request(db_session, first["approval_id"])).status == "expired"

    # A read of the list.
    second = await _send(client, author, ids, ttl_minutes=11)
    await aged(second)
    listed = (await client.get(API, headers=other)).json()
    assert listed["total"] == 0
    assert (await _request(db_session, second["approval_id"])).status == "expired"

    # An approval of one past its time, not marked yet.
    third = await _send(client, author, ids, ttl_minutes=12)
    await aged(third)
    resp = await client.post(
        f"{API}/{third['approval_id']}/approve", headers=other, json={}
    )
    assert resp.status_code == 409 and _code(resp) == "approval.not_pending"
    request = await _request(db_session, third["approval_id"])
    assert request.status == "expired" and request.decided_at is not None
    expiries = await _audit(db_session, "approval.expire")
    assert len(expiries) == 3
    assert expiries[-1].actor == "second@test.local"
    told = await _outbox(db_session, "auteur@test.local")
    assert len([m for m in told if "expiré" in m.subject]) == 3
    assert (await db_session.exec(select(ApprovalRequest))).all()


# --- The list, the badge, the detail ------------------------------------------------


async def test_list_badge_and_detail_follow_one_rule(client, db_session):
    from app.features.machine.models import Machine

    await _enable(db_session, threshold=2)
    admin = await account(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])
    await account(client, db_session, "admin2@test.local", [BuiltinGroup.ADMIN])
    site_a = await group(
        db_session, "Site A", RISKY, Scope(locations=frozenset({SITE_A}))
    )
    tech = await account(client, db_session, "tech-a@test.local", [site_a.id])
    a = [p.id for p in await _postes(db_session, 3, location=SITE_A)]
    for i in range(3):
        await machine(db_session, f"PC-B{i}", location=SITE_B)
    # The admin's request on site A, and one on the whole parc.
    on_a = await _send(client, admin, a)
    resp = await client.post(
        "/api/v1/commands", headers=admin, json={"type": "shutdown", "target_all": True}
    )
    assert resp.status_code == 202
    # The technician's own request.
    mine = await _send(client, tech, a, type_="wu_reset")

    listed = (await client.get(API, headers=tech)).json()
    assert [i["id"] for i in listed["items"]] == [on_a["approval_id"]]
    summary = (await client.get(f"{API}/summary", headers=tech)).json()
    assert summary == {"enabled": True, "to_decide": 1, "mine_pending": 1}
    assert summary["to_decide"] == listed["total"]
    own = (await client.get(API, headers=tech, params={"view": "mine"})).json()
    assert [i["id"] for i in own["items"]] == [mine["approval_id"]]
    admin_list = (await client.get(API, headers=admin)).json()
    assert [i["id"] for i in admin_list["items"]] == [mine["approval_id"]]

    # The technician's scope shrinks: their request's postes out of it are
    # no longer named to them.
    moved = await db_session.get(Machine, a[0])
    moved.location = SITE_B
    db_session.add(moved)
    await db_session.commit()
    detail = (await client.get(f"{API}/{mine['approval_id']}", headers=tech)).json()
    assert len(detail["machines"]) == 2 and detail["hidden"] == 1
    full = (await client.get(f"{API}/{mine['approval_id']}", headers=admin)).json()
    assert len(full["machines"]) == 3 and full["hidden"] == 0

    plain = await group(db_session, "Courants", {"command:execute"}, None)
    nobody = await account(client, db_session, "plain@test.local", [plain.id])
    resp = await client.get(f"{API}/summary", headers=nobody)
    assert resp.status_code == 403


# --- Mails, webhook ------------------------------------------------------------------


async def test_who_is_mailed_about_a_request(client, db_session, mail):
    from app.features.user import crud as user_crud

    await _enable(db_session, threshold=2)
    author = await account(
        client, db_session, "auteur@test.local", [BuiltinGroup.ADMIN]
    )
    await account(client, db_session, "fr@test.local", [BuiltinGroup.ADMIN])
    await account(client, db_session, "en@test.local", [BuiltinGroup.ADMIN])
    await account(client, db_session, "rien@test.local", [BuiltinGroup.ADMIN])
    await account(client, db_session, "parti@test.local", [BuiltinGroup.ADMIN])
    for email, field, value in (
        ("en@test.local", "language", "en"),
        ("rien@test.local", "email_preference", "none"),
        ("parti@test.local", "is_active", False),
    ):
        user = await user_crud.get_by_email(db_session, email)
        setattr(user, field, value)
        db_session.add(user)
    await db_session.commit()
    await _send(client, author, [p.id for p in await _postes(db_session, 3)])
    mails = {m.to_address: m for m in await _outbox(db_session)}
    assert set(mails) == {"fr@test.local", "en@test.local"}
    assert (
        "Approbation demandée : Redémarrer sur 3 postes"
        in mails["fr@test.local"].subject
    )
    assert (
        "Approval requested: Restart on 3 computers" in mails["en@test.local"].subject
    )
    assert "https://tiai.test/#/approvals" in mails["fr@test.local"].body


async def test_the_webhook_event(client, db_session):
    from app.features.approval.models import ApprovalRequest
    from app.features.webhook import emit, texts
    from app.features.webhook.models import (
        SUBSCRIBABLE,
        WebhookDelivery,
        WebhookEvent,
    )

    assert WebhookEvent.APPROVAL_REQUESTED in SUBSCRIBABLE
    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    await _hook(db_session)
    ids = [p.id for p in await _postes(db_session, 3)]

    # Rolled back with its request: nothing queued.
    request = ApprovalRequest(
        kind="command",
        command_type="reboot",
        target={"kind": "all"},
        machine_count=3,
        threshold=2,
        requested_by="x",
        expires_at=datetime.now(UTC),
    )
    assert await emit.approval_requested(db_session, request) == 1
    await db_session.rollback()
    assert (await db_session.exec(select(WebhookDelivery))).all() == []

    out = await _send(client, author, ids)
    db_session.expire_all()
    [delivery] = (await db_session.exec(select(WebhookDelivery))).all()
    data = delivery.payload["data"]
    assert data["id"] == out["approval_id"]
    assert data["target"] == {"target": "machines", "requested": 3}
    assert set(data) == {
        "id",
        "kind",
        "command_type",
        "package",
        "schedule",
        "target",
        "count",
        "threshold",
        "requested_by",
        "expires_at",
    }
    assert "machine_ids" not in str(data)
    fr = texts.text("approval.requested", data, "fr")
    en = texts.text("approval.requested", data, "en")
    assert fr.startswith(
        "Approbation demandée par auteur@test.local : « reboot » sur 3 postes"
    )
    assert en.startswith(
        "Approval requested by auteur@test.local: “reboot” on 3 computers"
    )


# --- Settings --------------------------------------------------------------------------


async def test_turning_it_on_needs_two_approvers(client, db_session):
    from app.features.approval import reach

    admin = await account(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])
    resp = await client.patch(
        "/api/v1/settings", headers=admin, json={"approval_enabled": True}
    )
    assert resp.status_code == 422 and _code(resp) == "approval.not_enough_approvers"
    assert resp.json()["error"]["details"]["eligible"] == 1

    techs = await group(db_session, "Techs", RISKY, None)
    await account(client, db_session, "tech@test.local", [techs.id])
    resp = await client.patch(
        "/api/v1/settings",
        headers=admin,
        json={
            "approval_enabled": True,
            "approval_threshold": 30,
            "approval_ttl_hours": 12,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["approval_enabled"] is True and body["approval_eligible"] == 2
    assert body["approval_threshold"] == 30 and body["approval_ttl_hours"] == 12
    assert body["env_approval_threshold"] == 40
    [entry] = await _audit(db_session, "settings.update")
    assert entry.details["approval_enabled"] == "True"

    for bad in (
        {"approval_threshold": 1},
        {"approval_threshold": 10001},
        {"approval_ttl_hours": 0},
        {"approval_ttl_hours": 169},
    ):
        resp = await client.patch("/api/v1/settings", headers=admin, json=bad)
        assert resp.status_code == 422, bad

    # Who counts: administrators and technicians with both rights; a
    # deactivated account does not; two accounts confined to two sites do.
    for site in (SITE_A, SITE_B):
        g = await group(
            db_session, f"Site {site}", RISKY, Scope(locations=frozenset({site}))
        )
        await account(client, db_session, f"tech-{site[-1]}@test.local", [g.id])
    from app.features.user import crud as user_crud

    gone = await user_crud.get_by_email(db_session, "tech@test.local")
    gone.is_active = False
    db_session.add(gone)
    await db_session.commit()
    assert await reach.eligible_count(db_session) == 3


async def test_turned_off_pending_requests_stay_decidable(client, db_session):
    await _enable(db_session, threshold=2)
    author, other = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    out = await _send(client, author, ids)
    resp = await client.patch(
        "/api/v1/settings", headers=author, json={"approval_enabled": False}
    )
    assert resp.status_code == 200
    # No new request: sent at once.
    sent = await _send(client, author, ids, type_="shutdown", status=200)
    assert sent["count"] == 3
    approved = await _approve(client, other, out["approval_id"])
    assert approved["status"] == "approved"


# --- Merge, purge ------------------------------------------------------------------------


async def test_a_merge_names_the_kept_poste_once(client, db_session):
    from app.features.approval.models import ApprovalRequestMachine

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    postes = await _postes(db_session, 4)
    ids = [p.id for p in postes]
    both = await _send(client, author, ids)
    only_dup = await _send(client, author, [ids[0], ids[2], ids[3]], type_="shutdown")
    resp = await client.post(
        f"/api/v1/machines/{ids[1]}/merge",
        headers=author,
        json={"source_id": str(ids[0])},
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()

    async def listed(approval_id):
        return {
            r.machine_id
            for r in (
                await db_session.exec(
                    select(ApprovalRequestMachine).where(
                        col(ApprovalRequestMachine.request_id) == uuid.UUID(approval_id)
                    )
                )
            ).all()
        }

    assert await listed(both["approval_id"]) == {ids[1], ids[2], ids[3]}
    assert await listed(only_dup["approval_id"]) == {ids[1], ids[2], ids[3]}
    assert (await _request(db_session, both["approval_id"])).machine_count == 4


async def test_the_purge_keeps_what_waits(client, db_session):
    from app.features.approval import crud
    from app.features.approval.models import ApprovalRequest, ApprovalRequestMachine

    await _enable(db_session, threshold=2)
    author, _ = await _admins(client, db_session)
    ids = [p.id for p in await _postes(db_session, 3)]
    closed = await _send(client, author, ids)
    waiting = await _send(client, author, ids, type_="shutdown")
    await client.post(f"{API}/{closed['approval_id']}/cancel", headers=author)
    request = await _request(db_session, closed["approval_id"])
    request.decided_at = datetime.now(UTC) - timedelta(days=200)
    db_session.add(request)
    await db_session.commit()
    assert (
        await crud.purge_before(db_session, datetime.now(UTC) - timedelta(days=180))
        == 1
    )
    db_session.expire_all()
    remaining = (await db_session.exec(select(ApprovalRequest))).all()
    assert [str(r.id) for r in remaining] == [waiting["approval_id"]]
    rows = (await db_session.exec(select(ApprovalRequestMachine))).all()
    assert {str(r.request_id) for r in rows} == {waiting["approval_id"]}
