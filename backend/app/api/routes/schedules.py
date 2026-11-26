"""Schedules, as the console writes and reads them (C3).

Read with ``schedule:read``, written with ``schedule:write`` — and the right
to run what the schedule carries, checked when it is written and again at each
run (``features.schedule.runner``). Writing a schedule, or turning it back on,
puts it in the writer's name: the runs are theirs, on their rights and scope.

A restricted account sees the schedules it wrote, and those aimed at a room,
a building or postes all within its scope; a schedule aimed at a whole domain,
site or the parc, written by someone else, is not its business.
"""

import uuid
from datetime import date, datetime, time
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, update
from sqlmodel import col, select

from app.api.deps import (
    CurrentPermissions,
    CurrentScope,
    CurrentUser,
    SessionDep,
    require_permission,
)
from app.core.config import settings as env
from app.core.errors import AppError, ErrorCode
from app.features.approval import crud as approval_crud
from app.features.approval import schedule as approval_schedule
from app.features.approval.models import ApprovalRequest, ApprovalStatus
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.command import target as target_crud
from app.features.command.models import (
    PACKAGE_COMMAND_TYPES,
    RISKY_COMMAND_TYPES,
    CommandType,
)
from app.features.command.target import Target
from app.features.machine.models import Machine
from app.features.machine.status import MachineStatus
from app.features.package.models import Package
from app.features.room.models import Building, Room
from app.features.schedule import crud as schedule_crud
from app.features.schedule import runner, windows
from app.features.schedule.models import (
    Recurrence,
    RunStatus,
    Schedule,
    ScheduleRun,
    ScheduleState,
)
from app.features.setting import crud as setting_crud
from app.features.user.permissions import (
    Action,
    Resource,
    has_permission,
    permission_key,
)
from app.features.user.scope import Scope

router = APIRouter(prefix="/schedules", tags=["schedules"])

_READ = Depends(require_permission(Resource.SCHEDULE, Action.READ))
_WRITE = Depends(require_permission(Resource.SCHEDULE, Action.WRITE))

# The types a deployment in rings is for: what changes the postes for good,
# and is worth trying on a pilot room first.
RING_TYPES = frozenset(
    {
        CommandType.WU_INSTALL,
        CommandType.WU_INSTALL_FULL,
        CommandType.PACKAGE_INSTALL,
    }
)
MAX_RINGS = 5


class TargetIn(BaseModel):
    kind: Literal["machines", "all", "domain", "location", "status", "room", "building"]
    machine_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    value: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _complete(self) -> "TargetIn":
        if self.kind == "machines" and not self.machine_ids:
            raise ValueError("a list of postes names at least one")
        if self.kind not in ("machines", "all") and not self.value:
            raise ValueError("this target needs a value")
        if self.kind == "status":
            MachineStatus(self.value or "")
        if self.kind in ("room", "building"):
            uuid.UUID(self.value or "")
        return self

    def target(self) -> Target:
        if self.kind == "machines":
            return Target(
                "machines", machine_ids=tuple(dict.fromkeys(self.machine_ids))
            )
        if self.kind == "all":
            return Target("all")
        return Target(self.kind, value=self.value)


