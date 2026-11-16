"""Units granted from a budget, per budget, key and minute.

One row per (budget, key, minute) something was granted in. A minute is the
grain of the sliding window: a grant counts for the window and at most one
minute more, never less. Kept in the database rather than in the API
process, so that every process draws from the same budget and a restart
does not hand out a fresh one (audit T36).
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Index, String
from sqlmodel import Field, SQLModel


class SharedCounter(SQLModel, table=True):
    __tablename__ = "shared_counter"
    __table_args__ = (
        # A give-back never takes a bucket below zero; the database says so too.
        CheckConstraint("used >= 0", name="ck_shared_counter_used"),
        # The housekeeping purge scans by age, across budgets and keys.
        Index("ix_shared_counter_bucket", "bucket"),
    )

    # Which budget (``app.features.counter.quota.Quota.name``).
    name: str = Field(sa_column=Column(String(64), primary_key=True))
    # Whom it is counted for: a poste's id, or one key for the whole fleet.
    key: str = Field(sa_column=Column(String(64), primary_key=True))
    # The start of a whole minute (database clock).
    bucket: datetime = Field(
        sa_column=Column(DateTime(timezone=True), primary_key=True)
    )
    used: int = Field(nullable=False)
