"""Console-facing read of the audit log (admin only)."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import String, and_, cast, or_
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.features.audit import crud
from app.features.audit.models import AuditEntry
from app.features.machine.models import Machine
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope, machine_clause, restrict

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(require_permission(Resource.AUDIT, Action.READ))],
)


class AuditEntryOut(BaseModel):
    """One administrative action as shown in the console."""

    id: uuid.UUID
    at: datetime
    actor: str
    action: str
    resource_type: str
    resource_id: str
    ip: str | None
    details: dict[str, Any]

    model_config = {"from_attributes": True}


class AuditList(BaseModel):
    """Paginated audit log, newest first."""

    items: list[AuditEntryOut]
    total: int
    page: int
    page_size: int


def _scope_clause(scope: Scope | None, email: str) -> Any:
    """What a confined account may read of the log (audit S17): the entries
    about a poste it sees, and its own actions. The rest — accounts, groups,
    settings, bulk actions across the parc, postes elsewhere — names what its
    scope exists to keep out of its sight. None for the unrestricted."""
    if scope is None:
        return None
    visible = restrict(select(cast(col(Machine.id), String)), machine_clause(scope))
    return or_(
        and_(
            col(AuditEntry.resource_type) == "machine",
            col(AuditEntry.resource_id).in_(visible),
        ),
        col(AuditEntry.actor) == email,
    )


@router.get("", response_model=AuditList)
async def list_audit(
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
    action: str | None = None,
    actor: str | None = Query(None, max_length=320),
    resource_type: str | None = None,
    resource_id: str | None = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> AuditList:
    """The administrative actions log, newest first.

    ``action`` filters on the exact slug ("machine.revoke_token", …);
    ``actor`` on part of the acting account's e-mail; ``resource_id`` answers
    "what happened to this machine/account". ``since`` (inclusive) and
    ``until`` (exclusive) bound the period and must carry a time zone: the
    console sends the reader's local midnight, and a naive datetime would be
    silently read as UTC.
    """
    entries, total = await crud.list_entries(
        session,
        action=action,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        since=since,
        until=until,
        page=page,
        page_size=page_size,
        where=_scope_clause(scope, current.email),
    )
    return AuditList(
        items=[AuditEntryOut.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/actions", response_model=list[str])
async def list_audit_actions(session: SessionDep) -> list[str]:
    """The action slugs present in the log, for the console's filter."""
    return await crud.list_actions(session)
