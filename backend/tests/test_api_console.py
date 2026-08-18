"""Console endpoint integration tests (require TIAI_TEST_DATABASE_URL).

Covers M3: broadcast commands, command expiry, is_up_to_date computation, stats
overview, machine status filtering, threat listing, and token revocation.
"""

from datetime import timedelta

import pytest


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.models import Role

    await crud.create_user(
        db_session, email="admin@test.local", password="pw", role=Role.ADMIN
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _readonly_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.models import Role

    await crud.create_user(
        db_session, email="ro@test.local", password="pw", role=Role.READONLY
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "ro@test.local", "password": "pw"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _enroll(client, machine_uuid: str, **fields) -> dict:
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, **fields},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _heartbeat(client, token: str, **body):
    return await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


# --- Broadcast commands ----------------------------------------------------


async def test_broadcast_targets_all_machines(client, db_session):
    headers = await _admin_headers(client, db_session)
    await _enroll(client, "m-all-1")
    await _enroll(client, "m-all-2")

    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_all": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 2


async def test_broadcast_by_domain(client, db_session):
    headers = await _admin_headers(client, db_session)
    await _enroll(client, "m-dom-1", domain="CORP")
    await _enroll(client, "m-dom-2", domain="OTHER")

    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "full_scan", "target_domain": "CORP"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


async def test_create_requires_exactly_one_target(client, db_session):
    headers = await _admin_headers(client, db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan"},  # no target
    )
    assert resp.status_code == 422


async def test_create_command_forbidden_for_readonly(client, db_session):
    headers = await _readonly_headers(client, db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_all": True},
    )
    assert resp.status_code == 403


# --- Command expiry --------------------------------------------------------


async def test_mark_expired_sweeps_stale_pending(client, db_session):
    from sqlmodel import select

    from app.features.base import utcnow
    from app.features.command import crud
    from app.features.command.models import Command, CommandStatus
    from app.features.machine.models import Machine

    machine = Machine(machine_uuid="m-expire")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)

    stale = Command(
        machine_id=machine.id,
        type="quick_scan",
        expires_at=utcnow() - timedelta(minutes=5),
    )
    stale_id = stale.id  # capture before commit expires the instance attributes
    db_session.add(stale)
    await db_session.commit()

    n = await crud.mark_expired(db_session)
    await db_session.commit()
    assert n == 1

    refreshed = (
        await db_session.exec(select(Command).where(Command.id == stale_id))
    ).one()
    assert refreshed.status == CommandStatus.EXPIRED


# --- Freshness + stats -----------------------------------------------------


