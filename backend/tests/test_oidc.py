"""Sign-in through the directory (C7): a provider simulated with its own RSA
keys, discovery and token endpoint, and the console's checks against it."""

import base64
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlmodel import select

from app.core.config import settings
from app.features.oidc import client as oidc_client
from tests.scope_helpers import STRONG, account, group

ISSUER = "https://login.test/tenant-1/v2.0"
CLIENT_ID = "console-client"
GROUP_TECHS = "11111111-aaaa-4bbb-8ccc-000000000001"
GROUP_OTHER = "11111111-aaaa-4bbb-8ccc-000000000002"


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@dataclass
class Provider:
    key: Any = field(
        default_factory=lambda: rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
    )
    kid: str = "k1"
    claims: dict[str, Any] = field(default_factory=dict)
    nonce: str = ""
    down: bool = False
    token_requests: list[dict[str, str]] = field(default_factory=list)

    def jwks(self) -> dict[str, Any]:
        pub = self.key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "kid": self.kid,
                    "n": _b64(pub.n),
                    "e": _b64(pub.e),
                }
            ]
        }

    def id_token(self, **overrides: Any) -> str:
        now = int(time.time())
        payload = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "subject-ana",
            "iat": now,
            "exp": now + 600,
            "nonce": self.nonce,
            "email": "ana@lycee.test",
            "name": "Ana",
            "groups": [GROUP_TECHS],
            **self.claims,
            **overrides,
        }
        return jwt.encode(
            payload, self.key, algorithm="RS256", headers={"kid": self.kid}
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": "https://login.test/authorize",
                    "token_endpoint": "https://login.test/token",
                    "jwks_uri": "https://login.test/keys",
                },
            )
        if path == "/keys":
            return httpx.Response(200, json=self.jwks())
        if path == "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            return httpx.Response(200, json={"id_token": self.id_token()})
        return httpx.Response(404)


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr(settings, "OIDC_ENABLED", True)
    monkeypatch.setattr(settings, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setattr(
        settings, "OIDC_REDIRECT_URI", "https://console.test/api/v1/auth/oidc/callback"
    )
    monkeypatch.setattr(oidc_client, "TRANSPORT", httpx.MockTransport(p.handler))
    oidc_client.reset_cache()
    yield p
    oidc_client.reset_cache()


async def _start(client, provider, headers=None, link=False, link_code=None):
    if link:
        resp = await client.post(
            "/api/v1/auth/oidc/link",
            headers=headers,
            json={"current_password": STRONG, **(link_code or {})},
        )
        assert resp.status_code == 200, resp.text
        url = resp.json()["url"]
    else:
        resp = await client.get(
            "/api/v1/auth/oidc/start", params={"redirect": "/machines"}
        )
        assert resp.status_code == 303, resp.text
        url = resp.headers["location"]
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == settings.OIDC_REDIRECT_URI
    provider.nonce = query["nonce"]
    browser = resp.cookies.get("tiai_oidc")
    assert browser
    return query["state"], browser


async def _callback(client, state, browser, code="code-1"):
    client.cookies.clear()
    return await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": code, "state": state},
        headers={"Cookie": f"tiai_oidc={browser}"},
    )


async def _sign_in(client, provider):
    state, browser = await _start(client, provider)
    return await _callback(client, state, browser)


def _error(resp) -> str | None:
    location = resp.headers.get("location", "")
    query = parse_qs(urlparse(location).query)
    return query.get("sso_error", [None])[0]


async def _map(db_session, name, idp_ids, permissions=frozenset({"machine:read"})):
    from app.features.user.models import GroupIdpLink

    g = await group(db_session, name, set(permissions), None)
    for idp in idp_ids:
        db_session.add(GroupIdpLink(group_id=g.id, idp_group_id=idp))
    await db_session.commit()
    return g


async def _user(db_session, email):
    from app.features.user.models import User

    return (
        await db_session.exec(select(User).where(User.email == email))
    ).one_or_none()


async def test_methods_and_disabled(client, monkeypatch):
    resp = await client.get("/api/v1/auth/methods")
    assert resp.json() == {"oidc_enabled": False, "oidc_label": "Microsoft"}
    resp = await client.get("/api/v1/auth/oidc/start")
    assert resp.status_code == 303 and _error(resp) == "auth.oidc.disabled"


