"""Maintenance: what is due, for whom, and the visits that were made.

``maintenance:read`` opens the lists; ``maintenance:write`` records a visit,
sets a poste's or a room's cycle and owner, and transfers an owner — which
is the same write, audited.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlmodel import col, select

from app.api.deps import (
    CurrentScope,
    CurrentUser,
    SessionDep,
    require_any_permission,
    require_permission,
)
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.intervention import crud as intervention_crud
from app.features.intervention.models import Intervention, InterventionKind
from app.features.machine.models import Machine
from app.features.maintenance import crud
from app.features.maintenance.models import Maintenance
from app.features.maintenance.policy import (
    MaintenanceState,
    Origin,
    Resolved,
    available,
)
from app.features.maintenance.reach import owner_reach
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
# Who may be named owner: asked by whoever sets one — on a poste or a room
# (maintenance:write), or as the parc's default (settings:write). Registered
# before ``router``, whose ``/{maintenance_id}`` would take the path.
owners_router = APIRouter(
    prefix="/maintenance",
    tags=["maintenance"],
    dependencies=[
        Depends(
            require_any_permission(
                (Resource.MAINTENANCE, Action.WRITE),
                (Resource.SETTINGS, Action.WRITE),
            )
        )
    ],
)


class UserRef(BaseModel):
    id: uuid.UUID
    name: str
    # False for an account deactivated since it was named: the console shows
    # « (désactivé) » rather than an id it cannot find among the choices.
    active: bool = True


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
    # Where each effective value comes from: the room, or the parc's default
    # — the room's own owner, deactivated or out of reach, counts as none.
    effective_cycle_origin: Literal["room", "global"] = "global"
    effective_owner_origin: Literal["room", "global"] = "global"


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
    # One room can be several groups — its own, and one per (owner, cycle)
    # its postes override it with: this tells them apart.
    key: str
    # "room": the postes following the room's owner and cycle — taking it
    # sets the room's owner. "machine": postes overriding them — taking it
    # sets those postes' own owner.
    level: Literal["room", "machine"] = "room"
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


# Lines per request, done and left out each: bounds one transaction and one
# request body (Caddy caps it at 8 MB). A larger room is sent in parts, the
# first creating the visit and the next ones added to it (``/lines``).
SESSION_LINES_MAX = 1000


class SessionCreate(BaseModel):
    """One visit. ``room_id`` names the room visited (for the record and the
    title); ``items`` says which postes were actually done — a poste absent
    or off that day is simply left out. A visit where nothing was done is
    recorded too, as long as it says why (audit T30)."""

    # Chosen by the console, so that this request can be sent again: when its
    # answer was lost, the second one gets the visit the first created
    # instead of creating its twin. Absent: the server chooses, as before.
    id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    # Not in the future: it would push the cycle out of reach (audit B06).
    performed_at: intervention_crud.PastDatetime | None = None
    note: str | None = Field(default=None, max_length=5000)
    items: list[SessionItemIn] = Field(
        default_factory=list, max_length=SESSION_LINES_MAX
    )
    # Postes left out, with why (« absent de la salle ») — written to their
    # own journal as « Maintenance non faite », their cycle untouched.
    skipped: list[SessionItemIn] = Field(
        default_factory=list, max_length=SESSION_LINES_MAX
    )


class SessionLinesIn(BaseModel):
    """More postes of a visit already recorded: the next part of a room too
    large for one request."""

    items: list[SessionItemIn] = Field(
        default_factory=list, max_length=SESSION_LINES_MAX
    )
    skipped: list[SessionItemIn] = Field(
        default_factory=list, max_length=SESSION_LINES_MAX
    )


class SessionItemOut(BaseModel):
    intervention_id: uuid.UUID
    machine_id: uuid.UUID
    hostname: str | None
    note: str | None


class SessionOut(BaseModel):
    id: uuid.UUID
    # Null for a confined reader when the room visited is outside its scope:
    # the visit is visible through one of its postes, not its room.
    room_id: uuid.UUID | None
    room_name: str | None
    performed_by: str
    performed_at: datetime
    # The visit's global observation, about the room and all its postes: null
    # for a confined reader unless the whole visit is in its scope.
    note: str | None
    # The postes still maintained by it: its remaining ``maintenance`` lines.
    machine_count: int
    items: list[SessionItemOut] = []
    # Postes left out, with why — and lines of the visit turned since into
    # another kind: in the session's record, not counted as maintained.
    skipped: list[SessionItemOut] = []
    # Part of the visit (its room, postes, or the global note) lies beyond
    # the caller's scope and is left out of this payload (audit S06).
    partial: bool = False


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


async def _owner_reaches(
    session: SessionDep,
    user_id: uuid.UUID,
    *,
    machine_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
) -> bool:
    """Whether the account can own this poste's or this room's maintenance:
    read the maintenance lists and record a visit, and see the poste — for a
    room, the room itself, which means seeing every poste filed in it. The
    rule of checks' ``_can_take``: an owner is mailed the hostnames of what
    they own, and must not be handed postes kept out of their sight (audit
    S18, T32). The rule itself is ``maintenance.reach``'s, the one the
    resolution applies again each time it names an owner."""
    reach = await owner_reach(session, {user_id})
    if machine_id is not None:
        machine = await session.get(Machine, machine_id)
        return machine is not None and reach.machine(user_id, machine)
    if room_id is not None:
        return reach.room(user_id, room_id)
    return reach.parc(user_id)


async def _require_owner(
    session: SessionDep,
    owner_id: uuid.UUID | None,
    *,
    machine_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
) -> None:
    if owner_id is None:
        return
    user = await session.get(User, owner_id)
    if user is None or not user.is_active:
        raise AppError(
            code=ErrorCode.USER_NOT_FOUND, status_code=404, message="User not found"
        )
    if not await _owner_reaches(
        session, user.id, machine_id=machine_id, room_id=room_id
    ):
        raise AppError(
            code=ErrorCode.MAINTENANCE_OWNER_OUT_OF_REACH,
            status_code=422,
            message="This account cannot own the maintenance of these postes",
        )


class OwnerChoice(BaseModel):
    """An account the picker offers: id and name only."""

    id: uuid.UUID
    name: str


def _ref(
    names: dict[uuid.UUID, str],
    user_id: uuid.UUID | None,
    inactive: frozenset[uuid.UUID] = frozenset(),
) -> UserRef | None:
    if user_id is None or user_id not in names:
        return None
    return UserRef(id=user_id, name=names[user_id], active=user_id not in inactive)


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
        maintenance_owner=_ref(
            names, machine.maintenance_owner_id, policy.inactive_owners
        ),
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
        # Re-sending the current owner, deactivated since, is not choosing
        # them: the form must still save its other fields (audit B08).
        if fields["maintenance_owner_id"] != machine.maintenance_owner_id:
            await _require_owner(
                session, fields["maintenance_owner_id"], machine_id=machine.id
            )
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
    own_owner = available(room.maintenance_owner_id, policy, room=room)
    effective_owner = room.maintenance_owner_id if own_owner else policy.owner_id
    names = await setting_crud.user_names(
        session, {i for i in (room.maintenance_owner_id, effective_owner) if i}
    )
    return RoomSettingsOut(
        maintenance_cycle_days=room.maintenance_cycle_days,
        maintenance_owner=_ref(
            names, room.maintenance_owner_id, policy.inactive_owners
        ),
        effective_cycle_days=(
            room.maintenance_cycle_days
            if room.maintenance_cycle_days is not None
            else policy.cycle_days
        ),
        effective_owner=_ref(names, effective_owner),
        effective_cycle_origin=(
            "room" if room.maintenance_cycle_days is not None else "global"
        ),
        effective_owner_origin="room" if own_owner else "global",
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
        if fields["maintenance_owner_id"] != room.maintenance_owner_id:
            await _require_owner(
                session, fields["maintenance_owner_id"], room_id=room.id
            )
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


@owners_router.get("/assignable-owners", response_model=list[OwnerChoice])
async def assignable_owners(
    session: SessionDep,
    scope: CurrentScope,
    machine_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
) -> list[OwnerChoice]:
    """Active accounts that may be named owner — of this poste, of this room,
    or, with neither, of the parc by default: exactly those the write that
    follows accepts. Id and name only, like ``/checks/assignable-users``,
    which offered every account that may read a check and left the server to
    refuse most of them."""
    if machine_id is not None and room_id is not None:
        raise AppError(
            code=ErrorCode.REQUEST_VALIDATION_ERROR,
            status_code=422,
            message="Give machine_id or room_id, not both",
        )
    # Out of the caller's own reach: who could own it is not theirs to learn.
    machine = (
        await _require_machine(session, machine_id, scope)
        if machine_id is not None
        else None
    )
    if room_id is not None:
        await _require_room(session, room_id, scope)
    rows = await session.exec(
        select(User).where(col(User.is_active).is_(True)).order_by(col(User.email))
    )
    users = list(rows.all())
    reach = await owner_reach(session, {u.id for u in users})

    def can_own(user_id: uuid.UUID) -> bool:
        if machine is not None:
            return reach.machine(user_id, machine)
        if room_id is not None:
            return reach.room(user_id, room_id)
        return reach.parc(user_id)

    return [
        OwnerChoice(id=u.id, name=u.full_name or u.email)
        for u in users
        if can_own(u.id)
    ]


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
            key=(
                str(r.room.id)
                if r.room_level
                else f"{r.room.id}:{r.owner_id or '-'}:{r.cycle_days}"
            ),
            level="room" if r.room_level else "machine",
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


@dataclass(frozen=True)
class _Reach:
    """How much of a visit a caller may read: its room (name and id), and the
    whole of it — room and every poste — which the global note speaks for."""

    room: bool
    whole: bool


_FULL = _Reach(room=True, whole=True)


async def _reach(
    session: SessionDep, visits: list[Maintenance], scope: Scope | None
) -> dict[uuid.UUID, _Reach]:
    """A confined account sees a visit through one poste of it (audit S06);
    the room's name is the room's, and the note is about the room and all
    its postes, so neither follows that one poste. A visit recorded without
    a room is named by its postes alone.

    A visit whose room was deleted since is never whole for a confined
    account: whether that room was in its scope can no longer be told, and a
    visit whose name and note were withheld must not hand them over — nor
    become the account's to delete — the day the room goes."""
    if scope is None:
        return {v.id: _FULL for v in visits}
    room_ids = {v.room_id for v in visits if v.room_id is not None}
    rooms: set[uuid.UUID] = set()
    if room_ids:
        found = await session.exec(
            select(col(Room.id))
            .where(col(Room.id).in_(room_ids))
            .where(room_clause(scope))
        )
        rooms = set(found.all())
    lines = await crud.line_counts(
        session, [v.id for v in visits], machine_clause(scope)
    )
    out: dict[uuid.UUID, _Reach] = {}
    for v in visits:
        total, seen = lines[v.id]
        postes = seen == total
        if v.room_id is None:
            # The name is kept on the visit when its room goes: it tells a
            # room deleted from a visit that never had one.
            room = postes and v.room_name is None
        else:
            room = v.room_id in rooms
        out[v.id] = _Reach(room=room, whole=room and postes)
    return out


