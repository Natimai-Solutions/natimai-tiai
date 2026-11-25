# ruff: noqa: F811  (the fixtures imported from the other test modules)
"""The review of C7 (2026-11-25): one test per finding fixed."""

import time
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlmodel import select

from app.core import totp
from app.core.config import settings
from app.features.oidc import client as oidc_client
from tests.scope_helpers import STRONG, account, group
from tests.test_oidc import (  # noqa: F401  (fixtures)
    GROUP_TECHS,
    ISSUER,
    _callback,
    _error,
    _map,
    _sign_in,
    _start,
    provider,
)
from tests.test_second_factor import (  # noqa: F401  (fixtures)
    _enrol,
    _password,
    _second_step,
    _user,
    clock,
)

# --- Linking a directory identity (high) -------------------------------------


async def test_link_needs_the_password_and_the_code(
    client, db_session, provider, clock
):
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "ra@lycee.test", [BuiltinGroup.ADMIN])
    secret, _ = await _enrol(client, headers, clock)
    url = "/api/v1/auth/oidc/link"
    # A stolen session alone, without the password: refused.
    resp = await client.post(
        url, headers=headers, json={"current_password": "wrong-123"}
    )
    assert resp.status_code == 400
    # The password without the code of an account with a second factor.
    resp = await client.post(url, headers=headers, json={"current_password": STRONG})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "auth.second_factor.code_invalid"
    clock.tick()
    resp = await client.post(
        url,
        headers=headers,
        json={"current_password": STRONG, "code": totp.code_at(secret, clock.step)},
    )
    assert resp.status_code == 200


async def test_password_changed_since_voids_the_link(client, db_session, provider):
    from app.features.base import utcnow
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "sa@lycee.test", [BuiltinGroup.ADMIN])
    state, browser = await _start(client, provider, headers=headers, link=True)
    # The owner takes the account back: a new password.
    user = await _user(db_session, "sa@lycee.test")
    user.password_changed_at = utcnow() + timedelta(seconds=1)
    db_session.add(user)
    await db_session.commit()
    provider.claims = {"sub": "subject-attacker", "groups": []}
    resp = await _callback(client, state, browser)
    assert _error(resp) == "auth.oidc.invalid"
    await db_session.refresh(user)
    assert user.oidc_subject is None


# --- The second factor's lock --------------------------------------------------


async def test_backup_code_regeneration_counts_towards_the_lock(
    client, db_session, clock
):
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "ta@lycee.test", [BuiltinGroup.ADMIN])
    secret, codes = await _enrol(client, headers, clock)
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/totp/backup-codes", headers=headers, json={"code": "000000"}
        )
        assert resp.status_code == 400
    user = await _user(db_session, "ta@lycee.test")
    await db_session.refresh(user)
    assert user.totp_locked_until is not None
    # Locked: even the right code is refused there, and at login.
    clock.tick()
    resp = await client.post(
        "/api/v1/auth/totp/backup-codes",
        headers=headers,
        json={"code": totp.code_at(secret, clock.step)},
    )
    assert resp.status_code == 400
    challenge = (await _password(client, "ta@lycee.test")).json()["challenge"]
    resp = await _second_step(client, challenge, totp.code_at(secret, clock.step))
    assert resp.status_code == 401
    # A backup code does not buy new backup codes.
    resp = await client.post(
        "/api/v1/auth/totp/backup-codes", headers=headers, json={"code": codes[0]}
    )
    assert resp.status_code == 400


