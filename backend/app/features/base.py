from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlmodel import Field


def utcnow() -> datetime:
    """Timezone-aware UTC now (all timestamps are stored in UTC)."""
    return datetime.now(UTC)


def utc_field(*, nullable: bool = False, **kwargs: Any) -> Any:
    """A model field stored as TIMESTAMPTZ, matching the Alembic migrations.

    A bare ``datetime`` annotation maps to a naive ``TIMESTAMP``, so the schema
    built by ``SQLModel.metadata.create_all`` (the tests) would read values back
    naive while the migrated production schema reads them back aware — the same
    comparison then works in one environment and raises TypeError in the other.
    Declaring the column type here keeps both schemas identical: every stored
    timestamp is an aware UTC instant.

    ``sa_column`` instances cannot be shared, hence a factory. ``nullable`` must
    be stated explicitly — with ``sa_column``, SQLModel no longer derives it
    from the ``| None`` annotation.
    """
    return Field(sa_column=Column(DateTime(timezone=True), nullable=nullable), **kwargs)


def escape_like(value: str) -> str:
    """``value`` as literal text in a LIKE pattern: ``%`` and ``_`` typed in a
    search mean themselves, not « anything » (audit S26)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains(column: Any, text: str) -> Any:
    """Case-insensitive substring match of ``text``, taken literally."""
    return column.ilike(f"%{escape_like(text)}%", escape="\\")
