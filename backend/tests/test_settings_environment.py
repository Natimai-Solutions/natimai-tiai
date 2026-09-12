"""The environment overview on the page Paramètres.

Two properties, one of which is the whole reason the module exists: it names
what an administrator needs, and it never prints a secret.
"""

import pytest

from app.core.config import Settings
from app.features.setting.environment import environment_overview, never_shown


def _items(env: Settings | None = None):
    groups = environment_overview(env) if env else environment_overview()
    return [item for group in groups for item in group.items]


def test_no_secret_is_ever_listed():
    assert never_shown() & {item.key for item in _items()} == set()


def test_no_secret_value_leaks_through_a_rendered_field():
    env = Settings(
        SECRET_KEY="the-signing-key-0123456789",
        ENROLLMENT_SECRET="the-enrollment-secret-0123",
        POSTGRES_PASSWORD="db-pass-word-xyz",
        MAILGUN_API_KEY="key-mailgun-abcdef",
        SMTP_PASSWORD="smtp-pass-word",
        SMTP_USER="smtp-user@example",
        FIRST_ADMIN_PASSWORD="first-admin-password",
        EMAIL_PROVIDER="smtp",
        SMTP_HOST="smtp.example.test",
        EMAIL_FROM_EMAIL="tiai@example.test",
    )
    rendered = " ".join(f"{i.key} {i.value or ''} {i.description}" for i in _items(env))
    for secret in (
        "the-signing-key",
        "the-enrollment-secret",
        "db-pass-word",
        "key-mailgun",
        "smtp-pass-word",
        "smtp-user@",
        "first-admin-password",
    ):
        assert secret not in rendered


def test_every_item_names_a_real_variable_or_a_documented_alias():
    """Keys are what the reader will grep for in ``.env`` — they must exist."""
    fields = set(Settings.model_fields)
    for item in _items():
        assert item.key in fields, item.key
        assert item.description


@pytest.mark.parametrize("provider", ["mailgun", "smtp"])
def test_only_the_chosen_mail_provider_is_listed(provider):
    env = Settings(EMAIL_PROVIDER=provider)
    keys = {i.key for i in _items(env)}
    if provider == "smtp":
        assert "SMTP_HOST" in keys and "MAILGUN_DOMAIN" not in keys
    else:
        assert "MAILGUN_DOMAIN" in keys and "SMTP_HOST" not in keys
    # The provider line says whether mail can leave at all.
    line = next(i for i in _items(env) if i.key == "EMAIL_PROVIDER")
    assert line.value is not None and "aucun e-mail" in line.value


def test_values_are_rendered_for_a_reader():
    env = Settings(
        WOL_RELAY_ENABLED=True,
        WOL_BROADCAST_ADDRESSES="10.0.0.255, 10.0.1.255",
        MAINTENANCE_REMINDER_WEEKDAY=4,
        AGENT_EXPECTED_VERSION=None,
    )
    by_key = {i.key: i.value for i in _items(env)}
    assert by_key["WOL_RELAY_ENABLED"] == "oui"
    assert by_key["WOL_BROADCAST_ADDRESSES"] == "10.0.0.255, 10.0.1.255"
    assert by_key["MAINTENANCE_REMINDER_WEEKDAY"] == "4 (vendredi)"
    assert by_key["AGENT_EXPECTED_VERSION"] is None
