"""Console-facing endpoints: list and inspect managed machines.

Auth (admin session/JWT) is added in M5; left open for the MVP.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, computed_field
from sqlalchemy import case, exists, func, or_
from sqlmodel import col, select

from app.api.deps import SessionDep, require_permission
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.base import utcnow
from app.features.machine import crud as machine_crud
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    WindowsUpdateFilter,
    is_online,
    status_clause,
    windows_update_clause,
)
from app.features.threat.models import Threat
from app.features.user.permissions import Action, Resource
from app.features.windows_update.models import WindowsUpdate

router = APIRouter(
    prefix="/machines",
    tags=["machines"],
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.READ))],
)


class MachineOut(BaseModel):
    """Machine summary for the console list/detail views."""

    id: uuid.UUID
    machine_uuid: str
    hostname: str | None
    domain: str | None
    ip_address: str | None
    os_version: str | None
    agent_version: str | None
    is_up_to_date: bool | None
    needs_verification: bool
    signature_version: str | None
    # Which antivirus guards the poste. In the list and not only in the detail:
    # on a mixed parc it is the column that explains an "outdated" Defender
    # reading, and the one people filter on. "" = no antivirus registered at all,
    # None = never reported (see the model).
    av_product_name: str | None
    av_product_enabled: bool | None
    av_product_signatures_up_to_date: bool | None
    av_product_is_defender: bool | None
    session_user_present: bool | None
    session_username: str | None
    # In the list and not only in the detail: "which postes are missing patches"
    # and "which are waiting on a restart" are the two questions this phase
    # exists to answer, and both are answered by scanning a column. NULL on the
    # count = never reported (see the model).
    wu_pending_count: int | None
    wu_reboot_required: bool
    last_seen: datetime

    model_config = {"from_attributes": True}

    # Derived here rather than stored, and served rather than left to the client:
    # the cadence it is read against is a server setting, and computing it at
    # serialization time keeps the answer free of any client clock skew.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_online(self) -> bool:
        """Whether the agent has phoned home within the online window."""
        return is_online(self.last_seen, utcnow(), settings.OFFLINE_AFTER_SECONDS)


class PendingUpdateOut(BaseModel):
    """An update WUA reports as applicable and not yet installed on this machine."""

    id: int
    update_id: str
    kb: str | None
    title: str
    severity: str | None
    type: str
    categories: str | None
    is_downloaded: bool
    size_mb: float | None
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


class MachineDetailOut(MachineOut):
    """Full machine detail (Defender state, session type, fingerprint, times)."""

    rtp_enabled: bool | None
    av_enabled: bool | None
    signature_last_updated: datetime | None
    signature_age_days: int | None
    last_quick_scan: datetime | None
    last_full_scan: datetime | None
    running_mode: str | None
    session_state: str | None
    session_is_remote: bool | None
    wu_last_search: datetime | None
    wu_last_install: datetime | None
    machine_guid: str | None
    smbios_uuid: str | None
    tpm_ek_hash: str | None
    first_seen: datetime
    created_at: datetime
    updated_at: datetime
    # Embedded rather than served from a /machines/{id}/updates of its own: the
    # list is a few dozen rows, it is only ever read next to the state above, and
    # a second round trip would only make the page load in two steps.
    pending_updates: list[PendingUpdateOut] = []


class MachineList(BaseModel):
    """Paginated machine list."""

    items: list[MachineOut]
    total: int
    page: int
    page_size: int


@router.get("", response_model=MachineList)
async def list_machines(
    session: SessionDep,
    search: str | None = None,
    domain: str | None = None,
    antivirus: str | None = None,
    status: MachineStatus | None = None,
    wu_status: WindowsUpdateFilter | None = None,
    with_active_threats: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> MachineList:
    """List machines with optional search/domain/antivirus/status filters, plus
    the two facets the dashboard cards link to: Windows Update state and the
    presence of an active threat.
    """
    stmt = select(Machine)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                col(Machine.hostname).ilike(pattern),
                col(Machine.machine_uuid).ilike(pattern),
                # Searchable too: going from an address in a firewall or DHCP
                # log back to the machine is the everyday use of this field.
                col(Machine.ip_address).ilike(pattern),
                # And from a vendor name: "which postes still run the antivirus
                # we are migrating off?" is the question a mixed parc asks.
                col(Machine.av_product_name).ilike(pattern),
            )
        )
    if domain:
        stmt = stmt.where(col(Machine.domain) == domain)
    if antivirus:
        # Substring rather than equality, unlike the domain filter: the dropdown
        # feeds it exact names from the fleet, but a hand-typed "eset" must find
        # "ESET Endpoint Security" too — vendors rename their products between
        # versions and a parc runs several at once.
        stmt = stmt.where(col(Machine.av_product_name).ilike(f"%{antivirus}%"))
    if status is not None:
        stmt = stmt.where(status_clause(status, utcnow(), settings.INACTIVE_AFTER_DAYS))
    if wu_status is not None:
        stmt = stmt.where(windows_update_clause(wu_status))
    if with_active_threats is not None:
        # Same definition as the dashboard's "avec menaces" KPI: at least one
        # threat Defender has not dealt with. False selects the complement.
        active = exists().where(
            (col(Threat.machine_id) == col(Machine.id))
            & (col(Threat.status) == "active")
        )
        stmt = stmt.where(active if with_active_threats else ~active)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.exec(
        stmt.order_by(col(Machine.last_seen).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [MachineOut.model_validate(m) for m in rows.all()]
    return MachineList(items=items, total=total or 0, page=page, page_size=page_size)


class AntivirusProduct(BaseModel):
    """One antivirus present in the fleet, with how many machines report it."""

    name: str
    count: int


# Declared before ``/{machine_id}``: FastAPI matches in declaration order, and
# the other way round "antivirus-products" would be parsed as a machine id.
@router.get("/antivirus-products", response_model=list[AntivirusProduct])
async def list_antivirus_products(session: SessionDep) -> list[AntivirusProduct]:
    """Antivirus names reported across the fleet, most widespread first.

    Feeds the console's filter dropdown: which products are installed is fleet
    data, not something a client can hardcode — and the counts double as a
    one-glance inventory of a mixed parc.

    Machines that reported no product (empty name) or nothing at all (NULL) are
    left out: they are not products to filter on, and the "Non à jour" status
    filter already gathers them.
    """
    name = col(Machine.av_product_name)
    rows = await session.exec(
        select(name, func.count().label("count"))
        .where(name.is_not(None))
        .where(name != "")
        .group_by(name)
        .order_by(func.count().desc(), name)
    )
    return [
        AntivirusProduct(name=product, count=count)
        # `if product` narrows away the NULL the SQL already excluded.
        for product, count in rows.all()
        if product
    ]


async def _require_machine(session: SessionDep, machine_id: uuid.UUID) -> Machine:
    """Fetch a machine or raise the stable not-found error."""
    machine = await session.get(Machine, machine_id)
    if machine is None:
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    return machine


async def _machine_detail(session: SessionDep, machine: Machine) -> MachineDetailOut:
    """Build a detail payload, pending Windows updates included.

    Ordered by severity then title rather than by insertion: the reason to open
    this table is to find the critical patch, and the ``severity`` values are
    MSRC's own vocabulary, which sorts alphabetically as critical < important <
    low < moderate — no use at all. Hence the explicit CASE.
    """
    severity_rank = case(
        {
            "critical": 0,
            "important": 1,
            "moderate": 2,
            "low": 3,
        },
        value=col(WindowsUpdate.severity),
        else_=4,
    )
    rows = await session.exec(
        select(WindowsUpdate)
        .where(col(WindowsUpdate.machine_id) == machine.id)
        .order_by(severity_rank, col(WindowsUpdate.title))
    )
    detail = MachineDetailOut.model_validate(machine)
    detail.pending_updates = [PendingUpdateOut.model_validate(u) for u in rows.all()]
    return detail


@router.get("/{machine_id}", response_model=MachineDetailOut)
async def get_machine(machine_id: uuid.UUID, session: SessionDep) -> MachineDetailOut:
    """Fetch a single machine by id (full Defender state + fingerprint)."""
    machine = await _require_machine(session, machine_id)
    return await _machine_detail(session, machine)


@router.get("/{machine_id}/duplicates", response_model=list[MachineOut])
async def list_duplicates(
    machine_id: uuid.UUID, session: SessionDep
) -> list[MachineOut]:
    """Candidate duplicates: other machines sharing this one's SMBIOS anchor
    (plan §2.3) — the records an admin may want to merge.
    """
    machine = await _require_machine(session, machine_id)
    if not machine.smbios_uuid:
        return []
    rows = await session.exec(
        select(Machine)
        .where(col(Machine.smbios_uuid) == machine.smbios_uuid)
        .where(col(Machine.id) != machine_id)
        .order_by(col(Machine.last_seen).desc())
    )
    return [MachineOut.model_validate(m) for m in rows.all()]


@router.post(
    "/{machine_id}/revoke-token",
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.WRITE))],
)
async def revoke_token(machine_id: uuid.UUID, session: SessionDep) -> dict[str, str]:
    """Revoke a machine's token (kill-switch): its next call is rejected and it
    must re-enroll, which issues a fresh token and clears the flag (plan §2.4).
    """
    machine = await _require_machine(session, machine_id)
    machine.token_revoked = True
    machine.updated_at = utcnow()
    await session.commit()
    return {"status": "revoked"}


class MergeRequest(BaseModel):
    """Merge the ``source`` machine into the path's target (kept) machine."""

    source_id: uuid.UUID


@router.post(
    "/{machine_id}/merge",
    response_model=MachineDetailOut,
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.WRITE))],
)
async def merge_machine(
    machine_id: uuid.UUID, payload: MergeRequest, session: SessionDep
) -> MachineDetailOut:
    """Merge a duplicate record into this one (plan §8): the source's threats
    and commands are reattached here, the verification flag is cleared, and the
    source is deleted. This machine (the path id) is the one kept.
    """
    if machine_id == payload.source_id:
        raise AppError(
            code=ErrorCode.MACHINE_MERGE_SELF,
            status_code=400,
            message="Cannot merge a machine into itself",
        )
    target = await _require_machine(session, machine_id)
    source = await _require_machine(session, payload.source_id)
    await machine_crud.merge_into(session, target=target, source=source)
    await session.commit()
    await session.refresh(target)
    return await _machine_detail(session, target)
