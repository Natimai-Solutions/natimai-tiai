"""The daily photo of the dashboard's counters, kept by place (C9, §2.2).

``trend_days``: one row per local day photographed — when, in which zone,
under which thresholds. ``trend_snapshots``: that day's counters, one row per
*cell*: the site the agent reports (``machines.location``) and the room, with
the room's building and effective site **as they were that day**, so that a
room moved or deleted since does not rewrite the history of its site.

The cells carry no foreign key to ``rooms`` or ``buildings``, and reference no
poste: a deleted room keeps its history, a merged poste changes nothing here.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Column, Date, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field


class TrendDay(SQLModel, table=True):
    __tablename__ = "trend_days"

    # The local day, in the console's zone (``schedules.timezone``).
    day: date = Field(sa_column=Column(Date(), primary_key=True))
    # The last photo of that day: the one kept.
    taken_at: datetime = utc_field()
    # The zone that fixed the day.
    zone: str = Field(max_length=64)
    # The thresholds the counters were taken with (``snapshot.policy_values``):
    # a jump of a curve the day one of them changed must be explainable.
    policies: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            JSONB(none_as_null=True),
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )


class TrendSnapshot(SQLModel, table=True):
    __tablename__ = "trend_snapshots"
    __table_args__ = (
        # One row per cell and day. NULLS NOT DISTINCT: a poste with neither
        # site nor room is a cell too, and the second photo of the day must
        # replace it, not add a second one. Leading with ``day``, it also
        # serves the reading of a period and the purge.
        Index(
            "uq_trend_snapshots_cell",
            "day",
            "location",
            "room_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    # A surrogate key: the natural one has two nullable columns. Read by
    # nobody.
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    day: date = Field(
        sa_column=Column(
            Date(),
            ForeignKey("trend_days.day", ondelete="CASCADE"),
            nullable=False,
        )
    )
    # ``machines.location``: the site the agent reports.
    location: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    # The room, its building and its effective site that day. No foreign
    # key: the room may go, the row stays.
    room_id: uuid.UUID | None = Field(default=None, nullable=True)
    building_id: uuid.UUID | None = Field(default=None, nullable=True)
    site: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    # The counters of the cell, without the zeros (an absent key is 0).
    counters: dict[str, int] = Field(
        default_factory=dict,
        sa_column=Column(
            JSONB(none_as_null=True),
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
