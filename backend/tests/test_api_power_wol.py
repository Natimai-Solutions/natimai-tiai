"""Powering a poste down and bringing it back (requires TIAI_TEST_DATABASE_URL).

Two halves that only make sense together: ``shutdown``, an ordinary catalogue
command executed by the agent, and the Wake-on-LAN that undoes it — the one
action in this console the *server* performs itself, because the machine it
targets is off and has no agent to ask.
"""

import uuid

import pytest


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.models import Role

    await crud.create_user(
        db_session, email="power-admin@test.local", password="pw", role=Role.ADMIN
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "power-admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _readonly_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.models import Role

    await crud.create_user(
        db_session, email="power-ro@test.local", password="pw", role=Role.READONLY
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "power-ro@test.local", "password": "pw"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _enroll(client, machine_uuid: str) -> dict:
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _heartbeat(client, token: str, **body):
    return await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def _detail(client, headers, machine_id: str) -> dict:
    resp = await client.get(f"/api/v1/machines/{machine_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _commands(client, headers, machine_id: str) -> list[dict]:
    resp = await client.get(
        f"/api/v1/commands?machine_id={machine_id}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have gone on the wire instead of putting it there."""
    calls: list[dict] = []

    def record(destinations, port, payload, count):
        calls.append(
            {
                "destinations": destinations,
                "port": port,
                "payload": payload,
                "count": count,
            }
        )

    monkeypatch.setattr("app.features.wol.sender._emit", record)
    return calls


# --- Shutdown ---------------------------------------------------------------


async def test_shutdown_round_trip(client, db_session):
    """Queued, delivered on a heartbeat, closed by the agent — like any command.

    The guards that make a shutdown different from a flush_dns are not here:
    they are in the console (confirmation) and, where it counts, in the agent
    itself (``agent/internal/agent/power.go``), on the machine actually going
    down.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-shutdown")

    created = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "shutdown", "machine_ids": [enrolled["machine_id"]]},
    )
    assert created.status_code == 200, created.text

    hb = await _heartbeat(client, enrolled["token"])
    commands = hb.json()["commands"]
    assert [c["type"] for c in commands] == ["shutdown"]

    done = await client.post(
        f"/api/v1/agent/commands/{commands[0]['id']}/result",
        headers={"Authorization": f"Bearer {enrolled['token']}"},
        json={"status": "succeeded", "output": "Arret programme dans 60 secondes."},
    )
    assert done.status_code == 200
    rows = await _commands(client, headers, enrolled["machine_id"])
    assert [(r["type"], r["status"]) for r in rows] == [("shutdown", "succeeded")]


async def test_shutdown_cannot_be_stacked(client, db_session):
    """Same de-duplication as the restart, and for a sharper reason.

    A second shutdown queued behind the first would meet the poste at its next
    boot — now that the console can wake it, that is a machine switching itself
    off the moment somebody wakes it.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-shutdown-dedup")
    body = {"type": "shutdown", "machine_ids": [enrolled["machine_id"]]}

    first = await client.post("/api/v1/commands", headers=headers, json=body)
    second = await client.post("/api/v1/commands", headers=headers, json=body)
    assert first.json()["count"] == 1
    assert second.json()["count"] == 0
    assert second.json()["skipped"] == 1


async def test_shutdown_forbidden_for_readonly(client, db_session):
    headers = await _readonly_headers(client, db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "shutdown", "target_all": True},
    )
    assert resp.status_code == 403


# --- The MAC the agent reports ----------------------------------------------


async def test_heartbeat_stores_the_mac_canonically(client, db_session):
    """Whatever notation arrives, one shape is stored and shown."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-mac")

    resp = await _heartbeat(client, enrolled["token"], mac_address="aa-bb-cc-dd-ee-ff")
    assert resp.status_code == 200

    detail = await _detail(client, headers, enrolled["machine_id"])
    assert detail["mac_address"] == "AA:BB:CC:DD:EE:FF"


async def test_a_malformed_mac_costs_the_mac_and_nothing_else(client, db_session):
    """One unreadable field must not 422 the heartbeat it rode in on.

    The Defender state, the threats and the command pickup travel in the same
    request; dropping the value to NULL simply leaves the stored MAC alone.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-mac-bad")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        mac_address="00:00:00:00:00:00",
        hostname="POSTE-42",
    )
    assert resp.status_code == 200

    detail = await _detail(client, headers, enrolled["machine_id"])
    assert detail["mac_address"] is None
    assert detail["hostname"] == "POSTE-42"


async def test_heartbeat_stores_the_mask_the_poste_reported(client, db_session):
    """The mask comes from the adapter, not from a server-side assumption."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-prefix")

    resp = await _heartbeat(
        client, enrolled["token"], ip_address="10.4.7.9", ip_prefix_length=16
    )
    assert resp.status_code == 200

    detail = await _detail(client, headers, enrolled["machine_id"])
    assert detail["ip_prefix_length"] == 16


async def test_a_mask_that_is_not_one_costs_the_mask_and_nothing_else(
    client, db_session
):
    """Zero is what Windows leaves when it did not fill the field in, and a /0
    whose broadcast address is 255.255.255.255 — never the poste. Dropped to
    NULL, and the heartbeat carries on.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-prefix-bad")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        ip_address="10.4.7.9",
        ip_prefix_length=0,
        hostname="POSTE-9",
    )
    assert resp.status_code == 200

    detail = await _detail(client, headers, enrolled["machine_id"])
    assert detail["ip_prefix_length"] is None
    assert detail["ip_address"] == "10.4.7.9"
    assert detail["hostname"] == "POSTE-9"


async def test_a_heartbeat_without_a_mac_keeps_the_last_known_one(client, db_session):
    """The only way to wake a poste: an agent that could not read the adapter
    must never erase the address that still can.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-mac-keep")

    await _heartbeat(client, enrolled["token"], mac_address="AA:BB:CC:DD:EE:FF")
    await _heartbeat(client, enrolled["token"], hostname="POSTE-7")

    detail = await _detail(client, headers, enrolled["machine_id"])
    assert detail["mac_address"] == "AA:BB:CC:DD:EE:FF"


# --- Wake-on-LAN ------------------------------------------------------------


async def test_wake_broadcasts_on_the_subnet_of_the_last_known_address(
    client, db_session, sent
):
    """The nominal path: a poste that has reported an address and a MAC.

    The destination is derived from the poste's *own* address — a packet
    broadcast on the server's segment would never reach a machine two VLANs
    away — and the packet is the magic pattern, asserted byte for byte because
    nothing downstream will ever tell us it was wrong.
    """
    from app.core.config import settings

    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake")
    await _heartbeat(
        client,
        enrolled["token"],
        ip_address="192.168.1.42",
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["woken"], body["failed"]) == (1, 0)
    assert body["results"][0]["ok"] is True
    assert "192.168.1.255" in body["results"][0]["detail"]

    assert len(sent) == 1
    assert sent[0]["destinations"] == ["192.168.1.255"]
    assert sent[0]["port"] == settings.WOL_PORT
    assert sent[0]["count"] == settings.WOL_PACKET_COUNT
    assert sent[0]["payload"] == b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16


async def test_a_wake_is_recorded_in_the_command_history(client, db_session, sent):
    """Who woke this poste, and when — answered where "who restarted it" is.

    The row is written already closed: the wake happened here, in the server,
    and there is nothing left for an agent to do about it.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-audit")
    await _heartbeat(
        client,
        enrolled["token"],
        ip_address="192.168.1.42",
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )

    rows = await _commands(client, headers, enrolled["machine_id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "wake_on_lan"
    assert row["status"] == "succeeded"
    assert row["created_by"] == "power-admin@test.local"
    assert row["finished_at"] is not None
    assert "AA:BB:CC:DD:EE:FF" in row["result_output"]
    assert row["error"] is None


async def test_a_wake_is_never_handed_to_an_agent(client, db_session, sent):
    """The guard that keeps a server-executed type out of the agent's way.

    ``wake_on_lan`` lives in the same enum as the commands an agent runs, so the
    heartbeat had better never offer it one: an agent that picked it up would
    log an unknown type and leave the row hanging as delivered forever.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-not-delivered")
    await _heartbeat(
        client,
        enrolled["token"],
        ip_address="192.168.1.42",
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )

    hb = await _heartbeat(client, enrolled["token"])
    assert hb.json()["commands"] == []


async def test_a_poste_in_16_is_woken_on_its_own_broadcast_not_the_default(
    client, db_session, sent, monkeypatch
):
    """The whole point of having the agent report the mask.

    The server is left on its /24 default and the poste says /16: the packet must
    go to 10.4.255.255, not to the 10.4.7.255 the default would have produced —
    an address nothing listens on when the segment is a /16.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "WOL_SUBNET_PREFIXLEN", 24)
    monkeypatch.setattr(settings, "WOL_BROADCAST_ADDRESSES", [])
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-16")
    await _heartbeat(
        client,
        enrolled["token"],
        ip_address="10.4.7.9",
        ip_prefix_length=16,
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )
    assert resp.json()["woken"] == 1
    assert sent[0]["destinations"] == ["10.4.255.255"]


async def test_a_poste_that_reported_no_mask_falls_back_on_the_setting(
    client, db_session, sent, monkeypatch
):
    """An agent older than the reporting still gets woken, on the configured mask."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "WOL_SUBNET_PREFIXLEN", 16)
    monkeypatch.setattr(settings, "WOL_BROADCAST_ADDRESSES", [])
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-old-agent")
    await _heartbeat(
        client,
        enrolled["token"],
        ip_address="10.4.7.9",
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )
    assert resp.json()["woken"] == 1
    assert sent[0]["destinations"] == ["10.4.255.255"]


async def test_configured_broadcast_addresses_replace_the_derived_one(
    client, db_session, sent, monkeypatch
):
    """A server that must reach segments it holds no address on."""
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "WOL_BROADCAST_ADDRESSES", ["10.0.0.255", "10.0.1.255"]
    )
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-configured")
    await _heartbeat(
        client,
        enrolled["token"],
        ip_address="192.168.1.42",
        mac_address="AA:BB:CC:DD:EE:FF",
    )

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )
    assert resp.json()["woken"] == 1
    assert sent[0]["destinations"] == ["10.0.0.255", "10.0.1.255"]


async def test_a_poste_without_a_mac_cannot_be_woken(client, db_session, sent):
    """Refused and recorded, not attempted: there is nothing to name.

    A poste enrolled but never heard from again — or one whose agent predates
    the MAC reporting — has no wake target, and the console has to say so rather
    than report a success nobody can check.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-no-mac")

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )
    body = resp.json()
    assert (body["woken"], body["failed"]) == (0, 1)
    assert "adresse MAC" in body["results"][0]["detail"]
    assert sent == []

    rows = await _commands(client, headers, enrolled["machine_id"])
    assert [(r["type"], r["status"]) for r in rows] == [("wake_on_lan", "failed")]
    assert rows[0]["error"]


async def test_a_poste_without_an_address_has_nowhere_to_be_woken(
    client, db_session, sent, monkeypatch
):
    """No last known IPv4 and nothing configured → no destination, no packet.

    255.255.255.255 is not substituted: from a container it reaches the Docker
    bridge and nothing else, and a wake that silently failed would be worse than
    one that explains itself.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "WOL_BROADCAST_ADDRESSES", [])
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-no-ip")
    await _heartbeat(client, enrolled["token"], mac_address="AA:BB:CC:DD:EE:FF")

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [enrolled["machine_id"]]},
    )
    body = resp.json()
    assert (body["woken"], body["failed"]) == (0, 1)
    assert "diffusion" in body["results"][0]["detail"]
    assert sent == []


async def test_one_unknown_id_does_not_cost_the_others_their_wake(
    client, db_session, sent
):
    """A selection is not the unit of success here; the poste is."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-wake-mixed")
    await _heartbeat(
        client,
        enrolled["token"],
        ip_address="192.168.1.42",
        mac_address="AA:BB:CC:DD:EE:FF",
    )
    ghost = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [ghost, enrolled["machine_id"]]},
    )
    body = resp.json()
    assert (body["woken"], body["failed"]) == (1, 1)
    # Order is the caller's, so a console can line the answers up with what it
    # asked for.
    assert [r["machine_id"] for r in body["results"]] == [
        ghost,
        enrolled["machine_id"],
    ]
    assert body["results"][0]["ok"] is False
    assert len(sent) == 1


async def test_wake_forbidden_for_readonly(client, db_session, sent):
    """Waking a poste is acting on it: command:execute, like every other action."""
    headers = await _readonly_headers(client, db_session)
    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": [str(uuid.uuid4())]},
    )
    assert resp.status_code == 403
    assert sent == []
