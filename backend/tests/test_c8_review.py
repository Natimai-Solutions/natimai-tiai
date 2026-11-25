"""The review of C8 (PR #136): each finding kept, with the behaviour that
answers it — destinations, the queue, the events, the tokens."""

import asyncio
import json
import socket
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.features.webhook import deliver, destination
from tests.scope_helpers import STRONG, account, group, login, two_sites

API = "/api/v1/webhooks"
TOKENS = "/api/v1/auth/api-tokens"
HOST = "hooks.example.test"
DEAD = "dead.example.test"
URL = f"https://{HOST}/in"


class Receiver:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.delay = 0.0

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        return httpx.Response(500 if request.url.host == DEAD else 200)


@pytest.fixture
def receiver(monkeypatch):
    r = Receiver()
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [HOST, DEAD])
    monkeypatch.setattr(deliver, "TRANSPORT", httpx.MockTransport(r.handler))
    return r


class Resolver:
    """What the name resolves to, as the test says, and the names asked."""

    def __init__(self) -> None:
        self.answer = "93.184.216.34"
        self.asked: list[str] = []

    async def getaddrinfo(self, host, port, **kwargs):
        if not str(host).endswith(".example"):
            # The database and the rest resolve as usual.
            return await self.real(host, port, **kwargs)
        self.asked.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (self.answer, 0))]


@pytest.fixture
async def resolver(monkeypatch):
    r = Resolver()
    loop = asyncio.get_running_loop()
    r.real = loop.getaddrinfo
    monkeypatch.setattr(loop, "getaddrinfo", r.getaddrinfo)
    return r


async def _create(client, headers, **fields):
    body = {"name": "Canal", "url": URL, "events": ["check.created"], **fields}
    resp = await client.post(API, headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _deliveries(db_session, event=None):
    from app.features.webhook.models import WebhookDelivery

    db_session.expire_all()
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.created_at)
    if event is not None:
        stmt = stmt.where(WebhookDelivery.event == event)
    return list((await db_session.exec(stmt)).all())


async def _drain(db_session):
    return await deliver.send_pending(db_session, budget_seconds=None)


# --- Destinations ---------------------------------------------------------------


async def test_the_name_checked_is_the_name_reached(resolver, monkeypatch):
    """IDNA 2008, as the HTTP client sends it: « ß » is not « ss »."""
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    target = await destination.resolve("https://straße.example/x")
    assert resolver.asked == ["xn--strae-oqa.example"]
    assert target.host == "xn--strae-oqa.example"


