"""Console endpoint integration tests (require TIAI_TEST_DATABASE_URL).

Covers M3: broadcast commands, command expiry, is_up_to_date computation, stats
overview, machine status filtering, threat listing, and token revocation.
"""

from datetime import timedelta


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