def _out(
    visit: Maintenance,
    reach: _Reach,
    count: int,
    items: list[tuple[Intervention, Machine]] | None = None,
) -> SessionOut:
    def item(i: Intervention, m: Machine) -> SessionItemOut:
        return SessionItemOut(
            intervention_id=i.id, machine_id=m.id, hostname=m.hostname, note=i.note
        )

    done = InterventionKind.MAINTENANCE.value
    return SessionOut(
        id=visit.id,
        room_id=visit.room_id if reach.room else None,
        room_name=visit.room_name if reach.room else None,
        performed_by=visit.performed_by,
        performed_at=visit.performed_at,
        note=visit.note if reach.whole else None,
        machine_count=count,
        items=[item(i, m) for i, m in items or [] if i.kind == done],
        skipped=[item(i, m) for i, m in items or [] if i.kind != done],
        partial=not reach.whole,
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
    reach = (await _reach(session, [visit], scope))[visit.id]
    return _out(visit, reach, count, items)


@dataclass
class _Lines:
    machines: list[Machine]
    notes: dict[uuid.UUID, str | None]
    skipped: dict[uuid.UUID, str]


async def _resolve_lines(
    session: SessionDep,
    scope: Scope | None,
    room_id: uuid.UUID | None,
    items: list[SessionItemIn],
    skipped_in: list[SessionItemIn],
) -> _Lines:
    """The postes of a visit, checked: each in the caller's scope, and in the
    room visited when there is one."""
    ids = [i.machine_id for i in items]
    # Only a skipped poste with something to say is written; one also done
    # is done.
    skipped = {
        i.machine_id: reason
        for i in skipped_in
        if (reason := _clean(i.note)) and i.machine_id not in set(ids)
    }
    wanted = set(ids) | set(skipped)
    every: list[Machine] = []
    if wanted:
        found = await session.exec(
            restrict(
                select(Machine).where(col(Machine.id).in_(wanted)),
                machine_clause(scope),
            )
        )
        every = list(found.all())
    if len(every) != len(wanted):
        # Named, among those the caller sent: a visit sent in parts must be
        # able to leave out the poste deleted, or merged, since it started.
        missing = wanted - {m.id for m in every}
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
            details={"machine_ids": sorted(str(i) for i in missing)},
        )
    if room_id is not None:
        # A visit of a room is the visit of its postes: a poste filed
        # elsewhere would get a line « Maintenance — <this room> » it never
        # had (the console only ever offers the room's own).
        strays = sorted(
            (m for m in every if m.room_id != room_id),
            key=lambda m: (m.hostname or "").lower(),
        )
        if strays:
            names = [m.hostname or str(m.id) for m in strays]
            raise AppError(
                code=ErrorCode.MAINTENANCE_ITEMS_NOT_IN_ROOM,
                status_code=422,
                message="Postes not in this room: " + ", ".join(names),
                details={
                    "machine_ids": [str(m.id) for m in strays],
                    "hostnames": names,
                },
            )
    return _Lines(
        machines=[m for m in every if m.id in set(ids)],
        notes={i.machine_id: _clean(i.note) for i in items},
        skipped=skipped,
    )