@pytest.mark.parametrize(
    "url",
    [
        "https://[64:ff9b::a00:1]/x",  # NAT64 to 10.0.0.1
        "https://[2002:a00:1::1]/x",  # 6to4 of 10.0.0.1
        "https://[fec0::1]/x",  # site-local
        "https://100.64.1.1/x",  # shared (CGNAT)
        "https://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/x",  # Teredo
    ],
)
async def test_more_internal_forms(url, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    with pytest.raises(destination.DestinationError) as info:
        await destination.check(url)
    assert info.value.code == destination.INTERNAL


async def test_refusal_does_not_name_the_internal_address(resolver, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    resolver.answer = "10.20.30.40"
    with pytest.raises(destination.DestinationError) as info:
        await destination.check("https://intranet.example/x")
    assert "10.20.30.40" not in str(info.value)


async def test_a_malformed_name_is_refused_not_a_server_error(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "ra@lycee.test", [BuiltinGroup.ADMIN])
    for url in ("https://a..b/x", f"https://{'a' * 64}.example/x", "https://é..x/"):
        resp = await client.post(
            API,
            headers=admin,
            json={"name": "X", "url": url, "events": ["check.created"]},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["details"]["reason"] == "webhook.url.host"


async def test_the_send_goes_to_the_address_checked(resolver, monkeypatch):
    """No second resolution: the connection is pinned, the name kept for
    Host and for the TLS handshake."""
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    monkeypatch.setattr(deliver, "TRANSPORT", httpx.MockTransport(handler))
    status = await deliver.post(
        "https://pub.example:8443/in?x=1", b"{}", "secret", "test", "id"
    )
    assert status == 204
    [request] = seen
    assert request.url.host == "93.184.216.34" and request.url.port == 8443
    assert request.url.path == "/in" and request.url.query == b"x=1"
    assert request.headers["Host"] == "pub.example:8443"
    assert request.extensions["sni_hostname"] == "pub.example"
    assert resolver.asked == ["pub.example"]


async def test_a_destination_turned_internal_is_refused_at_send(
    client, db_session, resolver, monkeypatch
):
    from app.features.webhook.models import WebhookDelivery

    seen: list[httpx.Request] = []
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    monkeypatch.setattr(
        deliver,
        "TRANSPORT",
        httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)),
    )
    sites = await two_sites(client, db_session)
    await _create(client, sites.admin, url="https://pub.example/in")
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    resolver.answer = "169.254.169.254"
    assert await _drain(db_session) == 0
    assert seen == []
    [row] = await _deliveries(db_session)
    assert isinstance(row, WebhookDelivery)
    assert row.status == "pending" and row.attempts == 1
    assert row.last_error.startswith("destination refused")


async def test_a_slow_receiver_is_cut_short(client, db_session, receiver, monkeypatch):
    sites = await two_sites(client, db_session)
    hook = await _create(client, sites.admin)
    monkeypatch.setattr(settings, "WEBHOOK_TIMEOUT_SECONDS", 1)
    receiver.delay = 5
    resp = await client.post(f"{API}/{hook['id']}/test", headers=sites.admin)
    assert resp.json()["ok"] is False
    assert "no answer within 1 s" in resp.json()["error"]
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    assert await _drain(db_session) == 0
    [row] = await _deliveries(db_session, "check.created")
    assert row.last_error == "no answer within 1 s"


# --- The queue ------------------------------------------------------------------


def test_retries_last_about_a_day():
    total = sum(
        (deliver._retry_delay(n) for n in range(1, settings.WEBHOOK_MAX_ATTEMPTS)),
        timedelta(),
    )
    assert timedelta(hours=20) < total < timedelta(hours=30)


async def test_a_claimed_delivery_is_not_sent_twice(client, db_session, receiver):
    from sqlmodel.ext.asyncio.session import AsyncSession

    sites = await two_sites(client, db_session)
    await _create(client, sites.admin)
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    claimed = await deliver._claim(db_session, 50)
    assert len(claimed) == 1
    async with AsyncSession(db_session.bind) as other:
        assert await deliver.send_pending(other, budget_seconds=None) == 0
    assert receiver.requests == []


async def test_a_receiver_down_does_not_hold_up_the_others(
    client, db_session, receiver
):
    from app.features.webhook.models import WebhookDelivery

    sites = await two_sites(client, db_session)
    dead = await _create(client, sites.admin, name="Mort", url=f"https://{DEAD}/x")
    alive = await _create(client, sites.admin, name="Vivant")
    for _ in range(3):
        db_session.add(
            WebhookDelivery(
                webhook_id=uuid.UUID(dead["id"]), event="check.created", payload={}
            )
        )
    db_session.add(
        WebhookDelivery(
            webhook_id=uuid.UUID(alive["id"]), event="check.created", payload={}
        )
    )
    await db_session.commit()
    assert await _drain(db_session) == 1
    # The dead one was tried once; its two others wait, untouched and due.
    assert [r.url.host for r in receiver.requests].count(DEAD) == 1
    rows = [r for r in await _deliveries(db_session) if str(r.webhook_id) == dead["id"]]
    assert sorted(r.attempts for r in rows) == [0, 0, 1]
    from app.features.base import utcnow

    assert all(r.next_attempt_at <= utcnow() for r in rows if r.attempts == 0)


async def test_switched_off_drops_without_blaming_the_receiver(
    client, db_session, receiver
):
    from app.features.webhook.models import Webhook

    sites = await two_sites(client, db_session)
    hook = await _create(client, sites.admin)
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    row = await db_session.get(Webhook, uuid.UUID(hook["id"]))
    row.enabled = False
    db_session.add(row)
    await db_session.commit()
    await _drain(db_session)
    [delivery] = await _deliveries(db_session)
    assert (delivery.status, delivery.last_error) == ("failed", "webhook disabled")
    await db_session.refresh(row)
    assert row.consecutive_failures == 0 and receiver.requests == []


async def test_an_unreadable_secret_says_to_renew_it(client, db_session, receiver):
    from app.features.webhook.models import Webhook

    sites = await two_sites(client, db_session)
    hook = await _create(client, sites.admin)
    row = await db_session.get(Webhook, uuid.UUID(hook["id"]))
    row.secret = "not-a-sealed-secret"
    db_session.add(row)
    await db_session.commit()
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    await _drain(db_session)
    [delivery] = await _deliveries(db_session)
    assert "renew it" in delivery.last_error and delivery.status == "pending"
    resp = await client.post(f"{API}/{hook['id']}/test", headers=sites.admin)
    assert "renew it" in resp.json()["error"]


# --- The API --------------------------------------------------------------------


async def test_patch_rules(client, db_session, receiver, resolver, monkeypatch):
    from app.features.audit.models import AuditEntry
    from app.features.webhook.models import Webhook

    sites = await two_sites(client, db_session)
    hook = await _create(client, sites.admin)
    path = f"{API}/{hook['id']}"
    resp = await client.patch(path, headers=sites.admin, json={"events": []})
    assert resp.status_code == 422
    resp = await client.patch(
        path, headers=sites.admin, json={"url": "https://10.0.0.9/x"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"]["reason"] == "webhook.url.internal"

    row = await db_session.get(Webhook, uuid.UUID(hook["id"]))
    row.consecutive_failures = 4
    db_session.add(row)
    await db_session.commit()
    # Renaming a failing one does not hide that it fails…
    resp = await client.patch(
        path, headers=sites.admin, json={"name": "Autre", "enabled": True}
    )
    assert resp.json()["consecutive_failures"] == 4
    # …switching it back on, or another address, starts again.
    await client.patch(path, headers=sites.admin, json={"enabled": False})
    resp = await client.patch(path, headers=sites.admin, json={"enabled": True})
    assert resp.json()["consecutive_failures"] == 0

    # The journal keeps the host, not the path that is the credential.
    await client.patch(
        path, headers=sites.admin, json={"url": f"https://{HOST}/hooks/SECRET"}
    )
    assert (await client.delete(path, headers=sites.admin)).status_code == 204
    entries = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.resource_type == "webhook")
        )
    ).all()
    assert [e.action for e in entries] == [
        "webhook.create",
        "webhook.update",
        "webhook.update",
        "webhook.update",
        "webhook.update",
        "webhook.delete",
    ]
    assert all("SECRET" not in json.dumps(e.details) for e in entries)
    assert entries[-1].details["host"] == HOST
    assert (await client.get(path, headers=sites.admin)).status_code == 404


