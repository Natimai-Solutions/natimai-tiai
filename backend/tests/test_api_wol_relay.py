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
        # A version that knows the command: an agent that names none, or
        # none that reads as one, is no relay (audit T35).
        json={"machine_uuid": machine_uuid, "agent_version": "1.2.0", **body},
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
    # The postes of these tests are all enrolled a second ago.
    monkeypatch.setattr(settings, "WOL_RELAY_MIN_AGE_MINUTES", 0)

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


async def test_a_claim_left_unanswered_goes_back_to_the_queue(
    client, db_session, relay_mode, site, monkeypatch
):
    """Audit B29: a relay that took the wake and said nothing (switched off,
    an agent that dropped it) does not keep it; another one takes it."""
    import uuid as _uuid
    from datetime import timedelta

    from sqlalchemy import update

    from app.core.config import settings
    from app.features.base import utcnow
    from app.features.command.models import Command

    headers = await _admin_headers(client, db_session)
    await _wake(client, headers, site["target"]["machine_id"])
    handed = (await _heartbeat(client, site["near"]["token"]))["commands"]
    assert len(handed) == 1
    await db_session.exec(
        update(Command)
        .where(Command.id == _uuid.UUID(handed[0]["id"]))
        .values(delivered_at=utcnow() - timedelta(minutes=5))
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 0)
    again = (await _heartbeat(client, site["far"]["token"]))["commands"]
    assert [c["id"] for c in again] == [handed[0]["id"]]


async def test_a_released_claim_is_not_handed_back_to_the_same_relay(
    client, db_session, relay_mode, site, monkeypatch
):
    """Audit B29 (T35): the relay that dropped the wake does not take it
    again on its next heartbeat; another poste of the site does."""
    import uuid as _uuid
    from datetime import timedelta

    from sqlalchemy import update

    from app.core.config import settings
    from app.features.base import utcnow
    from app.features.command.models import Command

    headers = await _admin_headers(client, db_session)
    await _wake(client, headers, site["target"]["machine_id"])
    handed = (await _heartbeat(client, site["near"]["token"]))["commands"]
    assert len(handed) == 1
    await db_session.exec(
        update(Command)
        .where(Command.id == _uuid.UUID(handed[0]["id"]))
        .values(delivered_at=utcnow() - timedelta(minutes=5))
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 0)
    assert (await _heartbeat(client, site["near"]["token"]))["commands"] == []
    rows = await _commands(client, headers, site["target"]["machine_id"])
    assert rows[0]["status"] == "pending"
    again = (await _heartbeat(client, site["far"]["token"]))["commands"]
    assert [c["id"] for c in again] == [handed[0]["id"]]


@pytest.mark.parametrize("version", ["0.9.0", "dev", ""])
async def test_only_trusted_relays_count_as_online_peers(
    client, db_session, relay_mode, version
):
    """Audit T35: an old agent (or one naming no usable version) online is
    not a poste that "can relay": the wake is refused at once."""
    headers = await _admin_headers(client, db_session)
    target = await _enroll(client, "m-t", location="Annexe")
    await _heartbeat(
        client, target["token"], location="Annexe", mac_address="AA:BB:CC:DD:EE:04"
    )
    peer = await _enroll(client, "m-old", location="Annexe", agent_version=version)
    await _heartbeat(client, peer["token"], location="Annexe")

    body = await _wake(client, headers, target["machine_id"])
    assert (body["woken"], body["failed"]) == (0, 1)
    assert "Aucun poste allumé" in body["results"][0]["detail"]


async def test_a_fresh_or_old_agent_does_not_relay(
    client, db_session, relay_mode, site, monkeypatch
):
    """Audit S19, B29: enrolled minutes ago, or older than the command."""
    from app.core.config import settings

    headers = await _admin_headers(client, db_session)
    await _wake(client, headers, site["target"]["machine_id"])
    monkeypatch.setattr(settings, "WOL_RELAY_MIN_AGE_MINUTES", 60)
    assert (await _heartbeat(client, site["near"]["token"]))["commands"] == []
    monkeypatch.setattr(settings, "WOL_RELAY_MIN_AGE_MINUTES", 0)
    old = await _heartbeat(client, site["near"]["token"], agent_version="0.9.0")
    assert old["commands"] == []
    ok = await _heartbeat(client, site["near"]["token"], agent_version="1.1.0")
    assert [c["type"] for c in ok["commands"]] == ["wake_on_lan"]


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


# --- third verification pass --------------------------------------------------


async def _age_claim(db_session, command_id: str) -> None:
    """Make a claim old enough to be released on the next heartbeat."""
    import uuid as _uuid
    from datetime import timedelta

    from sqlalchemy import update

    from app.features.base import utcnow
    from app.features.command.models import Command

    await db_session.exec(
        update(Command)
        .where(Command.id == _uuid.UUID(command_id))
        .values(delivered_at=utcnow() - timedelta(minutes=5))
    )
    await db_session.commit()


