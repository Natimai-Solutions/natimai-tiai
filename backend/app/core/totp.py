"""Time-based one-time passwords (RFC 6238), and the backup codes beside them.

Twenty lines of ``hmac`` rather than a dependency: the algorithm is fixed by
the RFC, its test vectors pin it (``tests/test_totp.py``), and the
parameters are the ones every authenticator app reads — SHA-1, six digits,
thirty-second steps — so nothing here needs a knob.

The secret is stored encrypted (``secretbox`` under its own label and, when
``TOTP_ENCRYPTION_KEY`` is set, its own key): a copy of the database alone
does not let anyone compute the codes.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30
# Steps accepted either side of now: thirty seconds of clock skew or of a
# code typed as it changes. More widens the guessing window for nothing.
WINDOW = 1
# 160 bits, the RFC 4226 recommendation for HMAC-SHA1.
SECRET_BYTES = 20

BACKUP_CODE_COUNT = 10
BACKUP_CODE_LENGTH = 10
# No 0/O, 1/I/L: a code is copied from paper.
_BACKUP_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_secret() -> str:
    """A fresh secret, base32 without padding — what authenticator apps take."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    text = secret.strip().replace(" ", "").upper()
    return base64.b32decode(text + "=" * (-len(text) % 8))


def code_at(secret: str, step: int, digits: int = DIGITS) -> str:
    """The code for one time step (RFC 4226 HOTP over the step counter)."""
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def matching_step(
    secret: str, code: str, now: float | None = None, after: int | None = None
) -> int | None:
    """The step ``code`` belongs to within the window, or None.

    ``after`` is the last step already accepted for this secret: a code of
    that step or an earlier one is refused, so a code seen over a shoulder
    is not good twice. Compared in constant time.
    """
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    here = current_step(now)
    found = None
    for step in range(here - WINDOW, here + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step), code) and found is None:
            found = step
    if found is None or (after is not None and found <= after):
        return None
    return found


def otpauth_uri(secret: str, account: str, issuer: str) -> str:
    """The ``otpauth://`` URI an authenticator app reads from the QR code."""
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


def new_backup_codes() -> list[str]:
    """Ten single-use codes, shown once, written « XXXXX-XXXXX »."""
    codes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = "".join(
            secrets.choice(_BACKUP_ALPHABET) for _ in range(BACKUP_CODE_LENGTH)
        )
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalise_backup_code(code: str) -> str | None:
    """A typed backup code reduced to its characters, or None when it cannot
    be one (wrong length, characters outside the alphabet)."""
    text = code.strip().upper().replace("-", "").replace(" ", "")
    if len(text) != BACKUP_CODE_LENGTH or any(c not in _BACKUP_ALPHABET for c in text):
        return None
    return text


def hash_backup_code(normalised: str) -> str:
    """Stored as a hash: shown once, never read back. 50 bits of entropy
    each and single use, so a plain SHA-256 is enough — and survives a
    change of key."""
    return hashlib.sha256(normalised.encode()).hexdigest()
