import uuid

from app.core import security


def test_agent_token_hash_roundtrip():
    """A generated agent token verifies against its stored hash."""
    token = security.generate_token()
    token_hash = security.hash_token(token)
    assert security.verify_token(token, token_hash)
    assert not security.verify_token("some-other-token", token_hash)


def test_agent_token_is_random():
    """Two generated tokens differ."""
    assert security.generate_token() != security.generate_token()


def test_password_hash_roundtrip():
    """A bcrypt-hashed password verifies, a wrong one does not."""
    hashed = security.get_password_hash("s3cret-passw0rd")
    assert security.verify_password("s3cret-passw0rd", hashed)
    assert not security.verify_password("wrong", hashed)


# Produced by the stack this module used before bcrypt replaced passlib
# (passlib 1.7.4 + bcrypt 4.0.1, CryptContext(schemes=["bcrypt"])). Stored
# password hashes outlive the library that wrote them, so the switch is only
# safe as long as these keep verifying.
_PASSLIB_HASH = "$2b$12$DLtzwoSJpYogq6JBHHhEO.8X98CQQtAHOhfl.jVoqB3y670wo7fqm"
_PASSLIB_HASH_LONG = "$2b$12$jkglKUtt0ohLyCwzkO802e1UleYAZ92Up9NGpd559RNbRdm.p/rF6"


def test_password_hash_from_passlib_still_verifies():
    """A hash written by the previous passlib-based implementation verifies."""
    assert security.verify_password("s3cret-passw0rd", _PASSLIB_HASH)
    assert not security.verify_password("wrong", _PASSLIB_HASH)


def test_password_over_72_bytes_matches_passlib_truncation():
    """Passwords past bcrypt's 72-byte limit are cut, not rejected.

    passlib truncated silently; anything else locks out the accounts whose
    password is longer than that.
    """
    assert security.verify_password("x" * 100, _PASSLIB_HASH_LONG)
    # Same first 72 bytes, different tail: bcrypt cannot tell them apart.
    assert security.verify_password("x" * 72 + "different", _PASSLIB_HASH_LONG)
    assert not security.verify_password("x" * 71, _PASSLIB_HASH_LONG)
    # And hashing one does not raise, which the raw bcrypt API would.
    assert security.verify_password("y" * 100, security.get_password_hash("y" * 100))


def test_verify_password_rejects_a_non_bcrypt_hash():
    """A malformed stored hash fails the login instead of raising."""
    assert not security.verify_password("s3cret-passw0rd", "not-a-bcrypt-hash")
    assert not security.verify_password("s3cret-passw0rd", "")


def test_jwt_roundtrip():
    """A created access token decodes back to its subject and its session."""
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    token = security.create_access_token(user_id, session_id=session_id)
    payload = security.decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["sid"] == str(session_id)
    assert payload["type"] == "access"


def test_access_token_lives_access_token_expire_minutes(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 15)
    payload = security.decode_access_token(
        security.create_access_token(uuid.uuid4(), session_id=uuid.uuid4())
    )
    assert payload["exp"] - payload["iat"] == 15 * 60


def test_dummy_hash_costs_what_a_real_hash_costs():
    """The unknown-account path must take as long as a real check: same
    algorithm, same cost factor as the hashes the console writes."""
    real = security.get_password_hash("whatever-password")
    assert security.DUMMY_PASSWORD_HASH[:7] == real[:7]  # "$2b$12$"
    assert not security.verify_password("", security.DUMMY_PASSWORD_HASH)


def test_refresh_token_names_its_session():
    session_id = uuid.uuid4()
    token = security.generate_refresh_token(session_id)
    assert security.refresh_token_session_id(token) == str(session_id)
    # 256 bits of secret behind the id, and a new one every time.
    assert len(token.split(".", 1)[1]) >= 43
    assert security.generate_refresh_token(session_id) != token


def test_a_malformed_refresh_token_names_no_session():
    for token in ("", "no-separator", ".secret-only", "id-only."):
        assert security.refresh_token_session_id(token) is None
