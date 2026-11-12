"""Buildings and rooms: lookups the routes and the machine list share."""

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.room.models import Building, Room

logger = logging.getLogger(__name__)


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


async def list_buildings(session: AsyncSession, where: Any = None) -> list[Building]:
    """Every building — or those matching ``where`` (a scope's
    ``building_clause``)."""
    stmt = select(Building) if where is None else select(Building).where(where)
    result = await session.exec(
        stmt.order_by(
            col(Building.location).nulls_last(), func.lower(col(Building.name))
        )
    )
    return list(result.all())


async def list_rooms(
    session: AsyncSession, where: Any = None
) -> list[tuple[Room, Building | None]]:
    """Every room with its building — or those matching ``where`` (a scope's
    ``room_clause``) — ordered as the page reads them: by site, then
    building, then room name."""
    stmt = select(Room, Building).outerjoin(
        Building, col(Building.id) == col(Room.building_id)
    )
    if where is not None:
        stmt = stmt.where(where)
    result = await session.exec(
        stmt.order_by(
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


async def detach_building(
    session: AsyncSession, building: Building
) -> list[tuple[str, str]]:
    """Before a building is deleted: its rooms keep the site they inherited,
    copied down, rather than losing it with the building.

    Out of their building, their names must also be unique among the rooms
    that have none: one that collides is renamed after its building —
    « Salle 101 (Bâtiment A) », then numbered — rather than failing the
    deletion (audit B07). Returns the renames. Flushes, does not commit."""
    await session.exec(
        update(Room)
        .where(col(Room.building_id) == building.id, col(Room.location).is_(None))
        .values(location=building.location, updated_at=utcnow())
    )
    renamed: list[tuple[str, str]] = []
    rooms = (
        await session.exec(select(Room).where(col(Room.building_id) == building.id))
    ).all()
    for room in rooms:
        if await room_by_name(session, None, room.name) is None:
            continue
        base = f"{room.name} ({building.name})"
        candidate = base[:ROOM_NAME_MAX]
        n = 2
        while (
            await room_by_name(session, None, candidate) is not None
            or await room_by_name(session, building.id, candidate) is not None
        ):
            suffix = f" ({n})"
            candidate = base[: ROOM_NAME_MAX - len(suffix)].rstrip() + suffix
            n += 1
        renamed.append((room.name, candidate))
        room.name = candidate
        room.updated_at = utcnow()
        session.add(room)
        await session.flush()
    return renamed


# --- Directory-driven placement (ROOM_SOURCE) -------------------------------


def directory_key(machine: Machine, source: str) -> tuple[str, str] | None:
    """What the directory files ``machine`` by under ``source``: the room's
    key and the name to give it when it has to be created. None when the
    poste has nothing to be filed by — no OU, no location attribute — which
    unfiles it rather than leaving it where it was: the directory has spoken,
    and it said "nowhere"."""
    if source == "ad_ou":
        if machine.ad_ou_dn and machine.ad_ou:
            return machine.ad_ou_dn, machine.ad_ou
        return None
    if source == "ad_location":
        if machine.ad_location:
            return machine.ad_location, machine.ad_location
        return None
    return None


# rooms.name is a VARCHAR(100).
ROOM_NAME_MAX = 100


# Rooms an agent's report may create in an hour, all postes together: a parc
# turning its directory on creates its rooms once; a token sending a new OU
# on every heartbeat must not fill the Salles page (audit S20).
AUTO_ROOMS_PER_HOUR = 200


async def room_for_key(
    session: AsyncSession, key: str, name: str, *, adopt: bool = True
) -> tuple[Room | None, bool]:
    """The room the directory names by ``key``, created if missing.

    Creation adopts a room of the same name that was made by hand and sits in
    no building — the usual case on a parc that filed by hand before turning
    the directory on, where "B12" already exists. Otherwise the name is taken
    as is, or suffixed when another key already holds it (two "Salle B12"
    OUs under two branches of the tree). Does not commit. Returns the room and
    whether it was created.
    """
    result = await session.exec(select(Room).where(Room.ad_key == key))
    room = result.one_or_none()
    if room is not None:
        return room, False
    loose = await room_by_name(session, None, name)
    if loose is not None and loose.ad_key is None:
        if not adopt:
            # A room made by hand is the console's: one agent's report does
            # not take it over (audit S20), and creating « Nom (2) » beside it
            # would only split the room. Left unfiled until an administrator
            # re-syncs from the directory, which does adopt it.
            return None, False
        loose.ad_key = key
        loose.updated_at = utcnow()
        session.add(loose)
        await session.flush()
        return loose, False
    # The directory allows far longer than the column (an AD « location » of
    # 125 characters is ordinary): cut, the suffix included (audit S07).
    name = name.strip()[:ROOM_NAME_MAX].strip() or key[:ROOM_NAME_MAX]
    if not adopt:
        recent = await session.scalar(
            select(func.count())
            .select_from(Room)
            .where(col(Room.ad_key).is_not(None))
            .where(col(Room.created_at) > utcnow() - timedelta(hours=1))
        )
        if (recent or 0) >= AUTO_ROOMS_PER_HOUR:
            logger.warning("directory: room creation capped, %r not created", name)
            return None, False
    candidate = name
    n = 2
    while await room_by_name(session, None, candidate) is not None:
        suffix = f" ({n})"
        candidate = name[: ROOM_NAME_MAX - len(suffix)].rstrip() + suffix
        n += 1
    room = Room(name=candidate, ad_key=key)
    session.add(room)
    await session.flush()
    return room, True


def reported_dn_consistent(machine: Machine) -> bool:
    """Whether the OU an agent reports is the one its own DN sits in — the
    least the server can check of what it is told (audit S20)."""
    dn = (machine.ad_distinguished_name or "").strip().lower()
    ou_dn = (machine.ad_ou_dn or "").strip().lower()
    return bool(dn and ou_dn) and dn.endswith("," + ou_dn)


async def place_from_directory(
    session: AsyncSession, machine: Machine, source: str, *, from_agent: bool = False
) -> bool:
    """File ``machine`` where the directory says, under ``source``. Returns
    whether a room was created on the way. A no-op in manual mode. Does not
    commit.

    ``from_agent``: the reading arrives in a heartbeat, the agent's word —
    an OU that its DN does not sit in is not taken, a room made by hand is
    not adopted, and the rooms created per hour are bounded (audit S20)."""
    if source == "manual":
        return False
    if (
        from_agent
        and source == "ad_ou"
        and machine.ad_ou_dn
        and not reported_dn_consistent(machine)
    ):
        logger.warning(
            "directory: machine %s reports an OU its DN is not in, not filed",
            machine.id,
        )
        return False
    key = directory_key(machine, source)
    if key is None:
        if machine.room_id is not None:
            machine.room_id = None
            machine.updated_at = utcnow()
            session.add(machine)
        return False
    room, created = await room_for_key(session, *key, adopt=not from_agent)
    if room is None:
        return False
    if machine.room_id != room.id:
        machine.room_id = room.id
        machine.updated_at = utcnow()
        session.add(machine)
    return created


@dataclass(frozen=True)
class SyncResult:
    placed: int = 0
    unplaced: int = 0
    rooms_created: int = 0


async def sync_from_directory(session: AsyncSession, source: str) -> SyncResult:
    """Re-file every poste from its stored directory reading — what the console
    runs after ``ROOM_SOURCE`` changed, since the agents only send the block
    when *their* reading changes. Does not commit."""
    if source == "manual":
        return SyncResult()
    result = await session.exec(select(Machine))
    placed = unplaced = created = 0
    for machine in result.all():
        if directory_key(machine, source) is None:
            if machine.room_id is not None:
                unplaced += 1
        else:
            placed += 1
        if await place_from_directory(session, machine, source):
            created += 1
    return SyncResult(placed=placed, unplaced=unplaced, rooms_created=created)
