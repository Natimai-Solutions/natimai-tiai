"""A software licence: what the établissement bought the right to install.

The software catalogue says what is installed; nothing said how many of
those installations are paid for, nor until when. A licence holds that: the
programs it covers, the number of postes, the end of the contract, the
supplier and the order — never the key itself, which has nothing to do in a
console read by several people (plan ``dev/plan-evolutions-itil.md``, C6).

The programs are named by patterns over the catalogue's names, not by ids:
the catalogue has a row per (name, version, publisher), and a licence for
« Microsoft Office 2021 » must not be re-linked at every monthly update. A
pattern is a substring of the program name, matched case-insensitively and
literally — the rule of the « logiciels interdits » list (C1).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Column, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class License(SQLModel, table=True):
    __tablename__ = "licenses"
    __table_args__ = (Index("ix_licenses_expires_on", "expires_on"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # What the console calls it: « Office 2021 Éducation (marché 2024) ».
    name: str = Field(max_length=200)
    # Substrings of the program names it covers, one at least.
    patterns: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB(none_as_null=True), nullable=False)
    )
    # Narrows the patterns to one publisher, when a name is shared
    # (« Reader »): a substring of the catalogue's publisher, or nothing.
    publisher: str | None = Field(default=None, max_length=200)
    # How many postes it covers; NULL for a site licence without a count.
    seats: int | None = None
    # The end of the contract or of the subscription; NULL when perpetual.
    expires_on: date | None = None
    vendor: str | None = Field(default=None, max_length=200)
    # The order, contract or agreement number — what the supplier asks for.
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
