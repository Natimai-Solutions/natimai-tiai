"""An account locks after repeated failed logins (require TIAI_TEST_DATABASE_URL).

The lock shuts out the addresses that failed on the account, not the account
itself (audit S03), answers like any failure (S12), and counts concurrent
failures (S13). Wrong current passwords on « changer mon mot de passe » count
too, and are budgeted per session (S04, T07). Failures spaced out over hours
lock the account too, to the addresses that failed over those hours (T06).
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


async def test_the_session_budget_holds_without_the_rate_limiter(
    client, db_session, monkeypatch
):
    """Verification of v1.2.1, F4: the five tries of a session were held by
    the in-process limiter alone. With it off (RATE_LIMIT_ENABLED=false, or
    several API processes each with its own), thirty guesses sent together
    all read the session as live and eighteen were checked against the
    password. The count kept on the session's row is read, under its lock,
    before any check: five are, the rest find the session ended."""
    from sqlmodel import select

    from app.core import security
    from app.features.auth_session.models import AuthSession

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    # Neither account lock in the way: the session's own budget is on test.
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 100)
    monkeypatch.setattr(settings, "LOGIN_SLOW_MAX_FAILED_ATTEMPTS", 1000)
    await _operator(db_session)
    thief = await _session_headers(client, "10.6.6.6")

    checked = 0
    check = security.check_password

    async def counting_check(password: str, hashed: str) -> bool:
        nonlocal checked
        checked += 1
        return await check(password, hashed)

    monkeypatch.setattr(security, "check_password", counting_check)
    answers = await asyncio.gather(*(_guess_current(client, thief) for _ in range(30)))
    codes = sorted(r.status_code for r in answers)
    assert codes == [400] * 5 + [401] * 25
    assert checked == 5
    refused = next(r for r in answers if r.status_code == 401)
    assert refused.json()["error"]["code"] == "auth.session.invalid"
    db_session.expire_all()
    row = (await db_session.exec(select(AuthSession))).one()
    assert row.password_failures == 5 and row.revoked_at is not None


async def test_a_session_whose_budget_is_spent_is_refused_unchecked(
    client, db_session, monkeypatch
):
    """The count stored on the session is the budget, whatever else ended
    or failed to end it: at five, the next try is refused before the
    password is looked at — even the right one — and the session ends."""
    from sqlalchemy import update
    from sqlmodel import select

    from app.api.routes.auth import PASSWORD_CHANGE_SESSION_FAILURES
    from app.core import security
    from app.features.auth_session.models import AuthSession

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    await _operator(db_session)
    headers = await _session_headers(client, "10.0.0.10")
    await db_session.exec(
        update(AuthSession).values(password_failures=PASSWORD_CHANGE_SESSION_FAILURES)
    )
    await db_session.commit()

    async def never(password: str, hashed: str) -> bool:
        raise AssertionError("the password must not be checked")

    monkeypatch.setattr(security, "check_password", never)
    resp = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": STRONG, "new_password": "a-brand-new-password-1"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.session.invalid"
    db_session.expire_all()
    row = (await db_session.exec(select(AuthSession))).one()
    assert row.revoked_at is not None


async def test_a_wrong_current_password_and_a_refresh_take_locks_in_one_order(
    client, db_session, monkeypatch
):
    """Verification of v1.2.1, F3: a wrong current password locked the
    address's row, the account's, then the session's; a refresh of the same
    session from the same address the session's, then the address's. Two
    tabs at the same instant could deadlock, and one answered a 500. Both
    now take the session's row first: the refresh waits its turn."""
    from app.features.user import crud

    await _operator(db_session)
    resp = await _login_from(client, "10.0.0.10")
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    cookie = resp.cookies[COOKIE]
    client.cookies.clear()

    counted = asyncio.Event()
    record = crud.record_failure

    async def record_then_linger(*args, **kwargs):
        # The address's row and the account's are locked on return; the
        # refresh is let in, and given time to reach the row it waits on.
        lock = await record(*args, **kwargs)
        counted.set()
        await asyncio.sleep(0.3)
        return lock

    monkeypatch.setattr(crud, "record_failure", record_then_linger)

    async def refresh():
        await counted.wait()
        return await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"{COOKIE}={cookie}", "X-Forwarded-For": "10.0.0.10"},
        )

    wrong, refreshed = await asyncio.gather(
        _guess_current(client, headers, ip="10.0.0.10"), refresh()
    )
    assert wrong.status_code == 400
    assert refreshed.status_code == 200, refreshed.text


