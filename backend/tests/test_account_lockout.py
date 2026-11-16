"""An account locks after repeated failed logins (require TIAI_TEST_DATABASE_URL).

The lock shuts out the addresses that failed on the account, not the account
itself (audit S03), answers like any failure (S12), and counts concurrent
failures (S13). Wrong current passwords on « changer mon mot de passe » count
too, and are budgeted per session (S04, T07). Failures spaced out over hours
lock the account too, to its usual addresses (T06).
"""

import asyncio

import pytest

from app.core.config import settings
from tests.test_api_login import STRONG, _admin, _login

COOKIE = "tiai_refresh"


async def _operator(db_session, email: str = "operator@test.local"):
    from app.features.user import crud

    return await crud.create_user(db_session, email=email, password=STRONG)


async def _login_from(client, ip, password=STRONG, email="operator@test.local"):
    return await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"X-Forwarded-For": ip},
    )


async def test_the_lock_shuts_out_the_guessing_address_not_the_account(
    client, db_session
):
    await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        refused = await _login_from(client, "10.0.0.66", "wrong-password-here")
        # The failure that locks answers like any other: no 423 to tell an
        # existing account from an unknown one.
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "auth.credentials.invalid"

    # The guessing address: refused, even with the right password.
    assert (await _login_from(client, "10.0.0.66")).status_code == 401
    # Anyone else with the right password: in, and the lock lifts.
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    assert (await _login_from(client, "10.0.0.66")).status_code == 200


async def test_an_unknown_address_answers_like_a_locked_one(client, db_session):
    await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS + 1):
        await _login_from(client, "10.0.0.66", "wrong-password-here")
    locked = await _login_from(client, "10.0.0.66", "wrong-password-here")
    unknown = await _login_from(
        client, "10.0.0.66", "wrong-password-here", email="nobody@test.local"
    )
    assert locked.status_code == unknown.status_code == 401
    assert locked.json() == unknown.json()


async def test_concurrent_failures_all_count(client, db_session):
    from app.features.user import crud

    user = await _operator(db_session)
    n = settings.LOGIN_MAX_FAILED_ATTEMPTS - 1
    await asyncio.gather(
        *(_login_from(client, f"10.0.1.{i}", "wrong-password-here") for i in range(n))
    )
    db_session.expire_all()
    fresh = await crud.get_by_email(db_session, "operator@test.local")
    assert fresh is not None and fresh.id == user.id
    assert fresh.failed_login_attempts == n


async def test_a_success_resets_the_counter(client, db_session):
    await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
        await _login(client, "operator@test.local", "wrong-password-here")
    assert (await _login(client, "operator@test.local")).status_code == 200
    # The count starts over: one more failure does not lock.
    again = await _login(client, "operator@test.local", "wrong-password-here")
    assert again.status_code == 401
    assert (await _login(client, "operator@test.local")).status_code == 200


async def test_an_admin_reset_lifts_the_lock_and_both_are_audited(client, db_session):
    admin = await _admin(client, db_session)
    await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await _login(client, "operator@test.local", "wrong-password-here")
    assert (await _login(client, "operator@test.local")).status_code == 401

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
    locked = [e for e in log if e["action"] == "user.locked"]
    assert len(locked) == 1 and locked[0]["ip"]
    assert any(e["action"] == "user.reset_password" for e in log)


async def test_guessing_the_current_password_ends_the_session(client, db_session):
    await _operator(db_session)
    resp = await _login(client, "operator@test.local")
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        wrong = await client.post(
            "/api/v1/auth/password",
            headers=headers,
            json={"current_password": "guess-guess", "new_password": "x" * 20},
        )
        assert wrong.status_code == 400
    # The session that guessed is ended: the stolen token is dead.
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def _session_headers(client, ip: str) -> dict[str, str]:
    resp = await _login_from(client, ip)
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _guess_current(client, headers, ip: str = "10.0.2.1"):
    return await client.post(
        "/api/v1/auth/password",
        headers={**headers, "X-Forwarded-For": ip},
        json={"current_password": "guess-guess", "new_password": "x" * 20},
    )


