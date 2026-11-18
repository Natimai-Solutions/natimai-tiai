"""Buildings and rooms: lookups the routes and the machine list share."""

import logging
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import violated_constraint
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
    # Case-insensitive: « Bâtiment A » and « bâtiment a » on one site are one
    # building to whoever reads the list. Both sides folded by the database:
    # Python's ``lower()`` is another function (« İ » becomes two characters
    # there, one here), and the unique index is built on this one.
    result = await session.exec(
        select(Building).where(
            func.lower(col(Building.name)) == func.lower(name),
            col(Building.location).is_(None)
            if location is None
            else col(Building.location) == location,
        )
    )
    return result.first()


async def room_by_name(
    session: AsyncSession, building_id: uuid.UUID | None, name: str
) -> Room | None:
    # Case-insensitive: « A101 » and « a101 » in one building are one room to
    # whoever files a poste. Folded by the database on both sides, as the
    # unique index is (``building_by_name``).
    result = await session.exec(
        select(Room).where(
            func.lower(col(Room.name)) == func.lower(name),
            col(Room.building_id).is_(None)
            if building_id is None
            else col(Room.building_id) == building_id,
        )
    )
    return result.first()


async def hand_made_rooms(session: AsyncSession, name: str) -> list[Room]:
    """The rooms made by hand (no directory key) bearing ``name``, in a
    building or not: what the directory may adopt for an OU of that name."""
    result = await session.exec(
        select(Room)
        .where(func.lower(col(Room.name)) == func.lower(name.strip()))
        .where(col(Room.ad_key).is_(None))
        .order_by(col(Room.created_at))
    )
    return list(result.all())


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
    session: AsyncSession,
    building_ids: Iterable[uuid.UUID],
    *,
    room_where: Any = None,
    machine_where: Any = None,
) -> dict[uuid.UUID, BuildingCounts]:
    """Rooms and postes per building — only those matching ``room_where`` and
    ``machine_where`` (a scope's ``room_clause`` and ``machine_clause``): a
    confined account is not told how many postes it cannot see."""
    ids = list(building_ids)
    if not ids:
        return {}
    counts = {bid: BuildingCounts() for bid in ids}
    room_stmt = (
        select(col(Room.building_id), func.count())
        .where(col(Room.building_id).in_(ids))
        .group_by(col(Room.building_id))
    )
    if room_where is not None:
        room_stmt = room_stmt.where(room_where)
    rooms = await session.exec(room_stmt)
    room_totals = dict(rooms.all())
    machine_stmt = (
        select(col(Room.building_id), func.count())
        .join(Machine, col(Machine.room_id) == col(Room.id))
        .where(col(Room.building_id).in_(ids))
        .group_by(col(Room.building_id))
    )
    if machine_where is not None:
        machine_stmt = machine_stmt.where(machine_where)
    machines = await session.exec(machine_stmt)
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
    session: AsyncSession,
    key: str,
    name: str,
    *,
    adopt: bool = True,
    capped: bool | None = None,
    _retry: bool = True,
) -> tuple[Room | None, bool]:
    """The room the directory names by ``key``, created if missing.

    Creation adopts a room of the same name that was made by hand, in a
    building or not — the usual case on a parc that filed by hand before
    turning the directory on, where "B12" already exists, often in its
    building. Two rooms made by hand bearing the name (« B12 » in two
    buildings) leave the name undecided: nothing is adopted, nothing is
    created beside them, the postes stay where they are. Otherwise the name is
    taken as is, or suffixed when another key already holds it (two "Salle
    B12" OUs under two branches of the tree). Does not commit. Returns the
    room and whether it was created.

    ``capped`` bounds the rooms created per hour (an agent's report); by
    default, whenever ``adopt`` is off.
    """
    if capped is None:
        capped = not adopt
    result = await session.exec(select(Room).where(Room.ad_key == key))
    room = result.one_or_none()
    if room is not None:
        return room, False
    hand_made = await hand_made_rooms(session, name)
    if hand_made:
        if not adopt or len(hand_made) > 1:
            # A room made by hand is the console's: one agent's report does
            # not take it over (audit S20), and creating « Nom (2) » beside it
            # would only split the room. Left unfiled until an administrator
            # re-syncs from the directory, which does adopt it.
            return None, False
        loose = hand_made[0]
        loose.ad_key = key
        loose.updated_at = utcnow()
        session.add(loose)
        await session.flush()
        return loose, False
    # The directory allows far longer than the column (an AD « location » of
    # 125 characters is ordinary): cut, the suffix included (audit S07).
    name = name.strip()[:ROOM_NAME_MAX].strip() or key[:ROOM_NAME_MAX]
    if capped:
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
    try:
        # In a savepoint: the postes of one OU report it together, and each
        # request finds no room for the key until the first has committed
        # its own. The others meet it here, on the key or on the name.
        async with session.begin_nested():
            session.add(room)
    except IntegrityError as exc:
        if not _retry or violated_constraint(exc) is None:
            raise
        # Committed by now: found by its key, or — another key's room of
        # that name — stepped around with a suffix.
        return await room_for_key(
            session, key, name, adopt=adopt, capped=capped, _retry=False
        )
    return room, True


