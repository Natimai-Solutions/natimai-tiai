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

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.routes.agent import clean_location
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.room import crud
from app.features.room.models import Building, Room
from app.features.user.permissions import Action, Resource

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
    machine_count: int
    # Postes of this room whose agent names another site.
    mismatch_count: int
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


class MachineIds(BaseModel):
    machine_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class PlacementResult(BaseModel):
    """What moving postes did, and which of them now disagree on the site —
    the console warns on those rather than the server refusing them."""

    moved: int
    mismatched: list[uuid.UUID]


# --- Helpers ----------------------------------------------------------------


async def _require_building(session: SessionDep, building_id: uuid.UUID) -> Building:
    building = await crud.get_building(session, building_id)
    if building is None:
        raise AppError(
            code=ErrorCode.BUILDING_NOT_FOUND,
            status_code=404,
            message="Building not found",
        )
    return building


async def _require_room(session: SessionDep, room_id: uuid.UUID) -> Room:
    room = await crud.get_room(session, room_id)
    if room is None:
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
    return [
        RoomOut(
            id=r.id,
            name=r.name,
            building=BuildingRef.model_validate(b) if b else None,
            location=r.location,
            effective_location=crud.effective_location(r, b),
            notes=r.notes,
            machine_count=counts[r.id].machines,
            mismatch_count=counts[r.id].mismatched,
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
async def list_buildings(session: SessionDep) -> list[BuildingOut]:
    """Every building, by site then name. Not paginated: a parc has dozens."""
    return await _buildings_out(session, await crud.list_buildings(session))


@buildings_router.post(
    "", response_model=BuildingOut, status_code=201, dependencies=[_WRITE]
)
async def create_building(
    payload: BuildingCreate, session: SessionDep, current: CurrentUser
) -> BuildingOut:
    name = _clean_name(payload.name)
    location = clean_location(payload.location)
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
) -> BuildingOut:
    building = await _require_building(session, building_id)
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields:
        fields["name"] = _clean_name(fields["name"])
    if "location" in fields:
        fields["location"] = clean_location(fields["location"])
    name = fields.get("name", building.name)
    location = fields.get("location", building.location)
    if name != building.name or location != building.location:
        await _reject_building_name_taken(session, location, name, exclude=building.id)
    for key, value in fields.items():
        setattr(building, key, value)
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
    building_id: uuid.UUID, session: SessionDep, current: CurrentUser
) -> None:
    """Delete a building. Its rooms stay, building-less, and keep the site they
    inherited from it."""
    building = await _require_building(session, building_id)
    await crud.detach_building(session, building)
    audit.record(
        session,
        actor=current.email,
        action="building.delete",
        resource_type="building",
        resource_id=str(building.id),
        details={"name": building.name, "location": building.location},
    )
    await session.delete(building)
    await session.commit()


# --- Rooms ------------------------------------------------------------------


@rooms_router.get("", response_model=list[RoomOut])
async def list_rooms(session: SessionDep) -> list[RoomOut]:
    """Every room with its building and counts, by site, building, name."""
    return await _rooms_out(session, await crud.list_rooms(session))


@rooms_router.post("", response_model=RoomOut, status_code=201, dependencies=[_WRITE])
async def create_room(
    payload: RoomCreate, session: SessionDep, current: CurrentUser
) -> RoomOut:
    name = _clean_name(payload.name)
    if payload.building_id is not None:
        await _require_building(session, payload.building_id)
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
async def get_room(room_id: uuid.UUID, session: SessionDep) -> RoomOut:
    return await _room_out(session, await _require_room(session, room_id))


@rooms_router.patch("/{room_id}", response_model=RoomOut, dependencies=[_WRITE])
async def update_room(
    room_id: uuid.UUID, payload: RoomUpdate, session: SessionDep, current: CurrentUser
) -> RoomOut:
    room = await _require_room(session, room_id)
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields:
        fields["name"] = _clean_name(fields["name"])
    if "location" in fields:
        fields["location"] = clean_location(fields["location"])
    if fields.get("building_id") is not None:
        await _require_building(session, fields["building_id"])
    name = fields.get("name", room.name)
    building_id = fields.get("building_id", room.building_id)
    if name != room.name or building_id != room.building_id:
        await _reject_room_name_taken(session, building_id, name, exclude=room.id)
    for key, value in fields.items():
        setattr(room, key, value)
    if room.building_id is not None:
        # A room in a building is where its building is; a site of its own
        # would only be a second answer.
        room.location = None
    room.updated_at = utcnow()
    session.add(room)
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
    room_id: uuid.UUID, session: SessionDep, current: CurrentUser
) -> None:
    """Delete a room. Its postes stay, room-less (``ON DELETE SET NULL``)."""
    room = await _require_room(session, room_id)
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
    session: SessionDep, machine_ids: list[uuid.UUID]
) -> list[Machine]:
    result = await session.exec(select(Machine).where(col(Machine.id).in_(machine_ids)))
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
    room_id: uuid.UUID, payload: MachineIds, session: SessionDep, current: CurrentUser
) -> PlacementResult:
    """Put postes in this room — from another room, or from none.

    Never refuses a poste whose agent names another site: it reports which
    ones do, and the console says so. The mismatch is a finding to act on
    (a GPO, a move), not a reason to leave a poste unfiled.
    """
    room = await _require_room(session, room_id)
    machines = await _require_machines(session, payload.machine_ids)
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
    payload: MachineIds, session: SessionDep, current: CurrentUser
) -> PlacementResult:
    """Take postes out of whatever room they are in."""
    await _require_machines(session, payload.machine_ids)
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
