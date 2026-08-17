"""Console-facing endpoints: list and inspect managed machines.

Auth (admin session/JWT) is added in M5; left open for the MVP.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import col, select

from app.api.deps import SessionDep, require_permission
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.base import utcnow
from app.features.machine import crud as machine_crud
from app.features.machine.models import Machine
from app.features.machine.status import MachineStatus, status_clause
from app.features.user.permissions import Action, Resource

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
    os_version: str | None
    agent_version: str | None
    is_up_to_date: bool | None
    needs_verification: bool
    signature_version: str | None
    session_user_present: bool | None
    session_username: str | None
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
    session_state: str | None
    session_is_remote: bool | None
    machine_guid: str | None
    smbios_uuid: str | None
    tpm_ek_hash: str | None
    first_seen: datetime
    created_at: datetime
    updated_at: datetime


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
    status: MachineStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> MachineList:
    """List machines with optional search/domain/status filters and pagination."""
    stmt = select(Machine)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                col(Machine.hostname).ilike(pattern),
                col(Machine.machine_uuid).ilike(pattern),
            )
        )
    if domain:
        stmt = stmt.where(col(Machine.domain) == domain)
    if status is not None:
        stmt = stmt.where(status_clause(status, utcnow(), settings.INACTIVE_AFTER_DAYS))

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.exec(
        stmt.order_by(col(Machine.last_seen).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [MachineOut.model_validate(m) for m in rows.all()]
    return MachineList(items=items, total=total or 0, page=page, page_size=page_size)


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


@router.get("/{machine_id}", response_model=MachineDetailOut)
async def get_machine(machine_id: uuid.UUID, session: SessionDep) -> MachineDetailOut:
    """Fetch a single machine by id (full Defender state + fingerprint)."""
    machine = await _require_machine(session, machine_id)
    return MachineDetailOut.model_validate(machine)


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
    return MachineDetailOut.model_validate(target)
