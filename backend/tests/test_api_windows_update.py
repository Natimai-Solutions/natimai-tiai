"""Windows Update integration tests (require TIAI_TEST_DATABASE_URL).

Covers Phase 2 J1: the heartbeat's ``windows_update`` block (machine columns +
the pending set), the four new command types, and the two dashboard KPIs.
"""

import pytest


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.models import Role

    await crud.create_user(
        db_session, email="wu-admin@test.local", password="pw", role=Role.ADMIN
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "wu-admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200
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


async def _detail(client, headers, enrolled) -> dict:
    resp = await client.get(
        f"/api/v1/machines/{enrolled['machine_id']}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _update(update_id: str, **fields) -> dict:
    """A pending update as the agent reports it."""
    return {
        "update_id": update_id,
        "kb": "KB5063878",
        "title": "Mise a jour cumulative 2026-08",
        "severity": "Critical",
        "type": "software",
        "categories": ["Security Updates"],
        "is_downloaded": True,
        "size_mb": 620.5,
        **fields,
    }


# --- Heartbeat: state + pending set ----------------------------------------


async def test_heartbeat_stores_windows_update_state(client, db_session):
    """The block fills the machine's columns and the pending table."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-state")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        windows_update={
            "reboot_required": True,
            "last_search_time": "2026-08-13T04:00:00Z",
            "last_install_time": "2026-08-01T03:12:00Z",
            "pending": [_update("u-1"), _update("u-2", kb=None, type="driver")],
        },
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled)
    assert body["wu_pending_count"] == 2
    assert body["wu_reboot_required"] is True
    assert body["wu_last_search"].startswith("2026-08-13T04:00:00")
    assert body["wu_last_install"].startswith("2026-08-01T03:12:00")

    updates = body["pending_updates"]
    assert {u["update_id"] for u in updates} == {"u-1", "u-2"}
    first = next(u for u in updates if u["update_id"] == "u-1")
    assert first["kb"] == "KB5063878"
    # Lowercased server-side so an older agent's "Critical" and a newer one's
    # "critical" land on the same value the console colours by.
    assert first["severity"] == "critical"
    assert first["type"] == "software"
    assert first["categories"] == "Security Updates"
    assert first["is_downloaded"] is True
    assert first["size_mb"] == 620.5
    driver = next(u for u in updates if u["update_id"] == "u-2")
    assert driver["kb"] is None
    assert driver["type"] == "driver"


async def test_pending_set_is_replaced_not_accumulated(client, db_session):
    """An installed update disappears; a still-pending one keeps its first_seen."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-replace")

    await _heartbeat(
        client,
        enrolled["token"],
        windows_update={"pending": [_update("u-keep"), _update("u-installed")]},
    )
    before = await _detail(client, headers, enrolled)
    first_seen = next(
        u["first_seen"] for u in before["pending_updates"] if u["update_id"] == "u-keep"
    )

    # Next cycle: one got installed, one is new, one is unchanged but revised.
    await _heartbeat(
        client,
        enrolled["token"],
        windows_update={
            "pending": [
                _update("u-keep", is_downloaded=False, title="Titre revise"),
                _update("u-new", severity="Important"),
            ]
        },
    )
    after = await _detail(client, headers, enrolled)

    assert after["wu_pending_count"] == 2
    updates = {u["update_id"]: u for u in after["pending_updates"]}
    assert set(updates) == {"u-keep", "u-new"}
    # Updated in place...
    assert updates["u-keep"]["title"] == "Titre revise"
    assert updates["u-keep"]["is_downloaded"] is False
    # ...but the age of the machine's failure to patch is not reset.
    assert updates["u-keep"]["first_seen"] == first_seen


async def test_empty_pending_list_clears_the_set(client, db_session):
    """A fully patched machine reports an empty list, and the table follows."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-empty")

    await _heartbeat(
        client, enrolled["token"], windows_update={"pending": [_update("u-x")]}
    )
    await _heartbeat(
        client,
        enrolled["token"],
        windows_update={"reboot_required": False, "pending": []},
    )

    body = await _detail(client, headers, enrolled)
    assert body["wu_pending_count"] == 0
    assert body["pending_updates"] == []


async def test_heartbeat_without_the_block_overwrites_nothing(client, db_session):
    """A plain heartbeat is not a claim that the machine has nothing pending."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-absent")

    await _heartbeat(
        client,
        enrolled["token"],
        windows_update={"reboot_required": True, "pending": [_update("u-keep")]},
    )
    # The hundreds of heartbeats between two WU cycles carry no block at all.
    await _heartbeat(client, enrolled["token"], agent_version="test")

    body = await _detail(client, headers, enrolled)
    assert body["wu_pending_count"] == 1
    assert body["wu_reboot_required"] is True
    assert [u["update_id"] for u in body["pending_updates"]] == ["u-keep"]


