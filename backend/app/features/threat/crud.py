import uuid

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.threat.models import Threat
from app.features.threat.schemas import ThreatReport

# The columns Defender may revise on a detection it has already reported. The
# identity (machine_id, detection_id) and ``detected_at`` are deliberately not
# in here: the first is the dedup key, the second is when the detection *first*
# happened and does not move.
_MUTABLE = ("threat_name", "severity", "category", "status", "action_taken")


async def upsert_threats(
    session: AsyncSession, machine_id: uuid.UUID, reports: list[ThreatReport]
) -> int:
    """Store reported threats, deduplicated on (machine_id, detection_id).

    ``INSERT ... ON CONFLICT DO UPDATE``, not DO NOTHING: the agent re-reads
    Defender's whole detection history on every poll, and a detection's *status*
    moves over its lifetime — detected, then quarantined or removed. Keeping only
    the first reading would freeze a threat as "active" forever, long after
    Defender dealt with it, and the console would report years-old detections as
    live ones. The detection is the stable thing; its status is not.

    The write is conditional (``where``) so an unchanged detection re-reported on
    every heartbeat does not rewrite its row: the whole history comes back each
    poll, and an unconditional update would churn the table for nothing.

    Reports without a detection_id are skipped (no stable key to deduplicate on).
    Returns the number of rows written (inserted or updated).
    """
    # Deduplicate within the batch first: ON CONFLICT DO UPDATE refuses to touch
    # the same row twice in one statement, and a batch *can* carry the same key
    # twice — the agent falls back to the ThreatID when Defender reports no
    # DetectionID, and several detections share a ThreatID. Last one wins, being
    # the most recent reading of that detection.
    deduped: dict[str, dict[str, object]] = {}
    for r in reports:
        if not r.detection_id:
            continue
        deduped[r.detection_id] = {
            "machine_id": machine_id,
            "detection_id": r.detection_id,
            "threat_name": r.threat_name,
            "severity": r.severity,
            "category": r.category,
            "status": r.status,
            "action_taken": r.action_taken,
            "detected_at": r.detected_at,
            "raw": r.model_dump(mode="json"),
        }
    rows = list(deduped.values())
    if not rows:
        return 0

    insert = pg_insert(Threat).values(rows)
    stored = Threat.__table__.c  # type: ignore[attr-defined]
    excluded = insert.excluded
    # An agent that could not read the timestamp must not erase the one already
    # recorded, so a missing value keeps what is stored.
    detected_at = func.coalesce(excluded.detected_at, stored.detected_at)

    stmt = insert.on_conflict_do_update(
        constraint="uq_threats_machine_detection",
        set_={
            **{name: excluded[name] for name in _MUTABLE},
            "detected_at": detected_at,
            "raw": excluded.raw,
        },
        where=or_(
            *(stored[name].is_distinct_from(excluded[name]) for name in _MUTABLE),
            stored.detected_at.is_distinct_from(detected_at),
        ),
    )
    result = await session.execute(stmt)
    return result.rowcount or 0  # type: ignore[attr-defined]
