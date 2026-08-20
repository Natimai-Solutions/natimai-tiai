"""Agent endpoint integration tests (require TIAI_TEST_DATABASE_URL)."""


async def test_enroll_then_heartbeat(client):
    """A machine enrolls with the shared secret, then heartbeats with its token."""
    from app.core.config import settings

    enroll = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": "machine-1", "fingerprint": {"smbios_uuid": "smbios-1"}},
    )
    assert enroll.status_code == 200
    token = enroll.json()["token"]
    assert token

    hb = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_version": "test", "fingerprint": {"smbios_uuid": "smbios-1"}},
    )
    assert hb.status_code == 200
    assert hb.json()["commands"] == []


async def test_enroll_rejects_bad_secret(client):
    """Enrollment fails without the correct shared secret."""
    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": "wrong"},
        json={"machine_uuid": "machine-2"},
    )
    assert resp.status_code == 401


async def test_heartbeat_requires_token(client):
    """Heartbeat without a bearer token is rejected."""
    resp = await client.post("/api/v1/agent/heartbeat", json={"agent_version": "x"})
    assert resp.status_code == 401


async def test_heartbeat_deduplicates_threats(client, db_session):
    """The same detection reported twice yields a single stored row."""
    from sqlmodel import select

    from app.core.config import settings
    from app.features.threat.models import Threat

    enroll = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": "machine-threats"},
    )
    token = enroll.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    threat = {
        "detection_id": "DET-1",
        "threat_name": "EICAR-Test-File",
        "severity": "high",
        "status": "quarantined",
    }

    for _ in range(2):
        hb = await client.post(
            "/api/v1/agent/heartbeat",
            headers=headers,
            json={"agent_version": "test", "threats": [threat]},
        )
        assert hb.status_code == 200

    rows = await db_session.execute(
        select(Threat).where(Threat.detection_id == "DET-1")
    )
    stored = rows.scalars().all()
    assert len(stored) == 1
    assert stored[0].threat_name == "EICAR-Test-File"
    assert stored[0].raw["severity"] == "high"


async def test_heartbeat_refreshes_a_threat_status(client, db_session):
    """A detection Defender later quarantines stops reading as active.

    The agent re-sends Defender's whole detection history on every poll, so the
    same detection_id comes back with a status that has moved. Keeping the first
    reading would leave years-old, long-remediated detections showing as live
    threats in the console.
    """
    from sqlmodel import select

    from app.core.config import settings
    from app.features.threat.models import Threat

    enroll = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": "machine-threat-status"},
    )
    headers = {"Authorization": f"Bearer {enroll.json()['token']}"}

    detected_at = "2021-12-01T09:30:00Z"
    for status in ("active", "quarantined"):
        hb = await client.post(
            "/api/v1/agent/heartbeat",
            headers=headers,
            json={
                "agent_version": "test",
                "threats": [
                    {
                        "detection_id": "DET-OLD",
                        "threat_name": "EICAR-Test-File",
                        "severity": "high",
                        "status": status,
                        "detected_at": detected_at,
                    }
                ],
            },
        )
        assert hb.status_code == 200

    rows = await db_session.execute(
        select(Threat).where(Threat.detection_id == "DET-OLD")
    )
    stored = rows.scalars().all()
    assert len(stored) == 1
    assert stored[0].status == "quarantined"
    # The detection date is the one thing that must not move: it says when the
    # threat was first seen, not when the agent last reported it.
    assert stored[0].detected_at is not None
    assert stored[0].detected_at.year == 2021


async def test_heartbeat_tolerates_a_repeated_detection_id_in_one_batch(
    client, db_session
):
    """Two entries sharing a detection_id in the same poll collapse to one row.

    The agent falls back to the ThreatID when Defender reports no DetectionID,
    and several detections share a ThreatID — a batch can therefore carry the
    same key twice, which ON CONFLICT DO UPDATE refuses to touch twice in one
    statement unless the batch is deduplicated first.
    """
    from sqlmodel import select

    from app.core.config import settings
    from app.features.threat.models import Threat

    enroll = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": "machine-threat-dupe-batch"},
    )
    headers = {"Authorization": f"Bearer {enroll.json()['token']}"}

    hb = await client.post(
        "/api/v1/agent/heartbeat",
        headers=headers,
        json={
            "agent_version": "test",
            "threats": [
                {"detection_id": "DUP-1", "threat_name": "A", "status": "active"},
                {"detection_id": "DUP-1", "threat_name": "B", "status": "removed"},
            ],
        },
    )
    assert hb.status_code == 200

    rows = await db_session.execute(
        select(Threat).where(Threat.detection_id == "DUP-1")
    )
    stored = rows.scalars().all()
    assert len(stored) == 1
    assert stored[0].threat_name == "B"  # last reading wins