async def test_the_only_relay_of_a_site_takes_its_released_wake_again(
    client, db_session, relay_mode
):
    """One trusted relay on the site: excluding it after a release would leave
    the wake with no taker until its TTL, and a second click answered
    "déjà en attente d'un poste relais"."""
    headers = await _admin_headers(client, db_session)
    target = await _enroll(client, "m-solo-target", location="École de Tautira")
    await _heartbeat(
        client,
        target["token"],
        location="École de Tautira",
        ip_address="10.9.1.200",
        ip_prefix_length=24,
        mac_address="AA:BB:CC:DD:EE:10",
    )
    only = await _enroll(client, "m-solo-relay", location="École de Tautira")
    await _heartbeat(
        client,
        only["token"],
        location="École de Tautira",
        ip_address="10.9.1.9",
        ip_prefix_length=24,
    )
    from app.features.machine.models import Machine

    # The target is off: it would otherwise close its own wake, and count.
    await _switch_off(db_session, Machine, target["machine_id"])

    await _wake(client, headers, target["machine_id"])
    handed = (await _heartbeat(client, only["token"]))["commands"]
    assert len(handed) == 1
    await _age_claim(db_session, handed[0]["id"])

    again = (await _heartbeat(client, only["token"]))["commands"]
    assert [c["id"] for c in again] == [handed[0]["id"]]
    rows = await _commands(client, headers, target["machine_id"])
    assert rows[0]["status"] == "delivered"


async def _switch_off(db_session, machine_model, machine_id: str) -> None:
    import uuid as _uuid
    from datetime import timedelta

    from sqlalchemy import update

    from app.features.base import utcnow

    await db_session.exec(
        update(machine_model)
        .where(machine_model.id == _uuid.UUID(machine_id))
        .values(last_seen=utcnow() - timedelta(hours=3))
    )
    await db_session.commit()


async def test_a_released_relay_waits_only_while_another_one_could_take_the_wake(
    client, db_session, relay_mode, site, monkeypatch
):
    """Two relays: the released one stays excluded while the other, never
    released for this wake, is on; once that one has dropped it too — or is
    off — nobody else is left and the first may claim again."""
    from app.core.config import settings
    from app.features.machine.models import Machine

    headers = await _admin_headers(client, db_session)
    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 0)
    # Two relays on the site, not three.
    await _switch_off(db_session, Machine, site["elsewhere"]["machine_id"])
    await _switch_off(db_session, Machine, site["target"]["machine_id"])

    await _wake(client, headers, site["target"]["machine_id"])
    first = (await _heartbeat(client, site["near"]["token"]))["commands"]
    assert len(first) == 1
    wake_id = first[0]["id"]
    await _age_claim(db_session, wake_id)

    # "far" is on and was never handed this wake: "near" keeps out.
    assert (await _heartbeat(client, site["near"]["token"]))["commands"] == []
    second = (await _heartbeat(client, site["far"]["token"]))["commands"]
    assert [c["id"] for c in second] == [wake_id]
    await _age_claim(db_session, wake_id)

    # Both have dropped it once: the next one to come takes it.
    third = (await _heartbeat(client, site["near"]["token"]))["commands"]
    assert [c["id"] for c in third] == [wake_id]


async def test_a_released_relay_claims_again_when_the_other_one_went_off(
    client, db_session, relay_mode, site, monkeypatch
):
    from app.core.config import settings
    from app.features.machine.models import Machine

    headers = await _admin_headers(client, db_session)
    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 0)
    await _switch_off(db_session, Machine, site["target"]["machine_id"])

    await _wake(client, headers, site["target"]["machine_id"])
    first = (await _heartbeat(client, site["near"]["token"]))["commands"]
    await _age_claim(db_session, first[0]["id"])
    assert (await _heartbeat(client, site["near"]["token"]))["commands"] == []

    await _switch_off(db_session, Machine, site["far"]["machine_id"])
    again = (await _heartbeat(client, site["near"]["token"]))["commands"]
    assert [c["id"] for c in again] == [first[0]["id"]]