class RingIn(BaseModel):
    target: TargetIn


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    command_type: CommandType
    package_id: uuid.UUID | None = None
    target: TargetIn
    recurrence: Recurrence
    # A one-off: the local date and time, in the console's zone.
    run_at_local: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"
    )
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    time_of_day: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    ttl_minutes: int | None = Field(default=None, ge=10, le=60 * 24)
    wake_first: bool = False
    shutdown_after: bool = False
    rings: list[RingIn] | None = Field(default=None, max_length=MAX_RINGS)
    ring_observe_hours: int | None = Field(default=None, ge=1, le=24 * 14)
    ring_failure_percent: int | None = Field(default=None, ge=0, le=100)

    @field_validator("name", mode="before")
    @classmethod
    def _trim(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("weekdays")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in value):
            raise ValueError("a weekday is 0 (Monday) to 6")
        return sorted(set(value))

    @model_validator(mode="after")
    def _coherent(self) -> "ScheduleIn":
        if self.recurrence == Recurrence.ONCE and not self.run_at_local:
            raise ValueError("a one-off needs its date and time")
        if self.recurrence == Recurrence.WEEKLY and (
            not self.weekdays or not self.time_of_day
        ):
            raise ValueError("a weekly schedule needs its days and time")
        if (
            self.package_id is not None
            and self.command_type not in PACKAGE_COMMAND_TYPES
        ):
            raise ValueError("package_id only goes with package_install/uninstall")
        if self.command_type in PACKAGE_COMMAND_TYPES and self.package_id is None:
            raise ValueError("a deployment names its package")
        if self.command_type == CommandType.DIRECTORY_READ:
            raise ValueError("directory_read is queued by the server alone")
        if self.command_type == CommandType.WAKE_ON_LAN and (
            self.wake_first or self.shutdown_after or self.rings
        ):
            raise ValueError("a wake is not chained")
        if self.command_type in (CommandType.SHUTDOWN, CommandType.REBOOT) and (
            self.shutdown_after
        ):
            raise ValueError("a shutdown is not followed by another")
        if self.shutdown_after and not self.wake_first:
            raise ValueError("only the postes woken are shut down after")
        if self.rings:
            if self.command_type not in RING_TYPES:
                raise ValueError("rings are for update installs and deployments")
            if len(self.rings) < 2:
                raise ValueError("rings have two stages at least")
            if self.ring_observe_hours is None or self.ring_failure_percent is None:
                raise ValueError("rings need an observation delay and a threshold")
        return self


class TargetOut(BaseModel):
    kind: str
    machine_ids: list[uuid.UUID] = Field(default_factory=list)
    value: str | None = None
    # What the console names it by: the room or building, a few postes.
    label: str | None = None
    machine_count: int | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    started_at: datetime
    # The same instant in the console's zone, as ``next_run_local``: the
    # history reads in the zone the schedules are planned in, whatever the
    # browser's. ``due_local``: the planned hour of a missed occurrence.
    started_local: str | None = None
    due_local: str | None = None
    finished_at: datetime | None
    status: str
    result_code: str | None
    result_params: dict[str, Any] | None
    created: int
    skipped: int
    left_out: int
    woken: int
    shut_down: int
    kept_on: int
    stage: int


class ScheduleApprovalOut(BaseModel):
    """Its approval (C10): the latest request, and who approved it."""

    id: uuid.UUID | None = None
    status: str | None = None
    expires_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    approved_count: int | None = None


class ScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    command_type: str
    package_id: uuid.UUID | None
    package_name: str | None = None
    target: TargetOut
    recurrence: str
    run_at_local: str | None
    weekdays: list[int]
    time_of_day: str | None
    ttl_minutes: int
    wake_first: bool
    shutdown_after: bool
    rings: list[TargetOut] | None
    ring_observe_hours: int | None
    ring_failure_percent: int | None
    state: str
    suspended_code: str | None
    suspended_at: datetime | None
    next_run_at: datetime | None
    # The next run in the console's zone, « 2026-11-25T18:00 »: what the
    # console shows, whatever the browser's zone.
    next_run_local: str | None
    last_run_at: datetime | None
    last_run: RunOut | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    approval: ScheduleApprovalOut | None = None


class ScheduleList(BaseModel):
    items: list[ScheduleOut]
    total: int
    page: int
    page_size: int
    # The console's zone and forbidden windows: the page plans in them.
    timezone: str
    forbidden_windows: list[dict[str, Any]]


class RunList(BaseModel):
    items: list[RunOut]
    total: int
    page: int
    page_size: int


# --- Helpers ------------------------------------------------------------------


def _local(instant: datetime | None, policy: windows.SchedulePolicy) -> str | None:
    if instant is None:
        return None
    return instant.astimezone(policy.zone).strftime("%Y-%m-%dT%H:%M")


