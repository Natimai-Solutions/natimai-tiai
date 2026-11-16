"""An account locks after repeated failed logins (require TIAI_TEST_DATABASE_URL).

The lock shuts out the addresses that failed on the account, not the account
itself (audit S03), answers like any failure (S12), and counts concurrent
failures (S13). Wrong current passwords on « changer mon mot de passe » count
too, and are rate limited per account (S04).
"""

import asyncio

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
    # The lock revoked every session: the stolen token is dead.
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_password_change_is_rate_limited_per_account(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 100)
    await _operator(db_session)
    resp = await _login(client, "operator@test.local")
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    codes = []
    for i in range(7):
        r = await client.post(
            "/api/v1/auth/password",
            headers={**headers, "X-Forwarded-For": f"10.0.2.{i}"},
            json={"current_password": "guess-guess", "new_password": "x" * 20},
        )
        codes.append(r.status_code)
    assert codes[:5] == [400] * 5
    assert codes[5:] == [429, 429]


async def _siege(client, *, start: int = 0) -> None:
    """Lock the operator's account, then fail from enough distinct addresses
    for the lock to admit only the known ones."""
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await _login_from(client, "10.0.0.66", "wrong-password-here")
    for n in range(start, start + settings.LOGIN_SIEGE_ADDRESSES - 1):
        await _login_from(client, f"10.9.{n}.1", "wrong-password-here")


async def test_guesses_spread_over_many_addresses_turn_the_lock_account_wide(
    client, db_session
):
    """Audit S03, second pass: during a lock every fresh address used to get
    one real guess, so a /24 or an IPv6 prefix bought hundreds. From
    LOGIN_SIEGE_ADDRESSES failing addresses on, the lock shuts out every
    address but those that opened the account before."""
    await _operator(db_session)
    # The owner's usual poste opened the account last week.
    assert (await _login_from(client, "10.0.0.10")).status_code == 200

    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await _login_from(client, "10.0.0.66", "wrong-password-here")
    # A few more addresses: still one person's postes, the lock stays narrow.
    assert (await _login_from(client, "10.0.1.1")).status_code == 200
    await _siege(client)

    # The right password from yet another address no longer gets a check.
    assert (await _login_from(client, "10.9.200.1")).status_code == 401
    # The owner's postes still open it, and that lifts the lock.
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    assert (await _login_from(client, "10.9.200.1")).status_code == 200


async def test_a_restart_neither_lifts_the_lock_nor_forgets_the_usual_postes(
    client, db_session
):
    """Audit S03, third pass: what guards the lock was in the process's
    memory. After a restart the lock in the database refused nobody, and the
    owner's poste was unknown — guesses from ten addresses then shut the owner
    out. It is all in the database now."""
    from app.core import ratelimit

    await _operator(db_session)
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    await _siege(client)

    # Everything a process holds in memory, gone.
    ratelimit.reset_all()

    # The guessing address is still shut out, a fresh one too…
    assert (await _login_from(client, "10.0.0.66")).status_code == 401
    assert (await _login_from(client, "10.9.200.1")).status_code == 401
    # …and the owner's poste is still the owner's.
    assert (await _login_from(client, "10.0.0.10")).status_code == 200


