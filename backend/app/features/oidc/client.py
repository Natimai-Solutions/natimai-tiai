"""The calls to the identity provider (C7): discovery, keys, the code
exchange, and the check of the identity token.

Every call is the server's, never the browser's: the console's CSP allows it
to talk to its own origin only, and nothing of the token passes through the
page. Over ``httpx`` with a timeout and, when the school's network needs it,
``OIDC_PROXY_URL``.

The identity token is checked as the standard says, without shortcut: an
RS256 signature by a key the provider publishes, the issuer configured (one
tenant: never « common »), this console as audience, the dates with a minute
of tolerance, and the nonce of this very sign-in.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt

from app.core.config import settings

# Discovery and keys are kept an hour; a token signed by a key not in the
# cache asks for the keys again, at most once a minute (a key rotation).
CACHE_SECONDS = 3600
KEY_REFRESH_SECONDS = 60
LEEWAY_SECONDS = 60

# The transport the calls go through: replaced by the tests with a provider
# of their own (``httpx.MockTransport``).
TRANSPORT: httpx.AsyncBaseTransport | None = None


class OidcError(Exception):
    """A sign-in that cannot go on. ``code`` is what the login page words."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


# The codes the callback can end with (``/login?sso_error=<code>``).
UNAVAILABLE = "auth.oidc.unavailable"
INVALID = "auth.oidc.invalid"


def configured() -> bool:
    """Whether a sign-in through the directory can be offered at all."""
    return bool(
        settings.OIDC_ENABLED
        and settings.OIDC_ISSUER
        and settings.OIDC_CLIENT_ID
        and settings.OIDC_CLIENT_SECRET
        and redirect_uri()
    )


def issuer() -> str:
    return settings.OIDC_ISSUER.rstrip("/")


def redirect_uri() -> str | None:
    if settings.OIDC_REDIRECT_URI:
        return settings.OIDC_REDIRECT_URI
    base = settings.console_base_url
    if base is None:
        return None
    return f"{base}{settings.API_V1_STR}/auth/oidc/callback"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.OIDC_TIMEOUT_SECONDS,
        proxy=settings.OIDC_PROXY_URL if TRANSPORT is None else None,
        transport=TRANSPORT,
    )


@dataclass
class _Cache:
    discovery: dict[str, Any] | None = None
    discovery_at: float = 0.0
    keys: dict[str, Any] = field(default_factory=dict)
    keys_at: float = 0.0


_cache = _Cache()


def reset_cache() -> None:
    """Forget the provider's metadata and keys (tests, a changed issuer)."""
    global _cache
    _cache = _Cache()


async def _get_json(url: str) -> dict[str, Any]:
    try:
        async with _client() as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise OidcError(UNAVAILABLE, f"{url}: {exc}") from exc
    if resp.status_code != 200:
        raise OidcError(UNAVAILABLE, f"{url}: HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise OidcError(UNAVAILABLE, f"{url}: not JSON") from exc
    if not isinstance(data, dict):
        raise OidcError(UNAVAILABLE, f"{url}: not an object")
    return data


async def discovery() -> dict[str, Any]:
    now = time.monotonic()
    if _cache.discovery is not None and now - _cache.discovery_at < CACHE_SECONDS:
        return _cache.discovery
    data = await _get_json(f"{issuer()}/.well-known/openid-configuration")
    # The document must be the issuer's own: one that names another issuer
    # would hand its tokens to the check below.
    if str(data.get("issuer", "")).rstrip("/") != issuer():
        raise OidcError(INVALID, "discovery names another issuer")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(data.get(key), str) or not data[key].startswith("https://"):
            raise OidcError(INVALID, f"discovery: {key} missing or not https")
    _cache.discovery = data
    _cache.discovery_at = now
    return data


async def _keys(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    fresh = now - _cache.keys_at < CACHE_SECONDS
    if _cache.keys and fresh and not force:
        return _cache.keys
    if force and now - _cache.keys_at < KEY_REFRESH_SECONDS:
        return _cache.keys
    meta = await discovery()
    data = await _get_json(meta["jwks_uri"])
    keys: dict[str, Any] = {}
    for jwk in data.get("keys", []):
        if not isinstance(jwk, dict) or jwk.get("kty") != "RSA":
            continue
        if jwk.get("use") not in (None, "sig"):
            continue
        try:
            keys[str(jwk.get("kid", ""))] = jwt.PyJWK.from_dict(jwk, algorithm="RS256")
        except jwt.exceptions.PyJWKError:
            continue
    _cache.keys = keys
    _cache.keys_at = now
    return keys


def new_pkce() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


async def authorize_url(state: str, nonce: str, challenge: str) -> str:
    meta = await discovery()
    params = httpx.QueryParams(
        {
            "client_id": settings.OIDC_CLIENT_ID,
            "response_type": "code",
            "response_mode": "query",
            "redirect_uri": redirect_uri() or "",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{meta['authorization_endpoint']}?{params}"


async def exchange(code: str, verifier: str) -> str:
    """Trade the authorization code for the identity token."""
    meta = await discovery()
    try:
        async with _client() as client:
            resp = await client.post(
                meta["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri() or "",
                    "client_id": settings.OIDC_CLIENT_ID,
                    "client_secret": settings.OIDC_CLIENT_SECRET,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise OidcError(UNAVAILABLE, f"token endpoint: {exc}") from exc
    if resp.status_code >= 500:
        raise OidcError(UNAVAILABLE, f"token endpoint: HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise OidcError(INVALID, "token endpoint: not JSON") from exc
    token = data.get("id_token") if isinstance(data, dict) else None
    if resp.status_code != 200 or not isinstance(token, str):
        raise OidcError(
            INVALID, f"token endpoint: HTTP {resp.status_code}, no id_token"
        )
    return token


async def verify(id_token: str, nonce: str) -> dict[str, Any]:
    """The identity token's claims, once every check has passed."""
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.exceptions.InvalidTokenError as exc:
        raise OidcError(INVALID, "malformed identity token") from exc
    if header.get("alg") != "RS256":
        raise OidcError(INVALID, f"algorithm {header.get('alg')!r} refused")
    kid = str(header.get("kid", ""))
    keys = await _keys()
    if kid not in keys:
        keys = await _keys(force=True)
    key = keys.get(kid)
    if key is None:
        raise OidcError(INVALID, "unknown signing key")
    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=settings.OIDC_CLIENT_ID,
            issuer=issuer(),
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.exceptions.InvalidTokenError as exc:
        raise OidcError(INVALID, f"identity token refused: {exc}") from exc
    # pyjwt compares the issuer exactly; the configured one may carry a
    # trailing slash the token does not, which the comparison above handles
    # by stripping it from ours — a token whose issuer has one is refused.
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError(INVALID, "nonce mismatch")
    return claims