def _due(run: ScheduleRun) -> datetime | None:
    raw = (run.result_params or {}).get("due")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _run_out(run: ScheduleRun, policy: windows.SchedulePolicy) -> RunOut:
    return RunOut(
        id=run.id,
        started_at=run.started_at,
        started_local=_local(run.started_at, policy),
        due_local=_local(_due(run), policy),
        finished_at=run.finished_at,
        status=run.status,
        result_code=run.result_code,
        result_params=run.result_params,
        created=run.created,
        skipped=run.skipped,
        left_out=run.left_out,
        woken=run.woken,
        shut_down=len(run.shutdown_ids or []),
        kept_on=len(run.kept_on_ids or []),
        stage=run.stage,
    )


async def _target_out(session: SessionDep, data: dict[str, Any]) -> TargetOut:
    target = Target.from_json(data)
    out = TargetOut(
        kind=target.kind, machine_ids=list(target.machine_ids), value=target.value
    )
    if target.room_id is not None:
        room = await session.get(Room, target.room_id)
        if room is not None:
            building = (
                await session.get(Building, room.building_id)
                if room.building_id
                else None
            )
            out.label = f"{building.name} — {room.name}" if building else room.name
    elif target.building_id is not None:
        building = await session.get(Building, target.building_id)
        out.label = building.name if building else None
    elif target.kind == "machines":
        names = (
            await session.exec(
                select(Machine.hostname)
                .where(col(Machine.id).in_(list(target.machine_ids)))
                .order_by(Machine.hostname)
                .limit(3)
            )
        ).all()
        out.label = ", ".join(n or "?" for n in names) or None
        out.machine_count = len(target.machine_ids)
    return out


async def _out(
    session: SessionDep, schedule: Schedule, policy: windows.SchedulePolicy
) -> ScheduleOut:
    last = (
        await session.exec(
            select(ScheduleRun)
            .where(col(ScheduleRun.schedule_id) == schedule.id)
            .order_by(col(ScheduleRun.started_at).desc())
            .limit(1)
        )
    ).first()
    request = (
        await session.exec(
            select(ApprovalRequest)
            .where(col(ApprovalRequest.schedule_id) == schedule.id)
            .order_by(col(ApprovalRequest.requested_at).desc())
            .limit(1)
        )
    ).first()
    approval = None
    if request is not None or schedule.approved_at is not None:
        approval = ScheduleApprovalOut(
            id=request.id if request is not None else None,
            status=request.status if request is not None else None,
            expires_at=request.expires_at if request is not None else None,
            approved_by=schedule.approved_by,
            approved_at=schedule.approved_at,
            approved_count=schedule.approved_count,
        )
    package_name = None
    if schedule.package_id is not None:
        package = await session.get(Package, schedule.package_id)
        if package is not None:
            package_name = (
                f"{package.name} {package.version}" if package.version else package.name
            )
    return ScheduleOut(
        id=schedule.id,
        name=schedule.name,
        command_type=schedule.command_type,
        package_id=schedule.package_id,
        package_name=package_name,
        target=await _target_out(session, schedule.target),
        recurrence=schedule.recurrence,
        run_at_local=_local(schedule.run_at, policy),
        weekdays=schedule.weekdays or [],
        time_of_day=schedule.time_of_day,
        ttl_minutes=schedule.ttl_minutes,
        wake_first=schedule.wake_first,
        shutdown_after=schedule.shutdown_after,
        rings=(
            [await _target_out(session, r["target"]) for r in schedule.rings]
            if schedule.rings
            else None
        ),
        ring_observe_hours=schedule.ring_observe_hours,
        ring_failure_percent=schedule.ring_failure_percent,
        state=schedule.state,
        suspended_code=schedule.suspended_code,
        suspended_at=schedule.suspended_at,
        next_run_at=schedule.next_run_at,
        next_run_local=_local(schedule.next_run_at, policy),
        last_run_at=schedule.last_run_at,
        last_run=_run_out(last, policy) if last is not None else None,
        created_by=schedule.created_by,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        approval=approval,
    )