# --- Many addresses (audit S03, T06) -------------------------------------------


async def test_a_siege_admits_only_the_usual_addresses(client, db_session, monkeypatch):
    """One guess per address during a lock is what a botnet multiplies: once
    LOGIN_SIEGE_ADDRESSES addresses failed within the window, the lock
    refuses every address but those that opened the account."""
    monkeypatch.setattr(settings, "LOGIN_SIEGE_ADDRESSES", 3)
    await _operator(db_session)
    assert (await _login_from(client, "10.0.0.10")).status_code == 200  # usual
    for i in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await _login_from(client, f"10.6.6.{i % 2}", "wrong-password-here")
    # Two addresses failed: below the siege, a third one still gets in…
    assert (await _login_from(client, "10.5.5.5")).status_code == 200
    # …which lifts the lock. Locked again, from three addresses this time.
    for i in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await _login_from(client, f"10.6.6.{i % 3}", "wrong-password-here")
    assert (await _login_from(client, "10.7.7.7")).status_code == 401
    assert (await _login_from(client, "10.0.0.10")).status_code == 200


# --- Slow guessing (audit T06, accepted limit fixed) ---------------------------

GUESSER = "10.0.0.66"


@pytest.fixture
def few_slow_guesses(monkeypatch):
    """A slow budget of 7 instead of 20: each guess is a bcrypt check, and
    the rules under test do not depend on how many it takes to lock."""
    monkeypatch.setattr(settings, "LOGIN_SLOW_MAX_FAILED_ATTEMPTS", 7)


async def _space_out(db_session, user_id) -> None:
    """Let LOGIN_LOCKOUT_MINUTES and a minute pass on the account: every
    instant its locks read moves back by as much. The quick counter and the
    address's recent failure no longer hold; the slow window has that much
    less to run."""
    from datetime import timedelta

    from sqlalchemy import update
    from sqlmodel import col

    from app.core import ratelimit
    from app.features.user.models import LoginAddress, User

    step = timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES + 1)
    await db_session.exec(
        update(User)
        .where(col(User.id) == user_id)
        .values(
            last_failed_login_at=col(User.last_failed_login_at) - step,
            locked_until=col(User.locked_until) - step,
            slow_window_started_at=col(User.slow_window_started_at) - step,
            slow_locked_until=col(User.slow_locked_until) - step,
        )
    )
    await db_session.exec(
        update(LoginAddress)
        .where(col(LoginAddress.user_id) == user_id)
        .values(last_failure_at=col(LoginAddress.last_failure_at) - step)
    )
    await db_session.commit()
    db_session.expire_all()
    # The per-address limiter's window has passed as well.
    ratelimit.login_limiter.reset()


async def _slow_guesses(client, db_session, user_id, n: int, ip=GUESSER) -> None:
    for _ in range(n):
        refused = await _login_from(client, ip, "wrong-password-here")
        assert refused.status_code == 401
        await _space_out(db_session, user_id)


async def _slow_lock(client, db_session, user_id, ip=GUESSER) -> None:
    """Trip the slow lock from one address, never two guesses within
    LOGIN_LOCKOUT_MINUTES."""
    await _slow_guesses(
        client, db_session, user_id, settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS, ip
    )


async def _locked_entries(client, admin) -> list[dict]:
    log = (await client.get("/api/v1/audit", headers=admin)).json()["items"]
    return [e for e in log if e["action"] == "user.locked"]


async def test_slow_guesses_lock_out_the_address_that_guessed(client, db_session):
    """Failures spaced more than LOGIN_LOCKOUT_MINUTES apart never locked
    (four guesses a quarter of an hour, for ever). LOGIN_SLOW_MAX_FAILED_
    ATTEMPTS of them within LOGIN_SLOW_WINDOW_HOURS set the slow lock: the
    address that guessed is refused for LOGIN_SLOW_WINDOW_HOURS, however
    long it waits between two tries, and the lock is audited."""
    from datetime import timedelta

    from app.features.base import utcnow

    user = await _operator(db_session)
    user_id = user.id
    admin = await _admin(client, db_session)

    await _slow_guesses(
        client, db_session, user_id, settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS - 1
    )
    await db_session.refresh(user)
    # Never two failures within LOGIN_LOCKOUT_MINUTES: no quick lock, ever.
    assert user.locked_until is None and user.slow_locked_until is None
    # Below the threshold the address is not shut out: one more guess counts.
    await _slow_guesses(client, db_session, user_id, 1)

    await db_session.refresh(user)
    assert user.locked_until is None
    assert user.slow_locked_until is not None
    assert user.slow_locked_until > utcnow() + timedelta(
        hours=settings.LOGIN_SLOW_WINDOW_HOURS - 1
    )
    # The guesser, with the right password at last, long after its last
    # failure: refused, and not checked — the counter does not move.
    assert (await _login_from(client, GUESSER)).status_code == 401
    await _slow_guesses(client, db_session, user_id, 3)
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS

    locked = await _locked_entries(client, admin)
    assert len(locked) == 1
    assert locked[0]["details"]["via"] == "slow_attempts"
    # The users page shows the account locked, until the slow lock's end.
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    shown = next(u for u in users if u["email"] == "operator@test.local")
    assert shown["locked_until"] is not None


