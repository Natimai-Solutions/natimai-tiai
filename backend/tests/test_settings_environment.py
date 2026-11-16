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


@pytest.mark.parametrize("provider", ["mailgun", "smtp"])
def test_mail_variables_say_the_console_overrides_them(provider):
    """Like the thresholds: the page must not present a value the console
    may have replaced as the one mail leaves with."""
    env = Settings(EMAIL_PROVIDER=provider)
    mail_keys = {
        i.key: i.description
        for group in environment_overview(env)
        if group.label == "E-mails"
        for i in group.items
        if i.key.startswith(("EMAIL_", "SMTP_", "MAILGUN_"))
        # The outbox's retention and attempts are the server's housekeeping,
        # Mailgun's timeout and proxy its network: not the mail account, and
        # the console does not override them.
        and i.key
        not in {
            "EMAIL_OUTBOX_RETENTION_DAYS",
            "EMAIL_MAX_ATTEMPTS",
            "MAILGUN_TIMEOUT_SECONDS",
            "MAILGUN_PROXY_URL",
        }
    }
    assert "EMAIL_PROVIDER" in mail_keys and len(mail_keys) >= 5
    for key, description in mail_keys.items():
        assert "valeur initiale" in description, key


def test_the_settings_of_the_audit_are_listed():
    """The variables introduced since the page was written: an administrator
    who reads a 429 or a partial inventory must find what decides it."""
    keys = {i.key for i in _items()}
    assert {
        "LOGIN_SIEGE_ADDRESSES",
        "LOGIN_KNOWN_ADDRESS_DAYS",
        "PASSWORD_RESET_COOLDOWN_MINUTES",
        "PASSWORD_RESET_MAX_LIVE_LINKS",
        "AGENT_HEARTBEAT_MAX_PER_MINUTE",
        "SOFTWARE_NEW_ENTRIES_PER_DAY",
        "SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET",
        "COMMAND_UNANSWERED_HOURS",
        "TRUSTED_PROXIES",
        "TRUSTED_PROXIES_ALLOW_WIDE",
        "TRUSTED_PROXY_HOSTS",
        "EXPOSE_OPENAPI",
        "LOGIN_SLOW_MAX_FAILED_ATTEMPTS",
        "LOGIN_SLOW_WINDOW_HOURS",
        "PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS",
        "WOL_ALLOWED_NETWORKS",
        "WOL_RELAY_MIN_AGE_MINUTES",
        "WOL_RELAY_MIN_AGENT_VERSION",
        "WOL_RELAY_CLAIM_TIMEOUT_SECONDS",
    } <= keys
    # Each variable once.
    assert len(keys) == len(_items())


def test_the_rate_limit_switch_says_all_it_switches_off():
    """It also lifts the heartbeat cap and the password-change limiter — and
    neither the account lock nor the software catalogue budget."""
    by_key = {i.key: i.description for i in _items()}
    text = by_key["RATE_LIMIT_ENABLED"]
    assert "battements" in text and "changement de mot de passe" in text
    assert "verrouillage" in text and "catalogue logiciel" in text
    assert "n'en dépendent" in text
    # The lock counts failures close to one another, not consecutive ones.
    assert "consécutifs" not in by_key["LOGIN_MAX_FAILED_ATTEMPTS"]
    assert "LOGIN_LOCKOUT_MINUTES" in by_key["LOGIN_MAX_FAILED_ATTEMPTS"]


def test_the_new_values_are_rendered():
    env = Settings(
        WOL_ALLOWED_NETWORKS="10.4.0.0/16,10.5.0.0/16",
        TRUSTED_PROXIES="172.18.0.0/16",
        # A /16 is refused at start without it (audit S28).
        TRUSTED_PROXIES_ALLOW_WIDE=True,
        EXPOSE_OPENAPI=False,
    )
    by_key = {i.key: i.value for i in _items(env)}
    assert by_key["WOL_ALLOWED_NETWORKS"] == "10.4.0.0/16, 10.5.0.0/16"
    assert by_key["TRUSTED_PROXIES"] == "172.18.0.0/16"
    assert by_key["TRUSTED_PROXIES_ALLOW_WIDE"] == "oui"
    assert by_key["TRUSTED_PROXY_HOSTS"] == "caddy"
    assert by_key["EXPOSE_OPENAPI"] == "non"
    assert by_key["SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET"] == "50000"


def test_the_server_settings_name_what_was_missing():
    """Acceptance, 2026-11: the packages, the outbox's attempts, the database
    pool, Mailgun's timeout and proxy and the server name are listed."""
    env = Settings(
        EMAIL_PROVIDER="mailgun",
        TIAI_SERVER_NAME="tiai.lycee.pf",
        PACKAGE_MAX_BYTES=2 * 1024**3,
    )
    by_key = {i.key: i.value for i in _items(env)}
    for key in (
        "PACKAGE_MAX_BYTES",
        "PACKAGE_METHOD_A_MAX_GB",
        "PACKAGES_DIR",
        "EMAIL_MAX_ATTEMPTS",
        "POSTGRES_POOL_SIZE",
        "POSTGRES_MAX_OVERFLOW",
        "POSTGRES_POOL_TIMEOUT",
        "MAILGUN_TIMEOUT_SECONDS",
        "MAILGUN_PROXY_URL",
        "TIAI_SERVER_NAME",
    ):
        assert key in by_key, key
    assert by_key["PACKAGE_MAX_BYTES"] == "2147483648 (2 Gio)"
    assert by_key["TIAI_SERVER_NAME"] == "tiai.lycee.pf"
    assert by_key["MAILGUN_PROXY_URL"] is None


@pytest.mark.parametrize(
    "url,shown",
    [
        ("http://proxy.lycee.pf:3128", "proxy.lycee.pf:3128"),
        ("http://jdupont:s3cr3t-pass@10.0.0.1:3128", "10.0.0.1:3128"),
        ("https://user@proxy.example", "proxy.example"),
        ("http://[::1", "défini (illisible)"),
    ],
)
def test_the_mailgun_proxy_shows_its_host_never_its_credentials(url, shown):
    env = Settings(EMAIL_PROVIDER="mailgun", MAILGUN_PROXY_URL=url)
    rendered = " ".join(f"{i.key} {i.value or ''} {i.description}" for i in _items(env))
    assert {i.key: i.value for i in _items(env)}["MAILGUN_PROXY_URL"] == shown
    for secret in ("jdupont", "s3cr3t-pass", "user@"):
        assert secret not in rendered
