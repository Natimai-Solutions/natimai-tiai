"""Encryption of the secrets the console stores (no database needed)."""

import base64

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core import secretbox
from app.core.config import settings


def test_round_trip_and_a_fresh_token_each_time():
    first = secretbox.encrypt("mot-de-passe-smtp")
    second = secretbox.encrypt("mot-de-passe-smtp")
    # A random IV per token: two equal passwords do not read as equal rows.
    assert first != second
    assert "mot-de-passe-smtp" not in first
    assert secretbox.decrypt(first) == "mot-de-passe-smtp"
    assert secretbox.decrypt(second) == "mot-de-passe-smtp"


def test_unicode_survives():
    assert secretbox.decrypt(secretbox.encrypt("pässwörd — 東京")) == "pässwörd — 東京"


def test_a_changed_secret_key_reads_as_absent_instead_of_raising(monkeypatch):
    token = secretbox.encrypt("s3cret")
    monkeypatch.setattr(
        settings, "SECRET_KEY", "another-secret-key-entirely-0123456789"
    )
    assert secretbox.decrypt(token) is None
    # And the new key works on its own tokens.
    assert secretbox.decrypt(secretbox.encrypt("autre")) == "autre"


def test_corrupted_and_foreign_values_read_as_absent():
    token = secretbox.encrypt("s3cret")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert secretbox.decrypt(tampered) is None
    assert secretbox.decrypt("") is None
    assert secretbox.decrypt("pas un jeton") is None
    assert secretbox.decrypt("é" * 40) is None


def test_the_key_is_derived_never_the_jwt_key_itself():
    """A token must not open with a key built straight from SECRET_KEY: the
    signing key and the storage key are two keys, derived apart."""
    raw = settings.SECRET_KEY.encode()[:32].ljust(32, b"\0")
    naive = Fernet(base64.urlsafe_b64encode(raw))
    token = secretbox.encrypt("s3cret")
    assert secretbox.decrypt(token) == "s3cret"
    with pytest.raises(InvalidToken):
        naive.decrypt(token.encode())
