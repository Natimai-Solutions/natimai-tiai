import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, literal_column, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.threat.models import Threat
from app.features.threat.schemas import ThreatReport

# The columns Defender may revise on a detection it has already reported. The
# identity (machine_id, detection_id) and ``detected_at`` are deliberately not
# in here: the first is the dedup key, the second is when the detection *first*
# happened and does not move.
_MUTABLE = ("threat_name", "severity", "category", "status", "action_taken")


@dataclass(frozen=True)
class NewDetection:
    """A detection this write recorded for the first time.

    The distinction matters to the alert path and only there: the agent re-reads
    Defender's whole history on every poll, so a *written* row is usually a
    status moving from active to quarantined — news for the console, but not
    something to mail anyone about a second time.
    """

    detection_id: str
    threat_name: str | None
    severity: str | None
    status: str | None
    detected_at: datetime | None


@dataclass(frozen=True)
class UpsertResult:
    """What a batch of reported threats changed."""

    written: int
    new_detections: list[NewDetection]


async def upsert_threats(
    session: AsyncSession, machine_id: uuid.UUID, reports: list[ThreatReport]
) -> UpsertResult:
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
    Returns the rows written (inserted or updated) and, among them, the ones
    that were genuinely new — see ``NewDetection``.
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
        return UpsertResult(written=0, new_detections=[])

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
    # ``xmax = 0`` is PostgreSQL's own answer to "did this row exist before?":
    # on an INSERT ... ON CONFLICT, an inserted tuple carries no deleting
    # transaction, an updated one carries the transaction that superseded the
    # previous version. It is the only way to tell the two apart in a single
    # statement — and issuing a SELECT first would race with the next heartbeat
    # of the same poste.
    returning: Any = stmt.returning(
        literal_column("detection_id"),
        literal_column("threat_name"),
        literal_column("severity"),
        literal_column("status"),
        literal_column("detected_at"),
        literal_column("xmax = 0").label("inserted"),
    )
    result = await session.exec(returning)
    written = result.fetchall()
    new_detections = [
        NewDetection(
            detection_id=row.detection_id,
            threat_name=row.threat_name,
            severity=row.severity,
            status=row.status,
            detected_at=row.detected_at,
        )
        for row in written
        if row.inserted
    ]
    return UpsertResult(written=len(written), new_detections=new_detections)
