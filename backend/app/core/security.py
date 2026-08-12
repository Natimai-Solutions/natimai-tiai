"""Per-machine token generation and verification.

Only the SHA-256 hash of a token is stored server-side; the clear token is
returned to the agent exactly once at enrollment.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def get_password_hash(password: str) -> str:
    """Hash a plaintext password (bcrypt)."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def generate_password() -> str:
    """Generate a random password for an admin-driven reset (shown once)."""
    return secrets.token_urlsafe(_PASSWORD_BYTES)


def create_access_token(subject: str | Any) -> str:
    """Create a signed JWT access token for a user id.

    ``iat`` is included so a password change can invalidate tokens issued
    before it (see ``app.api.deps.get_current_user``).
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"exp": expire, "iat": now, "sub": str(subject), "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT access token (raises on invalid/expired)."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
