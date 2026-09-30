"""Settings guard: placeholder secrets must not reach staging/production."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

# Every secret set to a real value — the baseline that must boot in production.
PROD_OK: dict[str, Any] = {
    "ENVIRONMENT": "production",
    "SECRET_KEY": "a-real-secret-key",
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
