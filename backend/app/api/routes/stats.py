"""Console dashboard KPIs (plan §6, M3)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, exists, func
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select

from app.api.deps import SessionDep, require_permission
from app.core.config import settings
from app.features.base import utcnow
from app.features.inventory.models import MachineSoftware, Volume
from app.features.machine.agent_version import fleet_versions
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    agent_outdated_clause,
    aging_hardware_clause,
    low_disk_clause,
    status_clause,
)
from app.features.threat.models import Threat
from app.features.user.permissions import Action, Resource

# What ``Win32_EncryptableVolume`` reports for a volume BitLocker has finished
# protecting. Anything else — in progress, decrypting, suspended, off — is a
# volume that is not protected right now, which is what the card counts.
FULLY_ENCRYPTED = "FullyEncrypted"

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
    # Inventory. Chosen to be *actionable*: each one is a list an administrator
    # can open and do something about, which is why "combien de Go de RAM au
    # total" is not among them.
    machines_low_disk: int
    machines_unencrypted: int
    machines_aging: int
    software_count: int
    # The threshold behind machines_low_disk, served rather than hardcoded in the
    # console: it is a server setting, and a card reading "moins de 10 %" while
    # the server counts at 15 would be a lie nobody could see.
    low_disk_free_percent: int
    hardware_aging_years: int
    # The agent itself: how many postes run something older than the
    # reference, and what the reference is — the deployment's progress bar,
    # on the wall screen the deployment is watched from.
    machines_agent_outdated: int
    agent_latest_version: str | None


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

    machines_low_disk = await _count(
        session, low_disk_clause(settings.LOW_DISK_FREE_PERCENT)
    )
    machines_aging = await _count(
        session, aging_hardware_clause(now, settings.HARDWARE_AGING_YEARS)
    )
    # Machines whose *system* volume is not fully encrypted. Read off the volume
    # rows and not off a machine column, unlike the disk figure above: this is
    # not a number the list sorts on, it is a link to a list of postes, and one
    # EXISTS on the dashboard is cheaper than a column maintained on every
    # inventory.
    #
    # A NULL status does not count: BitLocker's WMI namespace is absent on some
    # SKUs and needs elevation, so "not read" would otherwise be reported as
    # "not encrypted" — an alarm on a machine that may well be encrypted is how
    # a dashboard gets ignored.
    machines_unencrypted = await _count(
        session,
        exists().where(
            and_(
                col(Volume.machine_id) == col(Machine.id),
                col(Volume.is_system).is_(True),
                col(Volume.encryption_status).is_not(None),
                col(Volume.encryption_status) != FULLY_ENCRYPTED,
            )
        ),
    )
    # Distinct programs installed *somewhere*, which is the size of the
    # catalogue page. Counted through the link table rather than over
    # ``software``: an entry every machine has since dropped is history, not
    # something the parc runs.
    software_count = (
        await session.scalar(
            select(func.count(func.distinct(col(MachineSoftware.software_id))))
        )
        or 0
    )

    with_active_threats = (
        await session.scalar(
            select(func.count(func.distinct(Threat.machine_id))).where(
                col(Threat.status) == "active"
            )
        )
        or 0
    )

    # Postes below the reference agent version. The reference and the list of
    # versions behind it are the machine list's own (``fleet_versions``), so
    # the card and the list it opens cannot disagree.
    fleet = await fleet_versions(session)
    machines_agent_outdated = (
        await _count(session, agent_outdated_clause(fleet.outdated, True))
        if fleet.outdated
        else 0
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
        machines_low_disk=machines_low_disk,
        machines_unencrypted=machines_unencrypted,
        machines_aging=machines_aging,
        software_count=software_count,
        low_disk_free_percent=settings.LOW_DISK_FREE_PERCENT,
        hardware_aging_years=settings.HARDWARE_AGING_YEARS,
        machines_agent_outdated=machines_agent_outdated,
        agent_latest_version=fleet.latest,
    )
