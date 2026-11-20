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
    # The audit line names the rules by their codes.
    entries = (
        await client.get(
            "/api/v1/audit", headers=headers, params={"action": "settings.update"}
        )
    ).json()["items"]
    details = entries[0]["details"]
    assert details["alert_enabled_rules"] == "inactive, disk_low, inactive"
    assert details["alert_auto_check_rules"] == "disk_unhealthy"
    assert details["alert_forbidden_software"] == "uTorrent, TeamViewer"

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


async def test_list_filters_by_rule_and_state(client, db_session):
    sites = await two_sites(client, db_session)
    await _alert(db_session, sites.a.id)
    await _alert(db_session, sites.a.id, "inactive", resolved=True)
    await _alert(db_session, sites.b.id, "os_unsupported")

    async def rules(**params):
        resp = await client.get("/api/v1/alerts", headers=sites.admin, params=params)
        assert resp.status_code == 200, resp.text
        return sorted(a["rule"] for a in resp.json()["items"])

    assert await rules(rule="disk_low") == ["disk_low"]
    assert await rules(rule="inactive") == []
    assert await rules(state="resolved") == ["inactive"]
    assert await rules(state="all") == ["disk_low", "inactive", "os_unsupported"]
    assert await rules(rule="inactive", state="all") == ["inactive"]


async def test_warranty_date_needs_asset_read(client, db_session):
    """The warranty's end is purchase data: a technician (machine:read, no
    asset:read) reads that the warranty ends within the threshold, not when."""
    from tests.test_api_checks import _tech

    sites = await two_sites(client, db_session)
    await _alert(
        db_session,
        sites.a.id,
        "warranty_ending",
        warranty_end="2026-12-01",
        threshold_days=30,
    )
    tech, _ = await _tech(client, db_session)

    resp = await client.get("/api/v1/alerts", headers=sites.admin)
    [alert] = resp.json()["items"]
    assert alert["detail"] == {"warranty_end": "2026-12-01", "threshold_days": 30}

    resp = await client.get("/api/v1/alerts", headers=tech)
    assert resp.status_code == 200, resp.text
    [alert] = resp.json()["items"]
    assert alert["detail"] == {"threshold_days": 30}


async def test_warranty_check_does_not_carry_the_date(db_session):
    from app.features.alert.texts import check_instructions, worded_instructions
    from app.features.user.models import Language

    code, params, french = check_instructions(
        "warranty_ending", {"warranty_end": "2026-12-01", "threshold_days": 30}
    )
    assert code == "alert.warranty_ending"
    assert params == {"threshold_days": 30}
    assert french == "Alerte : La garantie se termine dans moins de 30 jours."
    assert (
        worded_instructions(french, code, params, Language.EN)
        == "Alert: The warranty ends within 30 days."
    )
    # Typed by someone: as typed, whatever the language.
    assert worded_instructions("Changer la souris", None, None, Language.EN) == (
        "Changer la souris"
    )


async def test_check_badge_follows_the_verification(client, db_session):
    """« Vérification demandée » only while the verification is open."""
    from app.features.alert.models import MachineAlert
    from app.features.check.models import MachineCheck

    sites = await two_sites(client, db_session)
    check = MachineCheck(machine_id=sites.a.id, requested_by="Tia'i")
    db_session.add(check)
    await db_session.commit()
    await db_session.refresh(check)
    check_id = check.id
    db_session.add(
        MachineAlert(
            machine_id=sites.a.id,
            rule="disk_low",
            opened_at=NOW,
            detail={"free_percent": 1.0},
            check_id=check_id,
        )
    )
    await db_session.commit()

    async def badge():
        resp = await client.get("/api/v1/alerts", headers=sites.admin)
        [alert] = resp.json()["items"]
        assert alert["check_id"] == str(check_id)
        return alert["check_open"]

    assert await badge() is True
    closed = await db_session.get(MachineCheck, check_id)
    closed.closed_at = NOW
    db_session.add(closed)
    await db_session.commit()
    assert await badge() is False


