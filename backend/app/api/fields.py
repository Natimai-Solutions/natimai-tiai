"""Shared request-field types for route payloads."""

from typing import Annotated

from pydantic import Field

from app.core.config import settings

# Any password accepted through the API must be at least this long.
Password = Annotated[str, Field(min_length=settings.PASSWORD_MIN_LENGTH)]

# Console account identifier. Deliberately looser than RFC-grade validation
# (pydantic's EmailStr): email-validator rejects special-use domains such as
# `.local` — exactly what the on-prem AD parks this tool targets use
# (admin@natimai.local). Shape check only: one @, a dotted domain, no spaces.
Email = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)]
