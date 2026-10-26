"""A live identity is not re-enrolled on the fleet secret alone (require
TIAI_TEST_DATABASE_URL)."""

import pytest

from tests.test_api_console import _admin_headers, _enroll, _heartbeat


async def _enroll_raw(client, machine_uuid: str, secret: str | None = None, **fields):
    from app.core.config import settings

    return await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": secret or settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, **fields},
    )


async def _audit(client, headers) -> list[dict]:
    return (await client.get("/api/v1/audit", headers=headers)).json()["items"]


async def test_second_enrollment_of_a_live_identity_is_held(client, db_session):
    """Someone presenting the secret under a known machine_uuid gets nothing,
    and the real poste keeps its token."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-held", hostname="PC-HELD")

    resp = await _enroll_raw(client, "m-held", hostname="IMPOSTOR")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "machine.enrollment.approval_required"

    # The live token still works: the impostor locked nobody out.
    assert (await _heartbeat(client, enrolled["token"])).status_code == 200

    detail = (
        await client.get(f"/api/v1/machines/{enrolled['machine_id']}", headers=headers)
    ).json()
    assert detail["reenroll_requested_at"] is not None
    assert detail["reenroll_requested_ip"]
    # The held request did not overwrite what the poste reports.
    assert detail["hostname"] == "PC-HELD"

    held = [
        e
        for e in await _audit(client, headers)
        if e["action"] == "machine.reenroll_requested"
    ]
    assert held and held[0]["actor"] == "agent"
    assert held[0]["details"]["hostname"] == "IMPOSTOR"
    assert held[0]["ip"]


async def test_allowing_the_request_lets_the_poste_back_with_a_new_token(
    client, db_session
):
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-approve")
    assert (await _enroll_raw(client, "m-approve")).status_code == 403

    allowed = await client.post(
        f"/api/v1/machines/{enrolled['machine_id']}/allow-reenroll", headers=headers
    )
    assert allowed.status_code == 200

    again = await _enroll_raw(client, "m-approve")
    assert again.status_code == 200, again.text
    assert again.json()["token"] != enrolled["token"]
    # The old token died with the approval.
    assert (await _heartbeat(client, enrolled["token"])).status_code == 401

    detail = (
        await client.get(f"/api/v1/machines/{enrolled['machine_id']}", headers=headers)
    ).json()
    assert detail["reenroll_requested_at"] is None
    allow = next(
        e
        for e in await _audit(client, headers)
        if e["action"] == "machine.allow_reenroll"
    )
    assert "requested_at" in allow["details"]
    assert allow["ip"]


async def test_approval_can_be_turned_off(client, db_session, monkeypatch):
    """The old behaviour, for a parc that re-images often and accepts the risk."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENROLLMENT_REENROLL_REQUIRES_APPROVAL", False)
    first = await _enroll(client, "m-noapproval")
    second = await _enroll_raw(client, "m-noapproval")
    assert second.status_code == 200
    assert second.json()["token"] != first["token"]


@pytest.mark.parametrize("which", ["current", "previous"])
async def test_both_secrets_enroll_during_a_rotation(client, monkeypatch, which):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "ENROLLMENT_SECRET_PREVIOUS", "the-retired-secret-0001"
    )
    secret = (
        settings.ENROLLMENT_SECRET if which == "current" else "the-retired-secret-0001"
    )
    resp = await _enroll_raw(client, f"m-rotate-{which}", secret=secret)
    assert resp.status_code == 200, resp.text


async def test_an_unknown_secret_is_refused_during_a_rotation(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "ENROLLMENT_SECRET_PREVIOUS", "the-retired-secret-0001"
    )
    resp = await _enroll_raw(client, "m-rotate-bad", secret="not-a-secret-at-all")
    assert resp.status_code == 401
