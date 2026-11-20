"""Compliance of the postes and third-party updates (C5): the inventory's
new readings, the checks, the summary the worker keeps, the list's filters,
the dashboard, the winget view and the settings."""

import uuid
from datetime import UTC, datetime, timedelta

from tests.scope_helpers import two_sites
from tests.test_api_inventory import (
    _admin_headers,
    _detail,
    _enroll,
    _heartbeat,
    _inventory,
)

NOW = datetime.now(UTC)
DOMAIN_SID = "S-1-5-21-1111-2222-3333"


def _policy(**overrides):
    from app.features.setting.crud import CompliancePolicy

    values = {
        "patch_grace_days": 14,
        "admins_allowed": (),
        "reboot_pending_days": 7,
        "unencrypted_scope": "laptops",
        "signature_max_age_days": 3,
    }
    values.update(overrides)
    return CompliancePolicy(**values)


def _states(results) -> dict[str, str]:
    return {r.check.value: r.state.value for r in results}


# --- The checks, pure ------------------------------------------------------


def test_unknown_is_not_counted_and_desktop_encryption_not_applicable():
    from app.features.compliance.checks import Facts, evaluate, summarize
    from app.features.machine.models import Machine

    m = Machine(machine_uuid="u", hw_chassis_type="desktop")
    results = evaluate(m, Facts(), _policy(), NOW)
    states = _states(results)
    assert states["encryption"] == "not_applicable"
    assert states["secure_boot"] == "unknown"
    assert states["firewall"] == "unknown"
    assert states["local_admins"] == "unknown"
    s = summarize(results)
    assert (s.passed, s.total, s.failed) == (0, 0, [])


def test_a_poste_failing_and_passing():
    from app.features.compliance.checks import Facts, evaluate, summarize
    from app.features.machine.models import Machine

    m = Machine(
        machine_uuid="u",
        hw_chassis_type="laptop",
        secure_boot=True,
        tpm_version="1.2",
        is_up_to_date=True,
        wu_pending_count=2,
        wu_reboot_required=True,
        wu_reboot_required_since=NOW - timedelta(days=10),
        os_version="Microsoft Windows 11 Pro 25H2 (Build 26200)",
        agent_version="0.9.0",
        firewall_domain=True,
        firewall_private=True,
        firewall_public=False,
        local_admins=[
            {"name": "PC\\Administrateur", "sid": f"{DOMAIN_SID}-500"},
            {"name": "LYCEE\\Admins du domaine", "sid": f"{DOMAIN_SID}-512"},
            {"name": "LYCEE\\GG-Techs", "sid": f"{DOMAIN_SID}-4100"},
            {"name": "PC\\eleve", "sid": f"{DOMAIN_SID}-1001"},
        ],
    )
    facts = Facts(
        system_encryption="FullyDecrypted",
        overdue_patches=["KB5063878"],
        outdated_agents=frozenset({"0.9.0"}),
    )
    results = evaluate(m, facts, _policy(admins_allowed=("gg-techs",)), NOW)
    states = _states(results)
    assert states == {
        "encryption": "fail",
        "secure_boot": "pass",
        "tpm": "fail",
        "antivirus": "pass",
        "patches": "fail",
        "reboot": "fail",
        "os_supported": "pass",
        "agent_current": "fail",
        "firewall": "fail",
        "local_admins": "fail",
    }
    detail = {r.check.value: r.detail for r in results}
    assert detail["firewall"] == {"profiles": ["public"]}
    # The built-in ones by SID, the allowed group by its bare name: only the
    # pupil's account is left.
    assert detail["local_admins"] == {"count": 1, "names": ["PC\\eleve"]}
    assert detail["patches"]["updates"] == ["KB5063878"]
    s = summarize(results)
    assert (s.passed, s.total) == (3, 10)
    assert "firewall" in s.failed


def test_a_reboot_within_the_delay_and_patches_in_grace_pass():
    from app.features.compliance.checks import Facts, evaluate
    from app.features.machine.models import Machine

    m = Machine(
        machine_uuid="u",
        wu_pending_count=1,
        wu_reboot_required=True,
        wu_reboot_required_since=NOW - timedelta(days=2),
    )
    states = _states(evaluate(m, Facts(overdue_patches=[]), _policy(), NOW))
    assert states["reboot"] == "pass"
    assert states["patches"] == "pass"


def test_a_builtin_sid_must_be_a_domain_or_local_account():
    from app.features.compliance.checks import extra_admins

    # A well-known SID ending in 500 that is not S-1-5-21 is not the
    # built-in Administrator.
    assert extra_admins([{"name": "X\\odd", "sid": "S-1-5-32-500"}], ()) == ["X\\odd"]
    assert extra_admins([{"name": "PC\\Admin", "sid": f"{DOMAIN_SID}-500"}], ()) == []
    assert extra_admins([{"name": "LYCEE\\Tech", "sid": None}], ("lycee\\tech",)) == []


