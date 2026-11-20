"""What a merge of postes does to the schedules (plan §2, « Fusion de postes »)."""

import uuid
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.schedule.models import Schedule


def _replaced(target: dict[str, Any], source: str, kept: str) -> dict[str, Any] | None:
    if target.get("kind") != "machines":
        return None
    ids = list(target.get("machine_ids") or [])
    if source not in ids:
        return None
    return {
        **target,
        "machine_ids": list(dict.fromkeys(kept if i == source else i for i in ids)),
    }


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A schedule aimed at the duplicate's record is aimed at the kept one:
    it is the same poste. The run history names postes as they were, and is
    left as it is."""
    source, kept = str(source_id), str(target_id)
    for schedule in (await session.exec(select(Schedule))).all():
        changed = False
        replaced = _replaced(schedule.target, source, kept)
        if replaced is not None:
            schedule.target = replaced
            changed = True
        if schedule.rings:
            rings = []
            for ring in schedule.rings:
                moved = _replaced(ring.get("target") or {}, source, kept)
                rings.append({**ring, "target": moved} if moved is not None else ring)
                changed = changed or moved is not None
            schedule.rings = rings
        if changed:
            session.add(schedule)