async def test_upsert_reports_only_genuinely_new_detections(client, db_session):
    """The alert path must fire on a first sighting, not on a status moving.

    The agent re-reads Defender's whole history every poll, so almost every
    write is a re-report. Telling the two apart is what keeps an operator on
    immediate alerts from being mailed the same threat every minute — it rides
    on PostgreSQL's ``xmax = 0``, which is worth a test of its own.
    """
    from app.features.machine.models import Machine
    from app.features.threat.crud import upsert_threats
    from app.features.threat.schemas import ThreatReport

    machine = Machine(machine_uuid="machine-new-detections")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)

    def report(status: str) -> ThreatReport:
        return ThreatReport(
            detection_id="DET-NEW", threat_name="EICAR-Test-File", status=status
        )

    first = await upsert_threats(db_session, machine.id, [report("active")])
    assert first.written == 1
    assert [d.detection_id for d in first.new_detections] == ["DET-NEW"]

    # Same detection, moved on: written again, but not new.
    moved = await upsert_threats(db_session, machine.id, [report("quarantined")])
    assert moved.written == 1
    assert moved.new_detections == []

    # Same detection, unchanged: not even written.
    unchanged = await upsert_threats(db_session, machine.id, [report("quarantined")])
    assert unchanged.written == 0
    assert unchanged.new_detections == []


async def test_heartbeat_mails_the_immediate_cadence_on_a_new_threat(
    client, db_session, engine, monkeypatch
):
    """End to end: a detection arriving on a heartbeat reaches an inbox.

    The mail goes out as a background task, which the ASGI transport runs before
    the response is handed back — so by the time the heartbeat returns here, the
    send has been attempted. The task opens a session of its own on the
    module-level engine (the request's is closed by then), which is pointed at
    the test database here, exactly as the ARQ job tests do.
    """
    from app.core.config import settings
    from app.features.notification import threat_alert
    from app.features.user import crud
    from app.features.user.models import EmailPreference, Role

    monkeypatch.setattr(threat_alert, "engine", engine)

    user = await crud.create_user(
        db_session, email="oncall@test.local", password="pw", role=Role.ADMIN
    )
    user.email_preference = EmailPreference.IMMEDIATE
    db_session.add(user)
    await db_session.commit()

    sent: list[dict] = []

    async def fake_send_email(subject: str, text: str, to=None):
        sent.append({"subject": subject, "text": text, "to": to})
        return True

    monkeypatch.setattr(threat_alert, "send_email", fake_send_email)

    enroll = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": "machine-alert", "hostname": "PC-ALERT"},
    )
    headers = {"Authorization": f"Bearer {enroll.json()['token']}"}
    threat = {
        "detection_id": "DET-ALERT",
        "threat_name": "Trojan:Win32/Wacatac",
        "severity": "high",
        "status": "active",
    }

    hb = await client.post(
        "/api/v1/agent/heartbeat",
        headers=headers,
        json={"agent_version": "test", "threats": [threat]},
    )
    assert hb.status_code == 200
    assert len(sent) == 1
    assert sent[0]["to"] == ["oncall@test.local"]
    assert "PC-ALERT" in sent[0]["subject"]

    # The same detection re-reported must not mail anyone a second time.
    hb = await client.post(
        "/api/v1/agent/heartbeat",
        headers=headers,
        json={"agent_version": "test", "threats": [threat]},
    )
    assert hb.status_code == 200
    assert len(sent) == 1


async def test_a_mixed_batch_reports_only_the_new_row(client, db_session):
    """The everyday shape of a heartbeat: a long history plus one new line.

    The agent re-sends every detection Defender holds, so a real batch is
    dozens of unchanged rows, a few whose status moved, and — on the poll that
    matters — one genuinely new. Only that last one may reach an inbox.
    """
    from app.features.machine.models import Machine
    from app.features.threat.crud import upsert_threats
    from app.features.threat.schemas import ThreatReport

    machine = Machine(machine_uuid="machine-mixed-batch")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)

    history = [
        ThreatReport(detection_id=f"OLD-{i}", threat_name="Known", status="quarantined")
        for i in range(5)
    ]
    first = await upsert_threats(db_session, machine.id, history)
    assert len(first.new_detections) == 5

    # Same five, one of them moved on, plus one never seen before.
    moved = ThreatReport(detection_id="OLD-2", threat_name="Known", status="removed")
    fresh = ThreatReport(
        detection_id="BRAND-NEW", threat_name="Trojan:Win32/Wacatac", status="active"
    )
    batch = [h for h in history if h.detection_id != "OLD-2"] + [moved, fresh]

    result = await upsert_threats(db_session, machine.id, batch)

    # Written: the one that moved and the one that is new. The four unchanged
    # rows are filtered out by the statement's own WHERE.
    assert result.written == 2
    assert [d.detection_id for d in result.new_detections] == ["BRAND-NEW"]
    assert result.new_detections[0].threat_name == "Trojan:Win32/Wacatac"
