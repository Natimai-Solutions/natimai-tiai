"""Maintenance: what is due, for whom, and the visits that were made.

``maintenance:read`` opens the lists; ``maintenance:write`` records a visit,
sets a poste's or a room's cycle and owner, and transfers an owner — which
is the same write, audited.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.intervention import crud as intervention_crud
from app.features.intervention.models import Intervention
from app.features.machine.models import Machine
from app.features.maintenance import crud
from app.features.maintenance.models import Maintenance
from app.features.maintenance.policy import MaintenanceState, Origin, Resolved
from app.features.room import crud as room_crud
from app.features.room.models import Room
from app.features.setting import crud as setting_crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource
from app.features.user.scope import (
    Scope,
    machine_clause,
    machine_ids_clause,
    machine_visible,
    restrict,
    room_clause,
)

_READ = Depends(require_permission(Resource.MAINTENANCE, Action.READ))
_WRITE = Depends(require_permission(Resource.MAINTENANCE, Action.WRITE))

router = APIRouter(prefix="/maintenance", tags=["maintenance"], dependencies=[_READ])
room_router = APIRouter(prefix="/rooms", tags=["maintenance"], dependencies=[_READ])
machine_router = APIRouter(
    prefix="/machines", tags=["maintenance"], dependencies=[_READ]
)


class UserRef(BaseModel):
    id: uuid.UUID
    name: str


class ResolvedOut(BaseModel):
    """A poste's maintenance as it resolves: the cycle and owner in force,
    where each came from, and where the poste stands on the cycle."""

    cycle_days: int
    cycle_origin: Origin
    owner: UserRef | None
    owner_origin: Origin
    last_maintenance_at: datetime | None
    due_at: datetime | None
    state: MaintenanceState


class MachineSettingsOut(BaseModel):
    """The poste's own overrides (null = inherit), and the resolution."""

    maintenance_cycle_days: int | None
    maintenance_owner: UserRef | None
    resolved: ResolvedOut


class RoomSettingsOut(BaseModel):
    maintenance_cycle_days: int | None
    maintenance_owner: UserRef | None
    effective_cycle_days: int
    effective_owner: UserRef | None


class SettingsUpdate(BaseModel):
    """Partial. ``maintenance_cycle_days``: null inherits, 0 excludes.
    ``maintenance_owner_id``: null inherits — a transfer is setting it."""

    maintenance_cycle_days: int | None = Field(default=None, ge=0, le=3650)
    maintenance_owner_id: uuid.UUID | None = None


class DueMachineOut(BaseModel):
    id: uuid.UUID
    hostname: str | None
    location: str | None
    room_name: str | None
    building_name: str | None
    last_maintenance_at: datetime | None
    due_at: datetime | None
    state: MaintenanceState
    owner: UserRef | None


class DueRoomOut(BaseModel):
    id: uuid.UUID
    name: str
    building_name: str | None
    location: str | None
    owner: UserRef | None
    cycle_days: int
    total: int
    overdue: int
    due_soon: int
    excluded: int
    next_due_at: datetime | None
    machines: list[DueMachineOut]


class DueOut(BaseModel):
    rooms: list[DueRoomOut]
    # Postes in no room, listed one by one.
    machines: list[DueMachineOut]
    overdue: int
    due_soon: int


class SessionItemIn(BaseModel):
    machine_id: uuid.UUID
    note: str | None = Field(default=None, max_length=5000)


class SessionCreate(BaseModel):
    """One visit. ``room_id`` names the room visited (for the record and the
    title); ``items`` says which postes were actually done — a poste absent
    or off that day is simply left out."""

    room_id: uuid.UUID | None = None
    # Not in the future: it would push the cycle out of reach (audit B06).
    performed_at: intervention_crud.PastDatetime | None = None
    note: str | None = Field(default=None, max_length=5000)
    items: list[SessionItemIn] = Field(min_length=1, max_length=1000)


class SessionItemOut(BaseModel):
    intervention_id: uuid.UUID
    machine_id: uuid.UUID
    hostname: str | None
    note: str | None


class SessionOut(BaseModel):
    id: uuid.UUID
    room_id: uuid.UUID | None
    room_name: str | None
    performed_by: str
    performed_at: datetime
    note: str | None
    machine_count: int
    items: list[SessionItemOut] = []


