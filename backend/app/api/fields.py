"""Shared request-field types for route payloads."""

from typing import Annotated, Any

from pydantic import AfterValidator, Field, model_validator

from app.core.config import EMAIL_PATTERN, settings
from app.core.security import PASSWORD_MAX_BYTES
from app.core.validation import invalid
from app.features.user.models import normalize_email


def _bcrypt_sized(value: str) -> str:
    """Refuse what bcrypt would cut: only the first ``PASSWORD_MAX_BYTES``
    bytes of the UTF-8 encoding count, and a password whose end does not
    count is not the password its owner thinks they chose."""
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise invalid(
            "password_too_long",
            f"le mot de passe ne doit pas dépasser {PASSWORD_MAX_BYTES} octets "
            f"({PASSWORD_MAX_BYTES} caractères sans accent, moins avec des "
            "accents ou des symboles) : au-delà, la fin ne serait pas prise en compte",
            max_bytes=PASSWORD_MAX_BYTES,
        )
    return value


# Any password accepted through the API must be at least this long, and no
# longer than bcrypt reads.
Password = Annotated[
    str,
    Field(min_length=settings.PASSWORD_MIN_LENGTH),
    AfterValidator(_bcrypt_sized),
]


def _trimmed_name(value: str | None) -> str | None:
    """A name as stored: without its surrounding spaces, and never blank —
    a name made of spaces shows as nothing in every list."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise invalid(
            "name_blank", "le nom ne peut pas être vide ou fait seulement d'espaces"
        )
    return value


def bounded_name(max_length: int) -> Any:
    """A display name — an account's, a group's: trimmed, not blank, at most
    ``max_length`` characters once trimmed (its column's size: a longer one
    used to end as a 500 when written)."""

    def check(value: str | None) -> str | None:
        value = _trimmed_name(value)
        if value is not None and len(value) > max_length:
            raise invalid(
                "name_too_long",
                f"le nom ne doit pas dépasser {max_length} caractères "
                f"(reçu : {len(value)})",
                max=max_length,
                length=len(value),
            )
        return value

    return AfterValidator(check)


# Console account identifier. Deliberately looser than RFC-grade validation
# (pydantic's EmailStr): email-validator rejects special-use domains such as
# `.local` — exactly what the on-prem AD parks this tool targets use
# (admin@natimai.local). Shape check only: one @, a dotted domain, no spaces.
# Lower-cased once accepted — the form an address is stored and compared in
# (``normalize_email``) — so a route never sees two spellings of one mailbox.
Email = Annotated[
    str,
    Field(pattern=EMAIL_PATTERN, max_length=255),
    AfterValidator(normalize_email),
]


def not_null(*names: str) -> Any:
    """A model validator for a partial update: these fields may be left out,
    not sent as null — their columns are NOT NULL, and a null used to end as
    a 500 when written (audit B27). Assign it in the class body."""

    def check(cls: Any, data: Any) -> Any:
        if isinstance(data, dict):
            bad = [n for n in names if n in data and data[n] is None]
            if bad:
                raise invalid(
                    "null_refused",
                    f"{', '.join(bad)} : valeur requise (null refusé)",
                    fields=bad,
                )
        return data

    return model_validator(mode="before")(check)
