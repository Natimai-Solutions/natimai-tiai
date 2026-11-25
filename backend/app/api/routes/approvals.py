"""Two-person approval of mass actions (C10, ``dev/plan-approbation-masse.md``).

Every route asks for ``risky_command:execute``. The list, the badge, the
detail and the decisions read one rule (``approval_crud.decidable``):
another account's request, the rights the action asks for, every poste of
it in the reader's scope. Approving and rejecting are a person's acts: a
personal API token is refused (``CurrentAuthSession``); creating a request
(``POST /commands``) and cancelling one's own remain open to a token
allowed to write.

A failure found while approving closes the request: committed first, then
answered (``approval_crud.CommitThenRaise``).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    CurrentAuthSession,
    CurrentPermissions,
    CurrentScope,
    CurrentUser,
    SessionDep,
    require_permission,
)
from app.core.errors import AppError, ErrorCode
from app.features.approval import crud
from app.features.approval import execute as approval_execute
from app.features.approval import schedule as approval_schedule
from app.features.approval.models import (
    ApprovalKind,
    ApprovalRequest,
    ApprovalRequestMachine,
    ApprovalStatus,
)
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.package import crud as package_crud
from app.features.room.models import Room
from app.features.schedule.models import Schedule, ScheduleState
from app.features.setting import crud as setting_crud
from app.features.user.permissions import Action, Resource
from app.features.user.scope import machine_ids_clause, restrict

router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
    dependencies=[Depends(require_permission(Resource.RISKY_COMMAND, Action.EXECUTE))],
)


class ApprovalOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    command_type: str
    package_id: uuid.UUID | None
    package_name: str | None
    target: dict[str, Any]
    machine_count: int
    threshold: int
    ttl_minutes: int | None
    schedule_id: uuid.UUID | None
    schedule_name: str | None
    requested_by: str
    requested_at: datetime
    expires_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    note: str | None
    result_code: str | None
    result_params: dict[str, Any] | None
    created: int | None
    skipped: int | None
    left_out: int | None

    model_config = {"from_attributes": True}


class ApprovalMachine(BaseModel):
    id: uuid.UUID
    hostname: str | None
    room: str | None


class ApprovalScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    state: str
    recurrence: str
    run_at: datetime | None
    weekdays: list[int]
    time_of_day: str | None
    stages: int


class ApprovalDetail(ApprovalOut):
    # The postes of the list within the reader's scope as it is now, and how
    # many others there are — an author whose scope shrank since does not
    # see their names any more.
    machines: list[ApprovalMachine] = Field(default_factory=list)
    hidden: int = 0
    schedule: ApprovalScheduleOut | None = None


class ApprovalList(BaseModel):
    items: list[ApprovalOut]
    total: int
    page: int
    page_size: int


class ApprovalSummary(BaseModel):
    enabled: bool
    to_decide: int
    mine_pending: int


class ApproveIn(BaseModel):
    # The approver saw the forbidden window open now, as the author was
    # asked when sending.
    confirm_forbidden_window: bool = False


class RejectIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _out(request: ApprovalRequest) -> ApprovalOut:
    return ApprovalOut.model_validate(request)


@router.get("", response_model=ApprovalList)
async def list_approvals(
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    scope: CurrentScope,
    view: Literal["to_decide", "mine"] = "to_decide",
    status: ApprovalStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ApprovalList:
    """``to_decide``: what the reader may decide, the oldest first to
    expire; ``mine``: their own, every status, the latest first."""
    user_id = user.id
    await crud.mark_expired(session, utcnow())
    if view == "mine":
        stmt = select(ApprovalRequest).where(
            col(ApprovalRequest.requested_by_id) == user_id
        )
        order = [col(ApprovalRequest.requested_at).desc(), col(ApprovalRequest.id)]
    else:
        clause = await crud.decidable(session, scope, user_id, permissions)
        stmt = select(ApprovalRequest).where(clause)
        order = [col(ApprovalRequest.expires_at), col(ApprovalRequest.id)]
    if status is not None:
        stmt = stmt.where(col(ApprovalRequest.status) == status)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await session.exec(
            stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return ApprovalList(
        items=[_out(r) for r in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=ApprovalSummary)
async def approvals_summary(
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    scope: CurrentScope,
) -> ApprovalSummary:
    """The menu's badge: what the reader may decide, and their own requests
    waiting."""
    user_id = user.id
    now = utcnow()
    clause = await crud.decidable(session, scope, user_id, permissions)
    to_decide = await session.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(clause, col(ApprovalRequest.expires_at) > now)
    )
    mine = await session.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(
            col(ApprovalRequest.requested_by_id) == user_id,
            col(ApprovalRequest.status) == ApprovalStatus.PENDING,
            col(ApprovalRequest.expires_at) > now,
        )
    )
    return ApprovalSummary(
        enabled=(await setting_crud.approval_policy(session)).enabled,
        to_decide=to_decide or 0,
        mine_pending=mine or 0,
    )


@router.get("/{approval_id}", response_model=ApprovalDetail)
async def get_approval(
    approval_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    scope: CurrentScope,
) -> ApprovalDetail:
    """Seen by its author and by whoever may decide it."""
    user_id = user.id
    clause = await crud.decidable(
        session, scope, user_id, permissions, pending=False, only_id=approval_id
    )
    request = (
        await session.exec(
            select(ApprovalRequest).where(
                col(ApprovalRequest.id) == approval_id,
                (col(ApprovalRequest.requested_by_id) == user_id) | clause,
            )
        )
    ).first()
    if request is None:
        raise AppError(
            code=ErrorCode.APPROVAL_NOT_FOUND,
            status_code=404,
            message="Approval request not found",
        )
    detail = ApprovalDetail.model_validate(request, from_attributes=True)
    if request.kind == ApprovalKind.COMMAND:
        listed = (
            select(ApprovalRequestMachine.machine_id)
            .where(col(ApprovalRequestMachine.request_id) == request.id)
            .subquery()
        )
        total = (await session.scalar(select(func.count()).select_from(listed))) or 0
        rows = (
            await session.exec(
                restrict(
                    select(Machine.id, Machine.hostname, Room.name)
                    .join(listed, listed.c.machine_id == col(Machine.id))
                    .outerjoin(Room, col(Room.id) == col(Machine.room_id)),
                    machine_ids_clause(scope, col(Machine.id)),
                ).order_by(col(Machine.hostname), col(Machine.id))
            )
        ).all()
        detail.machines = [
            ApprovalMachine(id=mid, hostname=hostname, room=room)
            for mid, hostname, room in rows
        ]
        detail.hidden = max(total - len(detail.machines), 0)
    elif request.schedule_id is not None:
        schedule = await session.get(Schedule, request.schedule_id)
        if schedule is not None:
            detail.schedule = ApprovalScheduleOut(
                id=schedule.id,
                name=schedule.name,
                state=schedule.state,
                recurrence=schedule.recurrence,
                run_at=schedule.run_at,
                weekdays=schedule.weekdays or [],
                time_of_day=schedule.time_of_day,
                stages=len(schedule.rings or []) or 1,
            )
    return detail


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: uuid.UUID,
    payload: ApproveIn,
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    scope: CurrentScope,
    _auth: CurrentAuthSession,
) -> ApprovalOut:
    """Approve: the frozen list is queued on the author's behalf, checked
    again now (§2.3) — or, for a schedule, it becomes active."""
    user_id, user_email = user.id, user.email
    now = utcnow()
    superseded = 0
    try:
        request = await crud.lock_for_decision(
            session,
            approval_id,
            user_id=user_id,
            user_email=user_email,
            permissions=permissions,
            scope=scope,
            now=now,
        )
        if request.kind == ApprovalKind.SCHEDULE:
            await approval_schedule.approve_schedule(
                session,
                request,
                approver_id=user_id,
                approver_email=user_email,
                approver_permissions=permissions,
                now=now,
            )
        else:
            approved = await approval_execute.approve_command(
                session,
                request,
                approver_id=user_id,
                approver_email=user_email,
                confirm_forbidden_window=payload.confirm_forbidden_window,
                now=now,
            )
            superseded = approved.superseded
    except crud.CommitThenRaise as exc:
        await session.commit()
        raise exc.error from None
    out = _out(request)
    await session.commit()
    if superseded:
        await package_crud.sweep_store(session)
    return out


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: uuid.UUID,
    payload: RejectIn,
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    scope: CurrentScope,
    _auth: CurrentAuthSession,
) -> ApprovalOut:
    """Reject, with an optional reason the author is mailed."""
    user_id, user_email = user.id, user.email
    now = utcnow()
    try:
        request = await crud.lock_for_decision(
            session,
            approval_id,
            user_id=user_id,
            user_email=user_email,
            permissions=permissions,
            scope=scope,
            now=now,
        )
    except crud.CommitThenRaise as exc:
        await session.commit()
        raise exc.error from None
    note = (payload.note or "").strip() or None
    await crud.reject(
        session, request, actor_id=user_id, actor_email=user_email, note=note, now=now
    )
    out = _out(request)
    await session.commit()
    return out


@router.post("/{approval_id}/cancel", response_model=ApprovalOut)
async def cancel(
    approval_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> ApprovalOut:
    """Cancel one's own pending request."""
    user_id, user_email = user.id, user.email
    now = utcnow()
    try:
        request = await crud.lock_own(session, approval_id, user_id=user_id, now=now)
    except crud.CommitThenRaise as exc:
        await session.commit()
        raise exc.error from None
    await crud.cancel(session, request, actor=user_email, now=now)
    if request.kind == ApprovalKind.SCHEDULE and request.schedule_id is not None:
        # Nothing waits for it any more: the schedule is off, as « Désactiver »
        # would leave it, rather than waiting for nobody.
        schedule = await session.get(Schedule, request.schedule_id)
        if schedule is not None and schedule.state == ScheduleState.TO_APPROVE:
            schedule.state = ScheduleState.DISABLED
            schedule.next_run_at = None
            schedule.updated_at = now
            session.add(schedule)
    out = _out(request)
    await session.commit()
    return out
