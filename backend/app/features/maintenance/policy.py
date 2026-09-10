"""What a poste's maintenance cycle and owner resolve to, and when it is due.

Three levels, the most specific winning: the poste, its room, the parc
(``app_settings``). The building is a grouping, not a level. A cycle of 0
excludes the poste — a server room, a VM — rather than a special flag.

    reference = last_maintenance_at ?? first_seen
    due       = reference + cycle days
    state     = excluded | overdue | due_soon | ok

Two forms of the same rule: SQL expressions, for the list's filter and sort
and the dashboard's counts, and a Python resolution, for the payloads. Both
read the same inputs so they cannot disagree.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, literal
from sqlmodel import col

from app.features.machine.models import Machine
from app.features.room.models import Room
from app.features.setting.crud import MaintenancePolicy


class MaintenanceState(enum.StrEnum):
    EXCLUDED = "excluded"
    OVERDUE = "overdue"
    DUE_SOON = "due_soon"
    OK = "ok"


class Origin(enum.StrEnum):
    """Which level a resolved value came from."""

    MACHINE = "machine"
    ROOM = "room"
    GLOBAL = "global"


@dataclass(frozen=True)
class Resolved:
    cycle_days: int
    cycle_origin: Origin
    owner_id: uuid.UUID | None
    owner_origin: Origin
    due_at: datetime | None
    state: MaintenanceState


def resolve(
    machine: Machine, room: Room | None, policy: MaintenancePolicy, now: datetime
) -> Resolved:
    if machine.maintenance_cycle_days is not None:
        cycle, cycle_origin = machine.maintenance_cycle_days, Origin.MACHINE
    elif room is not None and room.maintenance_cycle_days is not None:
        cycle, cycle_origin = room.maintenance_cycle_days, Origin.ROOM
    else:
        cycle, cycle_origin = policy.cycle_days, Origin.GLOBAL

    owner: uuid.UUID | None
    if machine.maintenance_owner_id is not None:
        owner, owner_origin = machine.maintenance_owner_id, Origin.MACHINE
    elif room is not None and room.maintenance_owner_id is not None:
        owner, owner_origin = room.maintenance_owner_id, Origin.ROOM
    else:
        owner, owner_origin = policy.owner_id, Origin.GLOBAL

    if cycle <= 0:
        return Resolved(
            cycle, cycle_origin, owner, owner_origin, None, MaintenanceState.EXCLUDED
        )
    reference = machine.last_maintenance_at or machine.first_seen
    due = reference + timedelta(days=cycle)
    if due < now:
        state = MaintenanceState.OVERDUE
    elif due - timedelta(days=policy.due_soon_days) <= now:
        state = MaintenanceState.DUE_SOON
    else:
        state = MaintenanceState.OK
    return Resolved(cycle, cycle_origin, owner, owner_origin, due, state)


# --- The same rule as SQL, over the (machines ⟕ rooms) join --------------------


def cycle_expr(policy: MaintenancePolicy) -> Any:
    return func.coalesce(
        col(Machine.maintenance_cycle_days),
        col(Room.maintenance_cycle_days),
        literal(policy.cycle_days),
    )


def due_expr(policy: MaintenancePolicy) -> Any:
    """When the poste is due — NULL for an excluded one, so that a sort on it
    puts the excluded last rather than first (a zero cycle would otherwise
    read as "due the day it was seen")."""
    reference = func.coalesce(col(Machine.last_maintenance_at), col(Machine.first_seen))
    cycle = cycle_expr(policy)
    # make_interval(years, months, weeks, days): the one interval constructor
    # that takes a column for the day count.
    return case(
        (cycle <= 0, None), else_=reference + func.make_interval(0, 0, 0, cycle)
    )


def state_clause(
    state: MaintenanceState, policy: MaintenancePolicy, now: datetime
) -> Any:
    cycle = cycle_expr(policy)
    due = due_expr(policy)
    soon = now + timedelta(days=policy.due_soon_days)
    if state == MaintenanceState.EXCLUDED:
        return cycle <= 0
    if state == MaintenanceState.OVERDUE:
        return (cycle > 0) & (due < now)
    if state == MaintenanceState.DUE_SOON:
        return (cycle > 0) & (due >= now) & (due <= soon)
    return (cycle > 0) & (due > soon)