async def test_a_session_in_use_keeps_its_address_known(client, db_session):
    """An owner who never logs out refreshes for SESSION_MAX_DAYS, the very
    time LOGIN_KNOWN_ADDRESS_DAYS lasts by default: without the refresh
    counting, their poste stopped being known the day they had to log in."""
    from datetime import timedelta

    from app.features.base import utcnow
    from app.features.user.models import LoginAddress

    user = await _operator(db_session)
    opened = await _login_from(client, "10.0.0.10")
    assert opened.status_code == 200
    cookie = opened.cookies.get(COOKIE)
    row = await db_session.get(LoginAddress, (user.id, "10.0.0.10"))
    row.last_success_at = utcnow() - timedelta(
        days=settings.LOGIN_KNOWN_ADDRESS_DAYS - 1
    )
    stale = row.last_success_at
    db_session.add(row)
    await db_session.commit()

    client.cookies.clear()
    refreshed = await client.post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": f"{COOKIE}={cookie}",
            "X-Forwarded-For": "10.0.0.10",
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    await db_session.refresh(row)
    assert row.last_success_at > stale
    # Written once a day at most: the next refresh leaves it alone.
    seen = row.last_success_at
    cookie = refreshed.cookies.get(COOKIE)
    client.cookies.clear()
    again = await client.post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": f"{COOKIE}={cookie}",
            "X-Forwarded-For": "10.0.0.10",
        },
    )
    assert again.status_code == 200, again.text
    await db_session.refresh(row)
    assert row.last_success_at == seen


async def test_a_reset_link_is_the_way_back_in_from_a_new_address(client, db_session):
    """An owner on an address the account has never seen, while guesses come
    from many: the lock refuses them, a reset link redeemed from that address
    lets them in — and the old password's addresses stop being known."""
    from app.features.user import crud
    from app.features.user.models import LoginAddress

    user = await _operator(db_session)
    user_id = user.id
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
    await _siege(client)
    assert (await _login_from(client, "10.7.7.7")).status_code == 401

    await db_session.refresh(user)
    token = await crud.create_reset_token(db_session, user)
    await db_session.commit()
    redeemed = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "a-brand-new-password-1"},
        headers={"X-Forwarded-For": "10.7.7.7"},
    )
    assert redeemed.status_code == 204, redeemed.text

    # The guessing resumes and locks the account again…
    await _siege(client, start=100)
    # …the address the link was redeemed from gets in all the same.
    back = await _login_from(client, "10.7.7.7", "a-brand-new-password-1")
    assert back.status_code == 200
    # The poste that knew the old password is no longer one of the owner's.
    assert await db_session.get(LoginAddress, (user_id, "10.0.0.10")) is None


async def test_the_addresses_that_say_nothing_any_more_are_purged(client, db_session):
    from datetime import timedelta

    from sqlmodel import select

    from app.features.base import utcnow
    from app.features.user import addresses
    from app.features.user.models import LoginAddress

    user = await _operator(db_session)
    now = utcnow()
    long_ago = now - timedelta(days=settings.LOGIN_KNOWN_ADDRESS_DAYS + 1)
    await addresses.note_success(db_session, user.id, "10.0.0.1", now)
    await addresses.note_failure(db_session, user.id, "10.0.0.2", now)
    await addresses.note_success(db_session, user.id, "10.0.0.3", long_ago)
    await addresses.note_failure(db_session, user.id, "10.0.0.4", long_ago)
    await db_session.commit()

    assert await addresses.purge_stale(db_session, now) == 2
    kept = (await db_session.exec(select(LoginAddress.ip))).all()
    assert sorted(kept) == ["10.0.0.1", "10.0.0.2"]


async def test_old_failures_do_not_add_up_to_a_lock(client, db_session):
    """Audit S03, second pass: the counter decays. Four failures long ago and
    one typo today do not lock the owner out of their poste."""
    from datetime import timedelta

    from app.features.base import utcnow

    user = await _operator(db_session)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS - 1):
        await _login_from(client, "10.0.0.66", "wrong-password-here")
    await db_session.refresh(user)
    assert user.failed_login_attempts == settings.LOGIN_MAX_FAILED_ATTEMPTS - 1
    user.last_failed_login_at = utcnow() - timedelta(days=7)
    db_session.add(user)
    await db_session.commit()

    await _login_from(client, "10.0.0.10", "a-typo-from-the-owner")
    await db_session.refresh(user)
    assert user.failed_login_attempts == 1
    assert user.locked_until is None
    assert (await _login_from(client, "10.0.0.10")).status_code == 200
