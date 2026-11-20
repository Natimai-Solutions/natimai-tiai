"""Alerts through the API (require TIAI_TEST_DATABASE_URL): the list and its
scope, the machine list's filter, the dashboard's counts, the settings, the
digest's section, the immediate mail and the worker's job."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import col, select

from tests.scope_helpers import two_sites
from tests.test_api_maintenance import _admin

NOW = datetime.now(UTC)


async def _alert(db_session, machine_id, rule="disk_low", *, resolved=False, **detail):
    from app.features.alert.models import MachineAlert

    db_session.add(
        MachineAlert(
            machine_id=machine_id,
            rule=rule,
            opened_at=NOW - timedelta(days=2),
            resolved_at=NOW - timedelta(days=1) if resolved else None,
            detail=detail or {"free_percent": 3.0},
        )
    )
    await db_session.commit()


async def test_list_is_scoped_and_counts_per_rule(client, db_session):
    sites = await two_sites(client, db_session)
    await _alert(db_session, sites.a.id)
    await _alert(db_session, sites.a.id, "inactive", resolved=True)
    await _alert(db_session, sites.b.id, "os_unsupported")

    resp = await client.get("/api/v1/alerts", headers=sites.admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["open_by_rule"]["disk_low"] == 1
    assert body["open_by_rule"]["os_unsupported"] == 1
    assert body["open_by_rule"]["inactive"] == 0

    resp = await client.get("/api/v1/alerts", headers=sites.scoped)
    body = resp.json()
    assert [a["machine"]["hostname"] for a in body["items"]] == ["PC-A"]
    assert body["open_by_rule"]["os_unsupported"] == 0

    # A poste's history, open first.
    resp = await client.get(
        "/api/v1/alerts",
        headers=sites.scoped,
        params={"machine_id": str(sites.a.id), "state": "all"},
    )
    assert [a["rule"] for a in resp.json()["items"]] == ["disk_low", "inactive"]

    # The poste of the other site is out of reach.
    resp = await client.get(
        "/api/v1/alerts", headers=sites.scoped, params={"machine_id": str(sites.b.id)}
    )
    assert resp.status_code == 404

    resp = await client.get(
        "/api/v1/alerts", headers=sites.admin, params={"rule": "nope"}
    )
    assert resp.status_code == 422


async def test_machine_list_filter_and_dashboard(client, db_session):
    sites = await two_sites(client, db_session)
    await _alert(db_session, sites.a.id)
    await _alert(db_session, sites.b.id, "inactive")
    await _alert(db_session, sites.b.id, "disk_low", resolved=True)

    async def hosts(**params):
        resp = await client.get("/api/v1/machines", headers=sites.admin, params=params)
        assert resp.status_code == 200, resp.text
        return sorted(m["hostname"] for m in resp.json()["items"])

    assert await hosts(alert="any") == ["PC-A", "PC-B"]
    assert await hosts(alert="disk_low") == ["PC-A"]
    resp = await client.get(
        "/api/v1/machines", headers=sites.admin, params={"alert": "nope"}
    )
    assert resp.status_code == 422

    resp = await client.get("/api/v1/stats/overview", headers=sites.admin)
    body = resp.json()
    assert body["machines_with_alerts"] == 2
    assert body["alerts_by_rule"]["disk_low"] == 1
    assert body["alerts_by_rule"]["inactive"] == 1

    resp = await client.get("/api/v1/stats/overview", headers=sites.scoped)
    assert resp.json()["machines_with_alerts"] == 1


async def test_settings_round_trip(client, db_session):
    headers, _ = await _admin(client, db_session)
    resp = await client.get("/api/v1/settings", headers=headers)
    body = resp.json()
    assert body["alert_rules"] == body["alert_enabled_rules"]
    assert "disk_low" in body["alert_rules"]
    assert body["alert_reboot_pending_days"] == 7
    assert body["alert_unencrypted_scope"] == "laptops"
    assert body["alert_forbidden_software"] == []

    resp = await client.patch(
        "/api/v1/settings",
        headers=headers,
        json={
            "alert_enabled_rules": ["inactive", "disk_low", "inactive"],
            "alert_reboot_pending_days": 14,
            "alert_unencrypted_scope": "all",
            "alert_forbidden_software": ["  uTorrent ", "TeamViewer"],
            "alert_auto_check_rules": ["disk_unhealthy"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Returned in the catalogue's order, duplicates gone.
    assert body["alert_enabled_rules"] == ["disk_low", "inactive"]
    assert body["alert_reboot_pending_days"] == 14
    assert body["alert_unencrypted_scope"] == "all"
    assert body["alert_forbidden_software"] == ["uTorrent", "TeamViewer"]
    assert body["alert_auto_check_rules"] == ["disk_unhealthy"]

    # Null hands a setting back to its default.
    resp = await client.patch(
        "/api/v1/settings",
        headers=headers,
        json={"alert_enabled_rules": None, "alert_reboot_pending_days": None},
    )
    body = resp.json()
    assert body["alert_enabled_rules"] == body["alert_rules"]
    assert body["alert_reboot_pending_days"] == 7

    for bad in (
        {"alert_enabled_rules": ["nope"]},
        {"alert_reboot_pending_days": 0},
        {"alert_unencrypted_scope": "desktops"},
        {"alert_forbidden_software": ["x"]},
    ):
        resp = await client.patch("/api/v1/settings", headers=headers, json=bad)
        assert resp.status_code == 422, bad


async def test_digest_lists_open_alerts(db_session):
    from app.features.notification.digest import build_digest, render_digest
    from app.features.user.models import Language
    from tests.scope_helpers import machine

    a = await machine(db_session, "PC-A")
    await _alert(db_session, a.id, "os_unsupported")
    await _alert(db_session, a.id, "disk_low", resolved=True)
    digest = await build_digest(db_session)
    assert digest.alerts_by_rule == {"os_unsupported": 1}
    _, body = render_digest(digest, language=Language.FR)
    assert "ALERTES OUVERTES\n  Windows hors support : 1 poste(s)" in body
    _, body = render_digest(digest, language=Language.EN)
    assert "OPEN ALERTS\n  Windows out of support: 1 computer" in body


async def test_unhealthy_disk_is_mailed_once(client, db_session, monkeypatch):
    from app.core import worker
    from app.features.inventory.models import Disk
    from app.features.notification.models import EmailOutbox
    from app.features.user import crud as user_crud
    from app.features.user.models import EmailPreference
    from app.features.user.permissions import BuiltinGroup
    from tests.scope_helpers import machine

    monkeypatch.setattr(worker, "engine", db_session.bind)
    monkeypatch.setattr("app.core.config.settings.MAILGUN_API_KEY", "key")
    monkeypatch.setattr("app.core.config.settings.MAILGUN_DOMAIN", "mg.test")
    user = await user_crud.create_user(
        db_session,
        email="ops@test.local",
        password="correct-horse-battery",
        groups=[BuiltinGroup.ADMIN],
    )
    user.email_preference = EmailPreference.IMMEDIATE
    db_session.add(user)
    await db_session.commit()
    m = await machine(db_session, "PC-DISK")
    db_session.add(
        Disk(machine_id=m.id, device_id="0", model="WD Blue", health_status="Warning")
    )
    await db_session.commit()

    assert await worker.evaluate_alerts() == 1
    assert await worker.evaluate_alerts() == 0
    db_session.expire_all()
    mails = (
        await db_session.exec(
            select(EmailOutbox).where(col(EmailOutbox.to_address) == "ops@test.local")
        )
    ).all()
    assert len(mails) == 1
    assert "PC-DISK" in mails[0].subject
    assert "WD Blue" in mails[0].body


async def test_check_carries_coded_instructions(client, db_session):
    from app.features.check.models import MachineCheck
    from tests.scope_helpers import machine

    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1")
    db_session.add(
        MachineCheck(
            machine_id=m.id,
            requested_by="Tia'i",
            instructions="Alerte : …",
            instructions_code="alert.disk_low",
            instructions_params={"free_percent": 2.0},
        )
    )
    await db_session.commit()
    resp = await client.get("/api/v1/checks", headers=headers)
    [check] = resp.json()["items"]
    assert check["instructions_code"] == "alert.disk_low"
    assert check["instructions_params"] == {"free_percent": 2.0}
    assert uuid.UUID(check["machine_id"]) == m.id