def reported_dn_consistent(machine: Machine) -> bool:
    """Whether the OU an agent reports is the one its own DN sits in — the
    least the server can check of what it is told (audit S20)."""
    dn = (machine.ad_distinguished_name or "").strip().lower()
    ou_dn = (machine.ad_ou_dn or "").strip().lower()
    return bool(dn and ou_dn) and dn.endswith("," + ou_dn)


async def place_from_directory(
    session: AsyncSession,
    machine: Machine,
    source: str,
    *,
    from_agent: bool = False,
    adopt: bool | None = None,
) -> bool:
    """File ``machine`` where the directory says, under ``source``. Returns
    whether a room was created on the way. A no-op in manual mode. Does not
    commit.

    An OU that the poste's own DN does not sit in is not taken, whoever asks:
    the stored reading is the agent's word either way (audit S20).

    ``from_agent``: the reading arrives in a heartbeat — a room made by hand
    is not adopted, and the rooms created per hour are bounded (audit S20).
    ``adopt`` overrides the first (the re-sync decides it per key)."""
    created, _filed = await _place(
        session, machine, source, from_agent=from_agent, adopt=adopt
    )
    return created


async def _place(
    session: AsyncSession,
    machine: Machine,
    source: str,
    *,
    from_agent: bool = False,
    adopt: bool | None = None,
) -> tuple[bool, bool]:
    """``place_from_directory``, saying also whether the poste ended up filed
    in the room its reading names: (room created, poste filed)."""
    if source == "manual":
        return False, False
    if source == "ad_ou" and machine.ad_ou_dn and not reported_dn_consistent(machine):
        logger.warning(
            "directory: machine %s reports an OU its DN is not in, not filed",
            machine.id,
        )
        return False, False
    key = directory_key(machine, source)
    if key is None:
        if machine.room_id is not None:
            machine.room_id = None
            machine.updated_at = utcnow()
            session.add(machine)
        return False, False
    room, created = await room_for_key(
        session,
        *key,
        adopt=(not from_agent) if adopt is None else adopt,
        capped=from_agent,
    )
    if room is None:
        return False, False
    if machine.room_id != room.id:
        machine.room_id = room.id
        machine.updated_at = utcnow()
        session.add(machine)
    return created, True


def _filable(machine: Machine, source: str) -> tuple[str, str] | None:
    """The key ``machine`` would be filed by, None when it has none or when
    its reported OU is not the one its DN sits in."""
    if source == "ad_ou" and machine.ad_ou_dn and not reported_dn_consistent(machine):
        return None
    return directory_key(machine, source)


# Room names a re-sync reports as left undecided: enough to act on, bounded
# so that the response and the audit entry stay small on any parc.
UNDECIDED_ROOMS_MAX = 20


@dataclass(frozen=True)
class SyncResult:
    # Postes now sitting in the room their reading names.
    placed: int = 0
    # Postes taken out of their room: the directory names none for them.
    unplaced: int = 0
    # Postes that left the room they were in — for another, or for none.
    moved_out: int = 0
    rooms_created: int = 0
    # Postes left where they were because the room made by hand that bears
    # their name was adopted by no key (a tie, no strict majority, no vote).
    undecided: int = 0
    # Those rooms, by name (``UNDECIDED_ROOMS_MAX`` at most).
    undecided_rooms: tuple[str, ...] = ()


def has_reading(machine: Machine) -> bool:
    """Whether the agent ever sent the directory block. A poste without any
    reading — an agent older than the block, a workgroup machine — has told
    the directory nothing: the re-sync leaves it where it was, as a heartbeat
    without the block does, rather than emptying a room filed by hand."""
    return any(
        (
            machine.ad_distinguished_name,
            machine.ad_ou,
            machine.ad_ou_dn,
            machine.ad_location,
        )
    )