async def test_pending_updates_are_scoped_to_their_machine(client, db_session):
    """Two machines reporting the same KB keep two independent rows."""
    headers = await _admin_headers(client, db_session)
    one = await _enroll(client, "m-wu-scope-1")
    two = await _enroll(client, "m-wu-scope-2")

    await _heartbeat(
        client, one["token"], windows_update={"pending": [_update("u-shared")]}
    )
    await _heartbeat(
        client, two["token"], windows_update={"pending": [_update("u-shared")]}
    )
    # One machine patches; the other must keep its row.
    await _heartbeat(client, one["token"], windows_update={"pending": []})

    assert (await _detail(client, headers, one))["pending_updates"] == []
    right = await _detail(client, headers, two)
    assert [u["update_id"] for u in right["pending_updates"]] == ["u-shared"]


async def test_malformed_update_degrades_instead_of_422(client, db_session):
    """One unusable entry must not cost the rest of the heartbeat."""
    from app.features.windows_update.schemas import TITLE_MAX

    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-degrade")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        defender={"av_enabled": True, "rtp_enabled": True, "signature_age_days": 1},
        windows_update={
            "pending": [
                # No update_id: nothing to key on, so it is dropped.
                _update("", kb="KB1"),
                # Unknown type and an over-long title: normalised, not rejected.
                _update("u-ok", type="firmware", title="T" * (TITLE_MAX + 100)),
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled)
    assert body["wu_pending_count"] == 1
    kept = body["pending_updates"][0]
    assert kept["update_id"] == "u-ok"
    assert kept["type"] == "software"
    assert len(kept["title"]) == TITLE_MAX
    # The Defender state riding along in the same request survived.
    assert body["is_up_to_date"] is True


async def test_same_update_twice_in_one_report(client, db_session):
    """A WUA search can list one update twice; the upsert must not blow up."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-dup")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        windows_update={
            "pending": [
                _update("u-dup", title="premiere"),
                _update("u-dup", title="derniere"),
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled)
    assert body["wu_pending_count"] == 1
    assert body["pending_updates"][0]["title"] == "derniere"


async def test_pending_updates_sorted_by_severity(client, db_session):
    """Critical first — MSRC's own vocabulary sorts uselessly on its own."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-sort")

    await _heartbeat(
        client,
        enrolled["token"],
        windows_update={
            "pending": [
                _update("u-low", severity="Low"),
                _update("u-none", severity=None),
                _update("u-crit", severity="Critical"),
                _update("u-mod", severity="Moderate"),
                _update("u-imp", severity="Important"),
            ]
        },
    )
    body = await _detail(client, headers, enrolled)
    assert [u["update_id"] for u in body["pending_updates"]] == [
        "u-crit",
        "u-imp",
        "u-mod",
        "u-low",
        "u-none",
    ]


async def test_machine_list_carries_the_wu_columns(client, db_session):
    """The list answers "who is behind" without opening every machine."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-list")
    await _heartbeat(
        client,
        enrolled["token"],
        windows_update={"reboot_required": True, "pending": [_update("u-1")]},
    )

    listed = await client.get("/api/v1/machines", headers=headers)
    row = next(m for m in listed.json()["items"] if m["machine_uuid"] == "m-wu-list")
    assert row["wu_pending_count"] == 1
    assert row["wu_reboot_required"] is True


async def test_machine_list_filters_on_wu_state(client, db_session):
    """The dashboard's card links: pending updates, and reboot pending.

    A machine that never reported (NULL count) matches neither filter — unknown
    is not behind.
    """
    headers = await _admin_headers(client, db_session)

    behind = await _enroll(client, "m-wu-filter-behind")
    await _heartbeat(
        client, behind["token"], windows_update={"pending": [_update("u-behind")]}
    )
    rebooting = await _enroll(client, "m-wu-filter-reboot")
    await _heartbeat(
        client,
        rebooting["token"],
        windows_update={"reboot_required": True, "pending": []},
    )
    await _enroll(client, "m-wu-filter-silent")

    resp = await client.get("/api/v1/machines?wu_status=pending", headers=headers)
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["m-wu-filter-behind"]

    resp = await client.get(
        "/api/v1/machines?wu_status=reboot_required", headers=headers
    )
    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["m-wu-filter-reboot"]


async def test_never_reported_machine_reads_as_unknown(client, db_session):
    """NULL count = never reported, which is not "nothing to install"."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-never")
    await _heartbeat(client, enrolled["token"], agent_version="test")

    body = await _detail(client, headers, enrolled)
    assert body["wu_pending_count"] is None
    assert body["wu_reboot_required"] is False
    assert body["wu_last_search"] is None
    assert body["pending_updates"] == []


