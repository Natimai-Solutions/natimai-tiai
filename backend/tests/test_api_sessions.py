"""Console sessions: login, refresh rotation and theft detection, logout,
the « Sessions ouvertes » list, and every event that ends sessions early.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import logging
import uuid
from datetime import timedelta

import jwt
import pytest
from sqlmodel import select

STRONG = "correct-horse-battery"
COOKIE = "tiai_refresh"


async def _account(db_session, email="op@test.local", *, admin=False):
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    if admin:
        await crud.ensure_builtin_groups(db_session)
        await db_session.commit()
    user = await crud.create_user(
        db_session,
        email=email,
        password=STRONG,
        groups=[BuiltinGroup.ADMIN if admin else BuiltinGroup.READONLY],
    )
    return str(user.id)


async def _login(client, email="op@test.local", password=STRONG, **headers):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp


def _bearer(resp) -> dict[str, str]:
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _refresh(client, token: str | None):
    """POST /auth/refresh with exactly this refresh token (or none).

    The jar is emptied first, so the test says which token travels — the
    browser's jar is what the cookie path and flags are about, not this."""
    client.cookies.clear()
    headers = {"Cookie": f"{COOKIE}={token}"} if token is not None else {}
    return await client.post("/api/v1/auth/refresh", headers=headers)


async def _me(client, headers):
    return await client.get("/api/v1/auth/me", headers=headers)


async def _sessions(db_session, user_id):
    from app.features.auth_session.models import AuthSession

    db_session.expire_all()
    rows = await db_session.exec(
        select(AuthSession).where(AuthSession.user_id == uuid.UUID(user_id))
    )
    return list(rows.all())


# --- Login --------------------------------------------------------------------


async def test_login_sets_a_hardened_refresh_cookie(client, db_session):
    await _account(db_session)
    resp = await _login(client)
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert f"Max-Age={7 * 24 * 3600}" in cookie
    # ENVIRONMENT=local in the tests: plain HTTP dev server, no Secure.
    assert "Secure" not in cookie
    # The refresh token never travels in a body.
    assert set(resp.json()) == {"access_token", "token_type"}


async def test_the_cookie_is_secure_outside_local(client, db_session, monkeypatch):
    from app.core.config import settings

    await _account(db_session)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    resp = await _login(client)
    assert "Secure" in resp.headers["set-cookie"]


