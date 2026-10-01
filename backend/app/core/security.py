"""Tokens and passwords: per-machine agent tokens, console passwords, and the
two tokens of a console session (access JWT, refresh token).

Only the SHA-256 hash of a random token is ever stored server-side — agent
token, refresh token, reset link alike; the clear value leaves the server once.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

_TOKEN_BYTES = 32
# Entropy of a generated console password: ~128 bits, still copy-pasteable.
_PASSWORD_BYTES = 16

# --- Agent tokens (per-machine, stored hashed) -----------------------------


def generate_token() -> str:
    """Generate a strong random per-machine token (URL-safe)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the hex SHA-256 hash of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    """Constant-time comparison of a token against a stored hash."""
    return hmac.compare_digest(hash_token(token), token_hash)


# --- Console users (password + JWT) ----------------------------------------

ALGORITHM = "HS256"
# The only ``type`` an access token may carry. Checked on every request: a JWT
# signed with the same key for any other purpose must not open the API.
ACCESS_TOKEN_TYPE = "access"

# bcrypt only ever reads the first 72 bytes of a password. passlib, which this
# module used to go through, cut the rest off silently; the `bcrypt` API raises
# instead. The cut therefore stays here, or every account whose password is
# longer than that would stop verifying against the hash stored before the
# switch. Bytes, not characters: bcrypt works on the UTF-8 encoding, and a cut
# landing mid-codepoint is harmless because the value is never decoded back.
_BCRYPT_MAX_BYTES = 72


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def get_password_hash(password: str) -> str:
    """Hash a plaintext password (bcrypt, 12 rounds)."""
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("ascii")


# What a login is checked against when there is no account to check it
# against — an unknown address, a deactivated account. Without it the login
# route answered such attempts in a millisecond and real accounts in the
# ~250 ms bcrypt takes: the response time alone told an attacker which
# addresses have a console account, the very thing the identical 401 hides.
#
# A constant rather than computed at import: hashing costs as much as
# verifying, and every process start (worker, migrations, each test run) would
# pay for it. The hash of 32 random bytes nobody kept, so no password matches
# it; its cost factor (``$12$``) must stay that of ``bcrypt.gensalt()``, or the
# two paths would differ again — a test holds it to that.
DUMMY_PASSWORD_HASH = "$2b$12$VeROjPwxlTxmvn05xf0aIuf4bALbEADDruCmkXF6X2xjmTRdNW7Ha"


def burn_password_check(plain_password: str) -> None:
    """Spend the time of a password check whose answer is already "no"."""
    verify_password(plain_password, DUMMY_PASSWORD_HASH)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(
            _password_bytes(plain_password), hashed_password.encode("utf-8")
        )
    except ValueError:
        # Row holds something that isn't a bcrypt hash (truncated column, hand-
        # edited value). That is a failed login, not a 500 on the login route.
        return False


def generate_password() -> str:
    """Generate a random password for an admin-driven reset (shown once)."""
    return secrets.token_urlsafe(_PASSWORD_BYTES)


def create_access_token(subject: str | Any, *, session_id: str | Any) -> str:
    """Create a signed JWT access token for a user, bound to one session.

    ``sid`` names the ``auth_sessions`` row the token belongs to: every request
    checks that row (``app.api.deps.get_current_user``), which is what makes a
    logout or a revocation take effect at once rather than at expiry. ``type``
    keeps the token from being mistaken for any other JWT signed with the same
    key. ``iat`` lets a password change refuse tokens issued before it.
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "sid": str(session_id),
        "type": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT access token (raises on invalid/expired)."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


# --- Console refresh tokens ---------------------------------------------------

# The refresh token reads ``<session id>.<secret>``. The id is not a secret —
# the console lists it with the account's sessions — but carrying it is what
# lets the server tell a *stale* token from a forged one: a token naming a
# live session with a secret that is no longer that session's is a token that
# was rotated away, presented again, i.e. a copy someone else holds.
_REFRESH_SEPARATOR = "."


def generate_refresh_token(session_id: str | Any) -> str:
    """A new refresh token for a session (256 bits of secret)."""
    return f"{session_id}{_REFRESH_SEPARATOR}{secrets.token_urlsafe(_TOKEN_BYTES)}"


def refresh_token_session_id(token: str) -> str | None:
    """The session id a refresh token names, or None if it is not one."""
    session_id, separator, secret = token.partition(_REFRESH_SEPARATOR)
    if not separator or not session_id or not secret:
        return None
    return session_id