@pytest.mark.parametrize("account_lock", [True, False])
async def test_a_stolen_session_spends_its_own_password_budget(
    client, db_session, monkeypatch, account_lock
):
    """Audit T07 (accepted limit, fixed): the five tries of the current
    password were the account's, shared by a stolen session and its owner —
    the thief spending them locked the owner's sessions out of the change,
    and the lock it tripped ended them. The budget is the session's: the
    thief's session ends, audited, and the owner's goes on.

    Run with the account lock tripping on the same failures (the defaults)
    and without (a high LOGIN_MAX_FAILED_ATTEMPTS): the session's own budget
    ends it either way."""
    from sqlmodel import select

    from app.features.audit.models import AuditEntry

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    if not account_lock:
        monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 100)
    await _operator(db_session)
    owner = await _session_headers(client, "10.0.0.10")
    thief = await _session_headers(client, "10.6.6.6")

    codes = [(await _guess_current(client, thief)).status_code for _ in range(5)]
    assert codes == [400] * 5
    # The thief's session is over…
    assert (await client.get("/api/v1/auth/me", headers=thief)).status_code == 401
    # …the owner's is not, and its own budget is whole.
    assert (await client.get("/api/v1/auth/me", headers=owner)).status_code == 200
    for _ in range(4):
        assert (await _guess_current(client, owner)).status_code == 400
    changed = await client.post(
        "/api/v1/auth/password",
        headers={**owner, "X-Forwarded-For": "10.0.0.10"},
        json={"current_password": STRONG, "new_password": "a-brand-new-password-1"},
    )
    assert changed.status_code == 204, changed.text

    entries = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "auth.session_revoked")
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].details["via"] == "password_change"
    assert entries[0].details["ip"] == "10.6.6.6"


async def test_password_change_is_rate_limited_per_session(
    client, db_session, monkeypatch
):
    """The bcrypt budget (audit S04) is the session's: one session's 429
    leaves the owner's others free to change the password."""
    from app.core import ratelimit

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    await _operator(db_session)
    first = await _session_headers(client, "10.0.0.10")
    second = await _session_headers(client, "10.0.0.11")
    me = (await client.get("/api/v1/auth/sessions", headers=first)).json()
    sid = next(s["id"] for s in me if s["current"])
    # The window filled by that session alone (say, five tries in a row).
    for _ in range(ratelimit.password_change_limiter.max_attempts):
        assert ratelimit.password_change_limiter.allow(sid)
    assert (await _guess_current(client, first)).status_code == 429
    assert (await _guess_current(client, second)).status_code == 400


# --- Slow guessing (audit T06, accepted limit fixed) ---------------------------


async def _space_out(db_session, user_id) -> None:
    """Make the last failure look LOGIN_LOCKOUT_MINUTES old: the quick
    counter and the address's recent failure no longer hold it."""
    from datetime import timedelta

    from sqlalchemy import update
    from sqlmodel import col

    from app.core import ratelimit
    from app.features.base import utcnow
    from app.features.user.models import LoginAddress, User

    past = utcnow() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES + 1)
    await db_session.exec(
        update(User).where(col(User.id) == user_id).values(last_failed_login_at=past)
    )
    await db_session.exec(
        update(LoginAddress)
        .where(col(LoginAddress.user_id) == user_id)
        .where(col(LoginAddress.last_failure_at).is_not(None))
        .values(last_failure_at=past)
    )
    await db_session.commit()
    # The per-address limiter's window has passed as well.
    ratelimit.login_limiter.reset()


async def _slow_guesses(client, db_session, user_id, n: int, ip="10.0.0.66") -> None:
    for _ in range(n):
        refused = await _login_from(client, ip, "wrong-password-here")
        assert refused.status_code == 401
        await _space_out(db_session, user_id)