async def test_first_sign_in_creates_the_account_in_its_groups(
    client, db_session, provider
):
    from app.features.audit.models import AuditEntry
    from app.features.auth_session.models import AuthSession

    assert (await client.get("/api/v1/auth/methods")).json()["oidc_enabled"] is True
    # No Tia'i group stands for the user's directory groups: refused.
    resp = await _sign_in(client, provider)
    assert _error(resp) == "auth.oidc.no_group"
    assert await _user(db_session, "ana@lycee.test") is None

    techs = await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    resp = await _sign_in(client, provider)
    assert resp.status_code == 303 and resp.headers["location"] == "/machines"
    assert "tiai_refresh=" in resp.headers.get("set-cookie", "")
    sent = provider.token_requests[-1]
    assert sent["grant_type"] == "authorization_code" and sent["code_verifier"]

    user = await _user(db_session, "ana@lycee.test")
    assert (user.auth_source, user.oidc_issuer, user.oidc_subject) == (
        "oidc",
        ISSUER,
        "subject-ana",
    )
    assert user.full_name == "Ana"
    session_row = (
        await db_session.exec(select(AuthSession).where(AuthSession.user_id == user.id))
    ).one()
    assert session_row.auth_method == "oidc"
    entry = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "user.directory_provisioned")
        )
    ).one()
    assert entry.details["groups"] == ["Techniciens annuaire"]

    # The session works: the refresh cookie buys an access token.
    refresh = resp.cookies.get("tiai_refresh")
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh", headers={"Cookie": f"tiai_refresh={refresh}"}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    me = (
        await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
    ).json()
    assert me["auth_source"] == "oidc"
    assert [g["id"] for g in me["groups"]] == [str(techs.id)]


async def test_groups_follow_the_directory_and_keep_manual_ones(
    client, db_session, provider
):
    from app.features.user.models import UserGroup

    techs = await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    others = await _map(db_session, "Autres", [GROUP_OTHER])
    manual = await group(db_session, "À la main", {"room:read"}, None)
    await _sign_in(client, provider)
    user_id = (await _user(db_session, "ana@lycee.test")).id
    db_session.add(UserGroup(user_id=user_id, group_id=manual.id))
    await db_session.commit()

    provider.claims = {"groups": [GROUP_OTHER]}
    resp = await _sign_in(client, provider)
    assert resp.headers["location"] == "/machines"
    held = set(
        (
            await db_session.exec(
                select(UserGroup.group_id).where(UserGroup.user_id == user_id)
            )
        ).all()
    )
    assert held == {others.id, manual.id}

    # Out of every mapped group: refused, and the mapped ones taken away.
    provider.claims = {"groups": []}
    resp = await _sign_in(client, provider)
    assert _error(resp) == "auth.oidc.no_group"
    held = set(
        (
            await db_session.exec(
                select(UserGroup.group_id).where(UserGroup.user_id == user_id)
            )
        ).all()
    )
    assert held == {manual.id}
    assert techs.id not in held


async def test_identity_checks(client, db_session, provider):
    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])

    # A state used once, or brought back by another browser, opens nothing.
    state, browser = await _start(client, provider)
    assert (
        _error(await _callback(client, state, "another-browser")) == "auth.oidc.invalid"
    )
    state, browser = await _start(client, provider)
    assert _error(await _callback(client, state, browser)) is None
    assert _error(await _callback(client, state, browser)) == "auth.oidc.invalid"

    for bad in (
        {"aud": "another-client"},
        {"iss": "https://login.test/another-tenant/v2.0"},
        {"exp": int(time.time()) - 3600},
        {"nonce": "not-this-one"},
    ):
        provider.claims = bad
        state, browser = await _start(client, provider)
        resp = await _callback(client, state, browser)
        assert _error(resp) == "auth.oidc.invalid", bad
    provider.claims = {}

    # Signed by a key the provider does not publish.
    real = provider.key
    provider.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = provider.id_token()
    provider.key = real
    state, browser = await _start(client, provider)
    provider_token = provider.id_token

    def forged_token(**_: Any) -> str:
        return forged

    provider.id_token = forged_token  # type: ignore[method-assign]
    assert _error(await _callback(client, state, browser)) == "auth.oidc.invalid"
    provider.id_token = provider_token  # type: ignore[method-assign]

    # Too many groups for the token: refused rather than guessed.
    provider.claims = {"groups": None, "hasgroups": True}
    state, browser = await _start(client, provider)
    assert (
        _error(await _callback(client, state, browser)) == "auth.oidc.too_many_groups"
    )


async def test_provider_down_cancelled_or_address_taken(client, db_session, provider):
    from app.features.user.permissions import BuiltinGroup

    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    resp = await client.get(
        "/api/v1/auth/oidc/callback", params={"error": "access_denied", "state": "x"}
    )
    assert _error(resp) == "auth.oidc.denied"

    await account(client, db_session, "ana@lycee.test", [BuiltinGroup.READONLY])
    resp = await _sign_in(client, provider)
    assert _error(resp) == "auth.oidc.email_taken"

    oidc_client.reset_cache()
    provider.down = True
    resp = await client.get("/api/v1/auth/oidc/start")
    assert _error(resp) == "auth.oidc.unavailable"


