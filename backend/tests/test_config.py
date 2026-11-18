"""Settings guard: placeholder secrets must not reach staging/production."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

# Every secret set to a real value — the baseline that must boot in production.
PROD_OK: dict[str, Any] = {
    "ENVIRONMENT": "production",
    "SECRET_KEY": "a-real-secret-key-of-at-least-32-chars",
    "ENROLLMENT_SECRET": "a-real-enrollment-secret",
    "POSTGRES_PASSWORD": "a-real-db-password",
}


def make_settings(**overrides: Any) -> Settings:
    """Build Settings without reading any .env file."""
    return Settings(_env_file=None, **{**PROD_OK, **overrides})


def test_production_boots_with_real_secrets():
    """All secrets set → no error."""
    settings = make_settings()
    assert settings.ENVIRONMENT == "production"


def test_local_tolerates_placeholders():
    """Local dev keeps working with code defaults (unit tests, no .env)."""
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="local",
        SECRET_KEY="changeme",
        ENROLLMENT_SECRET="changeme-enrollment-secret",
        POSTGRES_PASSWORD="",
    )
    assert settings.SECRET_KEY == "changeme"


@pytest.mark.parametrize(
    "field,value",
    [
        ("SECRET_KEY", "changeme"),
        ("SECRET_KEY", ""),
        ("ENROLLMENT_SECRET", "changeme-shared-enrollment-secret"),
        ("POSTGRES_PASSWORD", ""),
        ("POSTGRES_PASSWORD", "changeme-strong-password"),
        ("FIRST_ADMIN_PASSWORD", "changeme-strong-admin-password"),
    ],
)
def test_production_refuses_placeholder(field: str, value: str):
    """Any empty/'changeme' secret aborts startup outside local."""
    with pytest.raises(ValidationError, match=field):
        make_settings(**{field: value})


def test_staging_is_guarded_too():
    """The guard covers every non-local environment."""
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make_settings(ENVIRONMENT="staging", SECRET_KEY="changeme")


def test_production_refuses_a_short_first_admin_password():
    """Audit S33: the first administrator follows PASSWORD_MIN_LENGTH too."""
    with pytest.raises(ValidationError, match="FIRST_ADMIN_PASSWORD must be at least"):
        make_settings(FIRST_ADMIN_PASSWORD="admin2026")
    make_settings(FIRST_ADMIN_PASSWORD="a-long-enough-admin-password")


def test_unset_first_admin_password_is_allowed():
    """FIRST_ADMIN_PASSWORD is optional — None must not trip the guard."""
    settings = make_settings(FIRST_ADMIN_PASSWORD=None)
    assert settings.FIRST_ADMIN_PASSWORD is None


def test_usage_thresholds_must_hold_together():
    """The environment is checked like a PATCH on /settings would be."""
    make_settings(USAGE_WINDOW_DAYS=7, USAGE_LOW_HOURS=0, USAGE_HIGH_HOURS=168)
    with pytest.raises(ValidationError, match="below USAGE_HIGH_HOURS"):
        make_settings(USAGE_LOW_HOURS=30, USAGE_HIGH_HOURS=30)
    with pytest.raises(ValidationError, match="exceeds"):
        make_settings(USAGE_WINDOW_DAYS=7, USAGE_HIGH_HOURS=200)
    with pytest.raises(ValidationError):
        make_settings(USAGE_HIGH_HOURS=0)


# --- Console URL -------------------------------------------------------------


def _settings(**overrides):
    from app.core.config import Settings

    return Settings(_env_file=None, **overrides)


def test_console_url_is_derived_from_the_server_name():
    assert _settings(TIAI_SERVER_NAME="tiai.lycee.pf").console_base_url == (
        "https://tiai.lycee.pf"
    )


def test_explicit_console_url_wins_and_loses_its_trailing_slash():
    s = _settings(
        TIAI_SERVER_NAME="tiai.lycee.pf", CONSOLE_BASE_URL="https://x.y:8443/"
    )
    assert s.console_base_url == "https://x.y:8443"


def test_console_url_is_none_when_nothing_names_the_server():
    assert _settings().console_base_url is None
    assert _settings(CONSOLE_BASE_URL="").console_base_url is None


def test_production_is_the_default(monkeypatch: pytest.MonkeyPatch):
    """A deploy .env that forgets ENVIRONMENT still gets the guard."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    overrides = {k: v for k, v in PROD_OK.items() if k != "ENVIRONMENT"}
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, **{**overrides, "SECRET_KEY": "changeme"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("SECRET_KEY", "secret"),
        ("SECRET_KEY", "x" * 31),
        ("ENROLLMENT_SECRET", "short-secret"),
    ],
)
def test_production_refuses_short_secrets(field: str, value: str):
    """A secret that is no placeholder but too short aborts startup too."""
    with pytest.raises(ValidationError, match=f"{field} must be at least"):
        make_settings(**{field: value})