async def test_slow_guesses_lock_the_account_to_its_usual_addresses(client, db_session):
    """Failures spaced more than LOGIN_LOCKOUT_MINUTES apart never locked
    (four guesses a quarter of an hour, for ever). LOGIN_SLOW_MAX_FAILED_
    ATTEMPTS of them within LOGIN_SLOW_WINDOW_HOURS lock the account, to
    every address but the usual ones, and the lock is audited."""
    from datetime import timedelta

    from app.features.base import utcnow

    user = await _operator(db_session)
    user_id = user.id
    admin = await _admin(client, db_session)
    assert (await _login_from(client, "10.0.0.10")).status_code == 200

    await _slow_guesses(
        client, db_session, user_id, settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS - 1
    )
    await db_session.refresh(user)
    # Never two failures within LOGIN_LOCKOUT_MINUTES: no quick lock, ever.
    assert user.locked_until is None
    await _slow_guesses(client, db_session, user_id, 1)

    await db_session.refresh(user)
    assert user.lock_admits_known_only
    assert user.locked_until is not None
    assert user.locked_until > utcnow() + timedelta(
        hours=settings.LOGIN_SLOW_WINDOW_HOURS - 1
    )
    # The right password from an address that never opened the account: no.
    assert (await _login_from(client, "10.5.5.5")).status_code == 401
    # The owner's usual poste: in, and the lock lifts.
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    assert (await _login_from(client, "10.5.5.5")).status_code == 200

    log = (await client.get("/api/v1/audit", headers=admin)).json()["items"]
    locked = [e for e in log if e["action"] == "user.locked"]
    assert len(locked) == 1
    assert locked[0]["details"]["via"] == "slow_attempts"


async def test_a_reset_link_lifts_the_slow_lock(client, db_session):
    """The holder's ways out of a slow lock are a siege's: from a poste the
    account never saw, « mot de passe oublié »."""
    from app.features.user import crud

    user = await _operator(db_session)
    user_id = user.id
    await _slow_guesses(
        client, db_session, user_id, settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS
    )
    assert (await _login_from(client, "10.5.5.5")).status_code == 401

    await db_session.refresh(user)
    token = await crud.create_reset_token(db_session, user, "10.5.5.5")
    await db_session.commit()
    redeemed = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "a-brand-new-password-1"},
        headers={"X-Forwarded-For": "10.5.5.5"},
    )
    assert redeemed.status_code == 204, redeemed.text
    await db_session.refresh(user)
    assert user.locked_until is None and not user.lock_admits_known_only
    assert user.slow_failed_login_attempts == 0
    back = await _login_from(client, "10.9.9.9", "a-brand-new-password-1")
    assert back.status_code == 200


async def test_slow_failures_older_than_the_window_start_over(client, db_session):
    from datetime import timedelta

    from app.features.base import utcnow

    user = await _operator(db_session)
    await _slow_guesses(
        client, db_session, user.id, settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS - 1
    )
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == (
        settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS - 1
    )
    user.slow_window_started_at = utcnow() - timedelta(
        hours=settings.LOGIN_SLOW_WINDOW_HOURS, minutes=1
    )
    db_session.add(user)
    await db_session.commit()

    await _login_from(client, "10.0.0.66", "wrong-password-here")
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == 1
    assert user.locked_until is None


async def test_a_quick_lock_does_not_shorten_a_slow_one(client, db_session):
    """Failures from usual addresses during a slow lock still count; the
    quick lock they trip must not cut the slow one short, nor widen it."""
    user = await _operator(db_session)
    user_id = user.id
    usual = [f"10.0.1.{i}" for i in range(settings.LOGIN_MAX_FAILED_ATTEMPTS)]
    for ip in usual:
        assert (await _login_from(client, ip)).status_code == 200
    await _slow_guesses(
        client, db_session, user_id, settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS
    )
    await db_session.refresh(user)
    slow_until = user.locked_until
    assert slow_until is not None and user.lock_admits_known_only
    for ip in usual:
        await _login_from(client, ip, "wrong-password-here")
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0  # the quick lock tripped
    assert user.locked_until == slow_until
    assert user.lock_admits_known_only
