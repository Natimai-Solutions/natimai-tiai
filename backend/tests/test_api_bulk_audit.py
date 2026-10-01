"""Audit of the actions aimed at a set of postes: bulk commands, bulk wakes.

The command rows already say who sent what to which poste; these entries keep
what no row can — the target as it was asked, and what was skipped. A single
poste stays traced by its row alone. DB-backed tests require
TIAI_TEST_DATABASE_URL.
"""

import uuid

import pytest

# --- describe_command_target (pure) --------------------------------------------


def _target(**overrides):
    from app.features.command.bulk import describe_command_target

    args = {
        "machine_ids": None,
        "target_all": False,
        "target_domain": None,
        "target_location": None,
        "target_status": None,
    }
    return describe_command_target(**{**args, **overrides})


def test_each_filter_is_described():
    from app.features.machine.status import MachineStatus

    assert _target(target_all=True) == {"target": "all"}
    assert _target(target_domain="LYCEE") == {"target": "domain", "domain": "LYCEE"}
    assert _target(target_location="Taravao") == {
        "target": "location",
        "location": "Taravao",
    }
    assert _target(target_status=MachineStatus.OUTDATED) == {
        "target": "status",
        "status": "outdated",
    }


def test_an_empty_domain_is_still_a_filter():
    """ "" is a domain the console can send — postes outside any domain."""
    assert _target(target_domain="") == {"target": "domain", "domain": ""}


def test_a_list_is_a_set_from_two_distinct_postes():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert _target(machine_ids=[a, b]) == {"target": "machines", "requested": 2}
    assert _target(machine_ids=[a, b, a]) == {"target": "machines", "requested": 2}


def test_one_poste_is_not_a_set():
    a = uuid.uuid4()
    assert _target(machine_ids=[a]) is None
    assert _target(machine_ids=[a, a]) is None


# --- Through the API --------------------------------------------------------------


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="bulk-admin@test.local",
        password="pw",
        groups=[BuiltinGroup.ADMIN],
    )
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "bulk-admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200, resp.text
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