async def test_a_local_account_links_itself(client, db_session, provider):
    from app.features.audit.models import AuditEntry
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "bo@lycee.test", [BuiltinGroup.ADMIN])
    state, browser = await _start(client, provider, headers=headers, link=True)
    provider.claims = {"sub": "subject-bo", "groups": []}
    resp = await _callback(client, state, browser)
    assert resp.headers["location"] == "/account?linked=1"
    user = await _user(db_session, "bo@lycee.test")
    assert (user.auth_source, user.oidc_subject) == ("local", "subject-bo")
    assert (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "user.directory_linked")
        )
    ).one()

    # Signs in through the directory now, though no group is mapped: a
    # local account keeps the groups the console gave it.
    resp = await _sign_in(client, provider)
    assert resp.status_code == 303 and _error(resp) is None
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["directory_linked"] is True

    # Linking again is refused; unlinking keeps the password.
    resp = await client.post(
        "/api/v1/auth/oidc/link", headers=headers, json={"current_password": STRONG}
    )
    assert resp.status_code == 409
    resp = await client.delete("/api/v1/auth/oidc/link", headers=headers)
    assert resp.status_code == 204
    await db_session.refresh(user)
    assert user.oidc_subject is None
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "bo@lycee.test", "password": STRONG}
    )
    assert resp.status_code == 200


async def test_directory_accounts_have_no_password(client, db_session, provider):
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "ka@lycee.test", [BuiltinGroup.ADMIN])
    await _map(db_session, "Techniciens annuaire", [GROUP_TECHS])
    await _sign_in(client, provider)
    user = await _user(db_session, "ana@lycee.test")

    resp = await client.post(
        "/api/v1/auth/login", data={"username": "ana@lycee.test", "password": "!oidc"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.credentials.invalid"
    resp = await client.post(
        f"/api/v1/users/{user.id}/reset-password", headers=admin, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "user.external_account"
    resp = await client.patch(
        f"/api/v1/users/{user.id}", headers=admin, json={"email": "x@lycee.test"}
    )
    assert resp.status_code == 409
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    assert {u["email"]: u["auth_source"] for u in users}["ana@lycee.test"] == "oidc"


async def test_last_local_manager_is_kept(client, db_session):
    """An administrator of the directory cannot deactivate the console's last
    local one: the directory unreachable, nobody could get back in."""
    from app.core import security
    from app.features.auth_session import crud as auth_sessions
    from app.features.user import crud
    from app.features.user.models import User
    from app.features.user.permissions import BuiltinGroup

    await account(client, db_session, "mo@lycee.test", [BuiltinGroup.ADMIN])
    mo_id = (
        (await db_session.exec(select(User).where(User.email == "mo@lycee.test")))
        .one()
        .id
    )
    directory_admin = User(
        email="dir-admin@lycee.test",
        hashed_password="!oidc",
        auth_source="oidc",
        oidc_issuer=ISSUER,
        oidc_subject="dir-admin",
    )
    db_session.add(directory_admin)
    await db_session.flush()
    admin_group = await crud.builtin_group(db_session, BuiltinGroup.ADMIN)
    await crud.set_user_groups(db_session, directory_admin, [admin_group.id])
    row, _ = await auth_sessions.open_session(
        db_session, directory_admin.id, user_agent=None, ip=None, auth_method="oidc"
    )
    token = security.create_access_token(directory_admin.id, session_id=row.id)
    await db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}

    assert await crud.users_holding(db_session, "user:write") == 2
    assert await crud.users_holding(db_session, "user:write", local_only=True) == 1
    resp = await client.patch(
        f"/api/v1/users/{mo_id}", headers=headers, json={"is_active": False}
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "user.lockout"


async def test_group_links_through_the_api(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "na@lycee.test", [BuiltinGroup.ADMIN])
    resp = await client.post(
        "/api/v1/groups",
        headers=admin,
        json={
            "name": "Techs annuaire",
            "permissions": ["machine:read"],
            "idp_groups": [GROUP_TECHS.upper(), GROUP_TECHS],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["idp_groups"] == [GROUP_TECHS]
    gid = resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/groups/{gid}", headers=admin, json={"idp_groups": ["bad id;"]}
    )
    assert resp.status_code == 422
    resp = await client.patch(
        f"/api/v1/groups/{gid}", headers=admin, json={"idp_groups": []}
    )
    assert resp.json()["idp_groups"] == []

    # Linking a directory group is a grant: refused to whoever lacks the
    # group's rights.
    managers = await group(
        db_session, "Gestion comptes", {"user:read", "user:write"}, None
    )
    manager = await account(client, db_session, "ol@lycee.test", [managers.id])
    resp = await client.get("/api/v1/groups", headers=admin)
    admin_group = (
        next(g for g in resp.json() if g["builtin_key"] == "admin")
        if isinstance(resp.json(), list)
        else next(g for g in resp.json()["items"] if g["builtin_key"] == "admin")
    )
    resp = await client.patch(
        f"/api/v1/groups/{admin_group['id']}",
        headers=manager,
        json={"idp_groups": [GROUP_OTHER]},
    )
    assert resp.status_code == 403