class SessionList(BaseModel):
    items: list[SessionOut]
    total: int
    page: int
    page_size: int


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    return cleaned or None


async def _require_machine(
    session: SessionDep, machine_id: uuid.UUID, scope: Scope | None
) -> Machine:
    machine = await session.get(Machine, machine_id)
    if machine is None or not await machine_visible(session, machine_id, scope):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    return machine


async def _require_room(
    session: SessionDep, room_id: uuid.UUID, scope: Scope | None
) -> Room:
    room = await session.get(Room, room_id)
    clause = room_clause(scope)
    if room is None or (
        clause is not None
        and (
            await session.exec(
                select(col(Room.id)).where(col(Room.id) == room_id).where(clause)
            )
        ).first()
        is None
    ):
        raise AppError(
            code=ErrorCode.ROOM_NOT_FOUND, status_code=404, message="Room not found"
        )
    return room


async def _require_owner(session: SessionDep, owner_id: uuid.UUID | None) -> None:
    if owner_id is None:
        return
    user = await session.get(User, owner_id)
    if user is None or not user.is_active:
        raise AppError(
            code=ErrorCode.USER_NOT_FOUND, status_code=404, message="User not found"
        )


def _ref(names: dict[uuid.UUID, str], user_id: uuid.UUID | None) -> UserRef | None:
    if user_id is None or user_id not in names:
        return None
    return UserRef(id=user_id, name=names[user_id])


def _resolved_out(
    machine: Machine, res: Resolved, names: dict[uuid.UUID, str]
) -> ResolvedOut:
    return ResolvedOut(
        cycle_days=res.cycle_days,
        cycle_origin=res.cycle_origin,
        owner=_ref(names, res.owner_id),
        owner_origin=res.owner_origin,
        last_maintenance_at=machine.last_maintenance_at,
        due_at=res.due_at,
        state=res.state,
    )


# --- Per poste and per room settings ------------------------------------------