async def _already_recorded(
    session: SessionDep, visit_id: uuid.UUID, author: str, scope: Scope | None
) -> SessionOut | None:
    """The visit a creating request names by ``id``, when it exists already:
    the caller's own is given back as it stands — whatever this second
    request carries, nothing is written; somebody else's is a conflict."""
    visit = await session.get(Maintenance, visit_id)
    if visit is None:
        return None
    if visit.performed_by != author:
        raise AppError(
            code=ErrorCode.MAINTENANCE_SESSION_ID_TAKEN,
            status_code=409,
            message="This id is the visit of another account",
        )
    return await _session_out(session, visit, with_items=True, scope=scope)


@router.post("", response_model=SessionOut, status_code=201, dependencies=[_WRITE])
async def record_session(
    payload: SessionCreate,
    response: Response,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> SessionOut:
    """Record a visit: the global note, and one journal line per poste done.

    With an ``id``, the request may be sent again: once the visit exists, it
    is returned (200, nothing written) rather than created a second time — a
    large room's first part, like its next ones (``/lines``), survives a lost
    answer. Checked before the postes are: a retry is answered even if one
    of them has left the room since."""
    author = current.email
    if payload.id is not None:
        recorded = await _already_recorded(session, payload.id, author, scope)
        if recorded is not None:
            response.status_code = 200
            return recorded
    room = (
        await _require_room(session, payload.room_id, scope)
        if payload.room_id
        else None
    )
    lines = await _resolve_lines(
        session, scope, room.id if room else None, payload.items, payload.skipped
    )
    note = _clean(payload.note)
    # Nothing done is a visit too — the room was closed, every poste was
    # off — but only one that says why: a poste left out with its reason,
    # or the room's global note. Recorded, it moves no poste's cycle.
    if not lines.machines and not lines.skipped and not (room and note):
        raise AppError(
            code=ErrorCode.MAINTENANCE_SESSION_EMPTY,
            status_code=422,
            message="A visit with no poste done must say why: a note on a "
            "poste left out, or the room's global note",
        )
    visit = await crud.record_session(
        session,
        room=room,
        machines=lines.machines,
        notes=lines.notes,
        performed_by=author,
        performed_at=payload.performed_at or utcnow(),
        note=note,
        skipped=lines.skipped,
        visit_id=payload.id,
    )
    if visit is None:
        # The same request, served at the same time, created the visit while
        # this one was checking its postes: committed by now, it is the answer.
        assert payload.id is not None
        recorded = await _already_recorded(session, payload.id, author, scope)
        if recorded is None:
            # Created, then deleted, within this request: nothing to return.
            raise _session_not_found()
        response.status_code = 200
        return recorded
    await session.commit()
    await session.refresh(visit)
    return await _session_out(session, visit, with_items=True, scope=scope)


@router.post(
    "/{maintenance_id}/lines", response_model=SessionOut, dependencies=[_WRITE]
)
async def add_session_lines(
    maintenance_id: uuid.UUID,
    payload: SessionLinesIn,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> SessionOut:
    """The next part of a visit: postes done or left out, dated and titled as
    the visit. For a room larger than one request (audit T30), so that it
    stays one visit. Only its author adds to it; a poste that already has a
    line in it is passed over, so a part sent twice (a retry after a lost
    answer) writes nothing twice."""
    visit = await _require_session(session, maintenance_id, scope)
    if visit.performed_by != current.email:
        raise AppError(
            code=ErrorCode.MAINTENANCE_SESSION_NOT_AUTHOR,
            status_code=403,
            message="Only the author of a visit adds postes to it",
        )
    # Serialise the parts of one visit: two retries at once would each find
    # the poste unlined and write it twice. Its deletion takes the same lock:
    # a part that waited behind it finds the visit gone.
    if not await crud.lock_session(session, visit.id):
        raise _session_not_found()
    # Passed over before they are checked: the retry of a part already
    # recorded succeeds even if one of its postes has changed room, or left
    # the caller's scope, since — its line is written, there is nothing to ask.
    known = await crud.lined_machines(
        session,
        visit.id,
        {i.machine_id for i in payload.items} | {i.machine_id for i in payload.skipped},
    )
    room = await session.get(Room, visit.room_id) if visit.room_id else None
    lines = await _resolve_lines(
        session,
        scope,
        room.id if room else None,
        [i for i in payload.items if i.machine_id not in known],
        [i for i in payload.skipped if i.machine_id not in known],
    )
    await crud.add_lines(
        session,
        visit,
        machines=lines.machines,
        notes=lines.notes,
        skipped=lines.skipped,
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
    if machine_id is not None and not await machine_visible(session, machine_id, scope):
        # As for a poste that does not exist: a visit the caller sees through
        # one poste must not say which of the postes it cannot see were in it.
        return SessionList(items=[], total=0, page=page, page_size=page_size)
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
    reach = await _reach(session, rows, scope)
    return SessionList(
        items=[_out(r, reach[r.id], counts.get(r.id, 0)) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def _session_not_found() -> AppError:
    return AppError(
        code=ErrorCode.MAINTENANCE_NOT_FOUND,
        status_code=404,
        message="Maintenance session not found",
    )


async def _require_session(
    session: SessionDep, maintenance_id: uuid.UUID, scope: Scope | None
) -> Maintenance:
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
        raise _session_not_found()
    return visit


@router.get("/{maintenance_id}", response_model=SessionOut)
async def get_session(
    maintenance_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> SessionOut:
    visit = await _require_session(session, maintenance_id, scope)
    # The visit is visible through one of its postes; the others may lie
    # outside the caller's scope (audit S06).
    return await _session_out(session, visit, with_items=True, scope=scope)


@router.delete("/{maintenance_id}", status_code=204, dependencies=[_WRITE])
async def delete_session(
    maintenance_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> None:
    """Remove a visit recorded by mistake: the session, and every journal
    line it wrote. The postes' last maintenance goes back to what their
    journal then says. Audited, with what was removed."""
    visit = await _require_session(session, maintenance_id, scope)
    # Before its lines are read: a part being added (``/lines``) holds this
    # lock until it is committed — the deletion waits for it, then reads its
    # lines with the others — and a part arriving behind the deletion waits
    # in turn, and finds the visit gone. Every line goes with the visit;
    # none is left detached from it.
    if not await crud.lock_session(session, visit.id):
        raise _session_not_found()
    lines = await crud.session_items(session, visit.id)
    # Every line is removed, and the global note with them: a confined account
    # may only remove a visit wholly in its scope — its room and every poste
    # (audit S06). The trace written below would otherwise hand it the room's
    # name and the note it is not shown.
    if not (await _reach(session, [visit], scope))[visit.id].whole:
        raise AppError(
            code=ErrorCode.AUTH_SCOPE_RESTRICTED,
            status_code=403,
            message="This visit covers a room or postes beyond your scope",
        )
    audit.record(
        session,
        actor=current.email,
        action="maintenance.delete",
        resource_type="maintenance",
        resource_id=str(visit.id),
        details={
            "room_name": visit.room_name,
            "performed_by": visit.performed_by,
            "performed_at": visit.performed_at.isoformat(),
            "note": visit.note,
            "hostnames": sorted(m.hostname or str(m.id) for _, m in lines),
            "lines": len(lines),
        },
    )
    await crud.delete_session(session, visit)
    await session.commit()
