import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, ForeignKey, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class WindowsUpdate(SQLModel, table=True):
    """One update *pending* on one machine, as last reported by its agent.

    Unlike ``threats``, this table is not a history: it holds the current
    pending set and nothing else. An update that gets installed disappears from
    the agent's report, and ``crud.replace_pending`` deletes the row — the
    console must never offer to install a KB that is already in place.

    ``first_seen`` therefore carries the only historical fact worth keeping: how
    long a machine has been sitting on a patch it never applied.
    """

    __tablename__ = "windows_updates"
    __table_args__ = (
        UniqueConstraint(
            "machine_id", "update_id", name="uq_windows_updates_machine_update"
        ),
        Index("ix_windows_updates_machine_id", "machine_id"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    machine_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    )
    # WUA's UpdateID plus its revision number: the same update revised by
    # Microsoft is a different thing to install, so the revision belongs in the
    # key rather than being collapsed onto the previous row.
    update_id: str
    kb: str | None = None  # "KB5063878"; NULL on the many updates that have none
    title: str = ""
    severity: str | None = None  # MSRC severity, lowercased; NULL when unrated
    type: str = "software"  # software / driver
    categories: str | None = None  # WUA category names, comma-joined
    is_downloaded: bool = False
    size_mb: float | None = None
    # Set once, on the heartbeat that first reported the update. What answers
    # "this poste has been missing a critical patch for six weeks".
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)