@pytest.mark.parametrize("holder", ["new_account", "new_address", "admin_reset"])
async def test_one_outside_address_cannot_shut_the_right_password_out(
    client, db_session, few_slow_guesses, holder
):
    """Verification of v1.2.1, F1: the slow lock admitted only the account's
    usual addresses, so twenty spaced guesses from ONE address shut out, for
    a day, any holder the account had no usual address for — an account
    that never logged in, a holder on a new address, an account whose
    password an administrator had just reset (which forgets the usual
    addresses) while the guesser went on. The lock refuses the addresses
    that failed; the right password from any other opens the account."""
    user = await _operator(db_session)
    user_id = user.id
    password = STRONG
    if holder == "new_address":
        assert (await _login_from(client, "10.0.0.10")).status_code == 200
    if holder == "admin_reset":
        admin = await _admin(client, db_session)
        assert (await _login_from(client, "10.0.0.10")).status_code == 200
        await _slow_lock(client, db_session, user_id)
        reset = await client.post(
            f"/api/v1/users/{user_id}/reset-password", headers=admin, json={}
        )
        password = reset.json()["password"]
        # The reset lifted the lock and gave the guesser its budget back…
        await db_session.refresh(user)
        assert user.slow_locked_until is None
        assert user.slow_failed_login_attempts == 0
    # …which it spends, knowing nothing of the reset.
    await _slow_lock(client, db_session, user_id)
    await db_session.refresh(user)
    assert user.slow_locked_until is not None

    # The holder's poste is no usual address in any of the three cases (the
    # administrator's reset forgot it).
    poste = "10.0.0.77" if holder == "new_address" else "10.0.0.10"
    assert (await _login_from(client, poste, password)).status_code == 200
    # The guesser stays out: the holder's login did not lift the slow lock.
    assert (await _login_from(client, GUESSER, password)).status_code == 401


async def test_the_owners_login_gives_a_slow_guesser_no_new_budget(
    client, db_session, few_slow_guesses
):
    """Verification of v1.2.1, F6. The slow lock zeroed its counter, and a
    login from a usual poste lifted it: the owner logging in handed the
    guesser twenty more guesses at once, sixty a day with three logins.
    Neither the lock nor a login clears the slow window: within it, the
    guesser's address has LOGIN_SLOW_MAX_FAILED_ATTEMPTS real guesses."""
    user = await _operator(db_session)
    user_id = user.id
    admin = await _admin(client, db_session)
    assert (await _login_from(client, "10.0.0.10")).status_code == 200

    # Before the lock: the owner's login leaves the slow count where it is.
    half = settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS // 2
    await _slow_guesses(client, db_session, user_id, half)
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == half
    await _slow_guesses(
        client, db_session, user_id, settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS - half
    )
    await db_session.refresh(user)
    until = user.slow_locked_until
    assert until is not None

    # After it: three logins of the owner's, and the guesser trying on.
    for _ in range(3):
        assert (await _login_from(client, "10.0.0.10")).status_code == 200
        await _slow_guesses(client, db_session, user_id, 2)
        # Even the right password is not looked at.
        assert (await _login_from(client, GUESSER)).status_code == 401
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS
    assert user.slow_window_started_at is not None
    assert len(await _locked_entries(client, admin)) == 1