async def test_login_opens_a_session_the_access_token_names(client, db_session):
    from app.core.config import settings

    user_id = await _account(db_session)
    resp = await _login(client, **{"User-Agent": "Firefox/140 " + "x" * 400})
    payload = jwt.decode(
        resp.json()["access_token"], options={"verify_signature": False}
    )
    assert payload["type"] == "access"
    assert payload["exp"] - payload["iat"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    (row,) = await _sessions(db_session, user_id)
    assert str(row.id) == payload["sid"]
    # Only the hash is stored, and the client's description is bounded.
    assert resp.cookies[COOKIE] not in (row.refresh_token_hash, None)
    assert len(row.user_agent) == 255 and row.user_agent.startswith("Firefox/140")
    assert row.ip


def test_the_access_token_defaults_to_fifteen_minutes():
    from app.core.config import Settings

    assert Settings().ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert Settings().REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert Settings().SESSION_MAX_DAYS == 30


# --- Refresh ------------------------------------------------------------------


async def test_refresh_rotates_the_token_and_issues_an_access_token(client, db_session):
    await _account(db_session)
    login = await _login(client)
    first = login.cookies[COOKIE]

    resp = await _refresh(client, first)
    assert resp.status_code == 200, resp.text
    second = resp.cookies[COOKIE]
    assert second and second != first
    assert (await _me(client, _bearer(resp))).status_code == 200
    # Single use: the new one works in turn.
    assert (await _refresh(client, second)).status_code == 200


async def test_refresh_slides_the_session_end(client, db_session):
    from app.features.base import utcnow

    user_id = await _account(db_session)
    login = await _login(client)
    (row,) = await _sessions(db_session, user_id)
    row.expires_at = utcnow() + timedelta(days=1)
    db_session.add(row)
    await db_session.commit()

    assert (await _refresh(client, login.cookies[COOKIE])).status_code == 200
    (row,) = await _sessions(db_session, user_id)
    assert row.expires_at > utcnow() + timedelta(days=6)


async def test_the_session_ceiling_is_absolute(client, db_session):
    """However often it is refreshed, a session ends SESSION_MAX_DAYS after
    the login."""
    from app.features.base import utcnow

    user_id = await _account(db_session)
    login = await _login(client)
    (row,) = await _sessions(db_session, user_id)
    row.created_at = utcnow() - timedelta(days=29)
    db_session.add(row)
    await db_session.commit()

    resp = await _refresh(client, login.cookies[COOKIE])
    assert resp.status_code == 200
    (row,) = await _sessions(db_session, user_id)
    assert row.expires_at == row.created_at + timedelta(days=30)
    assert f"Max-Age={7 * 24 * 3600}" not in resp.headers["set-cookie"]


async def test_reusing_a_rotated_token_revokes_the_session(
    client, db_session, monkeypatch, caplog
):
    """Refresh tokens are single-use: a second use of one means two parties
    hold the session. Both are shut out."""
    from app.features.auth_session import crud as auth_sessions

    monkeypatch.setattr(auth_sessions, "REFRESH_REUSE_GRACE", timedelta(0))
    user_id = await _account(db_session)
    stolen = (await _login(client)).cookies[COOKIE]
    rotated = await _refresh(client, stolen)
    current = rotated.cookies[COOKIE]

    with caplog.at_level(logging.WARNING, logger="app.security"):
        resp = await _refresh(client, stolen)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.session.invalid"
    assert f'{COOKIE}=""' in resp.headers["set-cookie"]
    assert any("presumed theft" in r.getMessage() for r in caplog.records)

    # The legitimate holder is out too: neither token nor access opens anything.
    assert (await _refresh(client, current)).status_code == 401
    assert (await _me(client, _bearer(rotated))).status_code == 401
    (row,) = await _sessions(db_session, user_id)
    assert row.revoked_at is not None


async def test_a_token_older_than_the_last_one_is_theft_too(
    client, db_session, monkeypatch
):
    from app.features.auth_session import crud as auth_sessions

    monkeypatch.setattr(auth_sessions, "REFRESH_REUSE_GRACE", timedelta(0))
    await _account(db_session)
    first = (await _login(client)).cookies[COOKIE]
    second = (await _refresh(client, first)).cookies[COOKIE]
    third = (await _refresh(client, second)).cookies[COOKIE]
    assert (await _refresh(client, first)).status_code == 401
    assert (await _refresh(client, third)).status_code == 401


async def test_two_tabs_racing_for_the_same_token_are_not_theft(client, db_session):
    """Two tabs reloaded together both send the cookie. The second, a moment
    late, gets an access token and leaves the cookie as the first set it."""
    await _account(db_session)
    shared = (await _login(client)).cookies[COOKIE]
    first_tab = await _refresh(client, shared)
    assert first_tab.status_code == 200

    second_tab = await _refresh(client, shared)
    assert second_tab.status_code == 200, second_tab.text
    assert "set-cookie" not in second_tab.headers
    assert (await _me(client, _bearer(second_tab))).status_code == 200
    # The winner's token is still the session's.
    assert (await _refresh(client, first_tab.cookies[COOKIE])).status_code == 200


@pytest.mark.parametrize(
    "token",
    [None, "", "garbage", "not-a-uuid.secret", f"{uuid.uuid4()}.secret"],
)
async def test_refresh_without_a_valid_token_is_refused(client, db_session, token):
    resp = await _refresh(client, token)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.session.invalid"


async def test_a_forged_secret_for_a_live_session_ends_it(client, db_session):
    """The id half of a refresh token names a session; a secret that is not
    that session's is a stale copy — the conservative reading wins."""
    user_id = await _account(db_session)
    login = await _login(client)
    sid = jwt.decode(login.json()["access_token"], options={"verify_signature": False})[
        "sid"
    ]
    assert (await _refresh(client, f"{sid}.forged")).status_code == 401
    (row,) = await _sessions(db_session, user_id)
    assert row.revoked_at is not None


async def test_an_expired_session_is_over(client, db_session):
    from app.features.base import utcnow

    user_id = await _account(db_session)
    login = await _login(client)
    (row,) = await _sessions(db_session, user_id)
    row.expires_at = utcnow() - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()

    resp = await _me(client, _bearer(login))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.session.invalid"
    assert (await _refresh(client, login.cookies[COOKIE])).status_code == 401


async def test_refresh_refuses_a_deactivated_account(client, db_session):
    """Deactivation revokes the sessions; this is the backstop for one that
    escaped it (an account switched off in the database by hand)."""
    from app.features.user import crud

    user_id = await _account(db_session)
    login = await _login(client)
    user = await crud.get_by_email(db_session, "op@test.local")
    user.is_active = False
    db_session.add(user)
    await db_session.commit()

    assert (await _refresh(client, login.cookies[COOKIE])).status_code == 401
    (row,) = await _sessions(db_session, user_id)
    assert row.revoked_at is not None


# --- Access tokens --------------------------------------------------------------


def _forge(**claims):
    from datetime import UTC, datetime

    from app.core.config import settings
    from app.core.security import ALGORITHM

    now = datetime.now(UTC)
    payload = {"iat": now, "exp": now + timedelta(minutes=5), **claims}
    return {
        "Authorization": "Bearer "
        + jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    }


async def test_a_token_of_another_type_is_refused(client, db_session):
    user_id = await _account(db_session)
    login = await _login(client)
    sid = jwt.decode(login.json()["access_token"], options={"verify_signature": False})[
        "sid"
    ]
    for kind in ("refresh", "reset", None):
        claims = {"sub": user_id, "sid": sid}
        if kind is not None:
            claims["type"] = kind
        resp = await _me(client, _forge(**claims))
        assert resp.status_code == 401, kind
        assert resp.json()["error"]["code"] == "auth.credentials.invalid"
    assert (
        await _me(client, _forge(sub=user_id, sid=sid, type="access"))
    ).status_code == 200


async def test_a_token_without_a_live_session_is_refused(client, db_session):
    user_id = await _account(db_session)
    for sid in (None, "not-a-uuid", str(uuid.uuid4())):
        claims = {"sub": user_id, "type": "access"}
        if sid is not None:
            claims["sid"] = sid
        assert (await _me(client, _forge(**claims))).status_code == 401


async def test_a_session_does_not_open_another_account(client, db_session):
    await _account(db_session)
    other = await _account(db_session, "other@test.local")
    login = await _login(client)
    sid = jwt.decode(login.json()["access_token"], options={"verify_signature": False})[
        "sid"
    ]
    resp = await _me(client, _forge(sub=other, sid=sid, type="access"))
    assert resp.status_code == 401


# --- Logout ---------------------------------------------------------------------


async def test_logout_ends_the_session_at_once(client, db_session):
    await _account(db_session)
    login = await _login(client)
    headers = _bearer(login)
    assert (await _me(client, headers)).status_code == 200

    resp = await client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 204
    assert f'{COOKIE}=""' in resp.headers["set-cookie"]
    assert "Path=/api/v1/auth" in resp.headers["set-cookie"]

    resp = await _me(client, headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.session.invalid"
    assert (await _refresh(client, login.cookies[COOKIE])).status_code == 401


async def test_logout_with_the_cookie_alone(client, db_session):
    """An access token that just expired must not keep anyone logged in."""
    await _account(db_session)
    login = await _login(client)
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/logout", headers={"Cookie": f"{COOKIE}={login.cookies[COOKIE]}"}
    )
    assert resp.status_code == 204
    assert (await _me(client, _bearer(login))).status_code == 401


async def test_logout_with_the_access_token_alone(client, db_session):
    await _account(db_session)
    login = await _login(client)
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/logout", headers=_bearer(login))
    assert resp.status_code == 204
    assert (await _me(client, _bearer(login))).status_code == 401


async def test_logout_without_a_session_is_still_204(client, db_session):
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    resp = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer nope", "Cookie": f"{COOKIE}=nope"},
    )
    assert resp.status_code == 204


