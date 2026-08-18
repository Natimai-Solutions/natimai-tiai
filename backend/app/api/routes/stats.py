"""Console dashboard KPIs (plan §6, M3)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select

from app.api.deps import SessionDep, require_permission
from app.core.config import settings
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.machine.status import MachineStatus, status_clause
from app.features.threat.models import Threat
from app.features.user.permissions import Action, Resource

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.READ))],
)


class StatsOverview(BaseModel):
    """Fleet KPIs for the dashboard cards."""

    total: int
    up_to_date: int
    outdated: int
    needs_verification: int
    inactive: int
    with_active_threats: int
    # Windows Update (Phase 2). Counted over the machines' own columns rather
    # than over ``windows_updates``: a machine that reports zero pending updates
    # has no rows there, so counting rows would say nothing about how many
    # machines are behind.
    machines_wu_pending: int
    machines_reboot_required: int


async def _count(session: SessionDep, clause: ColumnElement[bool] | None = None) -> int:
    stmt = select(func.count()).select_from(Machine)
    if clause is not None:
        stmt = stmt.where(clause)
    return await session.scalar(stmt) or 0


@router.get("/overview", response_model=StatsOverview)
async def overview(session: SessionDep) -> StatsOverview:
    """Aggregate fleet status (total, freshness, verification, inactivity, threats)."""
    now: datetime = utcnow()
    days = settings.INACTIVE_AFTER_DAYS

    total = await _count(session)
    up_to_date = await _count(
        session, status_clause(MachineStatus.UP_TO_DATE, now, days)
    )
    needs_verification = await _count(
        session, status_clause(MachineStatus.NEEDS_VERIFICATION, now, days)
    )
    inactive = await _count(session, status_clause(MachineStatus.INACTIVE, now, days))

    machines_wu_pending = await _count(session, col(Machine.wu_pending_count) > 0)
    machines_reboot_required = await _count(
        session, col(Machine.wu_reboot_required).is_(True)
    )

    with_active_threats = (
        await session.scalar(
            select(func.count(func.distinct(Threat.machine_id))).where(
                col(Threat.status) == "active"
            )
        )
        or 0
    )

    return StatsOverview(
        total=total,
        up_to_date=up_to_date,
        outdated=total - up_to_date,
        needs_verification=needs_verification,
        inactive=inactive,
        with_active_threats=with_active_threats,
        machines_wu_pending=machines_wu_pending,
        machines_reboot_required=machines_reboot_required,
    )
