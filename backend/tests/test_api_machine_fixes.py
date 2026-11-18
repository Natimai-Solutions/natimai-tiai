"""Acceptance fixes on the agent boundary, the machines and the command queue
(require TIAI_TEST_DATABASE_URL).

Enrollment whose answer was lost, concurrent enrollments and merges, identity
confirmation, re-enrollment visibility, commands for a revoked poste, merged
commands, verdict finality, control characters, download slots, relayed-wake
wording and the signature age read at read time.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest


async def _admin(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session, email="admin@test.local", password="pw", groups=[BuiltinGroup.ADMIN]
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "admin@test.local", "password": "pw"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _readonly(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session, email="ro@test.local", password="pw", groups=[BuiltinGroup.READONLY]
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "ro@test.local", "password": "pw"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _enroll_raw(client, machine_uuid, **fields):
    from app.core.config import settings

    return await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, **fields},
    )


async def _enroll(client, machine_uuid, **fields) -> dict:
    resp = await _enroll_raw(client, machine_uuid, **fields)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _heartbeat(client, token, **body):
    return await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def _result(client, token, command_id, **body):
    return await client.post(
        f"/api/v1/agent/commands/{command_id}/result",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def _queue(client, headers, machine_id, command_type="quick_scan"):
    return await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": command_type, "machine_ids": [machine_id]},
    )


async def _command(db_session, command_id):
    from app.features.command.models import Command

    db_session.expire_all()
    return await db_session.get(Command, uuid.UUID(str(command_id)))


async def _machine(db_session, machine_id):
    from app.features.machine.models import Machine

    db_session.expire_all()
    return await db_session.get(Machine, uuid.UUID(str(machine_id)))


async def _audit_actions(db_session) -> list[str]:
    from sqlmodel import select

    from app.features.audit.models import AuditEntry

    db_session.expire_all()
    rows = await db_session.exec(select(AuditEntry.action))
    return list(rows.all())


FP = {"machine_guid": "guid-1", "smbios_uuid": "4c4c4544-0042-1111-2222-333344445555"}


# --- 1. An enrollment whose answer was lost ----------------------------------------


async def test_a_lost_enrollment_answer_is_completed_by_the_retry(client, db_session):
    first = await _enroll(client, "m-lost", hostname="PC-LOST", fingerprint=FP)
    retry = await _enroll(client, "m-lost", hostname="PC-LOST", fingerprint=FP)
    assert retry["machine_id"] == first["machine_id"]
    assert retry["token"] != first["token"]
    # The unused token is dead, the new one works: one live token per poste.
    assert (await _heartbeat(client, first["token"])).status_code == 401
    assert (await _heartbeat(client, retry["token"])).status_code == 200
    assert "machine.enrollment_retried" in await _audit_actions(db_session)
    machine = await _machine(db_session, first["machine_id"])
    assert machine.reenroll_requested_at is None


async def test_a_used_token_still_requires_approval(client, db_session):
    first = await _enroll(client, "m-used", fingerprint=FP)
    assert (await _heartbeat(client, first["token"])).status_code == 200
    again = await _enroll_raw(client, "m-used", fingerprint=FP)
    assert again.status_code == 403
    assert again.json()["error"]["code"] == "machine.enrollment.approval_required"
    assert (await _heartbeat(client, first["token"])).status_code == 200


async def test_a_retry_with_another_fingerprint_requires_approval(client, db_session):
    first = await _enroll(client, "m-fp", fingerprint=FP)
    other = {**FP, "smbios_uuid": "4c4c4544-0042-9999-9999-999999999999"}
    again = await _enroll_raw(client, "m-fp", fingerprint=other)
    assert again.status_code == 403
    # Omitting the fingerprint is no way around the comparison either.
    bare = await _enroll_raw(client, "m-fp")
    assert bare.status_code == 403
    assert (await _heartbeat(client, first["token"])).status_code == 200


async def test_a_retry_long_after_the_enrollment_requires_approval(client, db_session):
    first = await _enroll(client, "m-late", fingerprint=FP)
    machine = await _machine(db_session, first["machine_id"])
    machine.token_issued_at = datetime.now(UTC) - timedelta(hours=2)
    machine.last_seen = datetime.now(UTC) - timedelta(hours=3)
    db_session.add(machine)
    await db_session.commit()
    again = await _enroll_raw(client, "m-late", fingerprint=FP)
    assert again.status_code == 403


async def _rotation_offer(client, db_session, enrolled) -> str:
    """Age the poste's token past the rotation threshold and return the new
    one its next heartbeat is offered."""
    machine = await _machine(db_session, enrolled["machine_id"])
    machine.token_issued_at = datetime.now(UTC) - timedelta(days=31)
    db_session.add(machine)
    await db_session.commit()
    hb = await _heartbeat(client, enrolled["token"], supports_token_rotation=True)
    assert hb.status_code == 200, hb.text
    offered = hb.json()["new_token"]
    assert offered
    return offered


async def _assert_held_for_approval(client, db_session, machine_uuid, token) -> None:
    again = await _enroll_raw(client, machine_uuid, fingerprint=FP)
    assert again.status_code == 403, "an established poste was re-enrolled"
    assert again.json()["error"]["code"] == "machine.enrollment.approval_required"
    # The poste keeps its token, and the attempt leaves its trace.
    assert (await _heartbeat(client, token)).status_code == 200
    assert "machine.reenroll_requested" in await _audit_actions(db_session)
    assert "machine.enrollment_retried" not in await _audit_actions(db_session)


async def test_a_rotated_token_first_used_on_a_verdict_is_not_an_unused_one(
    client, db_session, monkeypatch
):
    """The agent stores a rotated token before it runs the commands of the
    same heartbeat: the first request carrying it is a verdict, which
    restarts ``token_issued_at`` without moving ``last_seen``."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_TOKEN_ROTATE_DAYS", 30)
    headers = await _admin(client, db_session)
    first = await _enroll(client, "m-rot", fingerprint=FP)
    assert (await _heartbeat(client, first["token"])).status_code == 200
    queued = (await _queue(client, headers, first["machine_id"])).json()
    new_token = await _rotation_offer(client, db_session, first)
    verdict = await _result(client, new_token, queued["created"][0], status="succeeded")
    assert verdict.json()["status"] == "ok"
    machine = await _machine(db_session, first["machine_id"])
    # The very state the retry used to read as « never used ».
    assert machine.token_issued_at > machine.last_seen
    assert machine.pending_token_hash is None

    await _assert_held_for_approval(client, db_session, "m-rot", new_token)