async def test_superuser_role_is_refused_outside_local(engine, monkeypatch):
    """A superuser role is tolerated in local and refused in production; the
    application role passes in both. The suite runs as either (CI's postgres
    service user is a superuser), so the expectation follows the role."""
    from sqlalchemy import text

    from app.core.config import settings
    from app.core.db import assert_not_superuser

    async with engine.connect() as conn:
        is_super = (
            await conn.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar_one()

    await assert_not_superuser(engine)  # local: always tolerated
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    if is_super:
        with pytest.raises(RuntimeError, match="superuser"):
            await assert_not_superuser(engine)
    else:
        await assert_not_superuser(engine)


TUNABLES = {
    "LOGIN_SIEGE_ADDRESSES": (10, 1, 1001),
    "LOGIN_KNOWN_ADDRESS_DAYS": (30, 0, 366),
    "PASSWORD_RESET_COOLDOWN_MINUTES": (5, -1, 61),
    "PASSWORD_RESET_MAX_LIVE_LINKS": (3, 0, 11),
    "AGENT_HEARTBEAT_MAX_PER_MINUTE": (12, 1, 601),
    "SOFTWARE_NEW_ENTRIES_PER_DAY": (2000, 99, 1_000_001),
    "SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET": (50_000, 999, 10_000_001),
}


@pytest.mark.parametrize("name", sorted(TUNABLES))
def test_the_audit_limits_are_settings_with_bounds(name: str):
    """The values chosen at the audit's second pass are settings, with their
    default, and a value out of bounds is refused at start."""
    default, too_low, too_high = TUNABLES[name]
    assert getattr(make_settings(), name) == default
    assert getattr(make_settings(**{name: default + 1}), name) == default + 1
    for wrong in (too_low, too_high):
        with pytest.raises(ValidationError):
            make_settings(**{name: wrong})


def test_the_limiters_read_their_settings(monkeypatch):
    """The heartbeat limiter and the catalogue quota are built from the
    settings; the lock's thresholds are read at each attempt."""
    from app.core import ratelimit
    from app.core.config import settings
    from app.features.inventory import budget

    assert ratelimit.heartbeat_limiter.max_attempts == (
        settings.AGENT_HEARTBEAT_MAX_PER_MINUTE
    )
    assert budget.software_quota.units == settings.SOFTWARE_NEW_ENTRIES_PER_DAY


@pytest.mark.parametrize(
    "value,entry",
    [
        ("10.4.0.0/16,pas-un-reseau", "pas-un-reseau"),
        ("10.4.0.0/33", "10.4.0.0/33"),
        (["192.168.1.0/24", "10.0.0.0/8/8"], "10.0.0.0/8/8"),
        # Readable, but a wake is broadcast over IPv4 only.
        ("fd00::/8", "fd00::/8"),
    ],
)
def test_an_unreadable_wol_allowed_network_refuses_the_start(value, entry):
    """A list whose entries cannot be read allowed nothing, and every direct
    wake was refused with no word at startup: the entry is named instead."""
    with pytest.raises(ValidationError) as caught:
        make_settings(WOL_ALLOWED_NETWORKS=value)
    message = str(caught.value)
    assert "WOL_ALLOWED_NETWORKS" in message and entry in message


def test_readable_wol_allowed_networks_are_kept():
    assert make_settings().WOL_ALLOWED_NETWORKS == []
    kept = make_settings(WOL_ALLOWED_NETWORKS="10.4.0.0/16, 192.168.1.7/24")
    # Host bits are tolerated, as the wake itself reads them.
    assert kept.WOL_ALLOWED_NETWORKS == ["10.4.0.0/16", "192.168.1.7/24"]


def test_the_wol_allowed_networks_are_checked_from_the_environment(monkeypatch):
    monkeypatch.setenv("WOL_ALLOWED_NETWORKS", "10.4.0.0/16,10.4.7.0/2A")
    with pytest.raises(ValidationError, match="10.4.7.0/2A"):
        make_settings()
    monkeypatch.setenv("WOL_ALLOWED_NETWORKS", "10.4.0.0/16,10.4.7.0/24")
    assert make_settings().WOL_ALLOWED_NETWORKS == ["10.4.0.0/16", "10.4.7.0/24"]


# --- Out-of-range values refuse the start (acceptance, 2026-11) ----------------
#
# Each pair: the variable, values just outside its range, values at its edges.
# Where the page Paramètres or the « Envoi des e-mails » card validates the
# same setting, the bounds are theirs.
_BOUNDS: list[tuple[str, list[Any], list[Any]]] = [
    ("WOL_PORT", [0, 65536], [1, 65535]),
    ("LOW_DISK_FREE_PERCENT", [0, 100], [1, 99]),
    ("INACTIVE_AFTER_DAYS", [0, 3651], [1, 3650]),
    ("SIGNATURE_MAX_AGE_DAYS", [-1, 366], [0, 365]),
    ("EMAIL_MAX_ATTEMPTS", [0], [1]),
    ("EMAIL_OUTBOX_RETENTION_DAYS", [-1], [0]),
    ("NOTIFICATION_MAX_ITEMS", [0], [1]),
    ("POSTGRES_POOL_SIZE", [0], [1]),
    ("POSTGRES_MAX_OVERFLOW", [-1], [0]),
    ("WOL_PACKET_COUNT", [0, 21], [1, 20]),
    ("WOL_SUBNET_PREFIXLEN", [7, 31], [8, 30]),
    ("SMTP_TIMEOUT_SECONDS", [0, 121], [1, 120]),
    ("EMAIL_FROM_EMAIL", ["tiai", "a b@x.fr", "tiai@local"], ["tiai@lycee.local", ""]),
    (
        "CONSOLE_BASE_URL",
        ["tiai.lycee.pf", "ftp://tiai.lycee.pf", "https://"],
        ["https://tiai.lycee.pf", "http://10.0.0.5:8080/console", ""],
    ),
]


@pytest.mark.parametrize(
    "name,value",
    [(name, v) for name, bad, _ in _BOUNDS for v in bad],
)
def test_an_out_of_range_setting_refuses_the_start(name: str, value: Any):
    with pytest.raises(ValidationError):
        make_settings(**{name: value})


@pytest.mark.parametrize(
    "name,value",
    [(name, v) for name, _, good in _BOUNDS for v in good],
)
def test_a_setting_at_the_edge_of_its_range_is_accepted(name: str, value: Any):
    assert getattr(make_settings(**{name: value}), name) == value


def test_the_console_bounds_are_the_environments():
    """The fleet thresholds and the SMTP timeout share their bounds with the
    console's forms, which override them."""
    from app.api.routes.settings_routes import SettingsUpdate
    from app.core.config import Settings
    from app.features.setting import email_policy as mail

    def bounds(model: Any, field: str) -> tuple[Any, Any]:
        meta = model.model_fields[field].metadata
        ge = next(m.ge for m in meta if hasattr(m, "ge") and m.ge is not None)
        le = next(m.le for m in meta if hasattr(m, "le") and m.le is not None)
        return ge, le

    for env_name, form_name in (
        ("SIGNATURE_MAX_AGE_DAYS", "signature_max_age_days"),
        ("INACTIVE_AFTER_DAYS", "inactive_after_days"),
        ("LOW_DISK_FREE_PERCENT", "low_disk_free_percent"),
    ):
        assert bounds(Settings, env_name) == bounds(SettingsUpdate, form_name)
    assert bounds(Settings, "SMTP_TIMEOUT_SECONDS") == (
        mail.TIMEOUT_MIN,
        mail.TIMEOUT_MAX,
    )


# --- Trusted proxies no wider than a proxy (audit S28, accepted limit fixed) ---


@pytest.mark.parametrize(
    "value,entry",
    [
        ("10.0.0.0/8", "10.0.0.0/8"),
        ("172.18.0.0/16", "172.18.0.0/16"),
        ("192.168.1.2/32,192.168.0.0/23", "192.168.0.0/23"),
        # Host bits do not narrow it: read as the network they sit in.
        ("192.168.1.7/16", "192.168.1.7/16"),
        ("2001:db8::/48", "2001:db8::/48"),
        ("::/0", "::/0"),
        # IPv4 written as IPv6: measured as the IPv4 network it covers.
        ("::ffff:10.0.0.0/104", "::ffff:10.0.0.0/104"),
        ("::/64", "::/64"),
    ],
)
def test_a_trusted_proxy_entry_wider_than_a_proxy_refuses_the_start(value, entry):
    """Every client inside a trusted network writes the X-Forwarded-For the
    API believes: listing the whole LAN let any poste choose its address.
    The start is refused, naming the entry and the way out."""
    with pytest.raises(ValidationError) as caught:
        make_settings(TRUSTED_PROXIES=value)
    message = str(caught.value)
    assert "TRUSTED_PROXIES" in message and repr(entry) in message
    assert "TRUSTED_PROXIES_ALLOW_WIDE" in message


@pytest.mark.parametrize(
    "value",
    [
        "",
        "172.18.0.3",
        "172.18.0.0/24",
        "192.168.1.2/32, 10.4.7.0/24",
        "2001:db8:0:1::/64",
        "fd00::5/128",
        "::ffff:10.0.0.0/120",
        # Unreadable: not refused here, granted nothing by net.trusted_proxy.
        "caddy",
    ],
)
def test_proxy_sized_trusted_entries_are_accepted(value):
    assert make_settings(TRUSTED_PROXIES=value).TRUSTED_PROXIES_ALLOW_WIDE is False


def test_a_wide_trusted_network_is_accepted_when_asked_for(monkeypatch):
    allowed = make_settings(
        TRUSTED_PROXIES="10.0.0.0/8,2001:db8::/48", TRUSTED_PROXIES_ALLOW_WIDE=True
    )
    assert allowed.TRUSTED_PROXIES == ["10.0.0.0/8", "2001:db8::/48"]
    monkeypatch.setenv("TRUSTED_PROXIES", "172.18.0.0/16")
    with pytest.raises(ValidationError, match="172.18.0.0/16"):
        make_settings()
    monkeypatch.setenv("TRUSTED_PROXIES_ALLOW_WIDE", "true")
    assert make_settings().TRUSTED_PROXIES == ["172.18.0.0/16"]


# --- Slow guessing and the reset budget (audit T06, T34) -----------------------


def test_the_slow_lock_and_reset_ceiling_have_bounded_defaults():
    env = make_settings()
    assert env.LOGIN_SLOW_MAX_FAILED_ATTEMPTS == 20
    assert env.LOGIN_SLOW_WINDOW_HOURS == 24
    assert env.PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS == 10
    for name, wrong in (
        ("LOGIN_SLOW_MAX_FAILED_ATTEMPTS", 1001),
        ("LOGIN_SLOW_WINDOW_HOURS", 0),
        ("LOGIN_SLOW_WINDOW_HOURS", 24 * 7 + 1),
        ("PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS", 0),
        ("PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS", 101),
    ):
        with pytest.raises(ValidationError):
            make_settings(**{name: wrong})


@pytest.mark.parametrize(
    "overrides,named",
    [
        (
            {"LOGIN_MAX_FAILED_ATTEMPTS": 20, "LOGIN_SLOW_MAX_FAILED_ATTEMPTS": 20},
            "LOGIN_SLOW_MAX_FAILED_ATTEMPTS",
        ),
        (
            {"LOGIN_LOCKOUT_MINUTES": 120, "LOGIN_SLOW_WINDOW_HOURS": 2},
            "LOGIN_SLOW_WINDOW_HOURS",
        ),
        (
            {
                "PASSWORD_RESET_MAX_LIVE_LINKS": 5,
                "PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS": 4,
            },
            "PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS",
        ),
    ],
)
def test_the_generous_limit_must_stay_above_the_tight_one(overrides, named):
    with pytest.raises(ValidationError, match=named):
        make_settings(**overrides)


@pytest.mark.parametrize(
    "quick,slow",
    [
        ({}, {"LOGIN_SLOW_MAX_FAILED_ATTEMPTS": 20, "LOGIN_SLOW_WINDOW_HOURS": 24}),
        ({"LOGIN_MAX_FAILED_ATTEMPTS": 3}, {"LOGIN_SLOW_MAX_FAILED_ATTEMPTS": 20}),
        ({"LOGIN_MAX_FAILED_ATTEMPTS": 20}, {"LOGIN_SLOW_MAX_FAILED_ATTEMPTS": 80}),
        ({"LOGIN_MAX_FAILED_ATTEMPTS": 100}, {"LOGIN_SLOW_MAX_FAILED_ATTEMPTS": 400}),
        ({"LOGIN_LOCKOUT_MINUTES": 720}, {"LOGIN_SLOW_WINDOW_HOURS": 24}),
        ({"LOGIN_LOCKOUT_MINUTES": 725}, {"LOGIN_SLOW_WINDOW_HOURS": 25}),
        ({"LOGIN_LOCKOUT_MINUTES": 1440}, {"LOGIN_SLOW_WINDOW_HOURS": 48}),
    ],
)
def test_the_slow_lock_follows_a_quick_one_set_alone(monkeypatch, quick, slow):
    """Verification of v1.2.1, F2: a ``.env`` valid before the slow lock
    existed — LOGIN_MAX_FAILED_ATTEMPTS of 20 or more, or a lock of a day —
    contradicted the new variables' defaults, and the backend refused to
    start on two variables its operator had never heard of. Left unset,
    each follows the quick value it must stay beyond: four times the
    attempts, twice the duration, never below its own default."""
    for name, value in quick.items():
        # From the environment, as a deployment sets them.
        monkeypatch.setenv(name, str(value))
    env = make_settings()
    for name, value in slow.items():
        assert getattr(env, name) == value


def test_an_explicit_slow_lock_is_not_adjusted(monkeypatch):
    """What the operator wrote is taken as written — and refused, both
    variables named, when the two contradict each other."""
    monkeypatch.setenv("LOGIN_MAX_FAILED_ATTEMPTS", "10")
    monkeypatch.setenv("LOGIN_SLOW_MAX_FAILED_ATTEMPTS", "12")
    assert make_settings().LOGIN_SLOW_MAX_FAILED_ATTEMPTS == 12
    monkeypatch.setenv("LOGIN_SLOW_MAX_FAILED_ATTEMPTS", "10")
    with pytest.raises(ValidationError) as refused:
        make_settings()
    assert "LOGIN_SLOW_MAX_FAILED_ATTEMPTS" in str(refused.value)
    assert "LOGIN_MAX_FAILED_ATTEMPTS (10 <= 10)" in str(refused.value)
    # An explicit slow value against the quick one's default is one too.
    monkeypatch.delenv("LOGIN_MAX_FAILED_ATTEMPTS")
    monkeypatch.setenv("LOGIN_SLOW_MAX_FAILED_ATTEMPTS", "5")
    with pytest.raises(ValidationError, match="LOGIN_MAX_FAILED_ATTEMPTS"):
        make_settings()
    monkeypatch.delenv("LOGIN_SLOW_MAX_FAILED_ATTEMPTS")
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "1440")
    monkeypatch.setenv("LOGIN_SLOW_WINDOW_HOURS", "24")
    with pytest.raises(ValidationError) as refused:
        make_settings()
    assert "LOGIN_SLOW_WINDOW_HOURS" in str(refused.value)
    assert "LOGIN_LOCKOUT_MINUTES" in str(refused.value)