async def test_reassigning_keeps_the_coded_instructions(
    client, db_session, monkeypatch
):
    """The console sends the text back with a reassignment: the code stays,
    and the assignee's mail and the export word it in their language. Only a
    text changed by hand drops it."""
    from app.features.check.models import MachineCheck
    from app.features.notification.models import EmailOutbox
    from app.features.user.models import Language, User
    from tests.test_api_checks import _tech

    monkeypatch.setattr("app.core.config.settings.MAILGUN_API_KEY", "key")
    monkeypatch.setattr("app.core.config.settings.MAILGUN_DOMAIN", "mg.test")
    headers, _ = await _admin(client, db_session)
    _, tech_id = await _tech(client, db_session)
    tech = await db_session.get(User, uuid.UUID(tech_id))
    tech.language = Language.EN.value
    db_session.add(tech)
    m = await two_sites_machine(db_session)
    french = (
        "Alerte : Il reste 2.0 % d'espace libre sur le volume système (seuil : 10 %)."
    )
    check = MachineCheck(
        machine_id=m,
        requested_by="Tia'i",
        instructions=french,
        instructions_code="alert.disk_low",
        instructions_params={"free_percent": 2.0, "threshold_percent": 10},
    )
    db_session.add(check)
    await db_session.commit()
    await db_session.refresh(check)
    url = f"/api/v1/checks/{check.id}"

    resp = await client.patch(
        url, headers=headers, json={"assigned_to_id": tech_id, "instructions": french}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["instructions_code"] == "alert.disk_low"
    assert body["instructions_params"]["free_percent"] == 2.0
    db_session.expire_all()
    [mail] = (
        await db_session.exec(
            select(EmailOutbox).where(col(EmailOutbox.to_address) == "tech@test.local")
        )
    ).all()
    assert "Alert: 2.0 % free space left on the system volume" in mail.body
    assert "Il reste" not in mail.body

    resp = await client.get(
        "/api/v1/machines/export.csv?columns=hostname,check_instructions&lang=en",
        headers=headers,
    )
    assert "Alert: 2.0 % free space left" in resp.text

    resp = await client.patch(
        url, headers=headers, json={"instructions": "Vider la corbeille"}
    )
    body = resp.json()
    assert body["instructions"] == "Vider la corbeille"
    assert body["instructions_code"] is None
    assert body["instructions_params"] is None


async def two_sites_machine(db_session):
    from tests.scope_helpers import machine

    return (await machine(db_session, "PC-CHECK")).id


async def test_digest_alerts_are_scoped(client, db_session):
    from app.features.notification.digest import build_digest
    from app.features.user.scope import Scope
    from tests.scope_helpers import SITE_A

    sites = await two_sites(client, db_session)
    await _alert(db_session, sites.a.id, "disk_low")
    await _alert(db_session, sites.b.id, "os_unsupported")
    digest = await build_digest(db_session, Scope(locations=frozenset({SITE_A})))
    assert digest.alerts_by_rule == {"disk_low": 1}
    digest = await build_digest(db_session)
    assert digest.alerts_by_rule == {"disk_low": 1, "os_unsupported": 1}


async def test_disk_mail_follows_scope_and_language(client, db_session, monkeypatch):
    """A site-A account hears of site A's disks only, in its own language;
    with mail turned off nothing is queued."""
    from app.core import worker
    from app.features.inventory.models import Disk
    from app.features.notification.models import EmailOutbox
    from app.features.user.models import EmailPreference, Language, User

    monkeypatch.setattr(worker, "engine", db_session.bind)
    sites = await two_sites(client, db_session)
    for email, language in (
        ("tech-a@test.local", Language.EN),
        ("admin@test.local", Language.FR),
    ):
        user = (
            await db_session.exec(select(User).where(col(User.email) == email))
        ).one()
        user.email_preference = EmailPreference.IMMEDIATE
        user.language = language.value
        db_session.add(user)
    db_session.add(
        Disk(
            machine_id=sites.b.id, device_id="0", model="WD B", health_status="Warning"
        )
    )
    await db_session.commit()

    async def mails():
        db_session.expire_all()
        rows = (await db_session.exec(select(EmailOutbox))).all()
        return {row.to_address: row for row in rows}

    # Mail not configured: the alert opens, nothing is queued.
    assert await worker.evaluate_alerts() == 1
    assert await mails() == {}

    monkeypatch.setattr("app.core.config.settings.MAILGUN_API_KEY", "key")
    monkeypatch.setattr("app.core.config.settings.MAILGUN_DOMAIN", "mg.test")
    db_session.add(
        Disk(
            machine_id=sites.a.id, device_id="0", model="WD A", health_status="Warning"
        )
    )
    await db_session.commit()
    assert await worker.evaluate_alerts() == 1
    found = await mails()
    assert set(found) == {"tech-a@test.local", "admin@test.local"}
    assert "unhealthy disk on PC-A" in found["tech-a@test.local"].subject
    assert "WD B" not in found["tech-a@test.local"].body
    assert "PC-A" in found["admin@test.local"].subject
    assert "unhealthy" not in found["admin@test.local"].subject