async def _visible(
    session: SessionDep, schedule: Schedule, scope: Scope | None, user_id: uuid.UUID
) -> bool:
    """Whether a restricted reader may see ``schedule`` (see the module):
    ``schedule_crud.visible_to``, the rule approving one follows too."""
    return await schedule_crud.visible_to(session, schedule, scope, user_id)


async def _require(
    session: SessionDep, schedule_id: uuid.UUID, scope: Scope | None, user_id: uuid.UUID
) -> Schedule:
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None or not await _visible(session, schedule, scope, user_id):
        raise AppError(
            code=ErrorCode.SCHEDULE_NOT_FOUND,
            status_code=404,
            message="Schedule not found",
        )
    return schedule


async def _lock(
    session: SessionDep, schedule_id: uuid.UUID, scope: Scope | None, user_id: uuid.UUID
) -> Schedule:
    """The schedule about to be rewritten, turned off or on, or deleted:
    locked in the order an approval locks them — its pending request, then
    the schedule (``approval.schedule.approve_schedule``) — and read again
    under the lock. An approval committed meanwhile is seen, and cleared by
    the write; never the reverse order, which deadlocks against it."""
    await session.exec(
        select(col(ApprovalRequest.id))
        .where(
            col(ApprovalRequest.schedule_id) == schedule_id,
            col(ApprovalRequest.status) == ApprovalStatus.PENDING,
        )
        .with_for_update()
    )
    schedule = (
        await session.exec(
            select(Schedule)
            .where(col(Schedule.id) == schedule_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()
    if schedule is None or not await _visible(session, schedule, scope, user_id):
        raise AppError(
            code=ErrorCode.SCHEDULE_NOT_FOUND,
            status_code=404,
            message="Schedule not found",
        )
    return schedule


def _require_command_rights(
    permissions: frozenset[str], command_type: CommandType, shutdown_after: bool
) -> None:
    """Writing a schedule asks for the right to run what it carries."""
    needed = [(Resource.COMMAND, Action.EXECUTE)]
    if command_type in RISKY_COMMAND_TYPES or shutdown_after:
        needed.append((Resource.RISKY_COMMAND, Action.EXECUTE))
    for resource, action in needed:
        if not has_permission(permissions, resource.value, action.value):
            raise AppError(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                status_code=403,
                message=f"Missing permission: {permission_key(resource, action)}",
                details={"resource": resource.value, "action": action.value},
            )


async def _check_target(
    session: SessionDep, target: Target, scope: Scope | None
) -> None:
    """A room or building out of reach, or postes none of which the writer
    sees, answer « introuvable » as everywhere."""
    if not await target_crud.place_visible(session, target, scope):
        raise AppError(
            code=(
                ErrorCode.ROOM_NOT_FOUND
                if target.kind == "room"
                else ErrorCode.BUILDING_NOT_FOUND
            ),
            status_code=404,
            message="Room or building not found",
        )
    if target.kind == "machines" and not await target_crud.resolve(
        session, target, scope
    ):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )


async def _apply(
    session: SessionDep,
    schedule: Schedule,
    payload: ScheduleIn,
    *,
    scope: Scope | None,
    permissions: frozenset[str],
    user: Any,
) -> None:
    """Validate ``payload`` against the writer and the clock, and write it
    onto ``schedule``, in the writer's name."""
    _require_command_rights(permissions, payload.command_type, payload.shutdown_after)
    target = payload.target.target()
    await _check_target(session, target, scope)
    for ring in payload.rings or []:
        await _check_target(session, ring.target.target(), scope)
    if (
        payload.package_id is not None
        and await session.get(Package, payload.package_id) is None
    ):
        raise AppError(
            code=ErrorCode.PACKAGE_NOT_FOUND,
            status_code=404,
            message="Package not found",
        )
    policy = await windows.schedule_policy(session)
    now = utcnow()
    at_risk = payload.command_type in RISKY_COMMAND_TYPES or payload.shutdown_after
    run_at: datetime | None = None
    next_run: datetime | None
    if payload.recurrence == Recurrence.ONCE:
        day, clock = (payload.run_at_local or "").split("T")
        run_at = windows.local_to_utc(
            date.fromisoformat(day), time.fromisoformat(clock), policy.zone
        )
        if run_at <= now:
            raise AppError(
                code=ErrorCode.SCHEDULE_IN_PAST,
                status_code=422,
                message="This date and time are past",
            )
        window = policy.forbidden_at(run_at) if at_risk else None
        next_run = run_at
    else:
        window = (
            windows.weekly_in_forbidden(
                payload.weekdays, payload.time_of_day or "", policy
            )
            if at_risk
            else None
        )
        next_run = windows.next_weekly(
            payload.weekdays, payload.time_of_day or "", policy.zone, now
        )
    if window is not None:
        raise AppError(
            code=ErrorCode.SCHEDULE_FORBIDDEN_WINDOW,
            status_code=409,
            message="This schedule would run inside a forbidden window",
            details=windows.window_details(window),
        )
    # Any write of its content voids its approval, and closes the request
    # still waiting for the previous version (C10).
    approval_schedule.clear_approval(schedule)
    await approval_crud.close_for_schedule(
        session, schedule.id, actor=user.email, cause="schedule_changed", now=now
    )
    schedule.name = payload.name
    schedule.command_type = payload.command_type.value
    schedule.package_id = payload.package_id
    schedule.target = target.as_json()
    schedule.recurrence = payload.recurrence.value
    schedule.run_at = run_at
    schedule.weekdays = (
        payload.weekdays if payload.recurrence == Recurrence.WEEKLY else None
    )
    schedule.time_of_day = (
        payload.time_of_day if payload.recurrence == Recurrence.WEEKLY else None
    )
    schedule.ttl_minutes = payload.ttl_minutes or env.SCHEDULE_COMMAND_TTL_MINUTES
    schedule.wake_first = payload.wake_first
    schedule.shutdown_after = payload.shutdown_after
    schedule.rings = (
        [{"target": r.target.target().as_json()} for r in payload.rings]
        if payload.rings
        else None
    )
    schedule.ring_observe_hours = payload.ring_observe_hours if payload.rings else None
    schedule.ring_failure_percent = (
        payload.ring_failure_percent if payload.rings else None
    )
    schedule.state = ScheduleState.ACTIVE
    schedule.suspended_code = None
    schedule.suspended_at = None
    schedule.next_run_at = next_run
    schedule.created_by_id = user.id
    schedule.created_by = user.email
    schedule.updated_at = now


async def _gate(
    session: SessionDep,
    schedule: Schedule,
    *,
    user_id: uuid.UUID,
    user_email: str,
    scope: Scope | None,
    keep_approval: bool = False,
) -> bool:
    """After a write or a reactivation: whether the schedule now waits for
    its approval (C10). A request still pending for it is closed first."""
    now = utcnow()
    policy = await setting_crud.approval_policy(session)
    request = await approval_schedule.gate(
        session,
        schedule,
        author_id=user_id,
        author_email=user_email,
        scope=scope,
        policy=policy,
        now=now,
        keep_approval=keep_approval,
    )
    return request is not None


def _audit_details(schedule: Schedule) -> dict[str, Any]:
    return {
        "name": schedule.name,
        "command_type": schedule.command_type,
        "target": schedule.target.get("kind"),
        "recurrence": schedule.recurrence,
        **({"package_id": str(schedule.package_id)} if schedule.package_id else {}),
        **({"wake_first": True} if schedule.wake_first else {}),
        **({"shutdown_after": True} if schedule.shutdown_after else {}),
        **({"rings": len(schedule.rings)} if schedule.rings else {}),
    }


# --- Routes -------------------------------------------------------------------


@router.get("", response_model=ScheduleList, dependencies=[_READ])
async def list_schedules(
    session: SessionDep,
    scope: CurrentScope,
    user: CurrentUser,
    state: ScheduleState | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ScheduleList:
    """The schedules the reader may see, the next to run first."""
    stmt = select(Schedule)
    if state is not None:
        stmt = stmt.where(col(Schedule.state) == state)
    rows = list(
        (
            await session.exec(
                stmt.order_by(
                    col(Schedule.next_run_at).asc().nulls_last(),
                    col(Schedule.name),
                    col(Schedule.id),
                )
            )
        ).all()
    )
    if scope is not None:
        rows = [r for r in rows if await _visible(session, r, scope, user.id)]
    policy = await windows.schedule_policy(session)
    page_rows = rows[(page - 1) * page_size : page * page_size]
    return ScheduleList(
        items=[await _out(session, r, policy) for r in page_rows],
        total=len(rows),
        page=page,
        page_size=page_size,
        timezone=policy.zone_name,
        forbidden_windows=[w.as_json() for w in policy.forbidden],
    )


@router.post("", response_model=ScheduleOut, status_code=201, dependencies=[_WRITE])
async def create_schedule(
    payload: ScheduleIn,
    session: SessionDep,
    scope: CurrentScope,
    user: CurrentUser,
    permissions: CurrentPermissions,
) -> ScheduleOut:
    user_id, user_email = user.id, user.email
    schedule = Schedule(
        name=payload.name,
        command_type=payload.command_type.value,
        target={},
        recurrence=payload.recurrence.value,
        created_by=user_email,
    )
    await _apply(
        session, schedule, payload, scope=scope, permissions=permissions, user=user
    )
    session.add(schedule)
    await session.flush()
    required = await _gate(
        session, schedule, user_id=user_id, user_email=user_email, scope=scope
    )
    audit.record(
        session,
        actor=user_email,
        action="schedule.create",
        resource_type="schedule",
        resource_id=str(schedule.id),
        details={
            **_audit_details(schedule),
            **({"approval": "required"} if required else {}),
        },
    )
    await session.commit()
    await session.refresh(schedule)
    return await _out(session, schedule, await windows.schedule_policy(session))


@router.get("/{schedule_id}", response_model=ScheduleOut, dependencies=[_READ])
async def get_schedule(
    schedule_id: uuid.UUID, session: SessionDep, scope: CurrentScope, user: CurrentUser
) -> ScheduleOut:
    schedule = await _require(session, schedule_id, scope, user.id)
    return await _out(session, schedule, await windows.schedule_policy(session))


@router.put("/{schedule_id}", response_model=ScheduleOut, dependencies=[_WRITE])
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleIn,
    session: SessionDep,
    scope: CurrentScope,
    user: CurrentUser,
    permissions: CurrentPermissions,
) -> ScheduleOut:
    """Rewrite a schedule — in the writer's name from now on, active again."""
    user_id, user_email = user.id, user.email
    schedule = await _lock(session, schedule_id, scope, user_id)
    previous_author = schedule.created_by
    previous_stages = len(schedule.rings or [])
    await _apply(
        session, schedule, payload, scope=scope, permissions=permissions, user=user
    )
    session.add(schedule)
    if previous_stages > 1:
        # A staged deployment under way does not go on to its next stage
        # with the rings — nor on behalf of the author — of this new version
        # (``runner.follow_one``, C10); what it woke is still shut down.
        await session.exec(
            update(ScheduleRun)
            .where(
                col(ScheduleRun.schedule_id) == schedule.id,
                col(ScheduleRun.status) == RunStatus.RUNNING,
                col(ScheduleRun.stage) < previous_stages - 1,
            )
            .values(result_code="schedule_changed")
        )
    await session.flush()
    required = await _gate(
        session, schedule, user_id=user_id, user_email=user_email, scope=scope
    )
    audit.record(
        session,
        actor=user_email,
        action="schedule.update",
        resource_type="schedule",
        resource_id=str(schedule.id),
        details={
            **_audit_details(schedule),
            **(
                {"previous_author": previous_author}
                if previous_author != user_email
                else {}
            ),
            **({"approval": "required"} if required else {}),
        },
    )
    await session.commit()
    await session.refresh(schedule)
    return await _out(session, schedule, await windows.schedule_policy(session))


class StateIn(BaseModel):
    enabled: bool


@router.post("/{schedule_id}/state", response_model=ScheduleOut, dependencies=[_WRITE])
async def set_state(
    schedule_id: uuid.UUID,
    payload: StateIn,
    session: SessionDep,
    scope: CurrentScope,
    user: CurrentUser,
    permissions: CurrentPermissions,
) -> ScheduleOut:
    """Turn a schedule off, or back on — suspended ones included, in the
    name of whoever turns it on, who must hold what it needs."""
    user_id, user_email = user.id, user.email
    schedule = await _lock(session, schedule_id, scope, user_id)
    now = utcnow()
    required = False
    if payload.enabled:
        _require_command_rights(
            permissions, CommandType(schedule.command_type), schedule.shutdown_after
        )
        policy = await windows.schedule_policy(session)
        if schedule.recurrence == Recurrence.ONCE:
            if schedule.run_at is None or schedule.run_at <= now:
                raise AppError(
                    code=ErrorCode.SCHEDULE_IN_PAST,
                    status_code=422,
                    message="This date and time are past",
                )
            schedule.next_run_at = schedule.run_at
        else:
            schedule.next_run_at = runner.next_occurrence(schedule, policy, now)
        schedule.state = ScheduleState.ACTIVE
        schedule.suspended_code = None
        schedule.suspended_at = None
        schedule.created_by_id = user_id
        schedule.created_by = user_email
        # Turned back on, it is its author's: approved for them and for
        # these postes, it runs; otherwise it is asked again (C10).
        await approval_crud.close_for_schedule(
            session, schedule.id, actor=user_email, cause="schedule_changed", now=now
        )
        schedule.updated_at = now
        session.add(schedule)
        await session.flush()
        required = await _gate(
            session,
            schedule,
            user_id=user_id,
            user_email=user_email,
            scope=scope,
            keep_approval=True,
        )
    else:
        schedule.state = ScheduleState.DISABLED
        schedule.next_run_at = None
        await approval_crud.close_for_schedule(
            session, schedule.id, actor=user_email, cause="schedule_disabled", now=now
        )
    schedule.updated_at = now
    session.add(schedule)
    audit.record(
        session,
        actor=user_email,
        action="schedule.enable" if payload.enabled else "schedule.disable",
        resource_type="schedule",
        resource_id=str(schedule.id),
        details={
            "name": schedule.name,
            **({"approval": "required"} if required else {}),
        },
    )
    await session.commit()
    await session.refresh(schedule)
    return await _out(session, schedule, await windows.schedule_policy(session))


@router.delete("/{schedule_id}", status_code=204, dependencies=[_WRITE])
async def delete_schedule(
    schedule_id: uuid.UUID, session: SessionDep, scope: CurrentScope, user: CurrentUser
) -> None:
    """Delete a schedule and its run history; the commands it created stay
    in the postes' history."""
    schedule = await _lock(session, schedule_id, scope, user.id)
    audit.record(
        session,
        actor=user.email,
        action="schedule.delete",
        resource_type="schedule",
        resource_id=str(schedule.id),
        details=_audit_details(schedule),
    )
    await session.delete(schedule)
    await session.commit()


@router.get("/{schedule_id}/runs", response_model=RunList, dependencies=[_READ])
async def list_runs(
    schedule_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> RunList:
    await _require(session, schedule_id, scope, user.id)
    stmt = select(ScheduleRun).where(col(ScheduleRun.schedule_id) == schedule_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await session.exec(
            stmt.order_by(col(ScheduleRun.started_at).desc(), col(ScheduleRun.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    policy = await windows.schedule_policy(session)
    return RunList(
        items=[_run_out(r, policy) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
