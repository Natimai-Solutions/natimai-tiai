"""Seconds a poste was on, per poste and per UTC hour.

One row per (poste, hour) it was seen on in. Hours rather than days: the parc
this was written for sits at UTC−10, where a UTC day turns over at two in the
afternoon, in the middle of the working day. An hour is the grain that makes
any sliding window exact and lets a reader cut days in *their* time zone, at
read time — the only place a day is ever drawn.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index
from sqlmodel import Field, SQLModel

# An hour holds 3 600 seconds and not one more. The database says so too: a
# bucket past it is a double count, and a constraint that fails loudly beats a
# statistic that quietly inflates.
SECONDS_PER_HOUR = 3600


class MachineUptime(SQLModel, table=True):
    __tablename__ = "machine_uptime_hourly"
    __table_args__ = (
        CheckConstraint(
            f"seconds_on >= 0 AND seconds_on <= {SECONDS_PER_HOUR}",
            name="ck_machine_uptime_hourly_seconds_on",
        ),
        # The fleet-wide sum scans by window, not by poste; the primary key
        # already serves the per-poste reads.
        Index("ix_machine_uptime_hourly_hour", "hour"),
    )

    machine_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
        )
    )
    # The start of a whole UTC hour.
    hour: datetime = Field(sa_column=Column(DateTime(timezone=True), primary_key=True))
    seconds_on: int = Field(nullable=False)
