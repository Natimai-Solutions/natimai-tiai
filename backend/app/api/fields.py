"""Shared request-field types for route payloads."""

from typing import Annotated

from pydantic import AfterValidator, Field

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
