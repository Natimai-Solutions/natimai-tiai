"""Console-facing threat listing across the fleet (plan §5)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import SessionDep, require_permission
from app.features.threat.models import Threat
from app.features.user.permissions import Action, Resource

router = APIRouter(
    prefix="/threats",
    tags=["threats"],
    dependencies=[Depends(require_permission(Resource.THREAT, Action.READ))],
)


class ThreatOut(BaseModel):
    """A stored Defender detection for the console."""

    id: int
    machine_id: uuid.UUID
    detection_id: str | None
    threat_name: str | None
    severity: str | None
    category: str | None
    status: str | None
    action_taken: str | None
    detected_at: datetime | None

    model_config = {"from_attributes": True}


class ThreatList(BaseModel):
    """Paginated threat list."""

    items: list[ThreatOut]
    total: int
    page: int
    page_size: int


@router.get("", response_model=ThreatList)
async def list_threats(
    session: SessionDep,
    machine_id: uuid.UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ThreatList:
    """List threats, optionally filtered by machine, status, and severity."""
    stmt = select(Threat)
    if machine_id is not None:
        stmt = stmt.where(col(Threat.machine_id) == machine_id)
    if status is not None:
        stmt = stmt.where(col(Threat.status) == status)
    if severity is not None:
        stmt = stmt.where(col(Threat.severity) == severity)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # NULLS LAST and a tiebreaker, both of which this list needs more than most:
    # ``detected_at`` is Defender's own clock and it is nullable, and a single
    # scan quarantining a folder writes a dozen rows carrying the very same
    # instant. Without ``id`` behind it PostgreSQL may order those ties
    # differently for each OFFSET, so a detection would show on two pages while
    # another never appeared at all — and a NULLS FIRST default would open the
    # history with the detections Defender never dated.
    rows = await session.exec(
        stmt.order_by(
            col(Threat.detected_at).desc().nulls_last(), col(Threat.id).desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [ThreatOut.model_validate(t) for t in rows.all()]
    return ThreatList(items=items, total=total or 0, page=page, page_size=page_size)
