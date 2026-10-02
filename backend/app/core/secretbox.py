"""Encryption of the few secrets the console stores in its own database.

The mail credentials an administrator types on the page Paramètres (an SMTP
password, a Mailgun API key) live in ``app_settings`` next to everything else.
Stored in clear, they would leave with every database dump, every backup
copied to a USB key, every ``SELECT *`` run while debugging; encrypted, a dump
alone is not enough — the key stays in ``deploy/.env``.

Fernet (AES-128-CBC + HMAC-SHA256, authenticated) with a key *derived* from
``SECRET_KEY`` by HKDF-SHA256, under an ``info`` label naming this one use.
Never ``SECRET_KEY`` itself: that value signs the console's JWTs, and one key
serving two algorithms is one key whose misuse in either breaks both. The
label also means any later use of ``SECRET_KEY`` derives an unrelated key.

The trade-off is stated in DEPLOYMENT.md: changing ``SECRET_KEY`` makes every
stored secret unreadable. ``decrypt`` then answers ``None`` instead of raising —
a mail setting that cannot be read is a mail setting to type again, never a
console that fails to start or a worker that crashes on every tick.
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

# Versioned, so a future change of scheme can derive a fresh key without
# colliding with this one.
_INFO = b"tiai:app-settings-secrets:v1"


@lru_cache(maxsize=4)
def _fernet(secret_key: str) -> Fernet:
    # Cached per key value rather than once: the key is read off ``settings``
    # at every call, so a test (or a process reloaded with another key) gets
    # the key that is current, not the one the first call happened to see.
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_INFO,
    ).derive(secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` under the current ``SECRET_KEY``; a printable token."""
    return _fernet(settings.SECRET_KEY).encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str | None:
    """The plaintext behind ``token``, or ``None`` when it cannot be read.

    ``None`` covers a token sealed under another ``SECRET_KEY``, a corrupted
    value and anything that is not a token at all: the caller treats all three
    as « no secret stored », which is what they are in practice.
    """
    try:
        return _fernet(settings.SECRET_KEY).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError, AttributeError):
        return None
