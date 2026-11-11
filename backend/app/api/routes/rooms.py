"""Buildings and rooms: where the postes are, as the console organises it.

Two routers in one module because they are one feature: a room sits in a
building, a building sits on a site, and the site is what a poste's agent
may disagree with (``features/room``). Reading either takes ``room:read``;
changing either, or moving a poste, takes ``room:write``.

Placing a poste by hand is always allowed here; the directory-driven mode
(``ROOM_SOURCE``, next milestone) will lock it.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.api.routes.agent import clean_location
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.maintenance import crud as maintenance_crud
from app.features.maintenance.policy import MaintenanceState
from app.features.room import crud
from app.features.room.models import Building, Room
from app.features.setting import crud as setting_crud
from app.features.user.permissions import Action, Resource
from app.features.user.scope import (
    Scope,
    building_clause,
    machine_clause,
    restrict,
    room_clause,
)

_READ = Depends(require_permission(Resource.ROOM, Action.READ))
_WRITE = Depends(require_permission(Resource.ROOM, Action.WRITE))

buildings_router = APIRouter(prefix="/buildings", tags=["rooms"], dependencies=[_READ])
rooms_router = APIRouter(prefix="/rooms", tags=["rooms"], dependencies=[_READ])


# --- Schemas ----------------------------------------------------------------


class BuildingOut(BaseModel):
    id: uuid.UUID
    name: str
    # The site, in the agents' words. Null for a building nobody placed yet.
    location: str | None
    notes: str | None
    room_count: int
    machine_count: int
    created_at: datetime
    updated_at: datetime


class BuildingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class BuildingUpdate(BaseModel):
    """Partial update — only the supplied fields are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class BuildingRef(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None

    model_config = {"from_attributes": True}


class RoomOut(BaseModel):
    id: uuid.UUID
    name: str
    building: BuildingRef | None
    # The room's own site — only read when it has no building.
    location: str | None
    # The site the room is on: its building's, else its own. What a poste's
    # agent is compared against.
    effective_location: str | None
    notes: str | None
    # Set on a room the directory created (the OU's DN, or the location
    # string): the console says so, and its membership is not editable.
    ad_key: str | None
    machine_count: int
    # Postes of this room whose agent names another site.
    mismatch_count: int
    # Maintenance: the room's own settings (null = inherit) and what they
    # resolve to, and where its postes stand on the cycle.
    maintenance_cycle_days: int | None
    maintenance_owner_name: str | None
    effective_cycle_days: int
    effective_owner_name: str | None
    maintenance_overdue: int
    maintenance_due_soon: int
    created_at: datetime
    updated_at: datetime


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    building_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class RoomUpdate(BaseModel):
    """Partial update — only the supplied fields are changed. ``building_id``
    set to null takes the room out of its building."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    building_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class RoomConfigOut(BaseModel):
    """How postes are filed: by hand, or by the directory (``ROOM_SOURCE``).
    The console reads it to lock the placement controls in a directory mode."""

    source: str
    manual: bool


class SyncOut(BaseModel):
    """What re-filing the parc from the directory did."""

    placed: int
    unplaced: int
    rooms_created: int


class MachineIds(BaseModel):
    machine_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class PlacementResult(BaseModel):
    """What moving postes did, and which of them now disagree on the site —
    the console warns on those rather than the server refusing them."""

    moved: int
    mismatched: list[uuid.UUID]


# --- Helpers ----------------------------------------------------------------


async def _visible(
    session: SessionDep, model: Any, ident: uuid.UUID, clause: Any
) -> bool:
    if clause is None:
        return True
    found = await session.exec(select(model.id).where(model.id == ident).where(clause))
    return found.first() is not None


def _reject_out_of_scope(allowed: bool) -> None:
    if not allowed:
        raise AppError(
            code=ErrorCode.AUTH_SCOPE_RESTRICTED,
            status_code=403,
            message="This reaches beyond the places your account is confined to",
        )


def _building_writable(building: Building, scope: Scope | None) -> bool:
    """A confined account edits a building only when its scope names it, or
    its site — not merely one of its rooms, which shows the building but does
    not hand over the whole of it."""
    return (
        scope is None
        or building.id in scope.buildings
        or (building.location is not None and building.location in scope.locations)
    )


def _site_move_allowed(scope: Scope | None, old: str | None, new: str | None) -> bool:
    """Whether a confined account may move a place from site ``old`` to site
    ``new``: only between sites it covers. A building or room it holds by id
    would otherwise carry its postes into another team's site, out of its
    own (audit S16)."""
    if scope is None or old == new:
        return True
    return old in scope.locations and new in scope.locations


async def _room_site(session: SessionDep, room: Room) -> str | None:
    """Where a room is: its building's site, or its own."""
    if room.building_id is not None:
        building = await session.get(Building, room.building_id)
        return building.location if building else None
    return room.location


async def _room_writable(
    session: SessionDep, room_id: uuid.UUID, scope: Scope | None
) -> bool:
    """A room is the account's to edit if it is in its scope — checked against
    the flushed state, so a move out of scope is refused as well."""
    await session.flush()
    return await _visible(session, Room, room_id, room_clause(scope))


async def _require_building(
    session: SessionDep, building_id: uuid.UUID, scope: Scope | None = None
) -> Building:
    building = await crud.get_building(session, building_id)
    if building is None or not await _visible(
        session, Building, building_id, building_clause(scope)
    ):
        raise AppError(
            code=ErrorCode.BUILDING_NOT_FOUND,
            status_code=404,
            message="Building not found",
        )
    return building


async def _require_room(
    session: SessionDep, room_id: uuid.UUID, scope: Scope | None = None
) -> Room:
    room = await crud.get_room(session, room_id)
    if room is None or not await _visible(session, Room, room_id, room_clause(scope)):
        raise AppError(
            code=ErrorCode.ROOM_NOT_FOUND, status_code=404, message="Room not found"
        )
    return room


async def _reject_building_name_taken(
    session: SessionDep,
    location: str | None,
    name: str,
    *,
    exclude: uuid.UUID | None = None,
) -> None:
    existing = await crud.building_by_name(session, location, name)
    if existing is not None and existing.id != exclude:
        raise AppError(
            code=ErrorCode.BUILDING_NAME_TAKEN,
            status_code=409,
            message="A building of this name already exists on this site",
        )


async def _reject_room_name_taken(
    session: SessionDep,
    building_id: uuid.UUID | None,
    name: str,
    *,
    exclude: uuid.UUID | None = None,
) -> None:
    existing = await crud.room_by_name(session, building_id, name)
    if existing is not None and existing.id != exclude:
        raise AppError(
            code=ErrorCode.ROOM_NAME_TAKEN,
            status_code=409,
            message="A room of this name already exists in this building",
        )


def _clean_name(name: str) -> str:
    return " ".join(name.split())


def _reject_locked_placement() -> None:
    """In a directory mode, a placement made by hand would be undone on the
    poste's next inventory: refused, with the mode named, rather than
    silently overwritten."""
    if settings.ROOM_SOURCE != "manual":
        raise AppError(
            code=ErrorCode.ROOM_PLACEMENT_LOCKED,
            status_code=409,
            message="Postes are filed by the directory (ROOM_SOURCE); "
            "manual placement is disabled",
            details={"source": settings.ROOM_SOURCE},
        )


async def _buildings_out(
    session: SessionDep, buildings: list[Building]
) -> list[BuildingOut]:
    counts = await crud.building_counts(session, [b.id for b in buildings])
    return [
        BuildingOut(
            id=b.id,
            name=b.name,
            location=b.location,
            notes=b.notes,
            room_count=counts[b.id].rooms,
            machine_count=counts[b.id].machines,
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
        for b in buildings
    ]


async def _rooms_out(
    session: SessionDep, rooms: list[tuple[Room, Building | None]]
) -> list[RoomOut]:
    counts = await crud.room_counts(session, [r.id for r, _ in rooms])
    policy = await setting_crud.maintenance_policy(session)
    resolved = await maintenance_crud.fleet_resolved(session, policy, utcnow())
    overdue: dict[uuid.UUID, int] = {}
    due_soon: dict[uuid.UUID, int] = {}
    for m, _room, _building, res in resolved:
        if m.room_id is None:
            continue
        if res.state == MaintenanceState.OVERDUE:
            overdue[m.room_id] = overdue.get(m.room_id, 0) + 1
        elif res.state == MaintenanceState.DUE_SOON:
            due_soon[m.room_id] = due_soon.get(m.room_id, 0) + 1
    owner_ids = {r.maintenance_owner_id for r, _ in rooms if r.maintenance_owner_id}
    if policy.owner_id:
        owner_ids.add(policy.owner_id)
    names = await setting_crud.user_names(session, owner_ids)

    def effective_owner_name(r: Room) -> str | None:
        owner = (
            r.maintenance_owner_id
            if r.maintenance_owner_id is not None
            else policy.owner_id
        )
        return names.get(owner) if owner is not None else None

    return [
        RoomOut(
            id=r.id,
            name=r.name,
            building=BuildingRef.model_validate(b) if b else None,
            location=r.location,
            effective_location=crud.effective_location(r, b),
            notes=r.notes,
            ad_key=r.ad_key,
            machine_count=counts[r.id].machines,
            mismatch_count=counts[r.id].mismatched,
            maintenance_cycle_days=r.maintenance_cycle_days,
            maintenance_owner_name=(
                names.get(r.maintenance_owner_id) if r.maintenance_owner_id else None
            ),
            effective_cycle_days=(
                r.maintenance_cycle_days
                if r.maintenance_cycle_days is not None
                else policy.cycle_days
            ),
            effective_owner_name=effective_owner_name(r),
            maintenance_overdue=overdue.get(r.id, 0),
            maintenance_due_soon=due_soon.get(r.id, 0),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r, b in rooms
    ]


async def _room_out(session: SessionDep, room: Room) -> RoomOut:
    building = (
        await crud.get_building(session, room.building_id) if room.building_id else None
    )
    return (await _rooms_out(session, [(room, building)]))[0]


# --- Buildings --------------------------------------------------------------


@buildings_router.get("", response_model=list[BuildingOut])
async def list_buildings(session: SessionDep, scope: CurrentScope) -> list[BuildingOut]:
    """Every building, by site then name. Not paginated: a parc has dozens."""
    return await _buildings_out(
        session, await crud.list_buildings(session, building_clause(scope))
    )


@buildings_router.post(
    "", response_model=BuildingOut, status_code=201, dependencies=[_WRITE]
)
async def create_building(
    payload: BuildingCreate,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> BuildingOut:
    name = _clean_name(payload.name)
    location = clean_location(payload.location)
    _reject_out_of_scope(
        scope is None or (location is not None and location in scope.locations)
    )
    await _reject_building_name_taken(session, location, name)
    building = Building(name=name, location=location, notes=payload.notes)
    session.add(building)
    await session.flush()
    audit.record(
        session,
        actor=current.email,
        action="building.create",
        resource_type="building",
        resource_id=str(building.id),
        details={"name": name, "location": location},
    )
    await session.commit()
    await session.refresh(building)
    return (await _buildings_out(session, [building]))[0]


@buildings_router.patch(
    "/{building_id}", response_model=BuildingOut, dependencies=[_WRITE]
)
async def update_building(
    building_id: uuid.UUID,
    payload: BuildingUpdate,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> BuildingOut:
    building = await _require_building(session, building_id, scope)
    _reject_out_of_scope(_building_writable(building, scope))
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields:
        fields["name"] = _clean_name(fields["name"])
    if "location" in fields:
        fields["location"] = clean_location(fields["location"])
    name = fields.get("name", building.name)
    location = fields.get("location", building.location)
    if name != building.name or location != building.location:
        await _reject_building_name_taken(session, location, name, exclude=building.id)
    _reject_out_of_scope(_site_move_allowed(scope, building.location, location))
    for key, value in fields.items():
        setattr(building, key, value)
    _reject_out_of_scope(_building_writable(building, scope))
    building.updated_at = utcnow()
    session.add(building)
    audit.record(
        session,
        actor=current.email,
        action="building.update",
        resource_type="building",
        resource_id=str(building.id),
        details={"name": building.name, "fields": sorted(fields)},
    )
    await session.commit()
    await session.refresh(building)
    return (await _buildings_out(session, [building]))[0]


@buildings_router.delete("/{building_id}", status_code=204, dependencies=[_WRITE])
async def delete_building(
    building_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> None:
    """Delete a building. Its rooms stay, building-less, and keep the site they
    inherited from it; one whose name is already taken outside any building
    is renamed after the building."""
    building = await _require_building(session, building_id, scope)
    _reject_out_of_scope(_building_writable(building, scope))
    renamed = await crud.detach_building(session, building)
    audit.record(
        session,
        actor=current.email,
        action="building.delete",
        resource_type="building",
        resource_id=str(building.id),
        details={
            "name": building.name,
            "location": building.location,
            # Rooms renamed so as not to collide with one already outside any
            # building.
            **({"renamed": [f"{a} → {b}" for a, b in renamed]} if renamed else {}),
        },
    )
    await session.delete(building)
    await session.commit()


# --- Rooms ------------------------------------------------------------------


@rooms_router.get("/config", response_model=RoomConfigOut)
async def room_config() -> RoomConfigOut:
    """Declared before ``/{room_id}`` so the path is not read as an id."""
    return RoomConfigOut(
        source=settings.ROOM_SOURCE, manual=settings.ROOM_SOURCE == "manual"
    )


@rooms_router.post("/sync-directory", response_model=SyncOut, dependencies=[_WRITE])
async def sync_directory(
    session: SessionDep, current: CurrentUser, scope: CurrentScope
) -> SyncOut:
    """Re-file every poste from what its agent last said of the directory.

    The agents send the block only when *their* reading changes, so a
    ``ROOM_SOURCE`` switched on the server would otherwise take effect one
    poste at a time, on the day each one moves. In manual mode this does
    nothing and says so.
    """
    # Parc-wide by nature: it refiles every poste, whatever its site.
    _reject_out_of_scope(scope is None)
    result = await crud.sync_from_directory(session, settings.ROOM_SOURCE)
    audit.record(
        session,
        actor=current.email,
        action="room.sync_directory",
        resource_type="room",
        resource_id="",
        details={
            "source": settings.ROOM_SOURCE,
            "placed": result.placed,
            "unplaced": result.unplaced,
            "rooms_created": result.rooms_created,
        },
    )
    await session.commit()
    return SyncOut(
        placed=result.placed,
        unplaced=result.unplaced,
        rooms_created=result.rooms_created,
    )


@rooms_router.get("", response_model=list[RoomOut])
async def list_rooms(session: SessionDep, scope: CurrentScope) -> list[RoomOut]:
    """Every room with its building and counts, by site, building, name."""
    return await _rooms_out(session, await crud.list_rooms(session, room_clause(scope)))


@rooms_router.post("", response_model=RoomOut, status_code=201, dependencies=[_WRITE])
async def create_room(
    payload: RoomCreate, session: SessionDep, current: CurrentUser, scope: CurrentScope
) -> RoomOut:
    name = _clean_name(payload.name)
    if payload.building_id is not None:
        await _require_building(session, payload.building_id, scope)
    await _reject_room_name_taken(session, payload.building_id, name)
    room = Room(
        name=name,
        building_id=payload.building_id,
        # Only meaningful without a building; not stored otherwise, so the
        # two can never be read as disagreeing.
        location=clean_location(payload.location)
        if payload.building_id is None
        else None,
        notes=payload.notes,
    )
    session.add(room)
    await session.flush()
    _reject_out_of_scope(await _room_writable(session, room.id, scope))
    audit.record(
        session,
        actor=current.email,
        action="room.create",
        resource_type="room",
        resource_id=str(room.id),
        details={
            "name": name,
            "building_id": str(payload.building_id) if payload.building_id else None,
        },
    )
    await session.commit()
    await session.refresh(room)
    return await _room_out(session, room)


@rooms_router.get("/{room_id}", response_model=RoomOut)
async def get_room(
    room_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> RoomOut:
    return await _room_out(session, await _require_room(session, room_id, scope))


@rooms_router.patch("/{room_id}", response_model=RoomOut, dependencies=[_WRITE])
async def update_room(
    room_id: uuid.UUID,
    payload: RoomUpdate,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> RoomOut:
    room = await _require_room(session, room_id, scope)
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields:
        fields["name"] = _clean_name(fields["name"])
    if "location" in fields:
        fields["location"] = clean_location(fields["location"])
    if fields.get("building_id") is not None:
        await _require_building(session, fields["building_id"], scope)
    name = fields.get("name", room.name)
    building_id = fields.get("building_id", room.building_id)
    if name != room.name or building_id != room.building_id:
        await _reject_room_name_taken(session, building_id, name, exclude=room.id)
    site_before = await _room_site(session, room)
    if (
        "building_id" in fields
        and fields["building_id"] is None
        and room.building_id is not None
        and fields.get("location") is None
    ):
        # Out of its building, a room keeps the site it had through it — as
        # deleting the building does (``detach_building``) — rather than
        # losing it, and with it the site the console compares postes to
        # (audit B22). Clearing it is a second, explicit change.
        fields["location"] = site_before
    for key, value in fields.items():
        setattr(room, key, value)
    if room.building_id is not None:
        # A room in a building is where its building is; a site of its own
        # would only be a second answer.
        room.location = None
    _reject_out_of_scope(
        _site_move_allowed(scope, site_before, await _room_site(session, room))
    )
    room.updated_at = utcnow()
    session.add(room)
    _reject_out_of_scope(await _room_writable(session, room.id, scope))
    audit.record(
        session,
        actor=current.email,
        action="room.update",
        resource_type="room",
        resource_id=str(room.id),
        details={"name": room.name, "fields": sorted(fields)},
    )
    await session.commit()
    await session.refresh(room)
    return await _room_out(session, room)


@rooms_router.delete("/{room_id}", status_code=204, dependencies=[_WRITE])
async def delete_room(
    room_id: uuid.UUID, session: SessionDep, current: CurrentUser, scope: CurrentScope
) -> None:
    """Delete a room. Its postes stay, room-less (``ON DELETE SET NULL``)."""
    room = await _require_room(session, room_id, scope)
    audit.record(
        session,
        actor=current.email,
        action="room.delete",
        resource_type="room",
        resource_id=str(room.id),
        details={"name": room.name},
    )
    await session.delete(room)
    await session.commit()


async def _require_machines(
    session: SessionDep, machine_ids: list[uuid.UUID], scope: Scope | None
) -> list[Machine]:
    result = await session.exec(
        restrict(
            select(Machine).where(col(Machine.id).in_(machine_ids)),
            machine_clause(scope),
        )
    )
    machines = list(result.all())
    if len(machines) != len(set(machine_ids)):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    return machines


@rooms_router.post(
    "/{room_id}/machines", response_model=PlacementResult, dependencies=[_WRITE]
)
async def place_machines(
    room_id: uuid.UUID,
    payload: MachineIds,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> PlacementResult:
    """Put postes in this room — from another room, or from none.

    Never refuses a poste whose agent names another site: it reports which
    ones do, and the console says so. The mismatch is a finding to act on
    (a GPO, a move), not a reason to leave a poste unfiled.
    """
    _reject_locked_placement()
    room = await _require_room(session, room_id, scope)
    machines = await _require_machines(session, payload.machine_ids, scope)
    site = (await crud.placement(session, room.id)).location
    mismatched = [m.id for m in machines if crud.location_mismatch(m.location, site)]
    moved = await crud.set_room(session, payload.machine_ids, room.id)
    audit.record(
        session,
        actor=current.email,
        action="room.place_machines",
        resource_type="room",
        resource_id=str(room.id),
        details={
            "name": room.name,
            "machine_ids": [str(m) for m in payload.machine_ids],
        },
    )
    await session.commit()
    return PlacementResult(moved=moved, mismatched=mismatched)


@rooms_router.post("/unassign", response_model=PlacementResult, dependencies=[_WRITE])
async def unassign_machines(
    payload: MachineIds, session: SessionDep, current: CurrentUser, scope: CurrentScope
) -> PlacementResult:
    """Take postes out of whatever room they are in."""
    _reject_locked_placement()
    await _require_machines(session, payload.machine_ids, scope)
    moved = await crud.set_room(session, payload.machine_ids, None)
    audit.record(
        session,
        actor=current.email,
        action="room.unassign_machines",
        resource_type="room",
        resource_id="",
        details={"machine_ids": [str(m) for m in payload.machine_ids]},
    )
    await session.commit()
    return PlacementResult(moved=moved, mismatched=[])