async def test_logout_ends_only_its_own_session(client, db_session):
    await _account(db_session)
    office = await _login(client)
    laptop = await _login(client)
    # Two workstations, two cookie jars: the office logs out with its own.
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/logout",
        headers={**_bearer(office), "Cookie": f"{COOKIE}={office.cookies[COOKIE]}"},
    )
    assert resp.status_code == 204
    assert (await _me(client, _bearer(office))).status_code == 401
    assert (await _me(client, _bearer(laptop))).status_code == 200
    assert (await _refresh(client, laptop.cookies[COOKIE])).status_code == 200


# --- « Sessions ouvertes » ----------------------------------------------------------


async def test_an_account_lists_its_open_sessions(client, db_session):
    await _account(db_session)
    await _account(db_session, "other@test.local")
    office = await _login(client, **{"User-Agent": "Bureau"})
    await _login(client, **{"User-Agent": "Portable"})
    await _login(client, "other@test.local", **{"User-Agent": "Autre"})
    gone = await _login(client, **{"User-Agent": "Fermee"})
    await client.post("/api/v1/auth/logout", headers=_bearer(gone))

    resp = await client.get("/api/v1/auth/sessions", headers=_bearer(office))
    assert resp.status_code == 200
    rows = resp.json()
    assert sorted(r["user_agent"] for r in rows) == ["Bureau", "Portable"]
    assert [r["current"] for r in rows if r["user_agent"] == "Bureau"] == [True]
    assert [r["current"] for r in rows if r["user_agent"] == "Portable"] == [False]
    assert set(rows[0]) == {
        "id",
        "created_at",
        "last_used_at",
        "expires_at",
        "user_agent",
        "ip",
        "current",
    }