# --- The inventory's new readings ---------------------------------------------


async def test_inventory_stores_and_clears_the_readings(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, str(uuid.uuid4()), hostname="PC-C5")
    report = _inventory(
        firewall={"domain": True, "private": True, "public": False},
        local_admins=[
            {"name": "PC\\Administrateur", "sid": f"{DOMAIN_SID}-500"},
            {"name": "", "sid": "S-1-5-21-9"},
        ],
        winget_packages=[
            {
                "id": "Mozilla.Firefox",
                "name": "Firefox",
                "version": "128.0",
                "available": "131.0",
            },
            {"id": "7zip.7zip", "name": "7-Zip", "version": "24.08"},
            {"id": "7zip.7zip", "name": "7-Zip dup", "version": "1"},
        ],
    )
    resp = await _heartbeat(client, enrolled["token"], inventory=report)
    assert resp.status_code == 200, resp.text

    detail = await _detail(client, headers, enrolled)
    assert detail["firewall_public"] is False and detail["firewall_domain"] is True
    # The nameless member is dropped.
    assert detail["local_admins"] == [
        {"name": "PC\\Administrateur", "sid": f"{DOMAIN_SID}-500"}
    ]
    assert [p["winget_id"] for p in detail["winget_packages"]] == [
        "7zip.7zip",
        "Mozilla.Firefox",
    ]
    assert detail["winget_reported_at"] is not None
    checks = {c["check"]: c for c in detail["compliance"]}
    assert checks["firewall"]["state"] == "fail"
    assert checks["firewall"]["detail"] == {"profiles": ["public"]}
    assert checks["local_admins"]["state"] == "pass"

    # The agent stops reporting them (a switch turned off, or an older
    # agent): the next inventory clears them.
    resp = await _heartbeat(client, enrolled["token"], inventory=_inventory(hash="h2"))
    assert resp.status_code == 200
    detail = await _detail(client, headers, enrolled)
    assert detail["local_admins"] is None
    assert detail["firewall_public"] is None
    assert detail["winget_packages"] == []
    assert detail["winget_reported_at"] is None


# --- The summary, the list and the dashboard ------------------------------------


async def _set(db_session, machine_id, **values):
    from app.features.machine.models import Machine

    m = await db_session.get(Machine, machine_id)
    for k, v in values.items():
        setattr(m, k, v)
    db_session.add(m)
    await db_session.commit()


async def test_worker_summary_feeds_the_list_and_the_dashboard(
    client, db_session, monkeypatch
):
    from app.core import worker

    monkeypatch.setattr(worker, "engine", db_session.bind)
    sites = await two_sites(client, db_session)
    await _set(
        db_session,
        sites.a.id,
        secure_boot=True,
        firewall_domain=True,
        firewall_private=True,
        firewall_public=True,
    )
    await _set(db_session, sites.b.id, secure_boot=False, firewall_domain=False)

    assert await worker.refresh_compliance() == 2
    # Nothing moved: nothing written.
    assert await worker.refresh_compliance() == 0

    async def hosts(headers=sites.admin, **params):
        resp = await client.get("/api/v1/machines", headers=headers, params=params)
        assert resp.status_code == 200, resp.text
        return sorted(m["hostname"] for m in resp.json()["items"])

    assert await hosts(compliance="passing") == ["PC-A"]
    assert await hosts(compliance="failing") == ["PC-B"]
    assert await hosts(compliance_check="firewall") == ["PC-B"]
    assert await hosts(compliance_check="tpm") == []
    assert await hosts(headers=sites.scoped, compliance="failing") == []
    resp = await client.get(
        "/api/v1/machines", headers=sites.admin, params={"compliance_check": "nope"}
    )
    assert resp.status_code == 422

    resp = await client.get("/api/v1/machines", headers=sites.admin)
    rows = {m["hostname"]: m for m in resp.json()["items"]}
    assert (rows["PC-A"]["compliance_passed"], rows["PC-A"]["compliance_total"]) == (
        2,
        2,
    )

    resp = await client.get("/api/v1/stats/overview", headers=sites.admin)
    body = resp.json()
    assert body["machines_compliant"] == 1
    assert body["machines_noncompliant"] == 1
    assert body["compliance_by_check"] == {"secure_boot": 1, "firewall": 1}
    resp = await client.get("/api/v1/stats/overview", headers=sites.scoped)
    body = resp.json()
    assert body["machines_noncompliant"] == 0
    assert body["compliance_by_check"] == {}