def _mixed_parc(now):
    """Postes of two sites and one domain, across every reason a poste is or
    is not a relay: flags, age, version, and being on at all."""
    import itertools
    import uuid as _uuid
    from datetime import timedelta

    from app.features.machine.models import Machine

    versions = [
        None,
        "",
        "  ",
        "dev",
        "0.9.3",
        "v0.2.0",
        "1.0.0",
        "v1.2.0",
        "2.0.0-rc1",
    ]
    machines = []
    combos = itertools.product(
        [("Site A", None), ("Site B", "dom.local"), (None, "dom.local")],
        versions,
        [timedelta(days=30), timedelta(minutes=5)],  # settled, or just enrolled
        [timedelta(seconds=30), timedelta(hours=2)],  # on, or off
    )
    for index, ((location, domain), version, age, silence) in enumerate(combos):
        machines.append(
            Machine(
                id=_uuid.uuid4(),
                machine_uuid=f"mixed-{index}",
                hostname=f"PC-{index}",
                location=location,
                domain=domain,
                agent_version=version,
                first_seen=now - age,
                last_seen=now - silence,
                needs_verification=index % 7 == 3,
                token_revoked=index % 11 == 5,
            )
        )
    return machines


async def test_the_sql_count_of_online_peers_matches_the_python_rule(
    db_session, monkeypatch
):
    """The count is done in SQL (flags, age) and per distinct version; it must
    say exactly what ``trusted_relay`` says of each poste, one by one."""
    from datetime import timedelta

    from app.core.config import settings
    from app.features.base import utcnow
    from app.features.wol import relay

    monkeypatch.setattr(settings, "WOL_RELAY_MIN_AGE_MINUTES", 60)
    monkeypatch.setattr(settings, "WOL_RELAY_MIN_AGENT_VERSION", "1.0.0")
    now = utcnow()
    machines = _mixed_parc(now)
    db_session.add_all(machines)
    await db_session.commit()
    for machine in machines:
        await db_session.refresh(machine)

    cutoff = now - timedelta(seconds=settings.OFFLINE_AFTER_SECONDS)

    def expected(target) -> int:
        return sum(
            1
            for m in machines
            if relay.shares_wire(m, target)
            and m.last_seen >= cutoff
            and relay.trusted_relay(m, now)
        )

    batch = relay.WakeBatch(now=now)
    seen = set()
    for target in machines:
        want = expected(target)
        seen.add(want)
        assert await relay.count_online_peers(db_session, target, now) == want
        assert (
            await relay.count_online_peers(db_session, target, now, batch=batch) == want
        )
    # The set is mixed enough to tell the rules apart, and the batch asked
    # once per site rather than once per poste.
    assert len(seen) > 2 and 0 not in seen
    assert set(batch.peers) == {
        ("location", "Site A"),
        ("location", "Site B"),
        ("domain", "dom.local"),
    }


async def test_a_bulk_wake_costs_queries_per_site_not_per_poste(
    client, db_session, engine, relay_mode
):
    """A selection of 120 postes over two sites: the statements issued by the
    request do not grow with the selection (they were two per poste)."""
    import uuid as _uuid
    from datetime import timedelta

    from sqlalchemy import event

    from app.features.base import utcnow
    from app.features.machine.models import Machine

    headers = await _admin_headers(client, db_session)
    now = utcnow()

    def poste(name: str, site_name: str, *, on: bool) -> Machine:
        return Machine(
            id=_uuid.uuid4(),
            machine_uuid=name,
            hostname=name,
            location=site_name,
            agent_version="1.2.0",
            mac_address="AA:BB:CC:00:00:01",
            first_seen=now - timedelta(days=30),
            last_seen=now - (timedelta(seconds=10) if on else timedelta(hours=5)),
        )

    targets = [
        poste(f"off-{site_name}-{n}", site_name, on=False)
        for site_name in ("Site A", "Site B")
        for n in range(60)
    ]
    relays = [
        poste(f"on-{s}-{n}", s, on=True) for s in ("Site A", "Site B") for n in range(3)
    ]
    ids = [str(t.id) for t in targets]
    db_session.add_all(targets + relays)
    await db_session.commit()

    statements: list[str] = []

    def count(_conn, _cursor, statement, *_rest):
        statements.append(statement)

    async def woken(selection: list[str]) -> int:
        statements.clear()
        body = await _wake(client, headers, *selection)
        assert (body["woken"], body["failed"]) == (len(selection), 0)
        assert "3 poste(s) allumé(s)" in body["results"][0]["detail"]
        return len(statements)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        few = await woken(ids[:2] + ids[60:62])
        many = await woken(ids[2:60] + ids[62:])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert many <= few + 2, (few, many)
    assert many < 25


async def test_the_same_poste_twice_in_a_selection_is_queued_once(
    client, db_session, relay_mode, site
):
    """The wakes already open are read ahead for the whole selection: the
    second mention of a poste must still find the wake the first one queued."""
    from app.features.machine.models import Machine

    headers = await _admin_headers(client, db_session)
    await _switch_off(db_session, Machine, site["target"]["machine_id"])
    target_id = site["target"]["machine_id"]
    body = await _wake(client, headers, target_id, target_id)
    assert "déjà en attente" in body["results"][1]["detail"]
    rows = await _commands(client, headers, target_id)
    assert [r["status"] for r in rows] == ["pending"]
