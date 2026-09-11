"""Settings an administrator changes from the console, without a restart.

A key/value table rather than columns: the keys are few and arrive one
milestone at a time, and a setting that names an account (the default
maintenance owner) has no honest place in a ``.env``. The environment still
provides the *initial* value of the settings that have one
(``MAINTENANCE_DEFAULT_CYCLE_DAYS``); once the console has written a row,
the row wins.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True, max_length=100)
    value: Any = Field(default=None, sa_column=Column(JSONB, nullable=True))
    updated_at: datetime = utc_field(default_factory=utcnow)
    updated_by: str | None = Field(default=None, max_length=255)