def test_the_lock_doubles_each_time(monkeypatch):
    from app.features.base import utcnow
    from app.features.user import second_factor
    from app.features.user.models import User

    monkeypatch.setattr(settings, "SECOND_FACTOR_MAX_FAILED_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_MINUTES", 15)
    user = User(email="x@y.z", hashed_password="x")
    now = utcnow()
    lengths = []
    for _ in range(5 * 9):
        if second_factor._note_wrong(user, now):
            lengths.append(user.totp_locked_until - now)
    minutes = [int(d.total_seconds() // 60) for d in lengths]
    assert minutes[:4] == [15, 30, 60, 120]
    assert max(minutes) == 24 * 60


async def test_setup_needs_the_password(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "ua@lycee.test", [BuiltinGroup.ADMIN])
    resp = await client.post(
        "/api/v1/auth/totp/setup",
        headers=headers,
        json={"current_password": "nope-123"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "password.current.invalid"
    resp = await client.post("/api/v1/auth/totp/setup", headers=headers)
    assert resp.status_code == 422


async def test_challenge_voided_by_password_change_or_deactivation(
    client, db_session, clock
):
    from app.features.base import utcnow
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "va@lycee.test", [BuiltinGroup.ADMIN])
    secret, _ = await _enrol(client, headers, clock)
    user = await _user(db_session, "va@lycee.test")
    for change in ("password", "inactive"):
        challenge = (await _password(client, "va@lycee.test")).json()["challenge"]
        if change == "password":
            user.password_changed_at = utcnow()
        else:
            user.is_active = False
        db_session.add(user)
        await db_session.commit()
        clock.tick()
        resp = await _second_step(client, challenge, totp.code_at(secret, clock.step))
        assert resp.status_code == 401, change
        if change == "password":
            # Back to the password the test logs in with, for the next round.
            user.password_changed_at = None
            db_session.add(user)
            await db_session.commit()


# --- The obligation applies at once --------------------------------------------


async def test_requiring_it_narrows_open_sessions(client, db_session):
    from app.features.user.permissions import ALL_PERMISSIONS

    g = await group(db_session, "Plus tard MFA", ALL_PERMISSIONS, None)
    headers = await account(client, db_session, "wa@lycee.test", [g.id])
    assert (await client.get("/api/v1/machines", headers=headers)).status_code == 200
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "xa@lycee.test", [BuiltinGroup.ADMIN])
    resp = await client.patch(
        f"/api/v1/groups/{g.id}", headers=admin, json={"mfa_required": True}
    )
    assert resp.status_code == 200
    resp = await client.get("/api/v1/machines", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "auth.second_factor.not_enrolled"
    # Its refresh still opens the enrolment session only.
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["enrolment_only"] is True
    # A path outside the allowlist, under /auth too.
    resp = await client.get("/api/v1/auth/sessions/", headers=headers)
    assert resp.status_code in (403, 404, 405, 307)


async def test_mfa_toggle_needs_reach_over_the_members(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    mixed = await group(db_session, "Mixte", {"machine:read"}, None)
    await account(client, db_session, "ya@lycee.test", [BuiltinGroup.ADMIN, mixed.id])
    managers = await group(
        db_session, "Gestion", {"user:read", "user:write", "machine:read"}, None
    )
    manager = await account(client, db_session, "za@lycee.test", [managers.id])
    resp = await client.patch(
        f"/api/v1/groups/{mixed.id}", headers=manager, json={"mfa_required": True}
    )
    assert resp.status_code == 403


# --- OpenID Connect ------------------------------------------------------------


async def test_issuer_with_a_trailing_slash(client, db_session, provider, monkeypatch):
    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    monkeypatch.setattr(settings, "OIDC_ISSUER", ISSUER + "/")
    oidc_client.reset_cache()
    resp = await _sign_in(client, provider)
    assert _error(resp) is None and resp.status_code == 303
    provider.claims = {
        "iss": ISSUER + "/",
        "sub": "subject-slash",
        "email": "s@lycee.test",
    }
    resp = await _sign_in(client, provider)
    assert _error(resp) is None


async def test_refused_state_is_spent(client, db_session, provider):
    # No mapped group: refused — and the same state cannot be tried again.
    state, browser = await _start(client, provider)
    assert _error(await _callback(client, state, browser)) == "auth.oidc.no_group"
    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    assert _error(await _callback(client, state, browser)) == "auth.oidc.invalid"


async def test_a_raced_creation_answers_a_redirect(
    client, db_session, provider, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    from app.features.oidc import crud as oidc_crud

    async def raced(*_: Any, **__: Any) -> Any:
        raise IntegrityError("insert", {}, Exception("duplicate"))

    state, browser = await _start(client, provider)
    monkeypatch.setattr(oidc_crud, "finish", raced)
    resp = await _callback(client, state, browser)
    assert resp.status_code == 303 and _error(resp) == "auth.oidc.invalid"


async def test_callback_account_states(client, db_session, provider):
    from app.features.user.models import User
    from app.features.user.permissions import BuiltinGroup

    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    # No address in the token.
    provider.claims = {"email": None, "preferred_username": "not-an-address"}
    assert _error(await _sign_in(client, provider)) == "auth.oidc.no_email"
    # A bound account, deactivated.
    provider.claims = {}
    await _sign_in(client, provider)
    user = await _user(db_session, "ana@lycee.test")
    user.is_active = False
    db_session.add(user)
    await db_session.commit()
    assert _error(await _sign_in(client, provider)) == "auth.oidc.account_disabled"
    # Linking an identity already bound to another account.
    headers = await account(client, db_session, "bi@lycee.test", [BuiltinGroup.ADMIN])
    state, browser = await _start(client, provider, headers=headers, link=True)
    assert _error(await _callback(client, state, browser)) == "auth.oidc.already_linked"
    # A directory account cannot start a link.
    _ = User


async def test_link_refused_when_unconfigured(client, db_session, monkeypatch):
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "ci@lycee.test", [BuiltinGroup.ADMIN])
    resp = await client.post(
        "/api/v1/auth/oidc/link", headers=headers, json={"current_password": STRONG}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "auth.oidc.disabled"


def test_safe_redirect():
    from app.features.oidc.crud import safe_redirect

    assert safe_redirect("/machines?tab=1") == "/machines?tab=1"
    for bad in (
        None,
        "",
        "machines",
        "//evil.example",
        "https://evil.example",
        "/\\evil.example",
        "/a\nb",
        "/" + "a" * 2001,
    ):
        assert safe_redirect(bad) is None, bad


class _Bad:
    """A provider whose answers are wrong in one way at a time."""

    def __init__(self, base: Any) -> None:
        self.base = base
        self.mode = ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if self.mode == "issuer" and path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://other.test",
                    "authorization_endpoint": "https://x",
                    "token_endpoint": "https://x",
                    "jwks_uri": "https://x",
                },
            )
        if self.mode == "http" and path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": "http://login.test/a",
                    "token_endpoint": "https://login.test/token",
                    "jwks_uri": "https://login.test/keys",
                },
            )
        if self.mode == "token500" and path == "/token":
            return httpx.Response(503)
        if self.mode == "token400" and path == "/token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if self.mode == "tokentext" and path == "/token":
            return httpx.Response(200, text="<html>")
        return self.base.handler(request)


async def test_provider_answers_checked(client, db_session, provider, monkeypatch):
    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    bad = _Bad(provider)
    monkeypatch.setattr(oidc_client, "TRANSPORT", httpx.MockTransport(bad.handler))
    for mode, code in (("issuer", "auth.oidc.invalid"), ("http", "auth.oidc.invalid")):
        bad.mode = mode
        oidc_client.reset_cache()
        resp = await client.get("/api/v1/auth/oidc/start")
        assert _error(resp) == code, mode
    for mode, code in (
        ("token500", "auth.oidc.unavailable"),
        ("token400", "auth.oidc.invalid"),
        ("tokentext", "auth.oidc.invalid"),
    ):
        bad.mode = ""
        oidc_client.reset_cache()
        state, browser = await _start(client, provider)
        bad.mode = mode
        assert _error(await _callback(client, state, browser)) == code, mode


async def test_token_algorithm_and_key_rotation(client, db_session, provider):
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    # « none » / HS256: refused whatever the key.
    state, browser = await _start(client, provider)
    real = provider.id_token

    def hs(**_: Any) -> str:
        now = int(time.time())
        return pyjwt.encode(
            {
                "iss": ISSUER,
                "aud": "console-client",
                "sub": "x",
                "iat": now,
                "exp": now + 60,
                "nonce": provider.nonce,
            },
            "secret",
            algorithm="HS256",
        )

    provider.id_token = hs  # type: ignore[method-assign]
    assert _error(await _callback(client, state, browser)) == "auth.oidc.invalid"
    provider.id_token = real  # type: ignore[method-assign]

    # The provider rotates its key: a token under the new key is accepted
    # once the keys are read again (the cache is older than a minute).
    assert _error(await _sign_in(client, provider)) is None
    provider.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider.kid = "k2"
    oidc_client._cache.keys_at -= 120
    assert _error(await _sign_in(client, provider)) is None


async def test_purges(client, db_session, provider, clock):
    from app.features.auth_session.models import LoginChallenge
    from app.features.base import utcnow
    from app.features.oidc import crud as oidc_crud
    from app.features.oidc.models import OidcLogin
    from app.features.user import second_factor
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "di@lycee.test", [BuiltinGroup.ADMIN])
    await _enrol(client, headers, clock)
    await _password(client, "di@lycee.test")
    await _start(client, provider)
    for row in (await db_session.exec(select(LoginChallenge))).all():
        row.expires_at = utcnow() - timedelta(seconds=1)
        db_session.add(row)
    for row in (await db_session.exec(select(OidcLogin))).all():
        row.expires_at = utcnow() - timedelta(seconds=1)
        db_session.add(row)
    await db_session.commit()
    assert await second_factor.purge_challenges(db_session) >= 1
    assert await oidc_crud.purge(db_session) >= 1
    assert (await db_session.exec(select(LoginChallenge))).all() == []
    assert (await db_session.exec(select(OidcLogin))).all() == []


@pytest.mark.parametrize("path", ["/api/v1/auth/totp/disable", "/api/v1/users"])
async def test_enrolment_session_reaches_nothing_else(client, db_session, path):
    from app.features.user.models import Group
    from app.features.user.permissions import ALL_PERMISSIONS

    g = await group(db_session, f"MFA {path}", ALL_PERMISSIONS, None)
    row = await db_session.get(Group, g.id)
    row.mfa_required = True
    db_session.add(row)
    await db_session.commit()
    headers = await account(client, db_session, f"e{len(path)}@lycee.test", [g.id])
    resp = await client.request(
        "POST" if "totp" in path else "GET", path, headers=headers, json={}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "auth.second_factor.not_enrolled"
