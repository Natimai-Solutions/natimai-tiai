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