def _votes(machine: Machine) -> bool:
    """Whether a poste's reading counts when a room made by hand is to be
    adopted: not one whose token is revoked, nor one whose identity is to be
    confirmed — their word is the one the server has reasons to doubt. They
    are filed like the others once the others have decided."""
    return not machine.token_revoked and not machine.needs_verification


async def sync_from_directory(session: AsyncSession, source: str) -> SyncResult:
    """Re-file every poste from its stored directory reading — what the console
    runs after ``ROOM_SOURCE`` changed, since the agents only send the block
    when *their* reading changes. Does not commit.

    A room made by hand is adopted by the key that a strict majority of the
    postes claiming its name report — not by whichever poste comes first: one
    forged reading would otherwise take « B12 » and send the real postes to
    « B12 (2) » (audit S20). On a tie no key adopts it, and the postes stay
    where they are until the directory says something clearer: they are
    counted as ``undecided``, not as placed, and the room is named.

    A room made by hand is found by name in a building as well as outside
    any (``room_for_key``). A poste with no directory reading at all is left
    where it is (``has_reading``).

    Only the postes in good standing vote (``_votes``).

    The postes it may move are locked first, in id order, for the length of
    the transaction (of the savepoint, on a dry run). A heartbeat carrying
    the directory block writes its poste, then looks for — or creates — the
    room its reading names; the sync created rooms, then wrote postes. The
    two orders crossed: each held what the other waited for, and PostgreSQL
    ended one of them (a 500 when it was the sync). Poste first on both
    sides, they queue instead: a heartbeat already at work is waited for
    before any room is touched, and one arriving later waits on its poste,
    holding nothing the sync wants."""
    if source == "manual":
        return SyncResult()
    locked = await session.exec(
        select(Machine)
        # ``has_reading``, loosely: the rows worth locking.
        .where(
            or_(
                col(Machine.ad_distinguished_name).is_not(None),
                col(Machine.ad_ou).is_not(None),
                col(Machine.ad_ou_dn).is_not(None),
                col(Machine.ad_location).is_not(None),
            )
        )
        .order_by(col(Machine.id))
        .with_for_update()
        # The rows as they are once the lock is held, not as an earlier read
        # of this session left them.
        .execution_options(populate_existing=True)
    )
    machines = [m for m in locked.all() if has_reading(m)]
    rooms_before = {m.id: m.room_id for m in machines}

    # Who claims each room made by hand, poste by poste.
    claims: dict[uuid.UUID, Counter[tuple[str, str]]] = {}
    for machine in machines:
        key = _filable(machine, source)
        if key is None or not _votes(machine):
            continue
        owned = await session.exec(select(Room.id).where(Room.ad_key == key[0]))
        if owned.first() is not None:
            continue
        hand_made = await hand_made_rooms(session, key[1])
        if len(hand_made) == 1:
            claims.setdefault(hand_made[0].id, Counter())[key] += 1
    adopting: set[str] = set()
    for room_id, counter in claims.items():
        (winner, votes), *_ = counter.most_common(1)
        if votes * 2 > sum(counter.values()):
            adopting.add(winner[0])
            # Adopted before any poste is placed: the order of the rows must
            # not decide who gets « Nom (2) ».
            await room_for_key(session, *winner, adopt=True, capped=False)
        else:
            logger.warning(
                "directory: room %s claimed by %d keys with no majority, not adopted",
                room_id,
                len(counter),
            )

    placed = unplaced = created = undecided = 0
    undecided_rooms: set[str] = set()
    for machine in machines:
        key = directory_key(machine, source)
        if key is None and machine.room_id is not None:
            unplaced += 1
        room_created, filed = await _place(
            session, machine, source, adopt=key is not None and key[0] in adopting
        )
        if room_created:
            created += 1
        if filed:
            placed += 1
        elif key is not None and _filable(machine, source) is not None:
            # A key the directory vouches for, and still no room: the one
            # made by hand that bears its name was adopted by nobody.
            undecided += 1
            held = await hand_made_rooms(session, key[1])
            undecided_rooms.add(held[0].name if held else key[1])
    moved_out = sum(
        1
        for m in machines
        if rooms_before[m.id] is not None and m.room_id != rooms_before[m.id]
    )
    return SyncResult(
        placed=placed,
        unplaced=unplaced,
        moved_out=moved_out,
        rooms_created=created,
        undecided=undecided,
        undecided_rooms=tuple(sorted(undecided_rooms)[:UNDECIDED_ROOMS_MAX]),
    )
