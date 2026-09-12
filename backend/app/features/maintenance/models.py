"""A maintenance session: one visit, one room (or one poste), one date.

The session carries the *global* observation of the visit; what was noted on
each poste is an ``interventions`` row of kind ``maintenance`` pointing back
here (``maintenance_id``). The fiche of a poste shows its own line and links
to the session for the rest.

The cycle and the owner are not here: they sit on the room and on the poste
(``rooms.maintenance_*``, ``machines.maintenance_*``), with the parc-wide
defaults in ``app_settings``. What is due is derived from them and from the
poste's ``last_maintenance_at`` — see ``features/maintenance/policy.py``.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class Maintenance(SQLModel, table=True):
    __tablename__ = "maintenances"
    __table_args__ = (
        Index("ix_maintenances_room_performed", "room_id", "performed_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # SET NULL: a room deleted keeps the record of its visits, room-less.
    room_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True),
    )
    # The room's name at the time, so a session still reads right after the
    # room is renamed or gone.
    room_name: str | None = Field(default=None, max_length=100)
    performed_by: str = Field(max_length=255)
    performed_at: datetime = utc_field(default_factory=utcnow)
    note: str | None = Field(default=None, max_length=5000)
    created_at: datetime = utc_field(default_factory=utcnow)
