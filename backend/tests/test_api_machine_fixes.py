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


def test_strip_controls_keeps_tab_newline_and_text():
    from app.core.control_chars import strip_controls

    assert strip_controls(
        {"a\u0000": ["x\u0000y", "\t\r\n", 3, None, {"k": "\u0007é"}]}
    ) == {"a": ["xy", "\t\r\n", 3, None, {"k": "é"}]}


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

    headers = await _admin(client, db_session)
    m = await _enroll(client, "m-silent-mail", hostname="PC-SILENCE")
    defender = {"av_enabled": True, "rtp_enabled": True, "signature_age_days": 1}
    await _heartbeat(client, m["token"], defender=defender)
    assert (await build_digest(db_session)).outdated_antivirus == 0

    await _age_out(db_session, m["machine_id"], 29)

    digest = await build_digest(db_session)
    assert digest.outdated_antivirus == 1
    assert [(line.hostname, line.detail) for line in digest.outdated_lines] == [
        ("PC-SILENCE", "signatures vieilles de 30 j")
    ]
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
