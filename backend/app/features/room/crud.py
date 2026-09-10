"""Buildings and rooms: lookups the routes and the machine list share."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.room.models import Building, Room


def effective_location(room: Room | None, building: Building | None) -> str | None:
    """Where a room is: its building's site, else its own."""
    if room is None:
        return None
    if building is not None:
        return building.location
    return room.location


def location_mismatch(machine_location: str | None, room_location: str | None) -> bool:
    """Whether the agent and the room disagree about the site. Only when both
    have an opinion: a poste whose agent names no site is not in the wrong
    one, and neither is a room nobody placed."""
    return bool(
        machine_location and room_location and machine_location != room_location
    )


@dataclass(frozen=True)
class Placement:
    """A machine's room and building, resolved."""

    room: Room | None
    building: Building | None

    @property
    def location(self) -> str | None:
        return effective_location(self.room, self.building)


async def placements(
    session: AsyncSession, room_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, Placement]:
    """Rooms and their buildings for a set of room ids — one query for a page
    of machines rather than one per row."""
    ids = {rid for rid in room_ids if rid is not None}
    if not ids:
        return {}
    rows = await session.exec(
        select(Room, Building)
        .outerjoin(Building, col(Building.id) == col(Room.building_id))
        .where(col(Room.id).in_(ids))
    )
    return {
        room.id: Placement(room=room, building=building)
        for room, building in rows.all()
    }


async def placement(session: AsyncSession, room_id: uuid.UUID | None) -> Placement:
    if room_id is None:
        return Placement(room=None, building=None)
    found = await placements(session, [room_id])
    return found.get(room_id, Placement(room=None, building=None))


async def get_building(
    session: AsyncSession, building_id: uuid.UUID
) -> Building | None:
    return await session.get(Building, building_id)


async def get_room(session: AsyncSession, room_id: uuid.UUID) -> Room | None:
    return await session.get(Room, room_id)


async def building_by_name(
    session: AsyncSession, location: str | None, name: str
) -> Building | None:
    result = await session.exec(
        select(Building).where(
            col(Building.name) == name,
            col(Building.location).is_(None)
            if location is None
            else col(Building.location) == location,
        )
    )
    return result.one_or_none()


async def room_by_name(
    session: AsyncSession, building_id: uuid.UUID | None, name: str
) -> Room | None:
    result = await session.exec(
        select(Room).where(
            col(Room.name) == name,
            col(Room.building_id).is_(None)
            if building_id is None
            else col(Room.building_id) == building_id,
        )
    )
    return result.one_or_none()


async def list_buildings(session: AsyncSession) -> list[Building]:
    result = await session.exec(
        select(Building).order_by(
            col(Building.location).nulls_last(), func.lower(col(Building.name))
        )
    )
    return list(result.all())


async def list_rooms(session: AsyncSession) -> list[tuple[Room, Building | None]]:
    """Every room with its building, ordered as the page reads them: by site,
    then building, then room name."""
    result = await session.exec(
        select(Room, Building)
        .outerjoin(Building, col(Building.id) == col(Room.building_id))
        .order_by(
            func.coalesce(col(Building.location), col(Room.location)).nulls_last(),
            func.lower(col(Building.name)).nulls_last(),
            func.lower(col(Room.name)),
        )
    )
    return [(room, building) for room, building in result.all()]


@dataclass(frozen=True)
class RoomCounts:
    machines: int = 0
    # Postes whose agent names another site than the room's.
    mismatched: int = 0


async def room_counts(
    session: AsyncSession, room_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RoomCounts]:
    """Per room: how many postes, and how many of them disagree on the site."""
    ids = list(room_ids)
    if not ids:
        return {}
    site = func.coalesce(col(Building.location), col(Room.location))
    mismatch = (
        col(Machine.location).is_not(None)
        & site.is_not(None)
        & (col(Machine.location) != site)
    )
    rows = await session.exec(
        select(
            col(Machine.room_id),
            func.count(),
            func.count().filter(mismatch),
        )
        .join(Room, col(Room.id) == col(Machine.room_id))
        .outerjoin(Building, col(Building.id) == col(Room.building_id))
        .where(col(Machine.room_id).in_(ids))
        .group_by(col(Machine.room_id))
    )
    counts = {rid: RoomCounts() for rid in ids}
    for rid, total, mismatched in rows.all():
        if rid is not None:
            counts[rid] = RoomCounts(machines=total, mismatched=mismatched)
    return counts


@dataclass(frozen=True)
class BuildingCounts:
    rooms: int = 0
    machines: int = 0


async def building_counts(
    session: AsyncSession, building_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, BuildingCounts]:
    ids = list(building_ids)
    if not ids:
        return {}
    counts = {bid: BuildingCounts() for bid in ids}
    rooms = await session.exec(
        select(col(Room.building_id), func.count())
        .where(col(Room.building_id).in_(ids))
        .group_by(col(Room.building_id))
    )
    room_totals = dict(rooms.all())
    machines = await session.exec(
        select(col(Room.building_id), func.count())
        .join(Machine, col(Machine.room_id) == col(Room.id))
        .where(col(Room.building_id).in_(ids))
        .group_by(col(Room.building_id))
    )
    machine_totals = dict(machines.all())
    for bid in ids:
        counts[bid] = BuildingCounts(
            rooms=room_totals.get(bid, 0), machines=machine_totals.get(bid, 0)
        )
    return counts


async def set_room(
    session: AsyncSession, machine_ids: Iterable[uuid.UUID], room_id: uuid.UUID | None
) -> int:
    """Move machines into a room (or out of any). Returns how many rows moved.
    Does not commit."""
    ids = list(machine_ids)
    if not ids:
        return 0
    result = await session.exec(
        update(Machine)
        .where(col(Machine.id).in_(ids))
        .values(room_id=room_id, updated_at=utcnow())
    )
    return result.rowcount


async def detach_building(session: AsyncSession, building: Building) -> None:
    """Before a building is deleted: its rooms keep the site they inherited,
    copied down, rather than losing it with the building. Does not commit."""
    await session.exec(
        update(Room)
        .where(col(Room.building_id) == building.id, col(Room.location).is_(None))
        .values(location=building.location, updated_at=utcnow())
    )
