"""Outbound webhooks (C8): destinations, the queue, signing, retries,
formats, the API and the events raised by the console."""

import hashlib
import hmac
import json

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.features.webhook import deliver, destination
from tests.scope_helpers import account, two_sites

API = "/api/v1/webhooks"
HOST = "hooks.example.test"
URL = f"https://{HOST}/in"


class Receiver:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


@pytest.fixture
def receiver(monkeypatch):
    r = Receiver()
    # The receiver's host is declared: no DNS in the tests.
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [HOST])
    monkeypatch.setattr(deliver, "TRANSPORT", httpx.MockTransport(r.handler))
    return r


async def _create(client, headers, **fields):
    body = {"name": "Canal", "url": URL, "events": ["check.created"], **fields}
    resp = await client.post(API, headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _drain(db_session):
    return await deliver.send_pending(db_session, budget_seconds=None)


def _verify(request: httpx.Request, secret: str) -> bool:
    parts = dict(
        p.split("=", 1) for p in request.headers["X-Tiai-Signature"].split(",")
    )
    mac = hmac.new(
        secret.encode(), f"{parts['t']}.".encode() + request.content, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(mac, parts["v1"])


# --- Destinations ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://example.com/x", destination.SCHEME),
        ("ftp://example.com/x", destination.SCHEME),
        ("https://user:pw@example.com/x", destination.CREDENTIALS),
        ("https:///nohost", destination.HOST),
        ("https://127.0.0.1/x", destination.INTERNAL),
        ("https://10.1.2.3/x", destination.INTERNAL),
        ("https://192.168.0.10/x", destination.INTERNAL),
        ("https://169.254.169.254/latest/meta-data", destination.INTERNAL),
        ("https://[::1]/x", destination.INTERNAL),
        ("https://[::ffff:10.0.0.1]/x", destination.INTERNAL),
        ("https://localhost/x", destination.INTERNAL),
    ],
)
async def test_refused_destinations(url, code, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", [])
    with pytest.raises(destination.DestinationError) as info:
        await destination.check(url)
    assert info.value.code == code


async def test_allowed_destinations(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", ["chat.lycee.local"])
    await destination.check("https://93.184.216.34/hook")
    # Declared: internal and over http.
    await destination.check("http://chat.lycee.local:8065/hooks/abc")
    with pytest.raises(destination.DestinationError):
        await destination.check("http://other.lycee.local/hooks/abc")


# --- API ------------------------------------------------------------------------


async def test_create_shows_the_secret_once_and_checks_the_url(
    client, db_session, receiver
):
    from app.features.audit.models import AuditEntry
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "wa@lycee.test", [BuiltinGroup.ADMIN])
    hook = await _create(client, admin, events=["check.created", "alert.opened"])
    assert len(hook["secret"]) >= 40
    listed = (await client.get(API, headers=admin)).json()
    assert "secret" not in listed[0]
    assert listed[0]["events"] == ["check.created", "alert.opened"]

    resp = await client.post(
        API,
        headers=admin,
        json={"name": "X", "url": "https://10.0.0.5/x", "events": ["check.created"]},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "webhook.destination_refused"
    assert resp.json()["error"]["details"]["reason"] == "webhook.url.internal"
    resp = await client.post(
        API, headers=admin, json={"name": "X", "url": URL, "events": ["test"]}
    )
    assert resp.status_code == 422

    renewed = (await client.post(f"{API}/{hook['id']}/secret", headers=admin)).json()
    assert renewed["secret"] != hook["secret"]
    actions = [
        e.action
        for e in (
            await db_session.exec(
                select(AuditEntry).where(AuditEntry.resource_type == "webhook")
            )
        ).all()
    ]
    assert actions == ["webhook.create", "webhook.secret_renew"]


async def test_rights_and_scope(client, db_session, receiver):
    from app.features.user.permissions import BuiltinGroup

    sites = await two_sites(client, db_session)
    tech = await account(client, db_session, "te@lycee.test", [BuiltinGroup.TECHNICIAN])
    assert (await client.get(API, headers=tech)).status_code == 403
    # Every permission, but confined to a site: the parc's events are not its.
    assert (await client.get(API, headers=sites.scoped)).status_code == 403
    resp = await client.post(
        API,
        headers=sites.scoped,
        json={"name": "X", "url": URL, "events": ["check.created"]},
    )
    assert resp.status_code == 403


# --- Queue and delivery -----------------------------------------------------------


async def test_a_check_is_queued_signed_and_sent(client, db_session, receiver):
    from app.features.user.permissions import BuiltinGroup
    from app.features.webhook.models import WebhookDelivery

    sites = await two_sites(client, db_session)
    hook = await _create(client, sites.admin)
    await _create(client, sites.admin, name="Autre", events=["alert.opened"])
    resp = await client.post(
        f"/api/v1/machines/{sites.a.id}/check",
        headers=sites.admin,
        json={"instructions": "Écran noir"},
    )
    assert resp.status_code in (200, 201), resp.text
    rows = (await db_session.exec(select(WebhookDelivery))).all()
    assert [r.event for r in rows] == ["check.created"]

    assert await _drain(db_session) == 1
    request = receiver.requests[0]
    assert request.headers["X-Tiai-Event"] == "check.created"
    assert _verify(request, hook["secret"])
    body = json.loads(request.content)
    assert body["event"] == "check.created"
    assert body["data"]["machine"]["hostname"] == "PC-A"
    assert body["data"]["instructions"] == "Écran noir"
    listed = (await client.get(API, headers=sites.admin)).json()
    assert listed[0]["last_success_at"] is not None
    history = (
        await client.get(f"{API}/{hook['id']}/deliveries", headers=sites.admin)
    ).json()
    assert history[0]["status"] == "sent"
    _ = BuiltinGroup


async def test_failures_are_retried_then_given_up(
    client, db_session, receiver, monkeypatch
):
    from app.features.base import utcnow
    from app.features.webhook.models import WebhookDelivery

    sites = await two_sites(client, db_session)
    await _create(client, sites.admin)
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    receiver.status = 500
    monkeypatch.setattr(settings, "WEBHOOK_MAX_ATTEMPTS", 2)
    assert await _drain(db_session) == 0
    row = (await db_session.exec(select(WebhookDelivery))).one()
    await db_session.refresh(row)
    assert (row.status, row.attempts, row.response_status) == ("pending", 1, 500)
    assert row.next_attempt_at > utcnow()
    # Not due yet: nothing tried.
    assert await _drain(db_session) == 0
    assert len(receiver.requests) == 1
    row.next_attempt_at = utcnow()
    db_session.add(row)
    await db_session.commit()
    await _drain(db_session)
    await db_session.refresh(row)
    assert (row.status, row.attempts) == ("failed", 2)
    listed = (await client.get(API, headers=sites.admin)).json()
    assert (
        listed[0]["consecutive_failures"] == 2 and listed[0]["last_error"] == "HTTP 500"
    )


async def test_chat_formats_word_the_event(client, db_session, receiver):
    sites = await two_sites(client, db_session)
    await _create(client, sites.admin, format="teams", language="fr")
    await _create(client, sites.admin, name="MM", format="mattermost", language="en")
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check",
        headers=sites.admin,
        json={"instructions": "Clavier"},
    )
    await _drain(db_session)
    texts = sorted(json.loads(r.content)["text"] for r in receiver.requests)
    assert texts == [
        "Check requested on PC-A: Clavier",
        "Vérification demandée sur PC-A : Clavier",
    ]


async def test_test_button_and_disabled_hooks(client, db_session, receiver):
    from app.features.webhook.models import WebhookDelivery

    sites = await two_sites(client, db_session)
    hook = await _create(client, sites.admin)
    resp = await client.post(f"{API}/{hook['id']}/test", headers=sites.admin)
    assert resp.json() == {"ok": True, "response_status": 200, "error": None}
    assert json.loads(receiver.requests[0].content)["event"] == "test"
    receiver.status = 404
    resp = await client.post(f"{API}/{hook['id']}/test", headers=sites.admin)
    assert resp.json()["ok"] is False and resp.json()["error"] == "HTTP 404"

    await client.patch(
        f"{API}/{hook['id']}", headers=sites.admin, json={"enabled": False}
    )
    before = len((await db_session.exec(select(WebhookDelivery))).all())
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    after = len((await db_session.exec(select(WebhookDelivery))).all())
    assert after == before


async def test_events_raised_by_the_console(client, db_session, receiver):
    from app.features.webhook import emit
    from app.features.webhook.models import WebhookDelivery

    sites = await two_sites(client, db_session)
    await _create(
        client,
        sites.admin,
        events=[
            "alert.opened",
            "alert.resolved",
            "check.closed",
            "command.failed",
            "threat.detected",
        ],
    )
    queued = await emit.alerts_changed(
        db_session,
        [(sites.a.id, "disk_low", {"free_percent": 3})],
        [(sites.b.id, "inactive")],
    )
    assert queued == 2
    await db_session.commit()
    payloads = {
        r.event: r.payload
        for r in (await db_session.exec(select(WebhookDelivery))).all()
    }
    assert payloads["alert.opened"]["data"]["items"][0]["hostname"] == "PC-A"
    assert payloads["alert.resolved"]["data"]["total"] == 1

    # Closing a check through the API.
    check = (
        await client.post(
            f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
        )
    ).json()
    resp = await client.post(
        f"/api/v1/checks/{check['id']}/close", headers=sites.admin, json={"note": "OK"}
    )
    assert resp.status_code == 200, resp.text
    events = [r.event for r in (await db_session.exec(select(WebhookDelivery))).all()]
    assert "check.closed" in events


async def test_purge_keeps_what_is_owed(client, db_session, receiver):
    from datetime import timedelta

    from app.features.base import utcnow
    from app.features.webhook.models import WebhookDelivery

    sites = await two_sites(client, db_session)
    await _create(client, sites.admin)
    await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=sites.admin, json={}
    )
    await _drain(db_session)
    sent = (await db_session.exec(select(WebhookDelivery))).one()
    old = utcnow() - timedelta(days=settings.WEBHOOK_DELIVERY_RETENTION_DAYS + 1)
    sent.created_at = old
    db_session.add(sent)
    pending = WebhookDelivery(
        webhook_id=sent.webhook_id, event="check.created", payload={}, created_at=old
    )
    db_session.add(pending)
    await db_session.commit()
    assert await deliver.purge(db_session) == 1
    left = (await db_session.exec(select(WebhookDelivery))).all()
    assert [r.status for r in left] == ["pending"]