async def test_heartbeat_computes_is_up_to_date(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-fresh")
    token = enrolled["token"]
    machine_id = enrolled["machine_id"]

    # Protected + fresh signatures → up to date.
    await _heartbeat(
        client,
        token,
        defender={
            "av_enabled": True,
            "rtp_enabled": True,
            "signature_age_days": 1,
        },
    )
    resp = await client.get(f"/api/v1/machines/{machine_id}", headers=headers)
    assert resp.json()["is_up_to_date"] is True

    # Stale signatures (older than the 3-day default) → not up to date.
    await _heartbeat(
        client,
        token,
        defender={
            "av_enabled": True,
            "rtp_enabled": True,
            "signature_age_days": 30,
        },
    )
    resp = await client.get(f"/api/v1/machines/{machine_id}", headers=headers)
    assert resp.json()["is_up_to_date"] is False


async def test_stats_overview_and_status_filter(client, db_session):
    headers = await _admin_headers(client, db_session)

    fresh = await _enroll(client, "m-stat-fresh")
    await _heartbeat(
        client,
        fresh["token"],
        defender={"av_enabled": True, "rtp_enabled": True, "signature_age_days": 1},
        threats=[{"detection_id": "DET-A", "threat_name": "X", "status": "active"}],
    )

    stale = await _enroll(client, "m-stat-stale")
    await _heartbeat(
        client,
        stale["token"],
        defender={"av_enabled": False, "rtp_enabled": False},
    )

    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["up_to_date"] == 1
    assert body["outdated"] == 1
    assert body["with_active_threats"] == 1

    # Status filter on the machine list.
    up = await client.get("/api/v1/machines?status=up_to_date", headers=headers)
    assert [m["machine_uuid"] for m in up.json()["items"]] == ["m-stat-fresh"]

    outdated = await client.get("/api/v1/machines?status=outdated", headers=headers)
    assert [m["machine_uuid"] for m in outdated.json()["items"]] == ["m-stat-stale"]


# --- Threats listing -------------------------------------------------------


async def test_threats_listing_and_severity_filter(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-threats")
    await _heartbeat(
        client,
        enrolled["token"],
        threats=[
            {
                "detection_id": "T-1",
                "threat_name": "EICAR",
                "severity": "high",
                "status": "active",
            },
            {
                "detection_id": "T-2",
                "threat_name": "Low",
                "severity": "low",
                "status": "removed",
            },
        ],
    )

    resp = await client.get("/api/v1/threats", headers=headers)
    assert resp.json()["total"] == 2

    high = await client.get("/api/v1/threats?severity=high", headers=headers)
    items = high.json()["items"]
    assert len(items) == 1 and items[0]["detection_id"] == "T-1"


async def test_machine_list_reports_online_state(client, db_session):
    """The list's presence dot: a poste that just polled is on, one silent past
    the window is off — and the field decays on read, with no write involved."""
    from datetime import timedelta

    from sqlmodel import select

    from app.core.config import settings
    from app.features.base import utcnow
    from app.features.machine.models import Machine

    headers = await _admin_headers(client, db_session)
    live = await _enroll(client, "m-online-live")
    await _heartbeat(client, live["token"], agent_version="test")
    gone = await _enroll(client, "m-online-gone")
    await _heartbeat(client, gone["token"], agent_version="test")

    # Age the second machine's heartbeat past the window, as a shutdown would.
    row = (
        await db_session.exec(
            select(Machine).where(Machine.machine_uuid == "m-online-gone")
        )
    ).one()
    row.last_seen = utcnow() - timedelta(seconds=settings.OFFLINE_AFTER_SECONDS + 60)
    db_session.add(row)
    await db_session.commit()

    listed = await client.get("/api/v1/machines", headers=headers)
    by_uuid = {m["machine_uuid"]: m for m in listed.json()["items"]}
    assert by_uuid["m-online-live"]["is_online"] is True
    assert by_uuid["m-online-gone"]["is_online"] is False

    # And on the detail payload, which inherits the same computation.
    detail = await client.get(
        f"/api/v1/machines/{gone['machine_id']}", headers=headers
    )
    assert detail.json()["is_online"] is False


async def test_machine_filter_with_active_threats(client, db_session):
    """The dashboard's "avec menaces" card link: a handled threat (or none at
    all) keeps the machine out of the filter; only an active one puts it in."""
    headers = await _admin_headers(client, db_session)

    hit = await _enroll(client, "m-tf-hit")
    await _heartbeat(
        client,
        hit["token"],
        threats=[{"detection_id": "TF-1", "threat_name": "EICAR", "status": "active"}],
    )
    handled = await _enroll(client, "m-tf-handled")
    await _heartbeat(
        client,
        handled["token"],
        threats=[{"detection_id": "TF-2", "threat_name": "Old", "status": "removed"}],
    )
    await _enroll(client, "m-tf-clean")

    resp = await client.get(
        "/api/v1/machines?with_active_threats=true", headers=headers
    )
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["m-tf-hit"]

    resp = await client.get(
        "/api/v1/machines?with_active_threats=false", headers=headers
    )
    assert {m["machine_uuid"] for m in resp.json()["items"]} == {
        "m-tf-handled",
        "m-tf-clean",
    }


# --- Token revocation ------------------------------------------------------


async def test_revoke_token_blocks_agent(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-revoke")
    token = enrolled["token"]

    # Token works before revocation.
    assert (await _heartbeat(client, token)).status_code == 200

    resp = await client.post(
        f"/api/v1/machines/{enrolled['machine_id']}/revoke-token", headers=headers
    )
    assert resp.status_code == 200

    # Rejected after revocation.
    assert (await _heartbeat(client, token)).status_code == 401

    # Re-enrollment issues a fresh token and clears the flag.
    re = await _enroll(client, "m-revoke")
    assert (await _heartbeat(client, re["token"])).status_code == 200


async def test_machine_detail_exposes_defender_state(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-detail")
    await _heartbeat(
        client,
        enrolled["token"],
        defender={
            "av_enabled": True,
            "rtp_enabled": True,
            "signature_version": "1.400.1.0",
            "signature_age_days": 2,
        },
    )

    resp = await client.get(
        f"/api/v1/machines/{enrolled['machine_id']}", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    # Fields present only on the detail view (not the lean list row).
    assert body["av_enabled"] is True
    assert body["rtp_enabled"] is True
    assert body["signature_age_days"] == 2
    assert "last_quick_scan" in body and "created_at" in body


# --- Logged-on session ------------------------------------------------------


async def _detail(client, headers, machine_id) -> dict:
    resp = await client.get(f"/api/v1/machines/{machine_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _list_row(client, headers, machine_uuid) -> dict:
    resp = await client.get(
        "/api/v1/machines", headers=headers, params={"search": machine_uuid}
    )
    assert resp.status_code == 200, resp.text
    rows = [m for m in resp.json()["items"] if m["machine_uuid"] == machine_uuid]
    assert len(rows) == 1
    return rows[0]


async def test_heartbeat_stores_session_user(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-sess-user")
    await _heartbeat(
        client,
        enrolled["token"],
        session={
            "user_present": True,
            "username": "CORP\\jdupont",
            "state": "active",
            "is_remote": False,
        },
    )

    row = await _list_row(client, headers, "m-sess-user")
    assert row["session_user_present"] is True
    assert row["session_username"] == "CORP\\jdupont"

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["session_state"] == "active"
    assert body["session_is_remote"] is False


async def test_heartbeat_session_without_username_keeps_presence(client, db_session):
    """Privacy toggle off: presence is reported, the name never arrives."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-sess-anon")
    await _heartbeat(
        client,
        enrolled["token"],
        session={"user_present": True, "state": "active"},
    )

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["session_user_present"] is True
    assert body["session_username"] is None
    assert body["session_state"] == "active"


async def test_heartbeat_session_logoff_clears_username(client, db_session):
    """A logoff must erase a name stored earlier, not leave it on display."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-sess-logoff")
    await _heartbeat(
        client,
        enrolled["token"],
        session={"user_present": True, "username": "CORP\\jdupont"},
    )
    await _heartbeat(client, enrolled["token"], session={"user_present": False})

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["session_user_present"] is False
    assert body["session_username"] is None


async def test_heartbeat_without_session_block_preserves_last_value(client, db_session):
    """Same contract as the defender block: an absent block overwrites nothing.

    An agent older than the feature — or one whose WTS read failed — must not
    silently blank the last known session.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-sess-keep")
    await _heartbeat(
        client,
        enrolled["token"],
        session={"user_present": True, "username": "CORP\\jdupont"},
    )
    await _heartbeat(client, enrolled["token"], hostname="PC-KEEP")

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["hostname"] == "PC-KEEP"
    assert body["session_user_present"] is True
    assert body["session_username"] == "CORP\\jdupont"


async def test_session_never_reported_stays_null(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-sess-unknown")
    await _heartbeat(client, enrolled["token"])

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["session_user_present"] is None
    assert body["session_username"] is None


async def test_machine_list_omits_session_type(client, db_session):
    """Session type stays on the detail view; the list row stays lean."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-sess-lean")
    await _heartbeat(
        client,
        enrolled["token"],
        session={"user_present": True, "state": "disconnected", "is_remote": True},
    )

    row = await _list_row(client, headers, "m-sess-lean")
    assert "session_user_present" in row
    assert "session_state" not in row
    assert "session_is_remote" not in row

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["session_state"] == "disconnected"
    assert body["session_is_remote"] is True


# --- Primary IP address -----------------------------------------------------


async def test_heartbeat_stores_ip_address(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-ip")
    await _heartbeat(client, enrolled["token"], ip_address="192.168.1.10")

    row = await _list_row(client, headers, "m-ip")
    assert row["ip_address"] == "192.168.1.10"

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["ip_address"] == "192.168.1.10"


async def test_ip_address_never_reported_stays_null(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-ip-unknown")
    await _heartbeat(client, enrolled["token"])

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["ip_address"] is None


async def test_heartbeat_updates_ip_address(client, db_session):
    """A new lease replaces the old address — nothing accumulates."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-ip-dhcp")
    await _heartbeat(client, enrolled["token"], ip_address="192.168.1.10")
    await _heartbeat(client, enrolled["token"], ip_address="10.0.0.20")

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["ip_address"] == "10.0.0.20"


async def test_heartbeat_without_ip_preserves_last_value(client, db_session):
    """An agent whose read failed omits the field; the last address survives."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-ip-keep")
    await _heartbeat(client, enrolled["token"], ip_address="192.168.1.10")
    await _heartbeat(client, enrolled["token"], hostname="PC-IP-KEEP")

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["hostname"] == "PC-IP-KEEP"
    assert body["ip_address"] == "192.168.1.10"


async def test_heartbeat_malformed_ip_is_dropped_not_rejected(client, db_session):
    """A bad address must not cost the heartbeat its Defender state."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-ip-bad")
    await _heartbeat(client, enrolled["token"], ip_address="192.168.1.10")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        ip_address="not-an-address",
        defender={"av_enabled": True},
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["av_enabled"] is True
    assert body["ip_address"] == "192.168.1.10"


async def test_heartbeat_normalizes_ipv6(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-ip-v6")
    await _heartbeat(client, enrolled["token"], ip_address="2001:0DB8:0000::0001")

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["ip_address"] == "2001:db8::1"


async def test_machines_search_matches_ip(client, db_session):
    """From an address in a firewall log back to the machine."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-ip-search", hostname="ZZZ-IP")
    await _heartbeat(client, enrolled["token"], ip_address="10.42.7.99")

    resp = await client.get("/api/v1/machines?search=10.42.7.99", headers=headers)
    assert resp.status_code == 200
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["m-ip-search"]


# --- Third-party antivirus (Security Center) --------------------------------

# The product name Windows reports for a third party, and the block an agent
# sends for it: running, definitions current, and not Defender.
ESET = "ESET Endpoint Security"
_ESET_BLOCK = {
    "name": ESET,
    "enabled": True,
    "signatures_up_to_date": True,
    "is_defender": False,
}
# Defender pushed into passive mode by the above — what its own WMI class then
# reports, which on its own reads as "unprotected".
_PASSIVE_DEFENDER = {
    "av_enabled": False,
    "rtp_enabled": False,
    "running_mode": "Passive",
}


async def test_heartbeat_stores_antivirus_product(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av")
    await _heartbeat(client, enrolled["token"], av_product=_ESET_BLOCK)

    # In the list row, not only the detail: this is a column people scan.
    row = await _list_row(client, headers, "m-av")
    assert row["av_product_name"] == ESET
    assert row["av_product_enabled"] is True
    assert row["av_product_signatures_up_to_date"] is True
    assert row["av_product_is_defender"] is False


async def test_third_party_antivirus_counts_as_up_to_date(client, db_session):
    """The point of the whole feature: a protected poste stops reading as unprotected."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av-fresh")
    await _heartbeat(
        client,
        enrolled["token"],
        defender=_PASSIVE_DEFENDER,
        av_product=_ESET_BLOCK,
    )

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["is_up_to_date"] is True
    # And the reason Defender reads as off is now visible rather than inferred.
    assert body["running_mode"] == "Passive"


async def test_third_party_with_stale_signatures_is_outdated(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av-stale")
    await _heartbeat(
        client,
        enrolled["token"],
        defender=_PASSIVE_DEFENDER,
        av_product={**_ESET_BLOCK, "signatures_up_to_date": False},
    )

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["is_up_to_date"] is False


async def test_uninstalling_the_antivirus_recomputes_without_defender_block(
    client, db_session
):
    """An empty name clears the product *and* the up-to-date flag it earned.

    The second heartbeat carries no Defender block at all, so recomputing only
    inside that block would leave the machine credited to an antivirus that is no
    longer installed.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av-gone")
    await _heartbeat(
        client,
        enrolled["token"],
        defender=_PASSIVE_DEFENDER,
        av_product=_ESET_BLOCK,
    )
    assert (await _detail(client, headers, enrolled["machine_id"]))["is_up_to_date"]

    await _heartbeat(client, enrolled["token"], av_product={"name": ""})

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["av_product_name"] == ""
    assert body["is_up_to_date"] is False


async def test_antivirus_never_reported_stays_null(client, db_session):
    """No Security Center to read (Windows Server) ≠ no antivirus installed."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av-unknown")
    await _heartbeat(client, enrolled["token"])

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["av_product_name"] is None
    assert body["av_product_enabled"] is None
    assert body["av_product_is_defender"] is None


async def test_heartbeat_without_av_block_preserves_last_value(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av-keep")
    await _heartbeat(client, enrolled["token"], av_product=_ESET_BLOCK)
    await _heartbeat(client, enrolled["token"], hostname="PC-AV-KEEP")

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["hostname"] == "PC-AV-KEEP"
    assert body["av_product_name"] == ESET


async def test_antivirus_name_is_trimmed_and_bounded(client, db_session):
    """A vendor display string is bounded here, never trusted — and never 422s."""
    from app.api.routes.agent import AV_PRODUCT_NAME_MAX

    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av-long")
    resp = await _heartbeat(
        client,
        enrolled["token"],
        av_product={"name": "  " + "A" * (AV_PRODUCT_NAME_MAX + 50) + "  "},
        defender={"av_enabled": True},
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled["machine_id"])
    assert body["av_product_name"] == "A" * AV_PRODUCT_NAME_MAX
    assert body["av_enabled"] is True


async def test_machines_search_matches_antivirus_name(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-av-search", hostname="ZZZ-AV")
    await _heartbeat(client, enrolled["token"], av_product=_ESET_BLOCK)

    resp = await client.get("/api/v1/machines?search=eset", headers=headers)
    assert resp.status_code == 200
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["m-av-search"]


async def test_antivirus_filter_selects_one_product(client, db_session):
    headers = await _admin_headers(client, db_session)
    eset = await _enroll(client, "m-av-eset")
    await _heartbeat(client, eset["token"], av_product=_ESET_BLOCK)
    defender = await _enroll(client, "m-av-defender")
    await _heartbeat(
        client,
        defender["token"],
        av_product={"name": "Windows Defender", "is_defender": True, "enabled": True},
    )

    resp = await client.get("/api/v1/machines?antivirus=ESET", headers=headers)
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["m-av-eset"]

    # Substring, so a partial vendor name works from the search box too.
    resp = await client.get("/api/v1/machines?antivirus=defend", headers=headers)
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["m-av-defender"]


async def test_antivirus_products_lists_the_fleet_most_common_first(client, db_session):
    headers = await _admin_headers(client, db_session)
    for uuid_ in ("m-inv-1", "m-inv-2"):
        enrolled = await _enroll(client, uuid_)
        await _heartbeat(client, enrolled["token"], av_product=_ESET_BLOCK)
    lonely = await _enroll(client, "m-inv-3")
    await _heartbeat(
        client,
        lonely["token"],
        av_product={"name": "Windows Defender", "is_defender": True},
    )
    # Reported no product at all, and never reported: neither is a product to
    # offer in a filter.
    none_at_all = await _enroll(client, "m-inv-4")
    await _heartbeat(client, none_at_all["token"], av_product={"name": ""})
    await _enroll(client, "m-inv-5")

    resp = await client.get("/api/v1/machines/antivirus-products", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {"name": ESET, "count": 2},
        {"name": "Windows Defender", "count": 1},
    ]


# --- Machine merge (plan §8) -----------------------------------------------


async def test_duplicates_lists_same_smbios(client, db_session):
    headers = await _admin_headers(client, db_session)
    a = await _enroll(client, "dup-a", fingerprint={"smbios_uuid": "SMB-DUP"})
    await _enroll(client, "dup-b", fingerprint={"smbios_uuid": "SMB-DUP"})
    await _enroll(client, "dup-c", fingerprint={"smbios_uuid": "SMB-OTHER"})

    resp = await client.get(
        f"/api/v1/machines/{a['machine_id']}/duplicates", headers=headers
    )
    assert resp.status_code == 200
    assert [m["machine_uuid"] for m in resp.json()] == ["dup-b"]


async def test_merge_reassigns_history_and_clears_flag(client, db_session):
    headers = await _admin_headers(client, db_session)
    a = await _enroll(client, "m-merge-a", fingerprint={"smbios_uuid": "SMB-MERGE"})
    b = await _enroll(client, "m-merge-b", fingerprint={"smbios_uuid": "SMB-MERGE"})

    # B (a second identity on the same anchor) is flagged for verification.
    detail_b = await client.get(f"/api/v1/machines/{b['machine_id']}", headers=headers)
    assert detail_b.json()["needs_verification"] is True

    # A has a threat and a queued command.
    await _heartbeat(
        client,
        a["token"],
        threats=[{"detection_id": "DA", "threat_name": "X", "status": "active"}],
    )
    cmd = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "machine_ids": [a["machine_id"]]},
    )
    assert cmd.json()["count"] == 1

    # Merge A into B (keep B).
    merged = await client.post(
        f"/api/v1/machines/{b['machine_id']}/merge",
        headers=headers,
        json={"source_id": a["machine_id"]},
    )
    assert merged.status_code == 200
    assert merged.json()["needs_verification"] is False

    # A is gone; its history now belongs to B.
    gone = await client.get(f"/api/v1/machines/{a['machine_id']}", headers=headers)
    assert gone.status_code == 404
    threats_b = await client.get(
        f"/api/v1/threats?machine_id={b['machine_id']}", headers=headers
    )
    assert [t["detection_id"] for t in threats_b.json()["items"]] == ["DA"]
    cmds_b = await client.get(
        f"/api/v1/commands?machine_id={b['machine_id']}", headers=headers
    )
    assert cmds_b.json()["total"] == 1


async def test_merge_dedups_colliding_threats(client, db_session):
    headers = await _admin_headers(client, db_session)
    a = await _enroll(client, "mt-a", fingerprint={"smbios_uuid": "SMB-MT"})
    b = await _enroll(client, "mt-b", fingerprint={"smbios_uuid": "SMB-MT"})

    # Both report the same detection id.
    await _heartbeat(
        client,
        a["token"],
        threats=[{"detection_id": "DUP", "threat_name": "from-A", "status": "active"}],
    )
    await _heartbeat(
        client,
        b["token"],
        threats=[{"detection_id": "DUP", "threat_name": "from-B", "status": "active"}],
    )

    await client.post(
        f"/api/v1/machines/{b['machine_id']}/merge",
        headers=headers,
        json={"source_id": a["machine_id"]},
    )

    threats_b = await client.get(
        f"/api/v1/threats?machine_id={b['machine_id']}", headers=headers
    )
    items = threats_b.json()["items"]
    assert len(items) == 1  # collision dropped; the target's row is kept
    assert items[0]["threat_name"] == "from-B"


async def test_merge_into_self_rejected(client, db_session):
    headers = await _admin_headers(client, db_session)
    a = await _enroll(client, "merge-self")
    resp = await client.post(
        f"/api/v1/machines/{a['machine_id']}/merge",
        headers=headers,
        json={"source_id": a["machine_id"]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "machine.merge.self"


# --- Agent command result + heartbeat details ------------------------------


async def test_command_result_flow(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-result")
    token = enrolled["token"]
    auth = {"Authorization": f"Bearer {token}"}

    await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "machine_ids": [enrolled["machine_id"]]},
    )
    # Heartbeat delivers the pending command.
    hb = await _heartbeat(client, token)
    commands = hb.json()["commands"]
    assert len(commands) == 1
    cmd_id = commands[0]["id"]

    # Agent posts the result.
    res = await client.post(
        f"/api/v1/agent/commands/{cmd_id}/result",
        headers=auth,
        json={"status": "succeeded", "output": "clean"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    listed = await client.get(
        f"/api/v1/commands?machine_id={enrolled['machine_id']}", headers=headers
    )
    item = listed.json()["items"][0]
    assert item["status"] == "succeeded"
    assert item["result_output"] == "clean"


async def test_command_result_unknown_is_ignored(client, db_session):
    import uuid

    enrolled = await _enroll(client, "m-result-x")
    res = await client.post(
        f"/api/v1/agent/commands/{uuid.uuid4()}/result",
        headers={"Authorization": f"Bearer {enrolled['token']}"},
        json={"status": "succeeded"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


# --- Maintenance catalogue + intermediate `running` ------------------------

# The closed catalogue of remote maintenance/diagnostic commands
# (plan-commandes-distantes.md §2), minus the three Defender ones covered above.
MAINTENANCE_TYPES = [
    "gpo_update",
    "flush_dns",
    "time_resync",
    "cert_pulse",
    "spooler_reset",
    "sfc_scan",
    "dism_restore_health",
    "dism_component_cleanup",
    "chkdsk_scan",
    "gpo_report",
    "net_config",
]


async def _queue_and_deliver(client, headers, enrolled, command_type: str) -> str:
    """Queue one command for the machine and let a heartbeat pick it up."""
    created = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": command_type, "machine_ids": [enrolled["machine_id"]]},
    )
    assert created.status_code == 200, created.text
    hb = await _heartbeat(client, enrolled["token"])
    commands = hb.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["type"] == command_type
    return str(commands[0]["id"])


async def _command_row(client, headers, enrolled, command_id: str) -> dict:
    listed = await client.get(
        f"/api/v1/commands?machine_id={enrolled['machine_id']}", headers=headers
    )
    rows = [c for c in listed.json()["items"] if c["id"] == command_id]
    assert rows, listed.text
    return rows[0]


def test_catalogue_is_fully_covered_below():
    """Guard the list above: a new command type must gain a round-trip test.

    Spelled out rather than derived from the enum on purpose — this is a closed
    catalogue for security reasons (no arguments cross the wire, the agent holds
    the command lines), so a value appearing in it should cost a deliberate edit
    here too.
    """
    from app.features.command.models import CommandType

    defender = {"quick_scan", "full_scan", "update_signatures"}
    # Phase 2's four types are covered by tests/test_api_windows_update.py, and
    # named here so this guard still fails on a type nobody tested anywhere.
    windows_update = {"wu_scan", "wu_install", "wu_install_full", "reboot"}
    assert {t.value for t in CommandType} == (
        defender | windows_update | set(MAINTENANCE_TYPES)
    )


@pytest.mark.parametrize("command_type", MAINTENANCE_TYPES)
async def test_maintenance_command_round_trip(client, db_session, command_type):
    """Every catalogue type is creatable, deliverable and closeable.

    The point is the catalogue's *exhaustiveness*: a value added to CommandType
    without the console or the agent knowing it would still pass this, but a
    type the API refuses to queue is caught here rather than on a real machine.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, f"m-cat-{command_type}")
    cmd_id = await _queue_and_deliver(client, headers, enrolled, command_type)

    res = await client.post(
        f"/api/v1/agent/commands/{cmd_id}/result",
        headers={"Authorization": f"Bearer {enrolled['token']}"},
        json={"status": "succeeded", "output": "ok"},
    )
    assert res.status_code == 200
    row = await _command_row(client, headers, enrolled, cmd_id)
    assert row["status"] == "succeeded"


async def test_maintenance_command_forbidden_for_readonly(client, db_session):
    headers = await _readonly_headers(client, db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "sfc_scan", "target_all": True},
    )
    assert resp.status_code == 403


async def test_running_marks_started_without_closing(client, db_session):
    """A long command reports `running`, then its verdict — two distinct writes."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-running")
    auth = {"Authorization": f"Bearer {enrolled['token']}"}
    cmd_id = await _queue_and_deliver(client, headers, enrolled, "sfc_scan")

    started = await client.post(
        f"/api/v1/agent/commands/{cmd_id}/result",
        headers=auth,
        json={"status": "running"},
    )
    assert started.status_code == 200
    row = await _command_row(client, headers, enrolled, cmd_id)
    assert row["status"] == "running"
    assert row["started_at"] is not None
    # Not closed: the verdict is still to come.
    assert row["finished_at"] is None
    assert row["result_output"] is None
    started_at = row["started_at"]

    final = await client.post(
        f"/api/v1/agent/commands/{cmd_id}/result",
        headers=auth,
        json={"status": "succeeded", "output": "aucune violation d'intégrité"},
    )
    assert final.status_code == 200
    row = await _command_row(client, headers, enrolled, cmd_id)
    assert row["status"] == "succeeded"
    assert row["finished_at"] is not None
    # The start time survives the close — it is what makes the duration readable.
    assert row["started_at"] == started_at
    assert row["result_output"] == "aucune violation d'intégrité"


async def test_running_after_final_is_ignored(client, db_session):
    """A late progress ping must not reopen a command that already has a verdict."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-running-late")
    auth = {"Authorization": f"Bearer {enrolled['token']}"}
    cmd_id = await _queue_and_deliver(client, headers, enrolled, "dism_restore_health")

    await client.post(
        f"/api/v1/agent/commands/{cmd_id}/result",
        headers=auth,
        json={"status": "failed", "error": "source de réparation inaccessible"},
    )
    late = await client.post(
        f"/api/v1/agent/commands/{cmd_id}/result",
        headers=auth,
        json={"status": "running"},
    )
    assert late.status_code == 200
    assert late.json()["status"] == "ignored"

    row = await _command_row(client, headers, enrolled, cmd_id)
    assert row["status"] == "failed"
    assert row["error"] == "source de réparation inaccessible"


async def test_agent_cannot_report_queue_statuses(client, db_session):
    """pending/delivered/expired are the server's to write, not the agent's."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-status-guard")
    auth = {"Authorization": f"Bearer {enrolled['token']}"}
    cmd_id = await _queue_and_deliver(client, headers, enrolled, "flush_dns")

    for status in ("pending", "delivered", "expired"):
        resp = await client.post(
            f"/api/v1/agent/commands/{cmd_id}/result",
            headers=auth,
            json={"status": status},
        )
        assert resp.status_code == 422, f"{status}: {resp.text}"

    row = await _command_row(client, headers, enrolled, cmd_id)
    assert row["status"] == "delivered"  # untouched


async def test_result_output_is_bounded_server_side(client, db_session):
    """The agent truncates; the server does not take its word for it."""
    from app.api.routes.agent import RESULT_TEXT_MAX

    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-bigout")
    auth = {"Authorization": f"Bearer {enrolled['token']}"}
    cmd_id = await _queue_and_deliver(client, headers, enrolled, "net_config")

    await client.post(
        f"/api/v1/agent/commands/{cmd_id}/result",
        headers=auth,
        json={"status": "succeeded", "output": "x" * (RESULT_TEXT_MAX + 5000)},
    )
    row = await _command_row(client, headers, enrolled, cmd_id)
    assert row["result_output"].startswith("x" * 100)
    assert len(row["result_output"]) < RESULT_TEXT_MAX + 200
    assert "tronqu" in row["result_output"]


async def test_heartbeat_stores_host_fields(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-host")
    await _heartbeat(
        client,
        enrolled["token"],
        hostname="PC-7",
        domain="CORP",
        os_version="Windows 11",
        agent_version="1.2.3",
    )
    body = (
        await client.get(f"/api/v1/machines/{enrolled['machine_id']}", headers=headers)
    ).json()
    assert body["hostname"] == "PC-7"
    assert body["domain"] == "CORP"
    assert body["os_version"] == "Windows 11"
    assert body["agent_version"] == "1.2.3"


async def test_heartbeat_fingerprint_change_flags_verification(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-fpchg", fingerprint={"smbios_uuid": "SMB-1"})
    # A different SMBIOS anchor on a later heartbeat is suspicious.
    await _heartbeat(client, enrolled["token"], fingerprint={"smbios_uuid": "SMB-2"})
    body = (
        await client.get(f"/api/v1/machines/{enrolled['machine_id']}", headers=headers)
    ).json()
    assert body["needs_verification"] is True


async def test_threats_status_filter(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-thst")
    await _heartbeat(
        client,
        enrolled["token"],
        threats=[
            {"detection_id": "A", "status": "active"},
            {"detection_id": "R", "status": "removed"},
        ],
    )
    active = await client.get("/api/v1/threats?status=active", headers=headers)
    assert [t["detection_id"] for t in active.json()["items"]] == ["A"]


async def test_machines_search_matches_uuid(client, db_session):
    headers = await _admin_headers(client, db_session)
    await _enroll(client, "uuid-search-target", hostname="ZZZ")
    resp = await client.get("/api/v1/machines?search=uuid-search", headers=headers)
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["uuid-search-target"]


async def test_duplicates_empty_without_smbios(client, db_session):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "no-smbios")  # no fingerprint → smbios is null
    resp = await client.get(
        f"/api/v1/machines/{enrolled['machine_id']}/duplicates", headers=headers
    )
    assert resp.json() == []


async def test_me_returns_current_user(client, db_session):
    headers = await _admin_headers(client, db_session)
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@test.local"


async def test_health_reports_database_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is True
