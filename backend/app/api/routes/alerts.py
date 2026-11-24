"""Alerts, as the console reads them: the open ones across the parc (page
Alertes, the dashboard's card), and a poste's own, open and past (its fiche).

Read with ``machine:read``, within the caller's scope like every poste: an
alert names a machine. Opening and resolving is the worker's alone
(``app.features.alert.crud.evaluate``) — there is nothing to write here; the
rules are set on the page Paramètres.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    CurrentPermissions,
    CurrentScope,
    SessionDep,
    require_permission,
)
from app.core.errors import AppError, ErrorCode
from app.features.alert.models import ALL_RULES, AlertRule, MachineAlert
from app.features.check.models import MachineCheck
from app.features.machine.models import Machine
from app.features.room import crud as room_crud
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import machine_ids_clause, machine_visible, restrict

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.READ))],
)


class AlertMachineRef(BaseModel):
    id: uuid.UUID
    hostname: str | None
    room_name: str | None
    building_name: str | None


class AlertOut(BaseModel):
    id: uuid.UUID
    machine_id: uuid.UUID
    rule: str
    opened_at: datetime
    resolved_at: datetime | None
    # The values the console words: a percentage, a letter, program names.
    detail: dict[str, Any] | None
    check_id: uuid.UUID | None
    # The verification opened for it is still open: closed — the user
    # warned, a part ordered — the alert can hold on without one.
    check_open: bool = False
    machine: AlertMachineRef | None = None


class AlertList(BaseModel):
    items: list[AlertOut]
    total: int
    page: int
    page_size: int
    # Open alerts per rule, over the caller's scope — the page's tabs.
    open_by_rule: dict[str, int]


async def _machines(
    session: SessionDep, ids: set[uuid.UUID]
) -> dict[uuid.UUID, AlertMachineRef]:
    if not ids:
        return {}
    rows = list(
        (await session.exec(select(Machine).where(col(Machine.id).in_(ids)))).all()
    )
    placements = await room_crud.placements(session, [m.room_id for m in rows])
    refs: dict[uuid.UUID, AlertMachineRef] = {}
    for m in rows:
        placement = placements.get(m.room_id) if m.room_id else None
        refs[m.id] = AlertMachineRef(
            id=m.id,
            hostname=m.hostname,
            room_name=placement.room.name if placement and placement.room else None,
            building_name=(
                placement.building.name if placement and placement.building else None
            ),
        )
    return refs


def _detail(row: MachineAlert, purchase_data: bool) -> dict[str, Any] | None:
    """The detail as the caller may read it: the warranty's end date is
    purchase data, read with ``asset:read`` like the export's column — without
    it, the alert only says the warranty ends within the threshold."""
    if row.detail is None or purchase_data or row.rule != AlertRule.WARRANTY_ENDING:
        return row.detail
    return {k: v for k, v in row.detail.items() if k != "warranty_end"}


def _out(
    row: MachineAlert,
    machine: AlertMachineRef | None,
    *,
    purchase_data: bool,
    open_checks: set[uuid.UUID],
) -> AlertOut:
    return AlertOut(
        id=row.id,
        machine_id=row.machine_id,
        rule=row.rule,
        opened_at=row.opened_at,
        resolved_at=row.resolved_at,
        detail=_detail(row, purchase_data),
        check_id=row.check_id,
        check_open=row.check_id in open_checks,
        machine=machine,
    )


@router.get("", response_model=AlertList)
async def list_alerts(
    session: SessionDep,
    scope: CurrentScope,
    permissions: CurrentPermissions,
    rule: AlertRule | None = None,
    state: Literal["open", "resolved", "all"] = "open",
    machine_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> AlertList:
    """Alerts, newest first. ``machine_id`` narrows to one poste — its fiche,
    which asks for ``state=all`` to show the history too."""
    in_scope = machine_ids_clause(scope, col(MachineAlert.machine_id))
    if machine_id is not None and not await machine_visible(session, machine_id, scope):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    stmt = restrict(select(MachineAlert), in_scope)
    if rule is not None:
        stmt = stmt.where(col(MachineAlert.rule) == rule)
    if state == "open":
        stmt = stmt.where(col(MachineAlert.resolved_at).is_(None))
    elif state == "resolved":
        stmt = stmt.where(col(MachineAlert.resolved_at).is_not(None))
    if machine_id is not None:
        stmt = stmt.where(col(MachineAlert.machine_id) == machine_id)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        (
            await session.exec(
                stmt.order_by(
                    col(MachineAlert.resolved_at).is_(None).desc(),
                    col(MachineAlert.opened_at).desc(),
                    col(MachineAlert.id),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    machines = await _machines(session, {r.machine_id for r in rows})
    check_ids = {r.check_id for r in rows if r.check_id is not None}
    open_checks = (
        set(
            (
                await session.exec(
                    select(col(MachineCheck.id)).where(
                        col(MachineCheck.id).in_(check_ids),
                        col(MachineCheck.closed_at).is_(None),
                    )
                )
            ).all()
        )
        if check_ids
        else set()
    )
    purchase_data = has_permission(permissions, Resource.ASSET.value, Action.READ.value)

    counts_stmt = restrict(
        select(col(MachineAlert.rule), func.count()).where(
            col(MachineAlert.resolved_at).is_(None)
        ),
        in_scope,
    ).group_by(col(MachineAlert.rule))
    if machine_id is not None:
        counts_stmt = counts_stmt.where(col(MachineAlert.machine_id) == machine_id)
    counts = dict((await session.exec(counts_stmt)).all())

    return AlertList(
        items=[
            _out(
                r,
                machines.get(r.machine_id),
                purchase_data=purchase_data,
                open_checks=open_checks,
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        open_by_rule={r.value: counts.get(r.value, 0) for r in ALL_RULES},
    )
