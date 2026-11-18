"""The codes stored beside a command's verdict (requires TIAI_TEST_DATABASE_URL).

Plan ``dev/plan-console-bilingue.md``, I3 and I5: a verdict the server writes,
or one the agent sends with a ``message_code``, is stored as
``result_code`` + ``result_params`` beside its French text, which stays as
before; the console words the code in its reader's language. An older agent
sends none, and nothing changes.
"""

import uuid
from datetime import timedelta

from tests.test_api_wol_relay import (  # noqa: F401 — fixtures
    _admin_headers,
    _commands,
    _enroll,
    _heartbeat,
    _wake,
    relay_mode,
    site,
)


async def _queue(client, headers, machine_id: str, type_: str = "flush_dns") -> None:
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": type_, "machine_ids": [machine_id]},
    )
    assert resp.status_code == 200, resp.text


async def _report(client, token: str, command_id: str, **body) -> dict:
    resp = await client.post(
        f"/api/v1/agent/commands/{command_id}/result",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_the_agent_code_is_stored_beside_its_text(client, db_session):
    headers = await _admin_headers(client, db_session)
    poste = await _enroll(client, "m-codes")
    await _queue(client, headers, poste["machine_id"])
    handed = (await _heartbeat(client, poste["token"]))["commands"]

    await _report(
        client,
        poste["token"],
        handed[0]["id"],
        status="failed",
        error="interrompue par l'arrêt de l'agent avant d'avoir commencé : à relancer",
        message_code="agent.stopped",
        message_params={"n": 1, "ok": True, "label": "x", "none": None},
    )
    row = (await _commands(client, headers, poste["machine_id"]))[0]
    assert row["status"] == "failed"
    assert row["error"] == (
        "interrompue par l'arrêt de l'agent avant d'avoir commencé : à relancer"
    )
    assert row["result_code"] == "agent.stopped"
    assert row["result_params"] == {"n": 1, "ok": True, "label": "x", "none": None}


async def test_an_older_agent_sends_no_code_and_nothing_changes(client, db_session):
    headers = await _admin_headers(client, db_session)
    poste = await _enroll(client, "m-old-agent")
    await _queue(client, headers, poste["machine_id"])
    handed = (await _heartbeat(client, poste["token"]))["commands"]

    await _report(
        client, poste["token"], handed[0]["id"], status="succeeded", output="OK"
    )
    row = (await _commands(client, headers, poste["machine_id"]))[0]
    assert (row["result_output"], row["result_code"], row["result_params"]) == (
        "OK",
        None,
        None,
    )


async def test_a_malformed_code_is_dropped_and_the_verdict_kept(client, db_session):
    headers = await _admin_headers(client, db_session)
    poste = await _enroll(client, "m-bad-code")
    await _queue(client, headers, poste["machine_id"])
    handed = (await _heartbeat(client, poste["token"]))["commands"]

    await _report(
        client,
        poste["token"],
        handed[0]["id"],
        status="failed",
        error="texte",
        message_code="Pas un code !",
        message_params={"nested": {"a": 1}},
    )
    row = (await _commands(client, headers, poste["machine_id"]))[0]
    assert (row["status"], row["error"]) == ("failed", "texte")
    assert (row["result_code"], row["result_params"]) == (None, None)


async def test_a_lost_command_carries_its_code_until_the_poste_answers(
    client, db_session
):
    """The server's closure is coded; the poste's late verdict replaces it,
    code included."""
    from app.features.command import crud as command_crud
    from app.features.command.models import Command

    headers = await _admin_headers(client, db_session)
    poste = await _enroll(client, "m-lost")
    await _queue(client, headers, poste["machine_id"])
    handed = (await _heartbeat(client, poste["token"]))["commands"]

    row = await db_session.get(Command, uuid.UUID(handed[0]["id"]))
    assert row is not None and row.delivered_at is not None
    row.delivered_at -= timedelta(hours=7)
    await db_session.commit()
    assert await command_crud.close_unanswered(db_session, hours=6) == 1
    await db_session.commit()

    listed = (await _commands(client, headers, poste["machine_id"]))[0]
    assert listed["status"] == "failed"
    assert listed["error"].startswith("Sans réponse du poste 6 h après la remise")
    assert (listed["result_code"], listed["result_params"]) == (
        "command.unanswered",
        {"hours": 6},
    )

    await _report(client, poste["token"], handed[0]["id"], status="succeeded")
    listed = (await _commands(client, headers, poste["machine_id"]))[0]
    assert listed["status"] == "succeeded"
    assert (listed["result_code"], listed["result_params"]) == (None, None)


async def test_a_wake_emitted_by_the_server_is_coded(client, db_session, monkeypatch):
    monkeypatch.setattr("app.features.wol.sender._emit", lambda *a, **k: None)
    headers = await _admin_headers(client, db_session)
    poste = await _enroll(client, "m-wake-coded")
    await _heartbeat(
        client,
        poste["token"],
        ip_address="10.4.7.200",
        ip_prefix_length=24,
        mac_address="AA:BB:CC:DD:EE:FF",
    )
    unknown = str(uuid.uuid4())

    body = await _wake(client, headers, poste["machine_id"], unknown)
    sent, missing = body["results"]
    assert sent["detail_code"] == "wol.sent"
    assert sent["detail_params"]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert sent["detail"].startswith("Paquet magique émis vers AA:BB:CC:DD:EE:FF")
    assert (missing["detail_code"], missing["detail_params"]) == (
        "wol.unknown_machine",
        {},
    )
    assert missing["detail"] == "Poste introuvable : il a été supprimé ou fusionné."

    row = (await _commands(client, headers, poste["machine_id"]))[0]
    assert row["result_output"] == sent["detail"]
    assert (row["result_code"], row["result_params"]) == (
        "wol.sent",
        sent["detail_params"],
    )


async def test_a_relayed_verdict_is_signed_in_its_params(
    client,
    db_session,
    relay_mode,  # noqa: F811
    site,  # noqa: F811
):
    headers = await _admin_headers(client, db_session)
    body = await _wake(client, headers, site["target"]["machine_id"])
    assert body["results"][0]["detail_code"] == "wol.relay_queued"
    assert body["results"][0]["detail_params"]["site"] == "Lycée de Taravao"

    handed = (await _heartbeat(client, site["near"]["token"]))["commands"]
    await _report(
        client,
        site["near"]["token"],
        handed[0]["id"],
        status="succeeded",
        output="Paquet magique émis",
        message_code="wol.relay.sent",
        message_params={"mac": "AA:BB:CC:DD:EE:FF", "copies": 3, "targets": "x"},
    )
    row = (await _commands(client, headers, site["target"]["machine_id"]))[0]
    assert row["result_output"].startswith("Relayé par ")
    assert row["result_code"] == "wol.relay.sent"
    assert row["result_params"]["relay"]
    assert row["result_output"] == (
        f"Relayé par {row['result_params']['relay']} — Paquet magique émis"
    )
    assert row["result_params"]["copies"] == 3


async def test_a_wake_refused_at_once_is_coded(
    client,
    db_session,
    relay_mode,  # noqa: F811
):
    headers = await _admin_headers(client, db_session)
    lonely = await _enroll(client, "m-lonely", location="Nulle part")
    await _heartbeat(
        client,
        lonely["token"],
        location="Nulle part",
        ip_address="10.9.9.9",
        ip_prefix_length=24,
        mac_address="AA:BB:CC:DD:EE:01",
    )
    body = await _wake(client, headers, lonely["machine_id"])
    # The target itself heartbeat a second ago: it counts as on, and is not
    # its own relay — no other poste of the site.
    assert body["results"][0]["detail_code"] == "wol.no_relay"
    assert body["results"][0]["detail_params"] == {
        "site_kind": "location",
        "site": "Nulle part",
    }
    row = (await _commands(client, headers, lonely["machine_id"]))[0]
    assert row["result_code"] == "wol.no_relay"
    assert row["error"] == body["results"][0]["detail"]
