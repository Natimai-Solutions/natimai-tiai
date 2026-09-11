"""Error-contract tests (require TIAI_TEST_DATABASE_URL).

Asserts every error path returns the standardized envelope
``{"error": {"code", "message", "details"}}`` with the expected stable code
(plan §2.14).
"""

import uuid


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session, email="admin@test.local", password="pw", groups=[BuiltinGroup.ADMIN]
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "admin@test.local", "password": "pw"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _assert_envelope(body: dict, code: str) -> None:
    assert set(body.keys()) == {"error"}
    err = body["error"]
    assert err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["details"], dict)


async def test_enrollment_secret_invalid(client):
    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": "wrong"},
        json={"machine_uuid": "m-x"},
    )
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.enrollment_secret.invalid")


async def test_heartbeat_missing_token(client):
    resp = await client.post("/api/v1/agent/heartbeat", json={"agent_version": "x"})
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.token.missing")


async def test_heartbeat_invalid_token(client):
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"agent_version": "x"},
    )
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.token.invalid")


async def test_login_bad_credentials(client):
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "nobody@test.local", "password": "nope"}
    )
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.credentials.invalid")


async def test_machine_not_found(client, db_session):
    headers = await _admin_headers(client, db_session)
    resp = await client.get(f"/api/v1/machines/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    _assert_envelope(resp.json(), "machine.not_found")


async def test_permission_denied(client, db_session):
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session, email="ro@test.local", password="pw", groups=[BuiltinGroup.READONLY]
    )
    login = await client.post(
        "/api/v1/auth/login", data={"username": "ro@test.local", "password": "pw"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_all": True},
    )
    assert resp.status_code == 403
    body = resp.json()
    _assert_envelope(body, "auth.permission.denied")
    # Permission denials carry the offending (resource, action) for the console.
    assert body["error"]["details"] == {"resource": "command", "action": "execute"}


async def test_validation_error_envelope(client, db_session):
    headers = await _admin_headers(client, db_session)
    resp = await client.post(
        "/api/v1/commands", headers=headers, json={"type": "quick_scan"}
    )
    assert resp.status_code == 422
    body = resp.json()
    _assert_envelope(body, "request.validation_error")
    assert "errors" in body["error"]["details"]


async def test_no_auth_uses_auth_required_code(client):
    # The oauth2 dependency raises a framework HTTPException (401) → wrapped.
    resp = await client.get("/api/v1/machines")
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.required")


async def test_malformed_jwt_rejected(client):
    resp = await client.get(
        "/api/v1/machines", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.credentials.invalid")


async def test_valid_jwt_unknown_user_rejected(client):
    from app.core import security

    token = security.create_access_token(uuid.uuid4())
    resp = await client.get(
        "/api/v1/machines", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.credentials.invalid")


async def test_jwt_without_subject_rejected(client):
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.core.config import settings
    from app.core.security import ALGORITHM

    token = jwt.encode(
        {"exp": datetime.now(UTC) + timedelta(minutes=5), "type": "access"},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    resp = await client.get(
        "/api/v1/machines", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
    _assert_envelope(resp.json(), "auth.credentials.invalid")
