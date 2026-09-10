"""Where a poste is, as the console organises it: a building, a room.

Distinct from ``machines.location`` — the *site*, which the agent reports from
its own configuration and which the Wake-on-LAN relay reads. Buildings and
rooms are console objects: created by hand, or, for rooms, derived from the
directory (``ROOM_SOURCE``, ``plan-salles-maintenance-interventions.md`` §3).

The site sits on the building (``Building.location``); a room inherits it from
its building, or carries its own when it has none. A poste whose agent names
another site than its room's is *flagged*, never refused: that mismatch is
what reveals a GPO aimed at the wrong OU, or a poste moved without its room.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class Building(SQLModel, table=True):
    """A building of a site. A grouping and a sort key: it carries no
    maintenance settings of its own, the room does."""

    __tablename__ = "buildings"
    __table_args__ = (
        # Two « Bâtiment B » on two sites, yes; on the same site, no. NULLS NOT
        # DISTINCT so that two site-less buildings cannot share a name either
        # (PostgreSQL ≥ 15; the compose runs 16).
        UniqueConstraint(
            "location",
            "name",
            name="uq_buildings_location_name",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100)
    # The site, in the same words the agents report it (``machines.location``)
    # — the console offers those words in a list, with free entry for a
    # building created before its first poste speaks.
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)


class Room(SQLModel, table=True):
    """A room, where postes are. The level that will carry the maintenance
    cycle and owner (a later milestone); this one carries the grouping."""

    __tablename__ = "rooms"
    __table_args__ = (
        # Two « B12 » in two buildings, yes; in the same, no — and two
        # building-less rooms cannot share a name either.
        UniqueConstraint(
            "building_id",
            "name",
            name="uq_rooms_building_name",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100)
    # SET NULL: deleting a building leaves its rooms standing, building-less.
    building_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    # Only read when ``building_id`` is NULL: a room in a building is where its
    # building is. Kept when a building is deleted (the route copies it down)
    # so the room does not lose its site with its building.
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
