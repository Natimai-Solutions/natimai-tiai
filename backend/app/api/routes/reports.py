"""Reports (C4): the form a label's QR code opens without an account, and the
queue the technicians sort.

The public half is the first unauthenticated entry point that is not the
agent, and is built as such: off unless the console turns it on, bounded
per address and per label (``core.ratelimit``), sizes bounded, and it says
nothing about the poste — not its name, not its state; the label's token is
all it reads, and renewing it (``POST /assets/{id}/token``) retires the
printed one.

The queue is read with ``report:read`` within the scope, sorted with
``report:write``; turning a report into a verification, or attaching it to
the one open, also asks for ``check:write`` and the poste in scope.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import (
    CurrentPermissions,
    CurrentScope,
    CurrentUser,
    SessionDep,
    require_permission,
)
from app.core import ratelimit
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.features.asset import crud as asset_crud
from app.features.asset.models import Asset
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.check import crud as check_crud
from app.features.check.models import CheckCategory, CheckPriority
from app.features.machine.models import Machine
from app.features.notification import tasks as task_mail
from app.features.report import crud
from app.features.report.models import Report, ReportStatus
from app.features.room import crud as room_crud
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import Scope, machine_visible, restrict

public_router = APIRouter(prefix="/public/reports", tags=["reports"])
router = APIRouter(prefix="/reports", tags=["reports"])

_READ = Depends(require_permission(Resource.REPORT, Action.READ))
_WRITE = Depends(require_permission(Resource.REPORT, Action.WRITE))

CATEGORIES = [c.value for c in CheckCategory]


# --- Public: the form -------------------------------------------------------------


class FormOut(BaseModel):
    """What the form needs, and nothing about the poste."""

    enabled: bool
    categories: list[str]


class ReportIn(BaseModel):
    category: CheckCategory
    text: str = Field(min_length=3, max_length=2000)
    contact: str | None = Field(default=None, max_length=200)
    language: Literal["fr", "en"] | None = None

    @field_validator("text", "contact", mode="before")
    @classmethod
    def _trim(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ReportAccepted(BaseModel):
    ok: bool = True


async def _label(session: SessionDep, token: str) -> Asset:
    asset = await asset_crud.by_token(session, token) if len(token) <= 64 else None
    if asset is None:
        raise AppError(
            code=ErrorCode.REPORT_LABEL_INVALID,
            status_code=404,
            message="This label leads nowhere",
        )
    return asset


def _disabled() -> AppError:
    return AppError(
        code=ErrorCode.REPORT_DISABLED,
        status_code=403,
        message="Reports are not open on this console",
    )


@public_router.get(
    "/{token}",
    response_model=FormOut,
    dependencies=[
        Depends(ratelimit.rate_limit(ratelimit.report_form_limiter, "report form"))
    ],
)
async def report_form(token: str, session: SessionDep) -> FormOut:
    """Whether the form is open for this label. Off, it says so whatever the
    token — a closed form tells nothing about the labels."""
    if not await crud.enabled(session):
        return FormOut(enabled=False, categories=[])
    await _label(session, token)
    return FormOut(enabled=True, categories=CATEGORIES)


@public_router.post(
    "/{token}",
    response_model=ReportAccepted,
    status_code=202,
    dependencies=[Depends(ratelimit.rate_limit(ratelimit.report_ip_limiter, "report"))],
)
async def submit_report(
    token: str, payload: ReportIn, session: SessionDep, request: Request
) -> ReportAccepted:
    """Leave a report on the labelled poste or equipment. Answers only that
    it was received."""
    if not await crud.enabled(session):
        raise _disabled()
    asset = await _label(session, token)
    ratelimit.check_account(
        ratelimit.report_label_limiter, str(asset.id), "report label"
    )
    session.add(
        Report(
            asset_id=asset.id,
            machine_id=asset.machine_id,
            category=payload.category.value,
            text=payload.text or "",
            contact=payload.contact,
            language=payload.language,
        )
    )
    audit.record(
        session,
        actor=f"report:{client_ip(request)}",
        action="report.create",
        resource_type="report",
        resource_id=str(asset.id),
        details={"category": payload.category.value},
    )
    await session.commit()
    return ReportAccepted()


# --- The queue ----------------------------------------------------------------------


class ReportOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID | None
    machine_id: uuid.UUID | None
    # What it is about: the poste's name, else the equipment's; its place.
    subject: str | None
    room_name: str | None
    building_name: str | None
    category: str
    text: str
    contact: str | None
    language: str | None
    status: str
    created_at: datetime
    handled_at: datetime | None
    handled_by: str | None
    handling_note: str | None
    check_id: uuid.UUID | None
    # The verification open on the poste right now, to attach to.
    open_check_id: uuid.UUID | None = None


class ReportList(BaseModel):
    items: list[ReportOut]
    total: int
    page: int
    page_size: int
    # Reports still to sort, within the scope: the menu's badge.
    new: int
    # Whether the form is open: a queue with the form closed fills no more.
    enabled: bool


async def _out(session: SessionDep, rows: list[Report]) -> list[ReportOut]:
    machine_ids = {r.machine_id for r in rows if r.machine_id}
    asset_ids = {r.asset_id for r in rows if r.asset_id}
    machines = (
        {
            m.id: m
            for m in (
                await session.exec(
                    select(Machine).where(col(Machine.id).in_(machine_ids))
                )
            ).all()
        }
        if machine_ids
        else {}
    )
    assets = (
        {
            a.id: a
            for a in (
                await session.exec(select(Asset).where(col(Asset.id).in_(asset_ids)))
            ).all()
        }
        if asset_ids
        else {}
    )
    open_checks = await check_crud.open_ids_for_machines(session, machine_ids)
    room_of: dict[uuid.UUID, uuid.UUID | None] = {}
    for r in rows:
        m = machines.get(r.machine_id) if r.machine_id else None
        a = assets.get(r.asset_id) if r.asset_id else None
        room_of[r.id] = m.room_id if m is not None else (a.room_id if a else None)
    placements = await room_crud.placements(session, room_of.values())
    out = []
    for r in rows:
        m = machines.get(r.machine_id) if r.machine_id else None
        a = assets.get(r.asset_id) if r.asset_id else None
        room_id = room_of[r.id]
        place = placements.get(room_id) if room_id else None
        out.append(
            ReportOut(
                id=r.id,
                asset_id=r.asset_id,
                machine_id=r.machine_id,
                subject=(m.hostname if m is not None else (a.name if a else None)),
                room_name=place.room.name if place and place.room else None,
                building_name=place.building.name if place and place.building else None,
                category=r.category,
                text=r.text,
                contact=r.contact,
                language=r.language,
                status=r.status,
                created_at=r.created_at,
                handled_at=r.handled_at,
                handled_by=r.handled_by,
                handling_note=r.handling_note,
                check_id=r.check_id,
                open_check_id=open_checks.get(r.machine_id) if r.machine_id else None,
            )
        )
    return out


async def _require(
    session: SessionDep, report_id: uuid.UUID, scope: Scope | None
) -> Report:
    report = (
        await session.exec(
            restrict(
                select(Report).where(col(Report.id) == report_id),
                crud.scope_clause(scope),
            )
        )
    ).first()
    if report is None:
        raise AppError(
            code=ErrorCode.REPORT_NOT_FOUND, status_code=404, message="Report not found"
        )
    found: Report = report
    return found


def _still_new(report: Report) -> None:
    if report.status != ReportStatus.NEW:
        raise AppError(
            code=ErrorCode.REPORT_ALREADY_HANDLED,
            status_code=409,
            message="This report was already handled",
        )


def _require_check_write(permissions: frozenset[str]) -> None:
    if not has_permission(permissions, Resource.CHECK.value, Action.WRITE.value):
        raise AppError(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            status_code=403,
            message="Missing permission: check:write",
            details={"resource": Resource.CHECK.value, "action": Action.WRITE.value},
        )


async def _require_machine(
    session: SessionDep, report: Report, scope: Scope | None
) -> Machine:
    machine = (
        await session.get(Machine, report.machine_id) if report.machine_id else None
    )
    if machine is None or not await machine_visible(session, machine.id, scope):
        raise AppError(
            code=ErrorCode.REPORT_NO_MACHINE,
            status_code=409,
            message="This report names no poste to open a verification on",
        )
    return machine


@router.get("", response_model=ReportList, dependencies=[_READ])
async def list_reports(
    session: SessionDep,
    scope: CurrentScope,
    state: Literal["new", "handled", "all"] = "new",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ReportList:
    """The queue: the reports to sort, oldest first; or those handled,
    newest first."""
    clause = crud.scope_clause(scope)
    stmt = restrict(select(Report), clause)
    if state == "new":
        stmt = stmt.where(col(Report.status) == ReportStatus.NEW).order_by(
            col(Report.created_at), col(Report.id)
        )
    else:
        if state == "handled":
            stmt = stmt.where(col(Report.status) != ReportStatus.NEW)
        stmt = stmt.order_by(col(Report.created_at).desc(), col(Report.id))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        (await session.exec(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    )
    new = await session.scalar(
        restrict(
            select(func.count())
            .select_from(Report)
            .where(col(Report.status) == ReportStatus.NEW),
            clause,
        )
    )
    return ReportList(
        items=await _out(session, rows),
        total=total,
        page=page,
        page_size=page_size,
        new=new or 0,
        enabled=await crud.enabled(session),
    )


class ConvertIn(BaseModel):
    assigned_to_id: uuid.UUID | None = None
    priority: CheckPriority = CheckPriority.NORMAL
    due_date: date | None = None


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


async def _record(
    session: SessionDep, actor: str, action: str, report: Report, **details: Any
) -> None:
    audit.record(
        session,
        actor=actor,
        action=f"report.{action}",
        resource_type="report",
        resource_id=str(report.id),
        details={"category": report.category, **details},
    )


@router.post("/{report_id}/convert", response_model=ReportOut, dependencies=[_WRITE])
async def convert_report(
    report_id: uuid.UUID,
    payload: ConvertIn,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
    permissions: CurrentPermissions,
) -> ReportOut:
    """Open a verification on the poste from the report — its words as the
    instructions. A verification already open: attach instead (409)."""
    _require_check_write(permissions)
    report = await _require(session, report_id, scope)
    _still_new(report)
    machine = await _require_machine(session, report, scope)
    if await check_crud.open_for_machine(session, machine.id) is not None:
        raise AppError(
            code=ErrorCode.CHECK_ALREADY_OPEN,
            status_code=409,
            message="A verification is already open on this machine",
        )
    assignee = None
    if payload.assigned_to_id is not None:
        from app.api.routes.checks import _require_assignee

        assignee = await _require_assignee(
            session, payload.assigned_to_id, [machine.id]
        )
    check = crud.open_check_from(
        report,
        requested_by=current.email,
        assigned_to_id=payload.assigned_to_id,
        priority=payload.priority,
        due_date=payload.due_date,
    )
    session.add(check)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise AppError(
            code=ErrorCode.CHECK_ALREADY_OPEN,
            status_code=409,
            message="A verification is already open on this machine",
        ) from None
    crud.mark_handled(
        report,
        ReportStatus.CONVERTED,
        by=current.email,
        now=utcnow(),
        check_id=check.id,
    )
    session.add(report)
    if assignee is not None and assignee.id != current.id:
        task_mail.send_checks_assigned(
            session,
            assignee=assignee,
            machines=[machine],
            requested_by=current.email,
            instructions=check.instructions,
        )
    await _record(session, current.email, "convert", report, check_id=str(check.id))
    await session.commit()
    await session.refresh(report)
    return (await _out(session, [report]))[0]


@router.post("/{report_id}/attach", response_model=ReportOut, dependencies=[_WRITE])
async def attach_report(
    report_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
    permissions: CurrentPermissions,
) -> ReportOut:
    """Attach the report to the verification already open on its poste."""
    _require_check_write(permissions)
    report = await _require(session, report_id, scope)
    _still_new(report)
    machine = await _require_machine(session, report, scope)
    check = await check_crud.open_for_machine(session, machine.id)
    if check is None:
        raise AppError(
            code=ErrorCode.REPORT_NO_OPEN_CHECK,
            status_code=409,
            message="No verification is open on this poste",
        )
    crud.mark_handled(
        report, ReportStatus.ATTACHED, by=current.email, now=utcnow(), check_id=check.id
    )
    session.add(report)
    await _record(session, current.email, "attach", report, check_id=str(check.id))
    await session.commit()
    await session.refresh(report)
    return (await _out(session, [report]))[0]


@router.post("/{report_id}/close", response_model=ReportOut, dependencies=[_WRITE])
async def close_report(
    report_id: uuid.UUID,
    payload: NoteIn,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
    reject: bool = False,
) -> ReportOut:
    """Close a report without a verification — seen to, or (``reject``)
    nothing to do."""
    report = await _require(session, report_id, scope)
    _still_new(report)
    note = (payload.note or "").strip() or None
    status = ReportStatus.REJECTED if reject else ReportStatus.CLOSED
    crud.mark_handled(report, status, by=current.email, now=utcnow(), note=note)
    session.add(report)
    await _record(session, current.email, "reject" if reject else "close", report)
    await session.commit()
    await session.refresh(report)
    return (await _out(session, [report]))[0]