async def _entries(client, headers, action: str) -> list[dict]:
    resp = await client.get("/api/v1/audit", headers=headers, params={"action": action})
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _send(client, headers, **body) -> dict:
    resp = await client.post("/api/v1/commands", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_a_fleet_wide_command_is_audited(client, db_session):
    headers = await _admin_headers(client, db_session)
    await _enroll(client, "bulk-all-1")
    await _enroll(client, "bulk-all-2")

    await _send(client, headers, type="quick_scan", target_all=True, ttl_minutes=120)

    [entry] = await _entries(client, headers, "command.bulk")
    assert entry["actor"] == "bulk-admin@test.local"
    assert entry["resource_type"] == "command"
    assert entry["resource_id"] == "quick_scan"
    assert entry["details"] == {
        "command_type": "quick_scan",
        "target": "all",
        "created": 2,
        "skipped": 0,
        "ttl_minutes": 120,
    }


async def test_the_applied_default_ttl_is_recorded(client, db_session, monkeypatch):
    """The lifetime the command actually got, not the absent request field."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "COMMAND_DEFAULT_TTL_MINUTES", 45)
    headers = await _admin_headers(client, db_session)
    await _enroll(client, "bulk-ttl", domain="LYCEE")

    await _send(client, headers, type="flush_dns", target_domain="LYCEE")

    [entry] = await _entries(client, headers, "command.bulk")
    assert entry["details"]["ttl_minutes"] == 45
    assert entry["details"]["target"] == "domain"
    assert entry["details"]["domain"] == "LYCEE"


async def test_skipped_postes_are_counted(client, db_session):
    """A poste that already has the command open gets no row — the entry is
    the only place that says it was part of the request."""
    headers = await _admin_headers(client, db_session)
    a = await _enroll(client, "bulk-skip-a", location="Taravao")
    await _enroll(client, "bulk-skip-b", location="Taravao")
    await _send(client, headers, type="full_scan", machine_ids=[a["machine_id"]])

    await _send(client, headers, type="full_scan", target_location="Taravao")

    [entry] = await _entries(client, headers, "command.bulk")
    assert entry["details"]["target"] == "location"
    assert entry["details"]["location"] == "Taravao"
    assert (entry["details"]["created"], entry["details"]["skipped"]) == (1, 1)


async def test_a_filter_matching_nobody_is_still_audited(client, db_session):
    headers = await _admin_headers(client, db_session)

    body = await _send(client, headers, type="quick_scan", target_status="inactive")
    assert body["count"] == 0

    [entry] = await _entries(client, headers, "command.bulk")
    assert entry["details"]["target"] == "status"
    assert entry["details"]["status"] == "inactive"
    assert (entry["details"]["created"], entry["details"]["skipped"]) == (0, 0)


async def test_a_selection_of_postes_is_audited(client, db_session):
    headers = await _admin_headers(client, db_session)
    a = await _enroll(client, "bulk-sel-a")
    b = await _enroll(client, "bulk-sel-b")

    await _send(
        client,
        headers,
        type="gpo_update",
        machine_ids=[a["machine_id"], b["machine_id"], str(uuid.uuid4())],
    )

    [entry] = await _entries(client, headers, "command.bulk")
    # Three asked, two exist: the stale id is neither created nor skipped.
    assert entry["details"]["target"] == "machines"
    assert entry["details"]["requested"] == 3
    assert (entry["details"]["created"], entry["details"]["skipped"]) == (2, 0)


async def test_a_single_poste_is_traced_by_its_row_only(client, db_session):
    headers = await _admin_headers(client, db_session)
    a = await _enroll(client, "bulk-one")

    await _send(client, headers, type="quick_scan", machine_ids=[a["machine_id"]])
    await _send(client, headers, type="flush_dns", machine_ids=[a["machine_id"]] * 2)

    assert await _entries(client, headers, "command.bulk") == []


async def test_a_refused_bulk_command_leaves_no_trace(client, db_session):
    """No risky permission, no command — and no entry for what did not happen."""
    from app.features.user import crud

    admin = await _admin_headers(client, db_session)
    await _enroll(client, "bulk-refused")
    resp = await client.post(
        "/api/v1/groups",
        headers=admin,
        json={"name": "Scans", "permissions": ["command:read", "command:execute"]},
    )
    assert resp.status_code == 201, resp.text
    await crud.create_user(
        db_session,
        email="scan@test.local",
        password="pw",
        groups=[uuid.UUID(resp.json()["id"])],
    )
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login", data={"username": "scan@test.local", "password": "pw"}
    )
    scan_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/commands",
        headers=scan_headers,
        json={"type": "reboot", "target_all": True},
    )
    assert resp.status_code == 403

    assert await _entries(client, admin, "command.bulk") == []


# --- Bulk wake ---------------------------------------------------------------------


@pytest.fixture
def sent(monkeypatch):
    """Keep magic packets off the wire."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.features.wol.sender._emit", lambda *args: calls.append(args)
    )
    return calls


async def _heartbeat(client, token: str, **body) -> None:
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert resp.status_code == 200, resp.text


async def test_a_bulk_wake_is_audited_with_its_outcome(client, db_session, sent):
    headers = await _admin_headers(client, db_session)
    ok = await _enroll(client, "wake-bulk-ok")
    await _heartbeat(
        client, ok["token"], ip_address="192.168.1.42", mac_address="AA:BB:CC:DD:EE:01"
    )
    no_mac = await _enroll(client, "wake-bulk-nomac")

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [ok["machine_id"], no_mac["machine_id"]]},
    )
    assert resp.status_code == 200, resp.text

    [entry] = await _entries(client, headers, "machine.wake_bulk")
    assert entry["actor"] == "bulk-admin@test.local"
    assert entry["resource_type"] == "machine"
    assert entry["resource_id"] == ""
    assert entry["details"] == {
        "machine_ids": [ok["machine_id"], no_mac["machine_id"]],
        "woken": 1,
        "failed": 1,
        "relayed": False,
    }


async def test_a_single_wake_is_not_audited(client, db_session, sent):
    headers = await _admin_headers(client, db_session)
    ok = await _enroll(client, "wake-single")
    await _heartbeat(
        client, ok["token"], ip_address="192.168.1.43", mac_address="AA:BB:CC:DD:EE:02"
    )

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [ok["machine_id"]]},
    )
    assert resp.status_code == 200

    assert await _entries(client, headers, "machine.wake_bulk") == []
