"""Shared request-field types for route payloads."""

from typing import Annotated, Any

from pydantic import AfterValidator, Field, model_validator

from app.core.config import settings
from app.features.user.models import normalize_email

# Any password accepted through the API must be at least this long.
Password = Annotated[str, Field(min_length=settings.PASSWORD_MIN_LENGTH)]

# Console account identifier. Deliberately looser than RFC-grade validation
# (pydantic's EmailStr): email-validator rejects special-use domains such as
# `.local` — exactly what the on-prem AD parks this tool targets use
# (admin@natimai.local). Shape check only: one @, a dotted domain, no spaces.
# Lower-cased once accepted — the form an address is stored and compared in
# (``normalize_email``) — so a route never sees two spellings of one mailbox.
Email = Annotated[
    str,
    Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255),
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
                raise ValueError(f"{', '.join(bad)} : valeur requise (null refusé)")
        return data

    return model_validator(mode="before")(check)