@machine_router.get("/{machine_id}/maintenance", response_model=MachineSettingsOut)
async def machine_maintenance(
    machine_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> MachineSettingsOut:
    from app.features.maintenance.policy import resolve

    machine = await _require_machine(session, machine_id, scope)
    placement = await room_crud.placement(session, machine.room_id)
    policy = await setting_crud.maintenance_policy(session)
    res = resolve(machine, placement.room, policy, utcnow())
    names = await setting_crud.user_names(
        session, {i for i in (machine.maintenance_owner_id, res.owner_id) if i}
    )
    return MachineSettingsOut(
        maintenance_cycle_days=machine.maintenance_cycle_days,
        maintenance_owner=_ref(names, machine.maintenance_owner_id),
        resolved=_resolved_out(machine, res, names),
    )


@machine_router.patch(
    "/{machine_id}/maintenance",
    response_model=MachineSettingsOut,
    dependencies=[_WRITE],
)
async def update_machine_maintenance(
    machine_id: uuid.UUID,
    payload: SettingsUpdate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> MachineSettingsOut:
    machine = await _require_machine(session, machine_id, scope)
    fields = payload.model_dump(exclude_unset=True)
    if "maintenance_owner_id" in fields:
        await _require_owner(session, fields["maintenance_owner_id"])
        machine.maintenance_owner_id = fields["maintenance_owner_id"]
    if "maintenance_cycle_days" in fields:
        machine.maintenance_cycle_days = fields["maintenance_cycle_days"]
    machine.updated_at = utcnow()
    session.add(machine)
    audit.record(
        session,
        actor=current.email,
        action="maintenance.machine_settings",
        resource_type="machine",
        resource_id=str(machine.id),
        details={
            "hostname": machine.hostname,
            **{k: str(v) for k, v in fields.items()},
        },
    )
    await session.commit()
    await session.refresh(machine)
    return await machine_maintenance(machine.id, session, scope)


@room_router.get("/{room_id}/maintenance", response_model=RoomSettingsOut)
async def room_maintenance(
    room_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> RoomSettingsOut:
    room = await _require_room(session, room_id, scope)
    policy = await setting_crud.maintenance_policy(session)
    effective_owner = (
        room.maintenance_owner_id
        if room.maintenance_owner_id is not None
        else policy.owner_id
    )
    names = await setting_crud.user_names(
        session, {i for i in (room.maintenance_owner_id, effective_owner) if i}
    )
    return RoomSettingsOut(
        maintenance_cycle_days=room.maintenance_cycle_days,
        maintenance_owner=_ref(names, room.maintenance_owner_id),
        effective_cycle_days=(
            room.maintenance_cycle_days
            if room.maintenance_cycle_days is not None
            else policy.cycle_days
        ),
        effective_owner=_ref(names, effective_owner),
    )


@room_router.patch(
    "/{room_id}/maintenance", response_model=RoomSettingsOut, dependencies=[_WRITE]
)
async def update_room_maintenance(
    room_id: uuid.UUID,
    payload: SettingsUpdate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> RoomSettingsOut:
    room = await _require_room(session, room_id, scope)
    fields = payload.model_dump(exclude_unset=True)
    if "maintenance_owner_id" in fields:
        await _require_owner(session, fields["maintenance_owner_id"])
        room.maintenance_owner_id = fields["maintenance_owner_id"]
    if "maintenance_cycle_days" in fields:
        room.maintenance_cycle_days = fields["maintenance_cycle_days"]
    room.updated_at = utcnow()
    session.add(room)
    audit.record(
        session,
        actor=current.email,
        action="maintenance.room_settings",
        resource_type="room",
        resource_id=str(room.id),
        details={"name": room.name, **{k: str(v) for k, v in fields.items()}},
    )
    await session.commit()
    await session.refresh(room)
    return await room_maintenance(room.id, session, scope)


# --- What is due ----------------------------------------------------------------


@router.get("/due", response_model=DueOut)
async def due(
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
    owner: str | None = Query(
        None,
        description="An account id, 'me', 'none' for the unowned; absent = everybody",
    ),
) -> DueOut:
    """Rooms and room-less postes with where each stands on its cycle, for
    one owner or for everybody. Excluded postes are counted, not listed."""
    owner_id: uuid.UUID | None = None
    unowned = False
    if owner == "me":
        owner_id = current.id
    elif owner == "none":
        unowned = True
    elif owner:
        try:
            owner_id = uuid.UUID(owner)
        except ValueError:
            raise AppError(
                code=ErrorCode.REQUEST_VALIDATION_ERROR,
                status_code=422,
                message="owner must be an account id, 'me' or 'none'",
            ) from None
    policy = await setting_crud.maintenance_policy(session)
    now = utcnow()
    resolved = await crud.fleet_resolved(session, policy, now, machine_clause(scope))
    rooms, loose = crud.group_due(
        resolved, policy, owner_filter=owner_id, unowned=unowned
    )
    ids = {r.owner_id for r in rooms if r.owner_id}
    ids |= {res.owner_id for _, res in loose if res.owner_id}
    for r in rooms:
        ids |= {res.owner_id for _, res in r.machines if res.owner_id}
    names = await setting_crud.user_names(session, ids)

    def machine_out(
        m: Machine, res: Resolved, room: Room | None, building_name: str | None
    ) -> DueMachineOut:
        return DueMachineOut(
            id=m.id,
            hostname=m.hostname,
            location=m.location,
            room_name=room.name if room else None,
            building_name=building_name,
            last_maintenance_at=m.last_maintenance_at,
            due_at=res.due_at,
            state=res.state,
            owner=_ref(names, res.owner_id),
        )

    rooms_out = [
        DueRoomOut(
            id=r.room.id,
            name=r.room.name,
            building_name=r.building.name if r.building else None,
            location=room_crud.effective_location(r.room, r.building),
            owner=_ref(names, r.owner_id),
            cycle_days=r.cycle_days,
            total=r.total,
            overdue=r.overdue,
            due_soon=r.due_soon,
            excluded=r.excluded,
            next_due_at=r.next_due_at,
            machines=[
                machine_out(m, res, r.room, r.building.name if r.building else None)
                for m, res in sorted(
                    r.machines, key=lambda x: (x[1].due_at is None, x[1].due_at or now)
                )
            ],
        )
        for r in rooms
    ]
    loose_out = [machine_out(m, res, None, None) for m, res in loose]
    return DueOut(
        rooms=rooms_out,
        machines=loose_out,
        overdue=sum(r.overdue for r in rooms)
        + sum(1 for _, res in loose if res.state == MaintenanceState.OVERDUE),
        due_soon=sum(r.due_soon for r in rooms)
        + sum(1 for _, res in loose if res.state == MaintenanceState.DUE_SOON),
    )


# --- Sessions ---------------------------------------------------------------------


def _visit_clause(scope: Scope | None) -> Any:
    """A maintenance session is visible when its room is, or when one of the
    postes it covers is — a session recorded without a room has only those."""
    if scope is None:
        return None
    return or_(
        col(Maintenance.room_id).in_(
            select(col(Room.id)).where(room_clause(scope)).correlate(None)
        ),
        col(Maintenance.id).in_(
            select(col(Intervention.maintenance_id))
            .where(machine_ids_clause(scope, col(Intervention.machine_id)))
            .correlate(None)
        ),
    )


async def _session_out(
    session: SessionDep,
    visit: Maintenance,
    *,
    with_items: bool,
    scope: Scope | None = None,
) -> SessionOut:
    items = (
        await crud.session_items(session, visit.id, machine_clause(scope))
        if with_items
        else []
    )
    count = (await crud.item_counts(session, [visit.id], machine_clause(scope)))[
        visit.id
    ]
    return SessionOut(
        id=visit.id,
        room_id=visit.room_id,
        room_name=visit.room_name,
        performed_by=visit.performed_by,
        performed_at=visit.performed_at,
        note=visit.note,
        machine_count=count,
        items=[
            SessionItemOut(
                intervention_id=i.id, machine_id=m.id, hostname=m.hostname, note=i.note
            )
            for i, m in items
        ],
    )


@router.post("", response_model=SessionOut, status_code=201, dependencies=[_WRITE])
async def record_session(
    payload: SessionCreate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> SessionOut:
    """Record a visit: the global note, and one journal line per poste done."""
    room = (
        await _require_room(session, payload.room_id, scope)
        if payload.room_id
        else None
    )
    ids = [i.machine_id for i in payload.items]
    found = await session.exec(
        restrict(select(Machine).where(col(Machine.id).in_(ids)), machine_clause(scope))
    )
    machines = list(found.all())
    if len(machines) != len(set(ids)):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    notes = {i.machine_id: _clean(i.note) for i in payload.items}
    visit = await crud.record_session(
        session,
        room=room,
        machines=machines,
        notes=notes,
        performed_by=current.email,
        performed_at=payload.performed_at or utcnow(),
        note=_clean(payload.note),
    )
    await session.commit()
    await session.refresh(visit)
    return await _session_out(session, visit, with_items=True, scope=scope)


@router.get("", response_model=SessionList)
async def list_sessions(
    session: SessionDep,
    scope: CurrentScope,
    room_id: uuid.UUID | None = None,
    machine_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> SessionList:
    """Visits, newest first, for a room, a poste, or the parc."""
    rows, total = await crud.list_sessions(
        session,
        room_id=room_id,
        machine_id=machine_id,
        page=page,
        page_size=page_size,
        where=_visit_clause(scope),
    )
    counts = await crud.item_counts(
        session, [r.id for r in rows], machine_clause(scope)
    )
    return SessionList(
        items=[
            SessionOut(
                id=r.id,
                room_id=r.room_id,
                room_name=r.room_name,
                performed_by=r.performed_by,
                performed_at=r.performed_at,
                note=r.note,
                machine_count=counts.get(r.id, 0),
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{maintenance_id}", response_model=SessionOut)
async def get_session(
    maintenance_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> SessionOut:
    visit = await session.get(Maintenance, maintenance_id)
    clause = _visit_clause(scope)
    if visit is None or (
        clause is not None
        and (
            await session.exec(
                select(col(Maintenance.id))
                .where(col(Maintenance.id) == maintenance_id)
                .where(clause)
            )
        ).first()
        is None
    ):
        raise AppError(
            code=ErrorCode.MAINTENANCE_NOT_FOUND,
            status_code=404,
            message="Maintenance session not found",
        )
    # The visit is visible through one of its postes; the others may lie
    # outside the caller's scope (audit S06).
    return await _session_out(session, visit, with_items=True, scope=scope)
