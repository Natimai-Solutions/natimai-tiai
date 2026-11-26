"""Procedure notes per hardware model (C11).

One plain-text note per ``machines.hw_model`` as the inventory writes it:
« sur ce modèle, le BIOS s'ouvre par F10 ». Shown on the fiche of every
poste of that model. No reference to ``machines.id``: a merge or a
retirement of postes leaves the notes as they are. Its history is the audit
log (``previous``), not a table of versions.
"""

import uuid
from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow

# ``inventory/schemas.py:TEXT_MAX``: what the inventory writes in hw_model.
HW_MODEL_MAX = 200
# The bound of ``interventions.note``.
BODY_MAX = 5000


class Procedure(SQLModel, table=True):
    __tablename__ = "procedures"
    __table_args__ = (Index("uq_procedures_hw_model", "hw_model", unique=True),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hw_model: str = Field(max_length=HW_MODEL_MAX)
    body: str = Field(max_length=BODY_MAX)
    # E-mails, the journal's convention: they outlive the accounts.
    created_by: str = Field(max_length=255)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_by: str = Field(max_length=255)
    updated_at: datetime = utc_field(default_factory=utcnow)
