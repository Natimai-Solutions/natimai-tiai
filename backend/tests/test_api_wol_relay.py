"""Wake-on-LAN relayed by an agent (requires TIAI_TEST_DATABASE_URL).

A server hosted off-site cannot put a frame on the postes' wire. With
``WOL_RELAY_ENABLED`` it hands the wake to the first poste of the target's
site to contact it, MAC included, and that poste emits. These tests walk the
whole path: the console queues, a heartbeat claims, the relay reports.
"""

import pytest


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="relay-admin@test.local",
        password="pw",
        groups=[BuiltinGroup.ADMIN],
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "relay-admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _enroll(client, machine_uuid: str, **body) -> dict:
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, **body},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _heartbeat(client, token: str, **body) -> dict:
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wake(client, headers, *machine_ids: str) -> dict:
    resp = await client.post(
        "/api/v1/machines/wake",
        headers=headers,
        json={"machine_ids": list(machine_ids)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _commands(client, headers, machine_id: str) -> list[dict]:
    resp = await client.get(
        f"/api/v1/commands?machine_id={machine_id}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


@pytest.fixture
def relay_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WOL_RELAY_ENABLED", True)
    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 90)

    # The server must not emit anything itself in this mode: a datagram from
    # a remote host reaches nothing, and reporting it would be a lie.
    def forbid(*_args, **_kwargs):
        raise AssertionError("the server emitted a packet in relay mode")

    monkeypatch.setattr("app.features.wol.sender._emit", forbid)


@pytest.fixture
async def site(client):
    """Two postes at Taravao on one subnet, a third on another VLAN of the
    same site, and one at Papeete. The first is the one to wake; it has
    heartbeat once, so its MAC and subnet are known, and is now "off"."""
    target = await _enroll(client, "m-target", location="Lycée de Taravao")
    await _heartbeat(
        client,
        target["token"],
        location="Lycée de Taravao",
        ip_address="10.4.7.200",
        ip_prefix_length=24,
        mac_address="AA:BB:CC:DD:EE:FF",
    )
    near = await _enroll(client, "m-near", location="Lycée de Taravao")
    await _heartbeat(
        client,
        near["token"],
        location="Lycée de Taravao",
        ip_address="10.4.7.9",
        ip_prefix_length=24,
    )
    far = await _enroll(client, "m-far", location="Lycée de Taravao")
    await _heartbeat(
        client,
        far["token"],
        location="Lycée de Taravao",
        ip_address="10.4.8.9",
        ip_prefix_length=24,
    )
    elsewhere = await _enroll(client, "m-elsewhere", location="Collège de Papeete")
    await _heartbeat(
        client,
        elsewhere["token"],
        location="Collège de Papeete",
        ip_address="10.4.7.10",
        ip_prefix_length=24,
    )
    return {"target": target, "near": near, "far": far, "elsewhere": elsewhere}


async def test_the_wake_is_queued_and_the_same_subnet_poste_claims_it(
    client, db_session, relay_mode, site
):
    """The nominal path, end to end."""
    headers = await _admin_headers(client, db_session)

    body = await _wake(client, headers, site["target"]["machine_id"])
    assert body["relayed"] is True
    assert (body["woken"], body["failed"]) == (1, 0)
    assert "Lycée de Taravao" in body["results"][0]["detail"]

    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert [(r["type"], r["status"]) for r in rows] == [("wake_on_lan", "pending")]

    # A poste of another site never sees it, whatever its subnet looks like.
    assert (await _heartbeat(client, site["elsewhere"]["token"]))["commands"] == []
    # A poste of the site on another VLAN waits for the better placed one.
    assert (await _heartbeat(client, site["far"]["token"]))["commands"] == []
    # The poste on the target's subnet gets it, MAC included.
    handed = (await _heartbeat(client, site["near"]["token"]))["commands"]
    assert len(handed) == 1
    assert handed[0]["type"] == "wake_on_lan"
    assert handed[0]["target_mac"] == "AA:BB:CC:DD:EE:FF"
    assert handed[0]["id"] == rows[0]["id"]
    # Once claimed, nobody else is handed it.
    assert (await _heartbeat(client, site["near"]["token"]))["commands"] == []

    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert rows[0]["status"] == "delivered"
    assert rows[0]["relay_machine_id"] == site["near"]["machine_id"]

    # The relay reports on the target's row, and is named for it.
    done = await client.post(
        f"/api/v1/agent/commands/{handed[0]['id']}/result",
        headers={"Authorization": f"Bearer {site['near']['token']}"},
        json={
            "status": "succeeded",
            "output": "Paquet magique émis vers AA:BB:CC:DD:EE:FF",
        },
    )
    assert done.json() == {"status": "ok"}
    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["result_output"].startswith("Relayé par ")
    assert "AA:BB:CC:DD:EE:FF" in rows[0]["result_output"]


async def test_another_vlan_of_the_site_claims_once_the_grace_has_run(
    client, db_session, relay_mode, site, monkeypatch
):
    from app.core.config import settings

    headers = await _admin_headers(client, db_session)
    await _wake(client, headers, site["target"]["machine_id"])
    assert (await _heartbeat(client, site["far"]["token"]))["commands"] == []

    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 0)
    handed = (await _heartbeat(client, site["far"]["token"]))["commands"]
    assert [c["type"] for c in handed] == ["wake_on_lan"]
    assert handed[0]["target_mac"] == "AA:BB:CC:DD:EE:FF"


async def test_the_domain_stands_in_for_a_missing_location(
    client, db_session, relay_mode
):
    """A parc deployed without locations still relays, within its domain."""
    headers = await _admin_headers(client, db_session)
    target = await _enroll(client, "m-nolocation", domain="natimai.local")
    await _heartbeat(client, target["token"], mac_address="AA:BB:CC:DD:EE:01")
    peer = await _enroll(client, "m-peer", domain="natimai.local")
    await _heartbeat(client, peer["token"])
    stranger = await _enroll(client, "m-stranger", domain="other.local")
    await _heartbeat(client, stranger["token"])

    body = await _wake(client, headers, target["machine_id"])
    assert body["woken"] == 1
    assert "natimai.local" in body["results"][0]["detail"]

    assert (await _heartbeat(client, stranger["token"]))["commands"] == []
    # No subnet is known on either side, so the peer waits the grace…
    assert (await _heartbeat(client, peer["token"]))["commands"] == []


async def test_a_site_with_nothing_on_is_refused_at_once(
    client, db_session, relay_mode
):
    """Saying so now beats a wake that expires unclaimed ten minutes later."""
    headers = await _admin_headers(client, db_session)
    target = await _enroll(client, "m-alone", location="Annexe")
    await _heartbeat(
        client, target["token"], location="Annexe", mac_address="AA:BB:CC:DD:EE:02"
    )

    body = await _wake(client, headers, target["machine_id"])
    assert (body["woken"], body["failed"]) == (0, 1)
    assert "Aucun poste allumé" in body["results"][0]["detail"]
    rows = await _commands(client, headers, target["machine_id"])
    assert [(r["type"], r["status"]) for r in rows] == [("wake_on_lan", "failed")]


async def test_a_target_without_a_mac_or_a_peer_key_is_refused(
    client, db_session, relay_mode
):
    headers = await _admin_headers(client, db_session)
    no_mac = await _enroll(client, "m-no-mac", location="Lycée de Taravao")
    orphan = await _enroll(client, "m-orphan")
    await _heartbeat(client, orphan["token"], mac_address="AA:BB:CC:DD:EE:03")

    body = await _wake(client, headers, no_mac["machine_id"], orphan["machine_id"])
    assert (body["woken"], body["failed"]) == (0, 2)
    assert "adresse MAC" in body["results"][0]["detail"]
    assert "ni emplacement ni domaine" in body["results"][1]["detail"]


async def test_a_second_click_does_not_queue_a_second_wake(
    client, db_session, relay_mode, site
):
    headers = await _admin_headers(client, db_session)
    first = await _wake(client, headers, site["target"]["machine_id"])
    second = await _wake(client, headers, site["target"]["machine_id"])
    assert first["woken"] == 1
    assert second["woken"] == 1
    assert "déjà en attente" in second["results"][0]["detail"]
    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert len(rows) == 1


async def test_the_target_coming_back_closes_its_own_wake(
    client, db_session, relay_mode, site
):
    """The one acknowledgement a wake can have: the poste's own heartbeat."""
    headers = await _admin_headers(client, db_session)
    await _wake(client, headers, site["target"]["machine_id"])

    hb = await _heartbeat(client, site["target"]["token"])
    # Never handed to the poste it targets.
    assert hb["commands"] == []
    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert rows[0]["status"] == "succeeded"
    assert "revenu en ligne" in rows[0]["result_output"]
    # And the relays have nothing left to claim.
    assert (await _heartbeat(client, site["near"]["token"]))["commands"] == []


async def test_a_relays_late_verdict_does_not_reopen_a_closed_wake(
    client, db_session, relay_mode, site
):
    headers = await _admin_headers(client, db_session)
    await _wake(client, headers, site["target"]["machine_id"])
    handed = (await _heartbeat(client, site["near"]["token"]))["commands"]
    await _heartbeat(client, site["target"]["token"])  # the poste is back

    late = await client.post(
        f"/api/v1/agent/commands/{handed[0]['id']}/result",
        headers={"Authorization": f"Bearer {site['near']['token']}"},
        json={"status": "failed", "error": "trop tard"},
    )
    assert late.json() == {"status": "ignored"}
    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["error"] is None


async def test_only_the_relay_that_claimed_may_report(
    client, db_session, relay_mode, site
):
    headers = await _admin_headers(client, db_session)
    await _wake(client, headers, site["target"]["machine_id"])
    handed = (await _heartbeat(client, site["near"]["token"]))["commands"]

    other = await client.post(
        f"/api/v1/agent/commands/{handed[0]['id']}/result",
        headers={"Authorization": f"Bearer {site['far']['token']}"},
        json={"status": "succeeded", "output": "pas moi"},
    )
    assert other.json() == {"status": "ignored"}
    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert rows[0]["status"] == "delivered"


async def test_a_wake_cannot_be_queued_through_the_command_endpoint(
    client, db_session, site
):
    """It would sit on the target with nobody designated to emit it."""
    headers = await _admin_headers(client, db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "wake_on_lan", "machine_ids": [site["target"]["machine_id"]]},
    )
    assert resp.status_code == 422


async def test_relay_mode_off_leaves_the_server_emitting(
    client, db_session, site, monkeypatch
):
    """The default: the server emits, the row is written closed, no relay."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "WOL_RELAY_ENABLED", False)
    sent = []
    monkeypatch.setattr(
        "app.features.wol.sender._emit",
        lambda dests, port, payload, count: sent.append(dests),
    )
    headers = await _admin_headers(client, db_session)
    body = await _wake(client, headers, site["target"]["machine_id"])
    assert body["relayed"] is False
    assert sent == [["10.4.7.255"]]
    assert (await _heartbeat(client, site["near"]["token"]))["commands"] == []