async def test_closing_a_session_ends_it_and_is_audited(client, db_session):
    from app.features.audit.models import AuditEntry

    user_id = await _account(db_session)
    office = await _login(client, **{"User-Agent": "Bureau"})
    laptop = await _login(client, **{"User-Agent": "Portable"})
    rows = (await client.get("/api/v1/auth/sessions", headers=_bearer(office))).json()
    target = next(r for r in rows if r["user_agent"] == "Portable")

    resp = await client.delete(
        f"/api/v1/auth/sessions/{target['id']}", headers=_bearer(office)
    )
    assert resp.status_code == 204
    assert "set-cookie" not in resp.headers
    assert (await _me(client, _bearer(laptop))).status_code == 401
    assert (await _me(client, _bearer(office))).status_code == 200

    entries = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "auth.session_revoked")
        )
    ).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor == "op@test.local"
    assert entry.resource_type == "user" and entry.resource_id == user_id
    assert entry.details["user_agent"] == "Portable"
    assert entry.details["current"] is False
    # The session id authorizes a refresh attempt: it stays out of the log.
    assert target["id"] not in str(entry.details)


async def test_closing_the_current_session_logs_out(client, db_session):
    await _account(db_session)
    login = await _login(client)
    rows = (await client.get("/api/v1/auth/sessions", headers=_bearer(login))).json()
    resp = await client.delete(
        f"/api/v1/auth/sessions/{rows[0]['id']}", headers=_bearer(login)
    )
    assert resp.status_code == 204
    assert f'{COOKIE}=""' in resp.headers["set-cookie"]
    assert (await _me(client, _bearer(login))).status_code == 401


async def test_another_accounts_session_is_not_found(client, db_session):
    await _account(db_session)
    await _account(db_session, "other@test.local")
    mine = await _login(client)
    theirs = await _login(client, "other@test.local")
    their_sid = jwt.decode(
        theirs.json()["access_token"], options={"verify_signature": False}
    )["sid"]
    for sid in (their_sid, str(uuid.uuid4())):
        resp = await client.delete(
            f"/api/v1/auth/sessions/{sid}", headers=_bearer(mine)
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "auth.session.not_found"
    assert (await _me(client, _bearer(theirs))).status_code == 200


async def test_sessions_require_authentication(client, db_session):
    assert (await client.get("/api/v1/auth/sessions")).status_code == 401
    resp = await client.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}")
    assert resp.status_code == 401


# --- Events that end every session of an account ------------------------------------