async def test_a_rotated_token_first_used_on_a_refused_heartbeat_is_not_unused(
    client, db_session, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_TOKEN_ROTATE_DAYS", 30)
    first = await _enroll(client, "m-rot-422", fingerprint=FP)
    assert (await _heartbeat(client, first["token"])).status_code == 200
    new_token = await _rotation_offer(client, db_session, first)
    # Authenticated, then refused on its body: the promotion is committed.
    refused = await _heartbeat(client, new_token, ip_prefix_length="not-a-number")
    assert refused.status_code == 422

    await _assert_held_for_approval(client, db_session, "m-rot-422", new_token)


async def test_any_authenticated_request_uses_the_enrollment_token(client, db_session):
    """Not the heartbeat alone: a verdict, a download or a request refused
    after authentication each prove the agent holds its token."""
    calls = {
        "verdict": lambda token: _result(
            client, token, uuid.uuid4(), status="succeeded"
        ),
        "download": lambda token: client.get(
            f"/api/v1/agent/packages/{uuid.uuid4()}/files/{'0' * 64}",
            headers={"Authorization": f"Bearer {token}"},
        ),
        "refused": lambda token: _heartbeat(client, token, threats="not-a-list"),
    }
    for name, call in calls.items():
        first = await _enroll(client, f"m-any-{name}", fingerprint=FP)
        machine = await _machine(db_session, first["machine_id"])
        assert machine.enrollment_token_unused is True
        assert (await call(first["token"])).status_code in (200, 404, 422)
        machine = await _machine(db_session, first["machine_id"])
        assert machine.enrollment_token_unused is False, name
        again = await _enroll_raw(client, f"m-any-{name}", fingerprint=FP)
        assert again.status_code == 403, name
        assert (await _heartbeat(client, first["token"])).status_code == 200


async def test_a_wrong_or_revoked_token_does_not_use_the_enrollment_token(
    client, db_session
):
    headers = await _admin(client, db_session)
    first = await _enroll(client, "m-not-used", fingerprint=FP)
    assert (await _heartbeat(client, "not-the-token")).status_code == 401
    machine = await _machine(db_session, first["machine_id"])
    assert machine.enrollment_token_unused is True
    # The retry of the lost answer still goes through…
    retry = await _enroll(client, "m-not-used", fingerprint=FP)
    # …and a revoked poste's request neither counts nor matters: it is refused.
    revoked = await client.post(
        f"/api/v1/machines/{first['machine_id']}/revoke-token", headers=headers
    )
    assert revoked.status_code == 200, revoked.text
    assert (await _heartbeat(client, retry["token"])).status_code == 401
    assert (await _enroll_raw(client, "m-not-used", fingerprint=FP)).status_code == 403


async def test_a_token_minted_after_an_approval_can_be_retried_once_unused(
    client, db_session
):
    headers = await _admin(client, db_session)
    first = await _enroll(client, "m-approved", fingerprint=FP)
    assert (await _heartbeat(client, first["token"])).status_code == 200
    assert (await _enroll_raw(client, "m-approved", fingerprint=FP)).status_code == 403
    allowed = await client.post(
        f"/api/v1/machines/{first['machine_id']}/allow-reenroll", headers=headers
    )
    assert allowed.status_code == 200, allowed.text
    # The answer to the approved enrollment is lost like any other…
    await _enroll(client, "m-approved", fingerprint=FP)
    second = await _enroll(client, "m-approved", fingerprint=FP)
    # …and once the poste has used its token, the door is shut again.
    assert (await _heartbeat(client, second["token"])).status_code == 200
    assert (await _enroll_raw(client, "m-approved", fingerprint=FP)).status_code == 403


async def test_an_offered_rotation_closes_the_retry(client, db_session):
    """Defence in depth: a rotation offer exists only because a heartbeat was
    accepted, so a row carrying one is never « unused », whatever its flag."""
    from app.core import security

    first = await _enroll(client, "m-pending", fingerprint=FP)
    machine = await _machine(db_session, first["machine_id"])
    assert machine.enrollment_token_unused is True
    machine.pending_token_hash = security.hash_token("offered")
    db_session.add(machine)
    await db_session.commit()
    again = await _enroll_raw(client, "m-pending", fingerprint=FP)
    assert again.status_code == 403


# --- 8. Races and the identity's spelling -------------------------------------------


async def test_simultaneous_enrollments_of_a_new_poste_never_500(
    client, db_session, monkeypatch
):
    from app.api.routes import agent as agent_routes

    # Every request looks the identity up before any of them inserts it — the
    # race as it happens on a loaded server, made certain here.
    lookup = agent_routes._locked_machine
    barrier = asyncio.Barrier(8)
    waited: set[int] = set()

    async def all_at_once(session, machine_uuid):
        found = await lookup(session, machine_uuid)
        if id(session) not in waited:
            waited.add(id(session))
            await barrier.wait()
        return found

    monkeypatch.setattr(agent_routes, "_locked_machine", all_at_once)
    responses = await asyncio.gather(
        *(_enroll_raw(client, "m-race", fingerprint=FP) for _ in range(8))
    )
    statuses = [r.status_code for r in responses]
    assert 500 not in statuses, [r.text for r in responses]
    assert all(s == 200 or 400 <= s < 500 for s in statuses)
    ids = {r.json()["machine_id"] for r in responses if r.status_code == 200}
    assert len(ids) == 1
    from sqlmodel import func, select

    from app.features.machine.models import Machine

    count = await db_session.scalar(
        select(func.count())
        .select_from(Machine)
        .where(Machine.machine_uuid == "m-race")
    )
    assert count == 1


async def test_two_enrollments_of_a_known_poste_are_served_one_after_the_other(
    client, db_session, monkeypatch
):
    """After an approval the poste holds no token. Its own agent and whoever
    else holds the fleet secret then ask at once: one token is minted, and
    the other request meets it — not two, of which the last to commit wins."""
    from app.api.routes import agent as agent_routes

    headers = await _admin(client, db_session)
    first = await _enroll(client, "m-two", fingerprint=FP)
    assert (await _heartbeat(client, first["token"])).status_code == 200
    allowed = await client.post(
        f"/api/v1/machines/{first['machine_id']}/allow-reenroll", headers=headers
    )
    assert allowed.status_code == 200, allowed.text

    # Both read the row before either writes, where the lock allows it: the
    # one holding it goes on alone after a second.
    lookup = agent_routes._locked_machine
    arrived = 0
    both = asyncio.Event()

    async def read_together(session, machine_uuid):
        nonlocal arrived
        found = await lookup(session, machine_uuid)
        arrived += 1
        if arrived == 2:
            both.set()
        try:
            await asyncio.wait_for(both.wait(), timeout=1)
        except TimeoutError:
            pass
        return found

    monkeypatch.setattr(agent_routes, "_locked_machine", read_together)
    other = {**FP, "smbios_uuid": "4c4c4544-0042-9999-9999-999999999999"}
    one, two = await asyncio.gather(
        _enroll_raw(client, "m-two", fingerprint=FP),
        _enroll_raw(client, "m-two", fingerprint=other),
    )
    assert sorted([one.status_code, two.status_code]) == [200, 403], (
        one.text,
        two.text,
    )
    served, held = (one, two) if one.status_code == 200 else (two, one)
    assert held.json()["error"]["code"] == "machine.enrollment.approval_required"
    assert (await _heartbeat(client, served.json()["token"])).status_code == 200


async def test_the_identity_is_trimmed_and_never_blank(client, db_session):
    padded = await _enroll(client, "  m-padded  ")
    machine = await _machine(db_session, padded["machine_id"])
    assert machine.machine_uuid == "m-padded"
    for blank in ("", "   "):
        resp = await _enroll_raw(client, blank)
        assert resp.status_code == 422, resp.text


async def test_crossed_merges_never_500(client, db_session, monkeypatch):
    from app.api.routes import machines as machine_routes

    headers = await _admin(client, db_session)
    a = await _enroll(client, "m-cross-a")
    b = await _enroll(client, "m-cross-b")
    # Both merges read their pair before either writes, where the timing
    # allows it: a merge holding its locks goes on alone after a second.
    require = machine_routes._require_machine
    barrier = asyncio.Barrier(2)
    reads: dict[int, int] = {}

    async def read_together(session, machine_id, scope):
        machine = await require(session, machine_id, scope)
        reads[id(session)] = reads.get(id(session), 0) + 1
        if reads[id(session)] == 2:
            try:
                await asyncio.wait_for(barrier.wait(), timeout=1)
            except TimeoutError:
                pass
        return machine

    monkeypatch.setattr(machine_routes, "_require_machine", read_together)
    one, two = await asyncio.gather(
        client.post(
            f"/api/v1/machines/{a['machine_id']}/merge",
            headers=headers,
            json={"source_id": b["machine_id"]},
        ),
        client.post(
            f"/api/v1/machines/{b['machine_id']}/merge",
            headers=headers,
            json={"source_id": a["machine_id"]},
        ),
    )
    assert sorted([one.status_code, two.status_code]) == [200, 404], (
        one.text,
        two.text,
    )


# --- 5. A merge closes the absorbed record's open commands -------------------------


async def test_a_merge_closes_the_open_commands_it_absorbs(client, db_session):
    from app.features.machine.crud import MERGED_ERROR

    headers = await _admin(client, db_session)
    kept = await _enroll(client, "m-kept")
    gone = await _enroll(client, "m-gone")
    # One delivered (« Transmise »), one still pending, one closed.
    assert (await _queue(client, headers, gone["machine_id"])).json()["count"] == 1
    delivered = (await _heartbeat(client, gone["token"])).json()["commands"][0]["id"]
    done = (await _queue(client, headers, gone["machine_id"], "flush_dns")).json()
    await _heartbeat(client, gone["token"])
    await _result(client, gone["token"], done["created"][0], status="succeeded")
    pending = (await _queue(client, headers, gone["machine_id"], "full_scan")).json()

    merged = await client.post(
        f"/api/v1/machines/{kept['machine_id']}/merge",
        headers=headers,
        json={"source_id": gone["machine_id"]},
    )
    assert merged.status_code == 200, merged.text

    for command_id in (delivered, pending["created"][0]):
        row = await _command(db_session, command_id)
        assert str(row.machine_id) == kept["machine_id"]
        assert (row.status, row.error) == ("failed", MERGED_ERROR)
        assert row.finished_at is not None
    closed = await _command(db_session, done["created"][0])
    assert (str(closed.machine_id), closed.status) == (kept["machine_id"], "succeeded")
    # Nothing is handed to the kept poste twice, and nothing blocks it.
    assert (await _heartbeat(client, kept["token"])).json()["commands"] == []
    again = await _queue(client, headers, kept["machine_id"])
    assert again.json()["count"] == 1


# --- 6. A verdict from the poste is final ------------------------------------------


async def _delivered(client, headers, enrolled) -> str:
    await _queue(client, headers, enrolled["machine_id"])
    return (await _heartbeat(client, enrolled["token"])).json()["commands"][0]["id"]


async def test_a_second_verdict_does_not_overwrite_the_first(client, db_session):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-verdict")
    cid = await _delivered(client, headers, m)
    ok = await _result(client, m["token"], cid, status="succeeded", output="clean")
    assert ok.json()["status"] == "ok"
    first = await _command(db_session, cid)
    finished = first.finished_at

    other = await _result(client, m["token"], cid, status="failed", error="boom")
    assert other.status_code == 200
    assert other.json()["status"] == "ignored"
    replay = await _result(client, m["token"], cid, status="succeeded", output="x")
    assert replay.json()["status"] == "ignored"
    row = await _command(db_session, cid)
    assert (row.status, row.result_output, row.error) == ("succeeded", "clean", None)
    assert row.finished_at == finished


async def test_two_deliveries_of_one_verdict_are_judged_one_after_the_other(
    client, db_session, monkeypatch
):
    """The agent's queue replays a verdict whose answer it missed while the
    first delivery is still being served: one is recorded, the other ignored
    — not both read as the first and written one over the other."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.command.models import Command

    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-verdict-race")
    cid = await _delivered(client, headers, m)

    # Both read the command before either writes, where the lock allows it:
    # the one holding it goes on alone after a second.
    get = AsyncSession.get
    arrived = 0
    both = asyncio.Event()

    async def read_together(self, entity, ident, **kwargs):
        nonlocal arrived
        found = await get(self, entity, ident, **kwargs)
        if entity is Command:
            arrived += 1
            if arrived == 2:
                both.set()
            try:
                await asyncio.wait_for(both.wait(), timeout=1)
            except TimeoutError:
                pass
        return found

    monkeypatch.setattr(AsyncSession, "get", read_together)
    ok, ko = await asyncio.gather(
        _result(client, m["token"], cid, status="succeeded", output="clean"),
        _result(client, m["token"], cid, status="failed", error="boom"),
    )
    monkeypatch.undo()
    assert sorted([ok.json()["status"], ko.json()["status"]]) == ["ignored", "ok"]
    row = await _command(db_session, cid)
    recorded = (row.status, row.result_output, row.error)
    if ok.json()["status"] == "ok":
        assert recorded == ("succeeded", "clean", None)
    else:
        assert recorded == ("failed", None, "boom")


async def test_a_late_verdict_wins_over_a_server_closure(client, db_session):
    from app.features.command import crud as command_crud

    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-late-verdict")
    cid = await _delivered(client, headers, m)
    # « Sans réponse du poste » — the server's closure, not the poste's.
    await command_crud.close_unanswered(db_session, hours=0)
    await db_session.commit()
    assert (await _command(db_session, cid)).status == "failed"

    late = await _result(client, m["token"], cid, status="succeeded", output="done")
    assert late.json()["status"] == "ok"
    row = await _command(db_session, cid)
    assert (row.status, row.result_output, row.error) == ("succeeded", "done", None)
    # And that verdict is final in its turn.
    again = await _result(client, m["token"], cid, status="failed", error="no")
    assert again.json()["status"] == "ignored"
    assert (await _command(db_session, cid)).status == "succeeded"


async def test_a_late_verdict_wins_over_an_expiry(client, db_session):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-expired-verdict")
    cid = await _delivered(client, headers, m)
    row = await _command(db_session, cid)
    row.status = "expired"
    db_session.add(row)
    await db_session.commit()
    late = await _result(client, m["token"], cid, status="failed", error="disk")
    assert late.json()["status"] == "ok"
    assert (await _command(db_session, cid)).status == "failed"


async def test_a_running_ping_after_the_verdict_is_ignored(client, db_session):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-running-late")
    cid = await _delivered(client, headers, m)
    await _result(client, m["token"], cid, status="failed", error="x")
    ping = await _result(client, m["token"], cid, status="running")
    assert ping.json()["status"] == "ignored"
    assert (await _command(db_session, cid)).status == "failed"


# --- 7. Control characters ----------------------------------------------------------


async def test_nul_in_every_reported_string_is_stripped(client, db_session):
    from sqlmodel import select

    from app.features.inventory.models import MachineSoftware, Software
    from app.features.threat.models import Threat
    from app.features.windows_update.models import WindowsUpdate

    m = await _enroll(client, "m-nul\u0000", hostname="PC\u0000-ENR")
    hb = await _heartbeat(
        client,
        m["token"],
        hostname="PC\u0000-1",
        domain="dom\u0000ain",
        os_version="Windows\u0000 11",
        agent_version="1.\u00002",
        defender={"signature_version": "1.\u00001", "running_mode": "Nor\u0000mal"},
        av_product={"name": "ES\u0000ET", "enabled": True, "is_defender": False},
        session={
            "user_present": True,
            "username": "jo\u0000hn",
            "state": "act\u0001ive",
        },
        threats=[{"detection_id": "D\u00001", "threat_name": "EI\u0000CAR"}],
        windows_update={
            "pending": [{"update_id": "u\u00001", "title": "KB\u0000 title"}],
        },
        inventory={
            "hash": "h\u00001",
            "software": [{"name": "Fire\u0000fox", "version": "1", "publisher": "M"}],
            "directory": {"ou": "Sal\u0000le 1", "ad_location": "B\u0000t A"},
        },
    )
    assert hb.status_code == 200, hb.text

    machine = await _machine(db_session, m["machine_id"])
    assert machine.machine_uuid == "m-nul"
    assert (machine.hostname, machine.domain) == ("PC-1", "domain")
    assert (machine.os_version, machine.agent_version) == ("Windows 11", "1.2")
    assert (machine.signature_version, machine.running_mode) == ("1.1", "Normal")
    assert machine.av_product_name == "ESET"
    assert (machine.session_username, machine.session_state) == ("john", "active")
    assert (machine.ad_ou, machine.ad_location) == ("Salle 1", "Bt A")
    threat = (await db_session.exec(select(Threat))).one()
    assert (threat.detection_id, threat.threat_name) == ("D1", "EICAR")
    update = (await db_session.exec(select(WindowsUpdate))).one()
    assert update.title == "KB title"
    names = (
        await db_session.exec(
            select(Software.name).join(
                MachineSoftware, MachineSoftware.software_id == Software.id
            )
        )
    ).all()
    assert names == ["Firefox"]


async def test_nul_in_a_command_result_is_stripped_but_newlines_kept(
    client, db_session
):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-nul-result")
    cid = await _delivered(client, headers, m)
    res = await _result(
        client,
        m["token"],
        cid,
        status="failed",
        output="line\u00001\r\n\tline 2\u001b[0m",
        error="err\u0000or",
    )
    assert res.status_code == 200, res.text
    row = await _command(db_session, cid)
    assert row.result_output == "line1\r\n\tline 2[0m"
    assert row.error == "error"


async def test_a_lone_surrogate_from_a_poste_is_stripped_like_a_nul(client, db_session):
    """The other character JSON can spell and PostgreSQL cannot store: half
    of a UTF-16 pair. Same answer as for the NUL — it costs the character,
    not the heartbeat — and a whole pair is a character like any other."""
    m = await _enroll(client, "m-surrogate")
    auth = {
        "Authorization": f"Bearer {m['token']}",
        "Content-Type": "application/json",
    }
    for body, stored in (
        (b'{"hostname": "PC\\ud800-1"}', "PC-1"),
        (b'{"hostname": "PC\\udc00-2\\u0000"}', "PC-2"),
        (b'{"hostname": "PC\\uD83D\\uDE00-3"}', "PC\U0001f600-3"),
        (b'{"hostname": "PC\\ud83d-4\\ud83d\\ude00\\ude00"}', "PC-4\U0001f600"),
    ):
        hb = await client.post("/api/v1/agent/heartbeat", headers=auth, content=body)
        assert hb.status_code == 200, (body, hb.text)
        assert (await _machine(db_session, m["machine_id"])).hostname == stored


async def test_console_requests_with_a_nul_are_refused_not_500(client, db_session):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-console-nul")

    patched = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"full_name": "Jo\u0000hn"}
    )
    posted = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_domain": "dom\u0000"},
    )
    got = await client.get(
        "/api/v1/machines", headers=headers, params={"search": "PC\u0000"}
    )
    merged = await client.post(
        f"/api/v1/machines/{m['machine_id']}/merge",
        headers={**headers, "Content-Type": "application/json"},
        content=b'{"source_id": "\\u0000"}',
    )
    for resp in (patched, posted, got, merged):
        assert resp.status_code == 422, resp.text
        error = resp.json()["error"]
        assert error["code"] == "request.validation_error"
        assert error["details"]["errors"][0]["msg"] == "Caractère nul refusé"

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@test.local\u0000", "password": "pw"},
    )
    assert login.status_code in (401, 422), login.text
    # An ordinary request still goes through, accents and all.
    ok = await client.get(
        "/api/v1/machines", headers=headers, params={"search": "Lycée"}
    )
    assert ok.status_code == 200


async def test_a_nul_in_the_path_is_refused_on_the_console_only(client, db_session):
    headers = await _admin(client, db_session)
    for path in (
        "/api/v1/machines/abc%00def",
        "/api/v1/machines/%00/neighbours",
        "/api/v1/rooms/%00",
    ):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 422, (path, resp.text)
        assert resp.json()["error"]["message"] == "Caractère nul refusé", path
    # A poste is never refused on a character: its route answers, here that
    # what is not a SHA-256 names no file.
    m = await _enroll(client, "m-path-nul")
    resp = await client.get(
        f"/api/v1/agent/packages/{uuid.uuid4()}/files/abc%00def",
        headers={"Authorization": f"Bearer {m['token']}"},
    )
    assert resp.status_code == 404, resp.text


async def _through_the_middleware(path: str, body: bytes, chunk: int = 7):
    """Run ``ControlCharMiddleware`` over a JSON request as a server hands it
    over — lower-case headers, the body in several messages — and return what
    the application behind it was given: its headers and its body."""
    from app.core.control_chars import ControlCharMiddleware

    given: dict = {}

    async def application(scope, receive, send):
        received = b""
        while True:
            message = await receive()
            received += message.get("body", b"")
            if not message.get("more_body", False):
                break
        given["headers"] = list(scope["headers"])
        given["body"] = received

    chunks = [body[i : i + chunk] for i in range(0, len(body), chunk)]

    async def receive():
        piece = chunks.pop(0)
        return {"type": "http.request", "body": piece, "more_body": bool(chunks)}

    async def send(message):
        given.setdefault("sent", []).append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"host", b"tiai.test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"authorization", b"Bearer token"),
        ],
    }
    await ControlCharMiddleware(application)(scope, receive, send)
    return given


async def test_a_cleaned_agent_body_is_announced_at_its_new_length():
    """The body handed on is shorter than the one received: the request must
    not go on announcing the old length to whatever reads it next."""
    from app.core.config import settings

    path = f"{settings.API_V1_STR}/agent/heartbeat"
    raw = b'{"hostname": "PC\\u0000-1", "domain": "\\u00e9cole\\u0007"}'
    given = await _through_the_middleware(path, raw)
    assert given["body"] == '{"hostname": "PC-1", "domain": "école"}'.encode()
    assert len(given["body"]) != len(raw)
    lengths = [v for k, v in given["headers"] if k == b"content-length"]
    assert lengths == [str(len(given["body"])).encode()]
    assert (b"authorization", b"Bearer token") in given["headers"]
    assert (b"content-type", b"application/json") in given["headers"]

    # A body with nothing to strip is handed on as it came, header included.
    clean = b'{"hostname": "PC-1"}'
    given = await _through_the_middleware(path, clean)
    assert given["body"] == clean
    assert (b"content-length", str(len(clean)).encode()) in given["headers"]


def test_strip_controls_keeps_tab_newline_and_text():
    from app.core.control_chars import strip_controls

    assert strip_controls(
        {"a\u0000": ["x\u0000y", "\t\r\n", 3, None, {"k": "\u0007é"}]}
    ) == {"a": ["xy", "\t\r\n", 3, None, {"k": "é"}]}
    # Order kept, and two keys the stripping makes one resolve to the last.
    cleaned = strip_controls({"b": 1, "a\u0000": 2, "c": [], "a": 3, "d": {}})
    assert list(cleaned.items()) == [("b", 1), ("a", 3), ("c", []), ("d", {})]
    assert strip_controls("x\u0000") == "x"
    assert strip_controls(3.5) == 3.5


def _nested(depth: int, inner: str = "") -> str:
    return "[" * depth + inner + "]" * depth


@pytest.mark.parametrize("depth", [600, 1200, 30_000])
def test_the_walkers_have_no_depth_of_their_own(depth):
    """Not recursive: a body nested deeper than Python's call stack is still
    cleaned, or refused — what bounds the depth is the JSON parser alone."""
    from app.core.control_chars import _contains_nul, strip_controls

    def wrapped(inner):
        # Built by hand: the depth the parser reads varies with the interpreter.
        for _ in range(depth):
            inner = [inner]
        return inner

    assert _contains_nul(wrapped("a\u0000")) is True
    assert _contains_nul(wrapped({"a\u0000": 1})) is True
    assert _contains_nul(wrapped("a")) is False
    cleaned = strip_controls(wrapped({"k\u0001": ["a\u0000", 1]}))
    for _ in range(depth):
        (cleaned,) = cleaned
    assert cleaned == {"k": ["a", 1]}


# Deeper than the JSON parser itself goes, and deeper than the walkers'
# recursion went: the two ways a nested body used to end as a 500.
_PAST_THE_PARSER = 200_000
_PAST_THE_CALL_STACK = 1_200


async def test_a_deeply_nested_body_with_a_nul_is_answered_not_500(client, db_session):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-deep")
    agent = {"Authorization": f"Bearer {m['token']}"}
    json_body = {"Content-Type": "application/json"}

    def body(depth: int, name: str) -> bytes:
        return f'{{"hostname": "{name}", "full_name": "{name}", "z": {_nested(depth)}}}'.encode()

    async def post(path, auth, content):
        return await client.post(path, headers={**auth, **json_body}, content=content)

    # Past the parser: « not JSON », and the route answers what it answers
    # to the same body without the character.
    for path, auth in (
        ("/api/v1/agent/heartbeat", agent),
        ("/api/v1/agent/heartbeat", {}),
        ("/api/v1/commands", headers),
        ("/api/v1/commands", {}),
    ):
        plain = await post(path, auth, body(_PAST_THE_PARSER, "PC"))
        nul = await post(path, auth, body(_PAST_THE_PARSER, "PC\\u0000"))
        bell = await post(path, auth, body(_PAST_THE_PARSER, "PC\\u0007"))
        assert plain.status_code < 500, (path, plain.text)
        assert (nul.status_code, bell.status_code) == (
            plain.status_code,
            plain.status_code,
        ), path

    # Within it: handled like any other body, however deep.
    hb = await post(
        "/api/v1/agent/heartbeat", agent, body(_PAST_THE_CALL_STACK, "PC\\u0000-DEEP")
    )
    assert hb.status_code == 200, hb.text
    assert (await _machine(db_session, m["machine_id"])).hostname == "PC-DEEP"
    refused = await client.patch(
        "/api/v1/auth/me",
        headers={**headers, **json_body},
        content=body(_PAST_THE_CALL_STACK, "Jo\\u0000hn"),
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["message"] == "Caractère nul refusé"


async def test_an_agent_body_that_cannot_be_written_back_is_refused(
    client, db_session, monkeypatch
):
    """Parsed, but too deep for the encoder: handing the route the body
    uncleaned would let the control character through to the database."""
    import json

    from app.core import control_chars

    m = await _enroll(client, "m-unwritable", hostname="PC-BEFORE")

    encode = json.dumps
    calls = 0

    def too_deep_once(*args, **kwargs):
        # The first call is the middleware writing the cleaned body back;
        # the refusal that follows is encoded for real.
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RecursionError("maximum recursion depth exceeded")
        return encode(*args, **kwargs)

    monkeypatch.setattr(control_chars.json, "dumps", too_deep_once)
    # ``content``, not ``json``: the client's own encoder is the one patched.
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={
            "Authorization": f"Bearer {m['token']}",
            "Content-Type": "application/json",
        },
        content=b'{"hostname": "PC\\u0000-AFTER"}',
    )
    monkeypatch.undo()
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "request.validation_error"
    assert json.loads(resp.content)["error"]["message"] == "Corps JSON trop imbriqué"
    assert (await _machine(db_session, m["machine_id"])).hostname == "PC-BEFORE"


@pytest.mark.parametrize("field", ["username", "password", "scope", "client_id"])
async def test_a_nul_in_a_multipart_login_is_refused_not_500(client, db_session, field):
    """The middleware lets multipart bodies through unread, and the login
    form takes one as readily as a urlencoded body."""
    await _admin(client, db_session)
    form = {"username": "admin@test.local", "password": "pw"}

    def multipart(fields: dict[str, str]):
        return client.post(
            "/api/v1/auth/login", files={k: (None, v) for k, v in fields.items()}
        )

    ok = await multipart(form)
    assert ok.status_code == 200, ok.text
    resp = await multipart({**form, field: form.get(field, "x") + "\u0000"})
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "request.validation_error"
    assert error["message"] == "Caractère nul refusé"
    assert error["details"]["errors"][0]["msg"] == "Caractère nul refusé"
    # The urlencoded form answers the same, from the middleware.
    encoded = await client.post(
        "/api/v1/auth/login", data={**form, field: form.get(field, "x") + "\u0000"}
    )
    assert encoded.status_code == 422, encoded.text
    assert encoded.json()["error"] == error


# --- 9. Download slots --------------------------------------------------------------


async def test_a_refused_range_gives_its_download_slot_back(
    client, db_session, tmp_path, monkeypatch
):
    import hashlib

    from app.api.routes import agent as agent_routes
    from app.core.config import settings
    from app.features.command.models import Command
    from app.features.package.models import Package

    monkeypatch.setattr(settings, "PACKAGES_DIR", str(tmp_path / "packages"))
    monkeypatch.setattr(settings, "PACKAGE_MAX_CONCURRENT_DOWNLOADS", 2)
    monkeypatch.setattr(agent_routes, "_downloads_in_flight", 0)
    data = b"0123456789abcdef"
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / sha).write_bytes(data)

    m = await _enroll(client, "m-download")
    package = Package(kind="files", name="Pkg")
    db_session.add(package)
    await db_session.flush()
    package_id = package.id
    db_session.add(
        Command(
            machine_id=uuid.UUID(m["machine_id"]),
            type="package_install",
            status="delivered",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            package_id=package_id,
            package_files=[sha],
        )
    )
    await db_session.commit()
    url = f"/api/v1/agent/packages/{package_id}/files/{sha}"
    auth = {"Authorization": f"Bearer {m['token']}"}

    for _ in range(5):
        beyond = await client.get(url, headers={**auth, "Range": "bytes=100-200"})
        assert beyond.status_code == 416
        backwards = await client.get(url, headers={**auth, "Range": "bytes=10-5"})
        assert backwards.status_code == 400
    assert agent_routes._downloads_in_flight == 0
    whole = await client.get(url, headers=auth)
    assert whole.status_code == 200
    assert whole.content == data
    assert agent_routes._downloads_in_flight == 0


# --- 10. The relayed-wake wording ---------------------------------------------------


def test_a_waiting_wake_is_dated_by_its_age_not_a_utc_clock():
    from app.features.wol.relay import _elapsed

    now = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
    assert _elapsed(now - timedelta(seconds=20), now) == "moins d'une minute"
    assert _elapsed(now - timedelta(minutes=12, seconds=30), now) == "12 min"
    assert _elapsed(now - timedelta(minutes=65), now) == "1 h 05"


async def test_a_second_relayed_wake_says_since_how_long(
    client, db_session, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WOL_RELAY_ENABLED", True)
    monkeypatch.setattr(settings, "WOL_RELAY_MIN_AGE_MINUTES", 0)
    headers = await _admin(client, db_session)
    site = {"location": "Lycée de Taravao", "agent_version": "1.2.0"}
    target = await _enroll(client, "m-wake-target", **site)
    relay = await _enroll(client, "m-wake-relay", **site)
    for enrolled, mac, ip in (
        (target, "AA:BB:CC:DD:EE:01", "10.0.0.11"),
        (relay, "AA:BB:CC:DD:EE:02", "10.0.0.12"),
    ):
        hb = await _heartbeat(
            client,
            enrolled["token"],
            mac_address=mac,
            ip_address=ip,
            ip_prefix_length=24,
            location=site["location"],
        )
        assert hb.status_code == 200, hb.text
    # The target goes to sleep.
    machine = await _machine(db_session, target["machine_id"])
    machine.last_seen = datetime.now(UTC) - timedelta(hours=1)
    db_session.add(machine)
    await db_session.commit()

    body = {"machine_ids": [target["machine_id"]]}
    first = await client.post("/api/v1/machines/wake", headers=headers, json=body)
    assert first.json()["woken"] == 1, first.text
    second = await client.post("/api/v1/machines/wake", headers=headers, json=body)
    detail = second.json()["results"][0]["detail"]
    assert "depuis moins d'une minute" in detail, detail
    assert "UTC" not in detail


# --- 11. The signature age, read now ------------------------------------------------


async def _age_out(db_session, machine_id, days):
    machine = await _machine(db_session, machine_id)
    machine.signature_reported_at = datetime.now(UTC) - timedelta(days=days)
    machine.last_seen = datetime.now(UTC) - timedelta(days=days)
    db_session.add(machine)
    await db_session.commit()


async def test_a_silent_poste_does_not_stay_up_to_date(client, db_session):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-silent")
    defender = {"av_enabled": True, "rtp_enabled": True, "signature_age_days": 1}
    await _heartbeat(client, m["token"], defender=defender)
    detail = await client.get(f"/api/v1/machines/{m['machine_id']}", headers=headers)
    assert detail.json()["is_up_to_date"] is True
    assert (await client.get("/api/v1/stats/overview", headers=headers)).json()[
        "up_to_date"
    ] == 1

    await _age_out(db_session, m["machine_id"], 29)

    detail = (
        await client.get(f"/api/v1/machines/{m['machine_id']}", headers=headers)
    ).json()
    assert detail["is_up_to_date"] is False
    assert detail["signature_age_days"] == 30
    row = (await client.get("/api/v1/machines", headers=headers)).json()["items"][0]
    assert row["is_up_to_date"] is False
    fresh = await client.get("/api/v1/machines?status=up_to_date", headers=headers)
    assert fresh.json()["total"] == 0
    stale = await client.get("/api/v1/machines?status=outdated", headers=headers)
    assert stale.json()["total"] == 1
    stats = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    assert (stats["up_to_date"], stats["outdated"]) == (0, 1)
    # A broadcast to « à jour » reaches it no more.
    broadcast = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_status": "up_to_date"},
    )
    assert broadcast.json()["count"] == 0


async def test_the_digest_and_the_export_age_a_silent_poste_too(client, db_session):
    """The mail and the spreadsheet read the signature age the console reads:
    a poste silent for a month is not « à jour » there either."""
    from app.features.notification.digest import build_digest
    from app.features.notification.digest_texts import FR as DIGEST_FR

    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-silent-mail", hostname="PC-SILENCE")
    defender = {"av_enabled": True, "rtp_enabled": True, "signature_age_days": 1}
    await _heartbeat(client, m["token"], defender=defender)
    assert (await build_digest(db_session)).outdated_antivirus == 0

    await _age_out(db_session, m["machine_id"], 29)

    digest = await build_digest(db_session)
    assert digest.outdated_antivirus == 1
    assert [
        (line.hostname, line.worded(DIGEST_FR)) for line in digest.outdated_lines
    ] == [("PC-SILENCE", "signatures vieilles de 30 j")]
    export = await client.get(
        "/api/v1/machines/export.csv?columns=hostname,is_up_to_date,signature_age_days",
        headers=headers,
    )
    assert export.status_code == 200, export.text
    assert export.text.lstrip("\ufeff").splitlines()[1].split(";") == [
        "PC-SILENCE",
        "Non",
        "30",
    ]


async def test_a_third_party_antivirus_does_not_age(client, db_session):
    from app.features.notification.digest import build_digest

    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-eset")
    await _heartbeat(
        client,
        m["token"],
        defender={"av_enabled": False, "rtp_enabled": False, "signature_age_days": 1},
        av_product={"name": "ESET", "enabled": True, "is_defender": False},
    )
    await _age_out(db_session, m["machine_id"], 29)
    detail = (
        await client.get(f"/api/v1/machines/{m['machine_id']}", headers=headers)
    ).json()
    assert detail["is_up_to_date"] is True
    # The SQL twin exempts it too: the filter, the dashboard, a broadcast and
    # the mail read « à jour » where the fiche does.
    assert await _status_totals(client, headers) == (1, 0)
    stats = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    assert (stats["up_to_date"], stats["outdated"]) == (1, 0)
    broadcast = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_status": "outdated"},
    )
    assert broadcast.json()["count"] == 0
    digest = await build_digest(db_session)
    assert (digest.outdated_antivirus, digest.outdated_lines) == (0, [])


async def _status_totals(client, headers) -> tuple[int, int]:
    """How many postes the list files under « à jour » and under « périmé »."""
    totals = []
    for status in ("up_to_date", "outdated"):
        resp = await client.get(f"/api/v1/machines?status={status}", headers=headers)
        assert resp.status_code == 200, resp.text
        totals.append(resp.json()["total"])
    return totals[0], totals[1]


async def test_a_heartbeat_dates_the_signature_age_it_carries(client, db_session):
    """What the age is aged from is stamped by the heartbeat itself: a poste
    that comes back after a month reads its fresh figure, not thirty days more."""
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-stamped")
    defender = {"av_enabled": True, "rtp_enabled": True, "signature_age_days": 1}
    before = datetime.now(UTC)
    await _heartbeat(client, m["token"], defender=defender)
    stamped = (await _machine(db_session, m["machine_id"])).signature_reported_at
    assert stamped is not None
    assert before <= stamped <= datetime.now(UTC)

    await _age_out(db_session, m["machine_id"], 29)
    assert await _status_totals(client, headers) == (0, 1)
    # A heartbeat without the Defender block says nothing about the age…
    await _heartbeat(client, m["token"])
    aged = (await _machine(db_session, m["machine_id"])).signature_reported_at
    assert datetime.now(UTC) - aged > timedelta(days=28)
    assert await _status_totals(client, headers) == (0, 1)
    # …and one carrying it dates it again.
    await _heartbeat(client, m["token"], defender=defender)
    detail = (
        await client.get(f"/api/v1/machines/{m['machine_id']}", headers=headers)
    ).json()
    assert (detail["is_up_to_date"], detail["signature_age_days"]) == (True, 1)
    assert await _status_totals(client, headers) == (1, 0)


@pytest.mark.parametrize(
    ("reported", "stored"),
    [
        (0, 0),
        (36500, 36500),
        (36501, None),
        (-1, None),
        (2147483647, None),
        (2147483648, None),
        (10**30, None),
    ],
)
async def test_an_absurd_signature_age_is_stored_as_unknown(
    client, db_session, reported, stored
):
    """Degraded, never refused: the Defender flags, the threats and the
    command pickup ride the same heartbeat."""
    m = await _enroll(client, "m-absurd")
    hb = await _heartbeat(
        client,
        m["token"],
        defender={
            "av_enabled": True,
            "rtp_enabled": True,
            "signature_age_days": reported,
            "signature_version": "1.2.3",
        },
    )
    assert hb.status_code == 200, hb.text
    machine = await _machine(db_session, m["machine_id"])
    assert machine.signature_age_days == stored
    assert (machine.av_enabled, machine.signature_version) == (True, "1.2.3")


@pytest.mark.parametrize("third_party", [True, False])
async def test_a_huge_stored_signature_age_breaks_nothing(
    client, db_session, third_party
):
    """A row written before the age was bounded on ingest: the SQL arithmetic
    must not overflow on it — one poste used to cost the whole parc its
    dashboard, its filters and its mail."""
    from app.features.notification.digest import build_digest
    from app.features.notification.digest_texts import FR as DIGEST_FR

    headers = await _admin(client, db_session)
    huge = await _enroll(client, "m-huge", hostname="PC-HUGE")
    fine = await _enroll(client, "m-fine", hostname="PC-FINE")
    for enrolled in (huge, fine):
        await _heartbeat(
            client,
            enrolled["token"],
            defender={"av_enabled": True, "rtp_enabled": True, "signature_age_days": 1},
            av_product=(
                {"name": "ESET", "enabled": True, "is_defender": False}
                if third_party
                else None
            ),
        )
    machine = await _machine(db_session, huge["machine_id"])
    machine.signature_age_days = 2147483647
    machine.signature_reported_at = datetime.now(UTC) - timedelta(days=2, minutes=1)
    db_session.add(machine)
    await db_session.commit()

    for url in (
        "/api/v1/machines",
        "/api/v1/stats/overview",
        f"/api/v1/machines/{huge['machine_id']}",
        f"/api/v1/machines/{huge['machine_id']}/neighbours?status=up_to_date",
        f"/api/v1/machines/{huge['machine_id']}/neighbours?status=outdated",
        "/api/v1/machines/export.csv?columns=hostname,signature_age_days",
    ):
        resp = await client.get(url, headers=headers)
        assert resp.status_code in (200, 404), (url, resp.text)
    broadcast = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_status": "outdated"},
    )
    assert broadcast.status_code == 200, broadcast.text
    digest = await build_digest(db_session)

    # And Python still agrees with SQL about the poste: the list's own flag
    # against the filter, the dashboard and the mail.
    rows = (await client.get("/api/v1/machines", headers=headers)).json()["items"]
    flags = {row["hostname"]: row["is_up_to_date"] for row in rows}
    assert flags == {"PC-HUGE": third_party, "PC-FINE": True}
    expected = (2, 0) if third_party else (1, 1)
    assert await _status_totals(client, headers) == expected
    stats = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    assert (stats["up_to_date"], stats["outdated"]) == expected
    assert digest.outdated_antivirus == expected[1]
    assert [
        (line.hostname, line.worded(DIGEST_FR)) for line in digest.outdated_lines
    ] == (
        []
        if third_party
        else [("PC-HUGE", f"signatures vieilles de {2147483647 + 2} j")]
    )
    detail = (
        await client.get(f"/api/v1/machines/{huge['machine_id']}", headers=headers)
    ).json()
    assert detail["signature_age_days"] == 2147483647 + 2


async def test_unknown_antivirus_stays_unknown_whatever_the_threshold(
    client, db_session
):
    from app.features.machine.crud import recompute_up_to_date

    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-unknown")
    await _heartbeat(client, m["token"])
    await recompute_up_to_date(db_session, max_age_days=3)
    await db_session.commit()
    assert (await _machine(db_session, m["machine_id"])).is_up_to_date is None
    row = (await client.get("/api/v1/machines", headers=headers)).json()["items"][0]
    assert row["is_up_to_date"] is None


# --- C1. Identity confirmed without a merge ------------------------------------------


async def test_identity_can_be_confirmed_without_a_merge(client, db_session):
    headers = await _admin(client, db_session)
    await _enroll(client, "m-id-a", fingerprint={"smbios_uuid": "SMB-SHARED-1"})
    b = await _enroll(client, "m-id-b", fingerprint={"smbios_uuid": "SMB-SHARED-1"})
    url = f"/api/v1/machines/{b['machine_id']}/confirm-identity"
    assert (await _machine(db_session, b["machine_id"])).needs_verification is True

    resp = await client.post(url, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == b["machine_id"]
    assert body["needs_verification"] is False
    assert "pending_updates" in body  # the detail payload
    assert "machine.identity_confirmed" in await _audit_actions(db_session)

    missing = await client.post(
        f"/api/v1/machines/{uuid.uuid4()}/confirm-identity", headers=headers
    )
    assert missing.status_code == 404


async def test_identity_confirmation_needs_write_and_scope(client, db_session):
    from tests.scope_helpers import two_sites

    sites = await two_sites(client, db_session)
    out = await client.post(
        f"/api/v1/machines/{sites.b.id}/confirm-identity", headers=sites.scoped
    )
    assert out.status_code == 404
    inside = await client.post(
        f"/api/v1/machines/{sites.a.id}/confirm-identity", headers=sites.scoped
    )
    assert inside.status_code == 200


async def test_identity_confirmation_is_refused_to_read_only(client, db_session):
    readonly = await _readonly(client, db_session)
    m = await _enroll(client, "m-id-ro")
    resp = await client.post(
        f"/api/v1/machines/{m['machine_id']}/confirm-identity", headers=readonly
    )
    assert resp.status_code == 403


# --- C2. Re-enrollments and revocations, seen and handled from the list -------------


async def _held(client, machine_uuid) -> dict:
    """A poste whose re-enrollment is held for approval."""
    first = await _enroll(client, machine_uuid)
    assert (await _heartbeat(client, first["token"])).status_code == 200
    held = await _enroll_raw(client, machine_uuid)
    assert held.status_code == 403
    return first


async def test_enrollment_states_are_in_the_list_filters_and_stats(client, db_session):
    headers = await _admin(client, db_session)
    held = await _held(client, "m-held")
    revoked = await _enroll(client, "m-revoked")
    await _enroll(client, "m-fine")
    resp = await client.post(
        f"/api/v1/machines/{revoked['machine_id']}/revoke-token", headers=headers
    )
    assert resp.status_code == 200

    rows = {
        r["machine_uuid"]: r
        for r in (await client.get("/api/v1/machines", headers=headers)).json()["items"]
    }
    assert (rows["m-held"]["reenroll_requested"], rows["m-held"]["token_revoked"]) == (
        True,
        False,
    )
    assert (
        rows["m-revoked"]["reenroll_requested"],
        rows["m-revoked"]["token_revoked"],
    ) == (False, True)
    assert (rows["m-fine"]["reenroll_requested"], rows["m-fine"]["token_revoked"]) == (
        False,
        False,
    )
    detail = await client.get(f"/api/v1/machines/{held['machine_id']}", headers=headers)
    assert detail.json()["reenroll_requested"] is True

    pending = await client.get("/api/v1/machines?enrollment=pending", headers=headers)
    assert [r["machine_uuid"] for r in pending.json()["items"]] == ["m-held"]
    cut = await client.get("/api/v1/machines?enrollment=revoked", headers=headers)
    assert [r["machine_uuid"] for r in cut.json()["items"]] == ["m-revoked"]
    bad = await client.get("/api/v1/machines?enrollment=other", headers=headers)
    assert bad.status_code == 422

    stats = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    assert stats["machines_reenroll_pending"] == 1
    assert stats["machines_token_revoked"] == 1


async def test_reenrollment_counters_are_scoped(client, db_session):
    from tests.scope_helpers import two_sites

    sites = await two_sites(client, db_session)
    for m in (sites.a, sites.b):
        machine = await _machine(db_session, m.id)
        machine.token_revoked = True
        db_session.add(machine)
        await db_session.commit()
    scoped = (await client.get("/api/v1/stats/overview", headers=sites.scoped)).json()
    full = (await client.get("/api/v1/stats/overview", headers=sites.admin)).json()
    assert (scoped["machines_token_revoked"], full["machines_token_revoked"]) == (1, 2)


async def test_held_reenrollments_are_approved_in_bulk(client, db_session):
    headers = await _admin(client, db_session)
    one = await _held(client, "m-bulk-1")
    two = await _held(client, "m-bulk-2")
    fine = await _enroll(client, "m-bulk-fine")
    resp = await client.post(
        "/api/v1/machines/approve-reenroll",
        headers=headers,
        json={
            "machine_ids": [
                one["machine_id"],
                two["machine_id"],
                fine["machine_id"],
                str(uuid.uuid4()),
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"approved": 2, "skipped": 2}
    actions = await _audit_actions(db_session)
    assert actions.count("machine.allow_reenroll") == 2
    # The approved postes come back with a fresh token; the other is untouched.
    assert (await _enroll_raw(client, "m-bulk-1")).status_code == 200
    assert (await _heartbeat(client, fine["token"])).status_code == 200

    too_many = await client.post(
        "/api/v1/machines/approve-reenroll",
        headers=headers,
        json={"machine_ids": [str(uuid.uuid4()) for _ in range(501)]},
    )
    assert too_many.status_code == 422
    readonly = await _readonly(client, db_session)
    denied = await client.post(
        "/api/v1/machines/approve-reenroll",
        headers=readonly,
        json={"machine_ids": [two["machine_id"]]},
    )
    assert denied.status_code == 403


async def test_bulk_approval_stays_in_scope(client, db_session):
    from tests.scope_helpers import two_sites

    sites = await two_sites(client, db_session)
    for m in (sites.a, sites.b):
        machine = await _machine(db_session, m.id)
        machine.reenroll_requested_at = datetime.now(UTC)
        db_session.add(machine)
        await db_session.commit()
    resp = await client.post(
        "/api/v1/machines/approve-reenroll",
        headers=sites.scoped,
        json={"machine_ids": [str(sites.a.id), str(sites.b.id)]},
    )
    assert resp.json() == {"approved": 1, "skipped": 1}
    assert (await _machine(db_session, sites.b.id)).reenroll_requested_at is not None


async def test_approving_in_bulk_does_not_lift_a_revocation(client, db_session):
    """A poste held for approval, then revoked: the request is still on its
    row, but it is « révoqué » — and that is lifted one poste at a time."""
    headers = await _admin(client, db_session)
    held = await _held(client, "m-held-revoked")
    fine = await _held(client, "m-held-only")
    revoked = await client.post(
        f"/api/v1/machines/{held['machine_id']}/revoke-token", headers=headers
    )
    assert revoked.status_code == 200, revoked.text
    machine = await _machine(db_session, held["machine_id"])
    assert machine.reenroll_requested_at is not None
    assert machine.token_revoked is True

    # Not « demandé » anywhere: the row, the filter, the dashboard.
    rows = {
        r["machine_uuid"]: r["reenroll_requested"]
        for r in (await client.get("/api/v1/machines", headers=headers)).json()["items"]
    }
    assert rows == {"m-held-revoked": False, "m-held-only": True}
    pending = await client.get("/api/v1/machines?enrollment=pending", headers=headers)
    assert [r["machine_uuid"] for r in pending.json()["items"]] == ["m-held-only"]
    stats = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    assert stats["machines_reenroll_pending"] == 1
    assert stats["machines_token_revoked"] == 1

    resp = await client.post(
        "/api/v1/machines/approve-reenroll",
        headers=headers,
        json={"machine_ids": [held["machine_id"], fine["machine_id"]]},
    )
    assert resp.json() == {"approved": 1, "skipped": 1}
    machine = await _machine(db_session, held["machine_id"])
    assert machine.token_revoked is True
    assert machine.token_hash is not None
    again = await _enroll_raw(client, "m-held-revoked")
    assert again.status_code == 403
    assert again.json()["error"]["code"] == "machine.enrollment.revoked"
    assert (await _audit_actions(db_session)).count("machine.allow_reenroll") == 1

    # From its fiche, deliberately: the revocation is lifted.
    lifted = await client.post(
        f"/api/v1/machines/{held['machine_id']}/allow-reenroll", headers=headers
    )
    assert lifted.status_code == 200, lifted.text
    assert (await _enroll_raw(client, "m-held-revoked")).status_code == 200


# --- Fixes whose tests were missing -------------------------------------------------


async def test_the_workbook_is_built_off_the_event_loop(
    client, db_session, monkeypatch
):
    """A fleet-wide workbook is seconds of CPU: built on the event loop, it
    froze every heartbeat and every console user for as long."""
    import threading

    from app.api import xlsx_export

    headers = await _admin(client, db_session)
    await _enroll(client, "m-xlsx", hostname="PC-XLSX")
    build = xlsx_export.xlsx_bytes
    built: list[tuple[bool, bool]] = []

    def recording(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            on_the_loop = True
        except RuntimeError:
            on_the_loop = False
        in_main_thread = threading.current_thread() is threading.main_thread()
        built.append((in_main_thread, on_the_loop))
        return build(*args, **kwargs)

    monkeypatch.setattr(xlsx_export, "xlsx_bytes", recording)
    resp = await client.get("/api/v1/machines/export.xlsx", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.content[:2] == b"PK"
    assert built == [(False, False)]


async def test_a_request_its_assignee_no_longer_reaches_names_nobody_in_the_list(
    client, db_session
):
    """« À prendre » in the list as in « Mes tâches »: an assignee whose
    scope no longer holds the poste is not shown as the one handling it."""
    from sqlmodel import select

    from app.features.user.models import User
    from tests.scope_helpers import SITE_B, two_sites

    sites = await two_sites(client, db_session)
    tech = (
        await db_session.exec(select(User).where(User.email == "tech-a@test.local"))
    ).one()
    tech_id, tech_name = str(tech.id), tech.full_name or tech.email
    asked = await client.post(
        f"/api/v1/machines/{sites.a.id}/check",
        headers=sites.admin,
        json={"assigned_to_id": tech_id},
    )
    assert asked.status_code == 201, asked.text

    async def row() -> dict:
        resp = await client.get(
            "/api/v1/machines", headers=sites.admin, params={"check_open": "true"}
        )
        (only,) = resp.json()["items"]
        return only

    assert (await row())["check_assigned_to"] == tech_name
    # The poste moves to the other site, out of the technician's scope.
    machine = await _machine(db_session, sites.a.id)
    machine.location = SITE_B
    db_session.add(machine)
    await db_session.commit()
    moved = await row()
    assert (moved["check_open"], moved["check_assigned_to"]) == (True, None)


# --- C3 / C4. What queueing a command says ------------------------------------------


async def test_a_revoked_poste_gets_no_command(client, db_session):
    headers = await _admin(client, db_session)
    revoked = await _enroll(client, "m-cmd-revoked")
    fine = await _enroll(client, "m-cmd-fine")
    await client.post(
        f"/api/v1/machines/{revoked['machine_id']}/revoke-token", headers=headers
    )

    single = await _queue(client, headers, revoked["machine_id"])
    assert single.status_code == 409
    assert single.json()["error"]["code"] == "machine.token_revoked"

    bulk = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={
            "type": "quick_scan",
            "machine_ids": [revoked["machine_id"], fine["machine_id"]],
        },
    )
    body = bulk.json()
    assert (body["count"], body["skipped"], body["revoked"]) == (1, 0, 1)
    everyone = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "flush_dns", "target_all": True},
    )
    assert (everyone.json()["count"], everyone.json()["revoked"]) == (1, 1)
    from sqlmodel import select

    from app.features.audit.models import AuditEntry

    db_session.expire_all()
    entries = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "command.bulk")
        )
    ).all()
    assert sorted(e.details.get("revoked", 0) for e in entries) == [1, 1]


async def test_a_skipped_command_says_why(client, db_session):
    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-reason")
    created = await _queue(client, headers, m["machine_id"])
    assert created.json()["reason"] is None
    assert (await _queue(client, headers, m["machine_id"])).json()["reason"] == (
        "pending"
    )
    cid = (await _heartbeat(client, m["token"])).json()["commands"][0]["id"]
    again = (await _queue(client, headers, m["machine_id"])).json()
    assert (again["count"], again["skipped"], again["reason"]) == (0, 1, "delivered")
    await _result(client, m["token"], cid, status="running")
    assert (await _queue(client, headers, m["machine_id"])).json()["reason"] == (
        "running"
    )
    # Several postes: no single reason to give.
    other = await _enroll(client, "m-reason-2")
    bulk = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={
            "type": "quick_scan",
            "machine_ids": [m["machine_id"], other["machine_id"]],
        },
    )
    assert (bulk.json()["skipped"], bulk.json()["reason"]) == (1, None)


async def test_a_command_for_a_poste_gone_is_a_404(client, db_session):
    headers = await _admin(client, db_session)
    kept = await _enroll(client, "m-gone-kept")
    gone = await _enroll(client, "m-gone-merged")
    await client.post(
        f"/api/v1/machines/{kept['machine_id']}/merge",
        headers=headers,
        json={"source_id": gone["machine_id"]},
    )
    resp = await _queue(client, headers, gone["machine_id"])
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "machine.not_found"


@pytest.mark.parametrize("seconds", [0, 3600])
def test_effective_signature_age_never_goes_back(seconds):
    from app.features.machine.status import effective_signature_age

    now = datetime(2026, 11, 16, tzinfo=UTC)
    assert effective_signature_age(None, now, now) is None
    assert effective_signature_age(2, None, now) == 2
    # A report dated in the future (a clock moved back) ages nothing.
    assert effective_signature_age(2, now + timedelta(seconds=seconds), now) == 2
    assert effective_signature_age(2, now - timedelta(days=3, hours=5), now) == 5
