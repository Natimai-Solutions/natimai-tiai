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
from app.features.room.models import Room
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope, machine_clause, restrict, room_clause

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


# What a ``machine.merge`` entry says of the record merged away: another
# poste, which may have stood on a site the reader does not see although the
# record kept is in its scope (audit S17).
_MERGE_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "source_hostname",
        "source_machine_uuid",
        "source_location",
        "source_room_id",
    }
)


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def _entries_out(
    session: SessionDep, entries: list[AuditEntry], scope: Scope | None, email: str
) -> list[AuditEntryOut]:
    """The entries as a reader may see them. A confined reader sees a merge on
    a poste of its scope, but the merged record's identity only when that
    record stood in its scope too — by the site its agent reported or by its
    room, as ``machine_clause`` would have seen it. The record is gone: its
    place is what the entry noted at the merge, and an entry written before
    that was noted says nothing of it, so it is withheld. Its own merges are
    left whole: it could only merge what it saw."""
    out = [AuditEntryOut.model_validate(e) for e in entries]
    if scope is None:
        return out
    merges = [
        e
        for e in out
        if e.action == "machine.merge"
        and e.actor != email
        and _MERGE_SOURCE_KEYS & e.details.keys()
    ]
    if not merges:
        return out
    room_ids = {rid for e in merges if (rid := _uuid(e.details.get("source_room_id")))}
    rooms: set[uuid.UUID] = set()
    if room_ids:
        found = await session.exec(
            select(col(Room.id))
            .where(col(Room.id).in_(room_ids))
            .where(room_clause(scope))
        )
        rooms = set(found.all())
    for e in merges:
        location = e.details.get("source_location")
        room_id = _uuid(e.details.get("source_room_id"))
        if location in scope.locations or (room_id is not None and room_id in rooms):
            continue
        e.details = {
            k: v for k, v in e.details.items() if k not in _MERGE_SOURCE_KEYS
        } | {"source_withheld": True}
    return out


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
        items=await _entries_out(session, entries, scope, current.email),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/actions", response_model=list[str])
async def list_audit_actions(session: SessionDep) -> list[str]:
    """The action slugs present in the log, for the console's filter."""
    return await crud.list_actions(session)
