"""Recurring failures: the ``incident`` interventions of a period, grouped by
hardware model or by room (C9, §4).

Both sides of the rate speak of the same parc — the postes in the parc, in
the caller's scope, today: ``incidents`` and ``machines`` over the in-parc
postes, ``parc`` the in-parc postes of that model or room, ``per_100`` their
ratio. The retired postes are shown apart (``retired_incidents``,
``retired_machines``) and kept out of the rate: a model that breaks until it
is retired is what a purchase decision wants to see, without a rate above
100 or a division by zero.

By room, the room is the poste's **current** one (an intervention does not
keep the room of its day). A poste visible by its agent's site but standing
in a room outside the scope is counted in one anonymous row, so that the
total by room equals the total by model without naming the room.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, false, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.asset import crud as asset_crud
from app.features.intervention.models import Intervention, InterventionKind
from app.features.machine.models import Machine
from app.features.room.models import Building, Room
from app.features.trend.crud import Period
from app.features.user.scope import (
    Scope,
    building_clause,
    machine_clause,
    restrict,
    room_clause,
)


@dataclass
class FailureRow:
    hw_model: str | None = None
    room_id: uuid.UUID | None = None
    room_name: str | None = None
    building_name: str | None = None
    out_of_scope: bool = False
    incidents: int = 0
    machines: int = 0
    parc: int = 0
    per_100: float | None = None
    retired_incidents: int = 0
    retired_machines: int = 0
    last_at: datetime | None = None


def _room_key(scope: Scope | None) -> tuple[Any, Any]:
    """(the room shown, whether the poste's room is out of sight)."""
    room_id = col(Machine.room_id)
    if scope is None:
        return room_id, false()
    visible = room_id.in_(
        select(col(Room.id)).where(room_clause(scope)).correlate(None)
    )
    return (
        case((visible, room_id), else_=None),
        and_(room_id.is_not(None), ~visible),
    )


async def recurring_failures(
    session: AsyncSession,
    scope: Scope | None,
    period: Period,
    *,
    by: str,
    min_incidents: int,
    limit: int,
) -> list[FailureRow]:
    retired = asset_crud.retired_clause()
    in_parc = ~retired
    if by == "room":
        room, hidden = _room_key(scope)
        keys: list[Any] = [room, hidden]
        # ``hidden`` is the constant false for an unrestricted account.
        group_keys = keys if scope is not None else keys[:1]
    else:
        keys = [col(Machine.hw_model), false()]
        group_keys = keys[:1]
    machine_id = col(Intervention.machine_id)
    columns: list[Any] = [
        *keys,
        func.count().filter(in_parc),
        func.count(func.distinct(machine_id)).filter(in_parc),
        func.count().filter(retired),
        func.count(func.distinct(machine_id)).filter(retired),
        func.max(col(Intervention.performed_at)),
    ]
    rows = await session.exec(
        restrict(
            select(*columns)
            .select_from(Intervention)
            .join(Machine, col(Machine.id) == machine_id),
            machine_clause(scope),
        )
        .where(
            col(Intervention.kind) == InterventionKind.INCIDENT,
            col(Intervention.performed_at) >= period.start,
            col(Intervention.performed_at) < period.end,
        )
        .group_by(*group_keys)
    )
    found: dict[tuple[Any, bool], FailureRow] = {}
    for key, hidden_flag, incidents, machines, r_inc, r_mach, last_at in rows.all():
        if incidents + r_inc < min_incidents:
            continue
        row = FailureRow(
            incidents=int(incidents),
            machines=int(machines),
            retired_incidents=int(r_inc),
            retired_machines=int(r_mach),
            last_at=last_at,
            out_of_scope=bool(hidden_flag),
        )
        if by == "room":
            row.room_id = key
        else:
            row.hw_model = key
        found[(key, bool(hidden_flag))] = row
    if not found:
        return []

    # The parc of each group, in the scope, in the parc, today.
    parc_rows = await session.exec(
        restrict(
            select(*[*keys, func.count()]).select_from(Machine),
            machine_clause(scope),
        )
        .where(asset_crud.in_parc_clause())
        .group_by(*group_keys)
    )
    for key, hidden_flag, count in parc_rows.all():
        row_or_none = found.get((key, bool(hidden_flag)))
        if row_or_none is not None:
            row_or_none.parc = int(count)
    for row in found.values():
        row.per_100 = round(row.incidents * 100 / row.parc, 1) if row.parc > 0 else None

    if by == "room":
        await _name_rooms(session, scope, list(found.values()))

    ordered = sorted(
        found.values(),
        key=lambda r: (
            -r.incidents,
            r.per_100 is None,
            -(r.per_100 or 0),
            -r.retired_incidents,
        ),
    )
    return ordered[:limit]


async def _name_rooms(
    session: AsyncSession, scope: Scope | None, rows: list[FailureRow]
) -> None:
    """The names of the rooms shown, and of their building where the scope
    allows it (``building_clause``)."""
    ids = [r.room_id for r in rows if r.room_id is not None]
    if not ids:
        return
    visible_building = building_clause(scope)
    building_name = (
        col(Building.name)
        if visible_building is None
        else case((visible_building, col(Building.name)), else_=None)
    )
    names = await session.exec(
        select(col(Room.id), col(Room.name), building_name)
        .outerjoin(Building, col(Building.id) == col(Room.building_id))
        .where(col(Room.id).in_(ids))
    )
    by_id = {room_id: (name, building) for room_id, name, building in names.all()}
    for row in rows:
        if row.room_id is not None and row.room_id in by_id:
            row.room_name, row.building_name = by_id[row.room_id]