async def test_the_limit_has_its_own_code(client, db_session, receiver, monkeypatch):
    from app.api.routes import webhooks

    sites = await two_sites(client, db_session)
    monkeypatch.setattr(webhooks, "MAX_WEBHOOKS", 1)
    await _create(client, sites.admin)
    resp = await client.post(
        API,
        headers=sites.admin,
        json={"name": "2", "url": URL, "events": ["check.created"]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "webhook.too_many"


# --- The events -----------------------------------------------------------------


async def test_threats_old_history_is_not_news(client, db_session, receiver):
    from app.features.base import utcnow
    from tests.test_api_wol_relay import _enroll, _heartbeat

    sites = await two_sites(client, db_session)
    await _create(client, sites.admin, events=["threat.detected"])
    poste = await _enroll(client, "m-threats-c8")
    old = {
        "detection_id": "OLD-1",
        "threat_name": "Ancien",
        "severity": "high",
        "status": "removed",
        "detected_at": "2020-01-01T00:00:00Z",
    }
    await _heartbeat(client, poste["token"], threats=[old])
    assert await _deliveries(db_session, "threat.detected") == []
    fresh = {
        "detection_id": "NEW-1",
        "threat_name": "Récent",
        "severity": "high",
        "status": "quarantined",
        "detected_at": utcnow().isoformat(),
    }
    await _heartbeat(client, poste["token"], threats=[old, fresh])
    [row] = await _deliveries(db_session, "threat.detected")
    assert [t["name"] for t in row.payload["data"]["items"]] == ["Récent"]


async def test_command_failures_from_the_agent_and_from_silence(
    client, db_session, receiver
):
    from app.features.command import crud as command_crud
    from tests.test_api_command_codes import _queue, _report
    from tests.test_api_wol_relay import _admin_headers, _enroll, _heartbeat

    headers = await _admin_headers(client, db_session)
    await _create(client, headers, events=["command.failed"])
    poste = await _enroll(client, "m-cmd-c8", hostname="PC-CMD")
    await _queue(client, headers, poste["machine_id"])
    [handed] = (await _heartbeat(client, poste["token"]))["commands"]
    await _report(client, poste["token"], handed["id"], status="failed", error="raté")
    [row] = await _deliveries(db_session, "command.failed")
    assert row.payload["data"]["command_id"] == handed["id"]
    assert row.payload["data"]["error"] == "raté"

    # Delivered and never answered: the server closes it, and says so.
    await _queue(client, headers, poste["machine_id"])
    [handed] = (await _heartbeat(client, poste["token"]))["commands"]
    assert await command_crud.close_unanswered(db_session, hours=0) == 1
    await db_session.commit()
    rows = await _deliveries(db_session, "command.failed")
    assert [r.payload["data"]["command_id"] for r in rows][-1] == handed["id"]


async def test_checks_carry_their_ids_and_group(client, db_session, receiver):
    sites = await two_sites(client, db_session)
    await _create(client, sites.admin, events=["check.created", "check.closed"])
    single = (
        await client.post(
            f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
        )
    ).json()
    [created] = await _deliveries(db_session, "check.created")
    assert created.payload["data"]["check_id"] == single["id"]
    assert created.payload["data"]["items"][0]["check_id"] == single["id"]
    await client.post(
        f"/api/v1/checks/{single['id']}/close", headers=sites.admin, json={}
    )
    [closed] = await _deliveries(db_session, "check.closed")
    assert closed.payload["data"]["check_id"] == single["id"]

    # A request for several postes: one event, each item with its check.
    resp = await client.post(
        "/api/v1/checks/bulk",
        headers=sites.admin,
        json={"machine_ids": [str(sites.a.id), str(sites.b.id)]},
    )
    assert resp.status_code == 201, resp.text
    bulk = (await _deliveries(db_session, "check.created"))[-1]
    assert bulk.payload["data"]["total"] == 2
    assert all(item["check_id"] for item in bulk.payload["data"]["items"])


async def test_a_report_turned_into_a_check(client, db_session, receiver):
    from tests.scope_helpers import machine
    from tests.test_api_maintenance import _admin
    from tests.test_reports import _label, _leave, _open_form

    headers, _ = await _admin(client, db_session)
    await _create(client, headers)
    m = await machine(db_session, "PC-REP")
    token = await _label(client, headers, m.id)
    await _open_form(client, headers)
    await _leave(client, token, text="Écran noir")
    [report] = (await client.get("/api/v1/reports", headers=headers)).json()["items"]
    resp = await client.post(
        f"/api/v1/reports/{report['id']}/convert", headers=headers, json={}
    )
    assert resp.status_code == 200, resp.text
    [row] = await _deliveries(db_session, "check.created")
    assert row.payload["data"]["check_id"] == resp.json()["check_id"]
    assert row.payload["data"]["machine"]["hostname"] == "PC-REP"


async def test_alert_checks_are_one_event(client, db_session, receiver):
    from app.features.alert import crud as alert_crud
    from app.features.base import utcnow
    from app.features.setting import crud as setting_crud
    from app.features.setting.crud import KEY_ALERT_AUTO_CHECK
    from app.features.user.permissions import BuiltinGroup
    from tests.scope_helpers import machine

    admin = await account(client, db_session, "rb@lycee.test", [BuiltinGroup.ADMIN])
    await _create(client, admin)
    await setting_crud.set_value(
        db_session, KEY_ALERT_AUTO_CHECK, ["disk_low"], actor="test"
    )
    for name in ("PC-D1", "PC-D2", "PC-D3"):
        await machine(
            db_session,
            name,
            last_seen=utcnow(),
            first_seen=utcnow() - timedelta(days=90),
            system_volume_total_mb=100_000,
            system_volume_free_mb=1_000,
        )
    await db_session.commit()
    result = await alert_crud.evaluate(db_session, utcnow())
    await db_session.commit()
    assert result.checks_opened == 3
    [row] = await _deliveries(db_session, "check.created")
    data = row.payload["data"]
    assert data["total"] == 3
    assert {i["hostname"] for i in data["items"]} == {"PC-D1", "PC-D2", "PC-D3"}
    assert all(i["check_id"] and "instructions" in i for i in data["items"])


# --- The tokens -----------------------------------------------------------------


async def _token(client, headers, **fields):
    body = {"name": "Script", "current_password": STRONG, **fields}
    resp = await client.post(TOKENS, headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json(), {"Authorization": f"Bearer {resp.json()['token']}"}


async def test_making_a_token_takes_the_password(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "ta@lycee.test", [BuiltinGroup.ADMIN])
    resp = await client.post(TOKENS, headers=admin, json={"name": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "password.current.invalid"
    resp = await client.post(
        TOKENS, headers=admin, json={"name": "x", "current_password": "nope"}
    )
    assert resp.status_code == 400
    await _token(client, admin)


async def test_with_a_second_factor_it_takes_a_code(client, db_session, monkeypatch):
    from app.core import totp
    from app.features.user.permissions import BuiltinGroup

    step = {"n": 70_000_000}
    monkeypatch.setattr(totp, "current_step", lambda now=None: step["n"])
    admin = await account(client, db_session, "tb@lycee.test", [BuiltinGroup.ADMIN])
    secret = (
        await client.post(
            "/api/v1/auth/totp/setup",
            headers=admin,
            json={"current_password": STRONG},
        )
    ).json()["secret"]
    await client.post(
        "/api/v1/auth/totp/confirm",
        headers=admin,
        json={"code": totp.code_at(secret, step["n"])},
    )
    resp = await client.post(
        TOKENS, headers=admin, json={"name": "x", "current_password": STRONG}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "auth.second_factor.code_invalid"
    step["n"] += 1
    await _token(client, admin, code=totp.code_at(secret, step["n"]))


async def test_a_directory_account_signs_in_again(client, db_session):
    from app.features.auth_session.models import AuthSession
    from app.features.base import utcnow
    from app.features.user.models import User
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "tc@lycee.test", [BuiltinGroup.ADMIN])
    user = (
        await db_session.exec(select(User).where(User.email == "tc@lycee.test"))
    ).one()
    user_id = user.id
    user.auth_source = "oidc"
    db_session.add(user)
    await db_session.commit()
    # Just signed in: its sign-in is the proof.
    await _token(client, admin, current_password=None)
    for row in (
        await db_session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all():
        row.created_at = utcnow() - timedelta(hours=1)
        db_session.add(row)
    await db_session.commit()
    resp = await client.post(TOKENS, headers=admin, json={"name": "plus tard"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "api_token.sign_in_again"


async def test_a_token_never_acts_on_its_own_account(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "td@lycee.test", [BuiltinGroup.ADMIN])
    other = await account(client, db_session, "te@lycee.test", [BuiltinGroup.ADMIN])
    _, token = await _token(client, admin, can_write=True)
    me = (await client.get("/api/v1/auth/me", headers=admin)).json()["id"]
    them = (await client.get("/api/v1/auth/me", headers=other)).json()["id"]
    for user_id in (me, me.upper(), me.replace("-", "")):
        for method, suffix, body in (
            ("PATCH", "", {"email": "evil@lycee.test"}),
            ("POST", "/reset-password", {}),
            ("POST", "/reset-second-factor", {}),
            ("DELETE", "", None),
        ):
            resp = await client.request(
                method, f"/api/v1/users/{user_id}{suffix}", headers=token, json=body
            )
            assert resp.status_code == 403, (method, suffix, resp.text)
            assert resp.json()["error"]["code"] == "api_token.forbidden_here"
    # Reading itself, and acting on another account, as its rights allow.
    assert (await client.get(f"/api/v1/users/{me}", headers=token)).status_code in (
        200,
        405,
    )
    resp = await client.patch(
        f"/api/v1/users/{them}", headers=token, json={"full_name": "Autre"}
    )
    assert resp.status_code == 200, resp.text


async def test_no_token_around_a_required_second_factor(client, db_session):
    from app.features.user.permissions import ALL_PERMISSIONS, BuiltinGroup

    g = await group(db_session, "Jetons MFA", ALL_PERMISSIONS, None)
    headers = await account(client, db_session, "tf@lycee.test", [g.id])
    _, token = await _token(client, headers, can_write=True)
    assert (await client.get("/api/v1/machines", headers=token)).status_code == 200
    admin = await account(client, db_session, "tg@lycee.test", [BuiltinGroup.ADMIN])
    await client.patch(
        f"/api/v1/groups/{g.id}", headers=admin, json={"mfa_required": True}
    )
    resp = await client.get("/api/v1/machines", headers=token)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "auth.second_factor.not_enrolled"


async def test_revoked_with_the_second_factor_reset_and_the_deactivation(
    client, db_session
):
    from app.features.audit.models import AuditEntry
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "th@lycee.test", [BuiltinGroup.ADMIN])
    owner = await account(client, db_session, "ti@lycee.test", [BuiltinGroup.ADMIN])
    owner_id = (await client.get("/api/v1/auth/me", headers=owner)).json()["id"]
    _, token = await _token(client, owner)
    resp = await client.post(
        f"/api/v1/users/{owner_id}/reset-second-factor", headers=admin, json={}
    )
    assert resp.status_code == 204, resp.text
    assert (await client.get("/api/v1/machines", headers=token)).status_code == 401

    owner = await login(client, "ti@lycee.test")
    body, token = await _token(client, owner, name="Deux")
    resp = await client.patch(
        f"/api/v1/users/{owner_id}", headers=admin, json={"is_active": False}
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get("/api/v1/machines", headers=token)).status_code == 401

    # Revoked by its owner: in the journal.
    tok, _ = await _token(client, admin, name="Trois")
    assert (
        await client.delete(f"{TOKENS}/{tok['id']}", headers=admin)
    ).status_code == 204
    actions = [
        e.action
        for e in (
            await db_session.exec(
                select(AuditEntry).where(AuditEntry.action == "api_token.revoke")
            )
        ).all()
    ]
    assert actions == ["api_token.revoke"]
    _ = body


async def test_the_live_limit_and_the_list(client, db_session, monkeypatch):
    from app.features.api_token import crud as api_tokens
    from app.features.api_token.models import ApiToken
    from app.features.base import utcnow
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "tj@lycee.test", [BuiltinGroup.ADMIN])
    monkeypatch.setattr(api_tokens, "MAX_ACTIVE", 2)
    first, _ = await _token(client, admin, name="Premier")
    await _token(client, admin, name="Second")
    resp = await client.post(
        TOKENS, headers=admin, json={"name": "x", "current_password": STRONG}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "api_token.too_many"
    # Many ended tokens, newer than a live one: the live one is still listed.
    row = await db_session.get(ApiToken, uuid.UUID(first["id"]))
    for n in range(120):
        db_session.add(
            ApiToken(
                user_id=row.user_id,
                name=f"vieux {n}",
                token_hash=f"h{n:062d}",
                prefix="tiai_pat_old",
                created_at=utcnow(),
                expires_at=utcnow() + timedelta(days=1),
                revoked_at=utcnow(),
            )
        )
    await db_session.commit()
    listed = (await client.get(TOKENS, headers=admin)).json()
    assert {t["name"] for t in listed[:2]} == {"Premier", "Second"}
    assert len(listed) == 2 + 50


async def test_last_use_is_written_at_most_once_a_minute(client, db_session):
    from app.features.api_token.models import ApiToken
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "tk@lycee.test", [BuiltinGroup.ADMIN])
    body, token = await _token(client, admin)
    await client.get("/api/v1/machines", headers=token)
    row = await db_session.get(ApiToken, uuid.UUID(body["id"]))
    await db_session.refresh(row)
    first = row.last_used_at
    assert first is not None
    await client.get("/api/v1/machines", headers=token)
    await db_session.refresh(row)
    assert row.last_used_at == first


# --- C7: a group change applies the obligation at once --------------------------


async def test_joining_a_group_that_requires_it_narrows_open_sessions(
    client, db_session
):
    from app.features.user.models import Group
    from app.features.user.permissions import ALL_PERMISSIONS, BuiltinGroup

    strict = await group(db_session, "Strict", ALL_PERMISSIONS, None)
    row = await db_session.get(Group, strict.id)
    row.mfa_required = True
    db_session.add(row)
    await db_session.commit()
    loose = await group(db_session, "Souple", ALL_PERMISSIONS, None)
    headers = await account(client, db_session, "tl@lycee.test", [loose.id])
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()["id"]
    admin = await account(client, db_session, "tm@lycee.test", [BuiltinGroup.ADMIN])
    resp = await client.patch(
        f"/api/v1/users/{me}",
        headers=admin,
        json={"group_ids": [str(loose.id), str(strict.id)]},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.get("/api/v1/machines", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "auth.second_factor.not_enrolled"


# --- The second pass over the fixes ---------------------------------------------


async def test_the_environment_proxy_is_used_by_name(resolver, monkeypatch):
    """HTTPS_PROXY from Docker: the send goes through it with the host's
    name, not pinned to an address the proxy would put in the handshake."""
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    monkeypatch.setattr(settings, "WEBHOOK_PROXY_URL", None)
    monkeypatch.setattr(deliver, "TRANSPORT", None)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.lycee.local:3128")
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    url = httpx.URL("https://pub.example/in")
    assert deliver._proxy_for(url) == "http://proxy.lycee.local:3128"
    sent: list[tuple[httpx.URL, str | None]] = []

    async def fake_send(url, proxy, headers, extensions, body):
        sent.append((url, proxy))
        return 200

    monkeypatch.setattr(deliver, "_send", fake_send)
    assert await deliver.post("https://pub.example/in", b"{}", "s", "test", "i") == 200
    assert sent == [(url, "http://proxy.lycee.local:3128")]
    # NO_PROXY honoured: pinned again.
    monkeypatch.setenv("NO_PROXY", "pub.example")
    assert deliver._proxy_for(url) is None
    sent.clear()
    await deliver.post("https://pub.example/in", b"{}", "s", "test", "i")
    assert sent[0][0].host == "93.184.216.34" and sent[0][1] is None


async def test_each_checked_address_in_turn(resolver, monkeypatch):
    tried: list[str] = []

    async def getaddrinfo(host, port, **kwargs):
        if not str(host).endswith(".example"):
            return await resolver.real(host, port, **kwargs)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 0)),
        ]

    def handler(request):
        tried.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    monkeypatch.setattr(deliver, "TRANSPORT", httpx.MockTransport(handler))
    assert await deliver.post("https://two.example/x", b"{}", "s", "test", "i") == 200
    assert tried == ["93.184.216.34", "93.184.216.35"]


async def test_an_allowed_host_written_in_unicode(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", ["chat.lycée.local"])
    scheme, host, allowed = destination.parse("http://chat.lycée.local/hook")
    assert (scheme, host, allowed) == ("http", "chat.xn--lyce-dpa.local", True)


async def test_a_slow_resolver_counts_in_the_deadline(monkeypatch):
    async def slow(host, port, **kwargs):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", slow)
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    monkeypatch.setattr(settings, "WEBHOOK_TIMEOUT_SECONDS", 1)
    with pytest.raises(TimeoutError):
        await deliver.post("https://slow.example/x", b"{}", "s", "test", "i")


async def test_answering_webhooks_go_first(client, db_session, receiver):
    from app.features.webhook.models import Webhook, WebhookDelivery

    sites = await two_sites(client, db_session)
    dead = await _create(client, sites.admin, name="Mort", url=f"https://{DEAD}/x")
    alive = await _create(client, sites.admin, name="Vivant")
    row = await db_session.get(Webhook, uuid.UUID(dead["id"]))
    row.consecutive_failures = 3
    db_session.add(row)
    # The failing webhook's deliveries are the oldest.
    for hook in (dead, dead, alive):
        db_session.add(
            WebhookDelivery(
                webhook_id=uuid.UUID(hook["id"]), event="check.created", payload={}
            )
        )
        await db_session.commit()
    claimed = await deliver._claim(db_session, 50)
    assert [str(c[5]) for c in claimed] == [alive["id"], dead["id"], dead["id"]]


async def test_the_password_proof_has_a_budget(client, db_session):
    from app.features.user.models import User
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "tn@lycee.test", [BuiltinGroup.ADMIN])
    body = {"name": "x", "current_password": "wrong"}
    for _ in range(4):
        resp = await client.post(TOKENS, headers=admin, json=body)
        assert resp.status_code == 400
    # The fifth wrong one ends the session: no endless guessing through it.
    resp = await client.post(TOKENS, headers=admin, json=body)
    assert resp.status_code == 401
    resp = await client.post(
        TOKENS, headers=admin, json={"name": "x", "current_password": STRONG}
    )
    assert resp.status_code == 401
    user = (
        await db_session.exec(select(User).where(User.email == "tn@lycee.test"))
    ).one()
    await db_session.refresh(user)
    # Each wrong one counted towards the account's lock, like a login.
    assert user.last_failed_login_at is not None and user.locked_until is not None


async def test_alert_checks_word_each_reason():
    from app.features.webhook.texts import text

    data = {
        "total": 2,
        "instructions": None,
        "items": [
            {"hostname": "PC1", "instructions": "Disque presque plein"},
            {"hostname": "PC2", "instructions": "Inactif"},
        ],
    }
    assert text("check.created", data, "fr") == (
        "Vérification demandée sur PC1 (Disque presque plein), PC2 (Inactif)"
    )
