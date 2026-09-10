"""Maintenance sessions and what is due."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.intervention.models import Intervention, InterventionKind
from app.features.machine.models import Machine
from app.features.maintenance.models import Maintenance
from app.features.maintenance.policy import MaintenanceState, Resolved, resolve
from app.features.room.models import Building, Room
from app.features.setting.crud import MaintenancePolicy


@dataclass
class DueRoom:
    """One room of the "to do" list: its counts, and the postes behind them."""

    room: Room
    building: Building | None
    owner_id: uuid.UUID | None
    cycle_days: int
    total: int = 0
    overdue: int = 0
    due_soon: int = 0
    excluded: int = 0
    next_due_at: datetime | None = None
    machines: list[tuple[Machine, Resolved]] = field(default_factory=list)


async def fleet_resolved(
    session: AsyncSession, policy: MaintenancePolicy, now: datetime
) -> list[tuple[Machine, Room | None, Building | None, Resolved]]:
    """Every poste with its placement and resolved maintenance. One query
    over the parc: what the due list and the room counts are built from."""
    rows = await session.exec(
        select(Machine, Room, Building)
        .outerjoin(Room, col(Room.id) == col(Machine.room_id))
        .outerjoin(Building, col(Building.id) == col(Room.building_id))
    )
    return [(m, r, b, resolve(m, r, policy, now)) for m, r, b in rows.all()]


def group_due(
    resolved: list[tuple[Machine, Room | None, Building | None, Resolved]],
    policy: MaintenancePolicy,
    *,
    owner_filter: uuid.UUID | None,
    unowned: bool,
) -> tuple[list[DueRoom], list[tuple[Machine, Resolved]]]:
    """Rooms with their counts, and the room-less postes, for one owner (or
    everybody). A room's owner is what its postes resolve to when none of
    them overrides it; a poste that overrides the owner is listed under its
    own owner, not its room's."""
    rooms: dict[uuid.UUID, DueRoom] = {}
    loose: list[tuple[Machine, Resolved]] = []
    for machine, room, building, res in resolved:
        if owner_filter is not None and res.owner_id != owner_filter:
            continue
        if unowned and res.owner_id is not None:
            continue
        if room is None:
            if res.state != MaintenanceState.EXCLUDED:
                loose.append((machine, res))
            continue
        entry = rooms.get(room.id)
        if entry is None:
            room_owner = (
                room.maintenance_owner_id
                if room.maintenance_owner_id is not None
                else policy.owner_id
            )
            room_cycle = (
                room.maintenance_cycle_days
                if room.maintenance_cycle_days is not None
                else policy.cycle_days
            )
            entry = DueRoom(
                room=room,
                building=building,
                owner_id=room_owner,
                cycle_days=room_cycle,
            )
            rooms[room.id] = entry
        entry.total += 1
        entry.machines.append((machine, res))
        if res.state == MaintenanceState.EXCLUDED:
            entry.excluded += 1
            continue
        if res.state == MaintenanceState.OVERDUE:
            entry.overdue += 1
        elif res.state == MaintenanceState.DUE_SOON:
            entry.due_soon += 1
        if res.due_at is not None and (
            entry.next_due_at is None or res.due_at < entry.next_due_at
        ):
            entry.next_due_at = res.due_at
    # The room whose next poste is due soonest first; rooms with nothing due
    # (every poste excluded) last, by name.
    far = utcnow()
    ordered = sorted(
        rooms.values(),
        key=lambda e: (
            e.next_due_at is None,
            e.next_due_at or far,
            e.room.name.lower(),
        ),
    )
    loose.sort(key=lambda x: (x[1].due_at is None, x[1].due_at or utcnow()))
    return ordered, loose


async def record_session(
    session: AsyncSession,
    *,
    room: Room | None,
    machines: list[Machine],
    notes: dict[uuid.UUID, str | None],
    performed_by: str,
    performed_at: datetime,
    note: str | None,
) -> Maintenance:
    """One visit: the session row, one journal entry per poste, and each
    poste's ``last_maintenance_at`` moved forward. Does not commit."""
    visit = Maintenance(
        room_id=room.id if room else None,
        room_name=room.name if room else None,
        performed_by=performed_by,
        performed_at=performed_at,
        note=note,
    )
    session.add(visit)
    await session.flush()
    title = f"Maintenance — {room.name}" if room else "Maintenance"
    for machine in machines:
        session.add(
            Intervention(
                machine_id=machine.id,
                kind=InterventionKind.MAINTENANCE.value,
                title=title,
                note=notes.get(machine.id),
                performed_by=performed_by,
                performed_at=performed_at,
                maintenance_id=visit.id,
            )
        )
        # Forward only: recording a visit older than the last one known is
        # history, not a step back on the cycle.
        if (
            machine.last_maintenance_at is None
            or performed_at > machine.last_maintenance_at
        ):
            machine.last_maintenance_at = performed_at
            machine.updated_at = utcnow()
            session.add(machine)
    return visit


async def list_sessions(
    session: AsyncSession,
    *,
    room_id: uuid.UUID | None,
    machine_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[Maintenance], int]:
    stmt = select(Maintenance)
    if room_id is not None:
        stmt = stmt.where(col(Maintenance.room_id) == room_id)
    if machine_id is not None:
        stmt = stmt.where(
            col(Maintenance.id).in_(
                select(Intervention.maintenance_id).where(
                    col(Intervention.machine_id) == machine_id,
                    col(Intervention.maintenance_id).is_not(None),
                )
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.exec(
        stmt.order_by(col(Maintenance.performed_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.all()), total or 0


async def session_items(
    session: AsyncSession, maintenance_id: uuid.UUID
) -> list[tuple[Intervention, Machine]]:
    rows = await session.exec(
        select(Intervention, Machine)
        .join(Machine, col(Machine.id) == col(Intervention.machine_id))
        .where(col(Intervention.maintenance_id) == maintenance_id)
        .order_by(func.lower(col(Machine.hostname)).nulls_last())
    )
    return [(i, m) for i, m in rows.all()]


async def item_counts(
    session: AsyncSession, maintenance_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not maintenance_ids:
        return {}
    rows = await session.exec(
        select(col(Intervention.maintenance_id), func.count())
        .where(col(Intervention.maintenance_id).in_(maintenance_ids))
        .group_by(col(Intervention.maintenance_id))
    )
    counts = dict.fromkeys(maintenance_ids, 0)
    for mid, n in rows.all():
        if mid is not None:
            counts[mid] = n
    return counts
