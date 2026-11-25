"""TOTP against RFC 6238's test vectors, the window, replay, backup codes."""

import base64

from app.core import totp

# RFC 6238 appendix B, SHA-1 seed « 12345678901234567890 », 8 digits.
SEED = base64.b32encode(b"12345678901234567890").decode()
VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


def test_rfc6238_vectors():
    for at, expected in VECTORS:
        assert totp.code_at(SEED, int(at // 30), digits=8) == expected


def test_window_and_replay():
    at = 1111111111.0
    step = totp.current_step(at)
    code = totp.code_at(SEED, step)
    assert totp.matching_step(SEED, code, at) == step
    # The previous and the next step are accepted, two steps away is not.
    assert totp.matching_step(SEED, totp.code_at(SEED, step - 1), at) == step - 1
    assert totp.matching_step(SEED, totp.code_at(SEED, step + 1), at) == step + 1
    assert totp.matching_step(SEED, totp.code_at(SEED, step - 2), at) is None
    # A step already accepted, or an earlier one, is refused.
    assert totp.matching_step(SEED, code, at, after=step) is None
    assert totp.matching_step(SEED, totp.code_at(SEED, step + 1), at, after=step) == (
        step + 1
    )
    # Not six digits: never a match.
    for bad in ("", "12345", "1234567", "abcdef", "12 34 5"):
        assert totp.matching_step(SEED, bad, at) is None
    assert totp.matching_step(SEED, f" {code[:3]} {code[3:]} ", at) == step


def test_secret_and_uri():
    secret = totp.new_secret()
    assert len(secret) == 32 and "=" not in secret
    uri = totp.otpauth_uri(secret, "a@b.c", "Tia'i")
    assert uri.startswith("otpauth://totp/Tia%27i%3Aa%40b.c?secret=")
    assert "issuer=Tia%27i" in uri and "digits=6" in uri and "period=30" in uri


def test_backup_codes():
    codes = totp.new_backup_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    for code in codes:
        assert len(code) == 11 and code[5] == "-"
        norm = totp.normalise_backup_code(code.lower().replace("-", " "))
        assert norm == code.replace("-", "")
        assert len(totp.hash_backup_code(norm)) == 64
    assert totp.normalise_backup_code("ABCDE-FGHI0") is None  # 0 not in alphabet
    assert totp.normalise_backup_code("123456") is None