async def test_a_retired_poste_has_no_summary(client, db_session, monkeypatch):
    from app.core import worker

    monkeypatch.setattr(worker, "engine", db_session.bind)
    from app.features.asset.models import Asset, AssetStatus
    from app.features.machine.models import Machine

    sites = await two_sites(client, db_session)
    await _set(db_session, sites.b.id, secure_boot=False)
    db_session.add(Asset(machine_id=sites.b.id, status=AssetStatus.RETIRED))
    await db_session.commit()
    await worker.refresh_compliance()
    m = await db_session.get(Machine, sites.b.id)
    await db_session.refresh(m)
    assert m.compliance_total is None


async def test_patch_grace_follows_the_setting(client, db_session):
    from app.features.compliance import crud
    from app.features.windows_update.models import WindowsUpdate

    sites = await two_sites(client, db_session)
    await _set(db_session, sites.a.id, wu_pending_count=2)
    for kb, severity, age in (
        ("KB1", "Critical", 20),
        ("KB2", "moderate", 30),
        ("KB3", "important", 3),
    ):
        db_session.add(
            WindowsUpdate(
                machine_id=sites.a.id,
                update_id=kb,
                kb=kb,
                title=kb,
                severity=severity.lower(),
                first_seen=NOW - timedelta(days=age),
            )
        )
    await db_session.commit()
    from app.features.machine.models import Machine

    m = await db_session.get(Machine, sites.a.id)
    results = {r.check.value: r for r in await crud.for_machine(db_session, m, NOW)}
    assert results["patches"].state.value == "fail"
    assert results["patches"].detail["updates"] == ["KB1"]

    resp = await client.patch(
        "/api/v1/settings",
        headers=sites.admin,
        json={
            "compliance_patch_grace_days": 30,
            "compliance_admins_allowed": ["GG-Techs", "GG-Techs"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["compliance_patch_grace_days"] == 30
    assert body["compliance_admins_allowed"] == ["GG-Techs"]
    assert body["env_compliance_patch_grace_days"] == 14
    results = {r.check.value: r for r in await crud.for_machine(db_session, m, NOW)}
    assert results["patches"].state.value == "pass"


# --- Third-party updates -----------------------------------------------------------


async def test_winget_updates_rate_scope_and_list_filter(client, db_session):
    from app.features.inventory.models import WingetPackage

    sites = await two_sites(client, db_session)
    await _set(db_session, sites.a.id, winget_reported_at=NOW)
    await _set(db_session, sites.b.id, winget_reported_at=NOW)
    rows = [
        (sites.a.id, "Mozilla.Firefox", "128.0", "131.0"),
        (sites.b.id, "Mozilla.Firefox", "129.0", "131.0.2"),
        (sites.a.id, "7zip.7zip", "24.08", None),
        (sites.b.id, "7zip.7zip", "24.08", ""),
    ]
    for machine_id, wid, version, available in rows:
        db_session.add(
            WingetPackage(
                machine_id=machine_id,
                winget_id=wid,
                name=wid.split(".")[1],
                version=version,
                available=available,
            )
        )
    await db_session.commit()

    resp = await client.get("/api/v1/software/updates", headers=sites.admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reporting"] == 2
    first, second = body["items"]
    assert first["winget_id"] == "Mozilla.Firefox"
    assert (first["installed"], first["outdated"]) == (2, 2)
    assert first["available"] == "131.0.2"
    assert first["up_to_date_percent"] == 0.0
    assert (second["installed"], second["outdated"]) == (2, 0)
    assert second["up_to_date_percent"] == 100.0

    resp = await client.get(
        "/api/v1/software/updates", headers=sites.admin, params={"outdated_only": True}
    )
    assert [i["winget_id"] for i in resp.json()["items"]] == ["Mozilla.Firefox"]
    resp = await client.get(
        "/api/v1/software/updates", headers=sites.admin, params={"search": "zip"}
    )
    assert [i["winget_id"] for i in resp.json()["items"]] == ["7zip.7zip"]

    resp = await client.get("/api/v1/software/updates", headers=sites.scoped)
    body = resp.json()
    assert body["reporting"] == 1
    assert body["items"][0]["installed"] == 1
    assert body["items"][0]["available"] == "131.0"

    resp = await client.get(
        "/api/v1/machines",
        headers=sites.admin,
        params={"winget_outdated": "Mozilla.Firefox"},
    )
    assert sorted(m["hostname"] for m in resp.json()["items"]) == ["PC-A", "PC-B"]
    resp = await client.get(
        "/api/v1/machines", headers=sites.admin, params={"winget_outdated": "7zip.7zip"}
    )
    assert resp.json()["items"] == []