async def test_changing_ones_password_ends_every_session(client, db_session):
    await _account(db_session)
    office = await _login(client)
    laptop = await _login(client)
    resp = await client.post(
        "/api/v1/auth/password",
        headers=_bearer(office),
        json={"current_password": STRONG, "new_password": "another-passphrase"},
    )
    assert resp.status_code == 204
    for login in (office, laptop):
        assert (await _me(client, _bearer(login))).status_code == 401
        assert (await _refresh(client, login.cookies[COOKIE])).status_code == 401
    # The new password opens a new session straight away (no second to wait).
    fresh = await _login(client, password="another-passphrase")
    assert (await _me(client, _bearer(fresh))).status_code == 200


async def test_a_reset_link_ends_every_session(client, db_session):
    from app.features.user import crud

    await _account(db_session)
    login = await _login(client)
    user = await crud.get_by_email(db_session, "op@test.local")
    token = await crud.create_reset_token(db_session, user)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "another-passphrase"},
    )
    assert resp.status_code == 204
    assert (await _me(client, _bearer(login))).status_code == 401


async def test_an_admin_reset_ends_every_session_at_once(client, db_session):
    victim = await _account(db_session)
    login = await _login(client)
    await _account(db_session, "admin@test.local", admin=True)
    admin = _bearer(await _login(client, "admin@test.local"))
    resp = await client.post(
        f"/api/v1/users/{victim}/reset-password", headers=admin, json={}
    )
    assert resp.status_code == 200
    assert (await _me(client, _bearer(login))).status_code == 401
    assert (await _refresh(client, login.cookies[COOKIE])).status_code == 401


async def test_deactivation_ends_every_session_for_good(client, db_session):
    target = await _account(db_session)
    login = await _login(client)
    await _account(db_session, "admin@test.local", admin=True)
    admin = _bearer(await _login(client, "admin@test.local"))

    resp = await client.patch(
        f"/api/v1/users/{target}", headers=admin, json={"is_active": False}
    )
    assert resp.status_code == 200
    assert (await _me(client, _bearer(login))).status_code == 401
    # Reactivating the account does not bring the old sessions back.
    resp = await client.patch(
        f"/api/v1/users/{target}", headers=admin, json={"is_active": True}
    )
    assert resp.status_code == 200
    assert (await _me(client, _bearer(login))).status_code == 401
    assert all(r.revoked_at is not None for r in await _sessions(db_session, target))


async def test_deletion_takes_the_sessions_with_it(client, db_session):
    target = await _account(db_session)
    login = await _login(client)
    await _account(db_session, "admin@test.local", admin=True)
    admin = _bearer(await _login(client, "admin@test.local"))

    assert (
        await client.delete(f"/api/v1/users/{target}", headers=admin)
    ).status_code == 204
    assert await _sessions(db_session, target) == []
    assert (await _me(client, _bearer(login))).status_code == 401


async def test_other_edits_leave_the_sessions_alone(client, db_session):
    target = await _account(db_session)
    login = await _login(client)
    await _account(db_session, "admin@test.local", admin=True)
    admin = _bearer(await _login(client, "admin@test.local"))
    resp = await client.patch(
        f"/api/v1/users/{target}", headers=admin, json={"full_name": "Opérateur"}
    )
    assert resp.status_code == 200
    assert (await _me(client, _bearer(login))).status_code == 200


# --- Purge --------------------------------------------------------------------------


async def test_purge_drops_expired_and_revoked_sessions_only(client, db_session):
    from app.features.auth_session import crud as auth_sessions
    from app.features.base import utcnow

    user_id = await _account(db_session)
    live = await _login(client)
    expired = await _login(client)
    revoked = await _login(client)
    await client.post("/api/v1/auth/logout", headers=_bearer(revoked))
    expired_sid = jwt.decode(
        expired.json()["access_token"], options={"verify_signature": False}
    )["sid"]
    for row in await _sessions(db_session, user_id):
        if str(row.id) == expired_sid:
            row.expires_at = utcnow() - timedelta(minutes=1)
            db_session.add(row)
    await db_session.commit()

    assert await auth_sessions.purge_expired_sessions(db_session) == 2
    (remaining,) = await _sessions(db_session, user_id)
    assert (await _me(client, _bearer(live))).status_code == 200
    assert (
        str(remaining.id)
        == jwt.decode(live.json()["access_token"], options={"verify_signature": False})[
            "sid"
        ]
    )
    assert await auth_sessions.purge_expired_sessions(db_session) == 0
