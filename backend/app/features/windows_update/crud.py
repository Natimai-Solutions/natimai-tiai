import uuid

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.windows_update.models import WindowsUpdate
from app.features.windows_update.schemas import PendingUpdateReport


async def replace_pending(
    session: AsyncSession, machine_id: uuid.UUID, reports: list[PendingUpdateReport]
) -> int:
    """Make the stored pending set match what the agent just reported.

    Replacement semantics, deliberately unlike ``upsert_threats``: a threat is a
    historical fact and accumulates, whereas a pending update is a *current
    state* — once installed it vanishes from the agent's report and must vanish
    here too, or the console would keep offering to install a KB already in
    place. So: upsert what was reported, delete what was not.

    Reports without an ``update_id`` are skipped (no stable key). Returns how
    many updates are now pending. The caller commits.
    """
    now = utcnow()
    rows: list[dict[str, object]] = [
        {
            "machine_id": machine_id,
            "update_id": r.update_id,
            "kb": r.kb,
            "title": r.title,
            "severity": r.severity,
            "type": r.type,
            "categories": r.categories_text(),
            "is_downloaded": r.is_downloaded,
            "size_mb": r.size_mb,
            "first_seen": now,
            "last_seen": now,
        }
        for r in reports
        if r.update_id
    ]
    # Deduplicated in Python: ON CONFLICT DO UPDATE raises
    # "cannot affect row a second time" if one statement carries the same key
    # twice, and a WUA search can list the same update under two categories.
    unique: dict[str, dict[str, object]] = {}
    for row in rows:
        unique[str(row["update_id"])] = row
    rows = list(unique.values())

    if rows:
        stmt = pg_insert(WindowsUpdate).values(rows)
        # first_seen is excluded from the update set on purpose: it is the age of
        # the machine's failure to patch, and re-reporting the same update every
        # cycle must not reset it.
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_windows_updates_machine_update",
                set_={
                    "kb": stmt.excluded.kb,
                    "title": stmt.excluded.title,
                    "severity": stmt.excluded.severity,
                    "type": stmt.excluded.type,
                    "categories": stmt.excluded.categories,
                    "is_downloaded": stmt.excluded.is_downloaded,
                    "size_mb": stmt.excluded.size_mb,
                    "last_seen": stmt.excluded.last_seen,
                },
            )
        )

    # Then drop whatever the machine no longer reports — the installed ones. Run
    # after the upsert so a still-pending update is never briefly absent.
    stale = delete(WindowsUpdate).where(col(WindowsUpdate.machine_id) == machine_id)
    if rows:
        stale = stale.where(
            col(WindowsUpdate.update_id).not_in([r["update_id"] for r in rows])
        )
    await session.execute(stale)

    return len(rows)