async def test_merged_duplicate_drops_its_pending_updates(client, db_session):
    """The kept machine's own set survives; the duplicate's rows go with it."""
    headers = await _admin_headers(client, db_session)
    target = await _enroll(
        client, "m-wu-merge-keep", fingerprint={"smbios_uuid": "s-wu"}
    )
    source = await _enroll(
        client, "m-wu-merge-drop", fingerprint={"smbios_uuid": "s-wu"}
    )

    await _heartbeat(
        client, target["token"], windows_update={"pending": [_update("u-target")]}
    )
    await _heartbeat(
        client, source["token"], windows_update={"pending": [_update("u-source")]}
    )

    merged = await client.post(
        f"/api/v1/machines/{target['machine_id']}/merge",
        headers=headers,
        json={"source_id": source["machine_id"]},
    )
    assert merged.status_code == 200, merged.text
    # Current state, not history: the duplicate's pending set is not reattached,
    # and the kept machine's count still matches its rows.
    body = merged.json()
    assert [u["update_id"] for u in body["pending_updates"]] == ["u-target"]
    assert body["wu_pending_count"] == 1


# --- Commands ---------------------------------------------------------------

WU_TYPES = ["wu_scan", "wu_install", "wu_install_full", "reboot"]


@pytest.mark.parametrize("command_type", WU_TYPES)
async def test_wu_command_round_trip(client, db_session, command_type):
    """Each new type is creatable, deliverable and closeable."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, f"m-wu-cmd-{command_type}")

    created = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": command_type, "machine_ids": [enrolled["machine_id"]]},
    )
    assert created.status_code == 200, created.text

    hb = await _heartbeat(client, enrolled["token"])
    commands = hb.json()["commands"]
    assert [c["type"] for c in commands] == [command_type]
    command_id = commands[0]["id"]

    res = await client.post(
        f"/api/v1/agent/commands/{command_id}/result",
        headers={"Authorization": f"Bearer {enrolled['token']}"},
        json={"status": "succeeded", "output": "ok"},
    )
    assert res.status_code == 200

    listed = await client.get(
        f"/api/v1/commands?machine_id={enrolled['machine_id']}", headers=headers
    )
    row = next(c for c in listed.json()["items"] if c["id"] == command_id)
    assert row["status"] == "succeeded"


async def test_wu_install_reports_running_then_its_verdict(client, db_session):
    """The long install announces itself, then closes — two distinct writes."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wu-running")
    auth = {"Authorization": f"Bearer {enrolled['token']}"}

    await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "wu_install", "machine_ids": [enrolled["machine_id"]]},
    )
    hb = await _heartbeat(client, enrolled["token"])
    command_id = hb.json()["commands"][0]["id"]

    await client.post(
        f"/api/v1/agent/commands/{command_id}/result",
        headers=auth,
        json={"status": "running"},
    )

    async def row() -> dict:
        listed = await client.get(
            f"/api/v1/commands?machine_id={enrolled['machine_id']}", headers=headers
        )
        return next(c for c in listed.json()["items"] if c["id"] == command_id)

    started = await row()
    assert started["status"] == "running"
    assert started["started_at"] is not None
    assert started["finished_at"] is None

    await client.post(
        f"/api/v1/agent/commands/{command_id}/result",
        headers=auth,
        json={"status": "succeeded", "output": "KB5063878 : installee"},
    )
    done = await row()
    assert done["status"] == "succeeded"
    assert done["started_at"] == started["started_at"]
    assert done["result_output"] == "KB5063878 : installee"


async def test_wu_commands_forbidden_for_readonly(client, db_session):
    """The new types need command:execute like every other one."""
    from app.features.user import crud
    from app.features.user.models import Role

    await crud.create_user(
        db_session, email="wu-ro@test.local", password="pw", role=Role.READONLY
    )
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "wu-ro@test.local", "password": "pw"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "reboot", "target_all": True},
    )
    assert resp.status_code == 403


# --- Stats ------------------------------------------------------------------


async def test_stats_counts_pending_and_reboot(client, db_session):
    """Two KPIs over machines, not over update rows."""
    headers = await _admin_headers(client, db_session)

    behind = await _enroll(client, "m-wu-kpi-behind")
    await _heartbeat(
        client,
        behind["token"],
        windows_update={
            "reboot_required": True,
            "pending": [_update("u-1"), _update("u-2")],
        },
    )

    patched = await _enroll(client, "m-wu-kpi-patched")
    await _heartbeat(
        client,
        patched["token"],
        windows_update={"reboot_required": True, "pending": []},
    )

    silent = await _enroll(client, "m-wu-kpi-silent")
    await _heartbeat(client, silent["token"], agent_version="test")

    body = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    # Only the machine with rows counts as behind: the patched one reports zero
    # and the silent one has never reported at all.
    assert body["machines_wu_pending"] == 1
    # Both machines that reported reboot_required count, patched or not: what
    # matters is the pending restart, not the reason for it.
    assert body["machines_reboot_required"] == 2