async def test_the_slow_window_does_not_restart_while_its_lock_runs(
    client, db_session, few_slow_guesses
):
    """The lock outlives the window that set it (it starts at the last of
    the guesses, the window at the first). A failure in between must not
    open a new window: the addresses the lock refuses are those that failed
    since the window began, and would be forgotten with it."""
    from datetime import timedelta

    from app.features.base import utcnow

    user = await _operator(db_session)
    user_id = user.id
    await _slow_lock(client, db_session, user_id)
    await db_session.refresh(user)
    # The window is over, the lock has an hour left.
    span = timedelta(hours=settings.LOGIN_SLOW_WINDOW_HOURS)
    started = utcnow() - span - timedelta(hours=1)
    user.slow_window_started_at = started
    user.slow_locked_until = utcnow() + timedelta(hours=1)
    db_session.add(user)
    await db_session.commit()

    # Another address fails: counted in the same window, and shut out too.
    assert (await _login_from(client, "10.4.4.4", "wrong-password-here")).status_code
    await _space_out(db_session, user_id)
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == (
        settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS + 1
    )
    assert user.slow_window_started_at < utcnow() - span
    # …and the lock is not set a second time: once per window.
    assert user.slow_locked_until < utcnow() + timedelta(hours=1)
    assert (await _login_from(client, "10.4.4.4")).status_code == 401
    assert (await _login_from(client, GUESSER)).status_code == 401

    # The lock over, the next failure opens a new window with a new budget,
    # and the addresses of the old one are admitted again.
    user.slow_locked_until = utcnow() - timedelta(minutes=1)
    db_session.add(user)
    await db_session.commit()
    assert (await _login_from(client, GUESSER, "wrong-password-here")).status_code
    await _space_out(db_session, user_id)
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == 1
    assert user.slow_window_started_at > utcnow() - timedelta(hours=1)
    assert (await _login_from(client, GUESSER)).status_code == 200


async def test_a_typo_on_the_usual_poste_during_a_slow_lock(
    client, db_session, few_slow_guesses
):
    """An address that fails while the slow lock runs joins those it shuts
    out — one guess per new address is all the lock leaves. The holder's
    usual poste is back after LOGIN_LOCKOUT_MINUTES, as under any lock; an
    address the account never opened from stays out to the lock's end."""
    user = await _operator(db_session)
    user_id = user.id
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    await _slow_lock(client, db_session, user_id)

    for ip in ("10.0.0.10", "10.5.5.5"):
        assert (await _login_from(client, ip, "typo-typo-typo-1")).status_code == 401
        assert (await _login_from(client, ip)).status_code == 401
    await _space_out(db_session, user_id)
    assert (await _login_from(client, "10.5.5.5")).status_code == 401
    assert (await _login_from(client, "10.0.0.10")).status_code == 200


async def test_a_slow_siege_admits_only_the_usual_addresses(
    client, db_session, monkeypatch, few_slow_guesses
):
    """Slow guesses from many addresses: one address shut out per guess
    would leave the lock one guess per address. Once LOGIN_SIEGE_ADDRESSES
    of them failed since the slow window began, however far apart, the lock
    refuses every address but the usual ones — the documented limit."""
    monkeypatch.setattr(settings, "LOGIN_SIEGE_ADDRESSES", 3)
    user = await _operator(db_session)
    user_id = user.id
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    for i in range(settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS):
        await _slow_guesses(client, db_session, user_id, 1, ip=f"10.6.6.{i % 2}")
    # Two addresses guessed: an address that did not is admitted.
    assert (await _login_from(client, "10.5.5.5")).status_code == 200
    await _slow_guesses(client, db_session, user_id, 1, ip="10.6.6.2")
    # Three did, none of them within LOGIN_LOCKOUT_MINUTES: a siege.
    assert (await _login_from(client, "10.7.7.7")).status_code == 401
    assert (await _login_from(client, "10.0.0.10")).status_code == 200


async def test_a_reset_link_lifts_the_slow_lock(client, db_session, few_slow_guesses):
    """The way out of a holder the slow lock refuses — their address failed
    during the window: « mot de passe oublié ». The new password clears the
    lock, the window and the failures, for every address."""
    from app.features.user import crud

    user = await _operator(db_session)
    user_id = user.id
    await _slow_lock(client, db_session, user_id)
    assert (await _login_from(client, "10.5.5.5", "typo-typo-typo-1")).status_code
    await _space_out(db_session, user_id)
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
    assert user.locked_until is None and user.slow_locked_until is None
    assert user.slow_failed_login_attempts == 0
    assert user.slow_window_started_at is None
    for ip in ("10.5.5.5", "10.9.9.9", GUESSER):
        back = await _login_from(client, ip, "a-brand-new-password-1")
        assert back.status_code == 200


async def _ask_reset(client, ip: str):
    return await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "operator@test.local"},
        headers={"X-Forwarded-For": ip},
    )


