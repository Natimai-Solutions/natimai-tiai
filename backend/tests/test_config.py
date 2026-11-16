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

    assert ratelimit.heartbeat_limiter.max_attempts == (
        settings.AGENT_HEARTBEAT_MAX_PER_MINUTE
    )
    assert ratelimit.software_quota.units == settings.SOFTWARE_NEW_ENTRIES_PER_DAY


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
