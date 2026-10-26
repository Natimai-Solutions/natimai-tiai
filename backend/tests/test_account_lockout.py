"""An account locks after repeated failed logins (require TIAI_TEST_DATABASE_URL)."""

from app.core.config import settings
from tests.test_api_login import STRONG, _admin, _login


async def _operator(db_session, email: str = "operator@test.local"):
    from app.features.user import crud

    return await crud.create_user(db_session, email=email, password=STRONG)


async def test_account_locks_after_repeated_failures(client, db_session):
    await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
        refused = await _login(client, "operator@test.local", "wrong-password-here")
        assert refused.status_code == 401
    locking = await _login(client, "operator@test.local", "wrong-password-here")
    assert locking.status_code == 423
    assert locking.json()["error"]["code"] == "auth.account.locked"
    assert "locked_until" in locking.json()["error"]["details"]

    # Locked: even the right password is refused until it lifts.
    assert (await _login(client, "operator@test.local")).status_code == 423


async def test_a_success_resets_the_counter(client, db_session):
    await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
        await _login(client, "operator@test.local", "wrong-password-here")
    assert (await _login(client, "operator@test.local")).status_code == 200
    # The count starts over: one more failure is not the one that locks.
    again = await _login(client, "operator@test.local", "wrong-password-here")
    assert again.status_code == 401


async def test_an_admin_reset_lifts_the_lock_and_both_are_audited(client, db_session):
    admin = await _admin(client, db_session)
    await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await _login(client, "operator@test.local", "wrong-password-here")
    assert (await _login(client, "operator@test.local")).status_code == 423

    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    operator = next(u for u in users if u["email"] == "operator@test.local")
    assert operator["locked_until"] is not None
    reset = await client.post(
        f"/api/v1/users/{operator['id']}/reset-password",
        headers=admin,
        json={"password": "a-brand-new-password-1"},
    )
    assert reset.status_code == 200, reset.text
    relogin = await _login(client, "operator@test.local", "a-brand-new-password-1")
    assert relogin.status_code == 200

    log = (await client.get("/api/v1/audit", headers=admin)).json()["items"]
    locked = next(e for e in log if e["action"] == "user.locked")
    assert locked["ip"]
    assert any(e["action"] == "user.reset_password" for e in log)