async def test_the_reset_ceiling_does_not_close_the_way_out_of_a_slow_lock(
    client, db_session, monkeypatch, few_slow_guesses
):
    """Verification of v1.2.1, F1: a third party keeping the account's
    ceiling of live reset links full closed « mot de passe oublié » to a
    holder asking from an address that is not a usual one — the very holder
    the slow lock refuses. While the slow lock runs, the ceiling refuses
    nobody; the budget of each address still holds."""
    from sqlmodel import select

    from app.api.routes import auth
    from app.features.user.models import PasswordResetToken

    monkeypatch.setattr(auth, "PASSWORD_RESET_REQUEST_SECONDS", 0)
    monkeypatch.setattr(settings, "PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS", 4)
    user = await _operator(db_session)
    user_id = user.id

    async def links_asked_from(ip: str) -> int:
        db_session.expire_all()
        rows = await db_session.exec(
            select(PasswordResetToken).where(PasswordResetToken.requested_ip == ip)
        )
        return len(rows.all())

    for i in range(4):
        assert (await _ask_reset(client, f"198.51.100.{i + 1}")).status_code == 204
    # No slow lock: the ceiling holds against an address the account never saw.
    assert (await _ask_reset(client, "10.0.0.77")).status_code == 204
    assert await links_asked_from("10.0.0.77") == 0

    await _slow_lock(client, db_session, user_id)
    # The holder mistyped from this poste during the lock: refused at login…
    assert (await _login_from(client, "10.0.0.10", "typo-typo-typo-1")).status_code
    assert (await _login_from(client, "10.0.0.10")).status_code == 401
    # …and asks for a link from it: issued, the ceiling notwithstanding.
    assert (await _ask_reset(client, "10.0.0.10")).status_code == 204
    assert await links_asked_from("10.0.0.10") == 1
    # One address's own budget is not lifted: no second link within the cooldown.
    assert (await _ask_reset(client, "10.0.0.10")).status_code == 204
    assert await links_asked_from("10.0.0.10") == 1


async def test_slow_failures_older_than_the_window_start_over(
    client, db_session, few_slow_guesses
):
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

    await _login_from(client, GUESSER, "wrong-password-here")
    await db_session.refresh(user)
    assert user.slow_failed_login_attempts == 1
    assert user.locked_until is None and user.slow_locked_until is None


async def test_a_quick_lock_and_a_slow_one_keep_to_themselves(
    client, db_session, few_slow_guesses
):
    """Failures during a slow lock still count towards the quick one. The
    quick lock they trip neither shortens the slow one nor replaces it, and
    the login that lifts the quick lock leaves the slow one running."""
    user = await _operator(db_session)
    user_id = user.id
    usual = [f"10.0.1.{i}" for i in range(settings.LOGIN_MAX_FAILED_ATTEMPTS)]
    for ip in [*usual, "10.0.0.10"]:
        assert (await _login_from(client, ip)).status_code == 200
    await _slow_lock(client, db_session, user_id)
    await db_session.refresh(user)
    slow_until = user.slow_locked_until
    assert slow_until is not None and user.locked_until is None
    for ip in usual:
        await _login_from(client, ip, "wrong-password-here")
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0  # the quick lock tripped
    assert user.locked_until is not None and user.locked_until < slow_until
    assert user.slow_locked_until == slow_until

    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    await db_session.refresh(user)
    assert user.locked_until is None
    assert user.slow_locked_until == slow_until
    assert (await _login_from(client, GUESSER)).status_code == 401


async def test_the_morning_purge_keeps_what_the_slow_lock_reads(
    client, db_session, few_slow_guesses
):
    """The address rows are purged every morning. The guesser's failure is
    hours old by then, and still what the slow lock refuses it on: it stays
    for as long as a slow lock may need it."""
    from datetime import timedelta

    from sqlalchemy import update
    from sqlmodel import col, select

    from app.features.base import utcnow
    from app.features.user import addresses
    from app.features.user.models import LoginAddress

    user = await _operator(db_session)
    user_id = user.id
    await _slow_lock(client, db_session, user_id)
    assert await addresses.purge_stale(db_session, utcnow()) == 0
    assert (await _login_from(client, GUESSER)).status_code == 401

    # Twice the slow window later, no lock can still read it.
    await db_session.exec(
        update(LoginAddress)
        .where(col(LoginAddress.user_id) == user_id)
        .values(
            last_failure_at=utcnow()
            - timedelta(hours=2 * settings.LOGIN_SLOW_WINDOW_HOURS, minutes=1)
        )
    )
    await db_session.commit()
    assert await addresses.purge_stale(db_session, utcnow()) == 1
    assert (await db_session.exec(select(LoginAddress))).all() == []
