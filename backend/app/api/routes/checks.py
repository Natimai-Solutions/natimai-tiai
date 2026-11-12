"""Verification requests: "go and look at this poste", assigned or not, closed
with a note that stays.

``check:read`` opens the lists; ``check:write`` creates, reassigns and closes.
Closing also writes the poste's journal (``interventions``), which is why it
is a route of its own rather than a PATCH with a date.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import (
    CurrentScope,
    CurrentUser,
    SessionDep,
    require_any_permission,
    require_permission,
)
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.check import crud
from app.features.check.models import MachineCheck
from app.features.intervention.models import Intervention, InterventionKind
from app.features.machine.models import Machine
from app.features.notification import tasks as task_mail
from app.features.room import crud as room_crud
from app.features.user import crud as user_crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import (
    Scope,
    machine_clause,
    machine_ids_clause,
    machine_visible,
    restrict,
)

_READ = Depends(require_permission(Resource.CHECK, Action.READ))
_WRITE = Depends(require_permission(Resource.CHECK, Action.WRITE))

machine_router = APIRouter(prefix="/machines", tags=["checks"], dependencies=[_READ])
router = APIRouter(prefix="/checks", tags=["checks"], dependencies=[_READ])
assignable_router = APIRouter(
    prefix="/checks",
    tags=["checks"],
    dependencies=[
        Depends(
            require_any_permission(
                (Resource.CHECK, Action.READ),
                (Resource.MAINTENANCE, Action.WRITE),
                (Resource.SETTINGS, Action.WRITE),
            )
        )
    ],
)


class UserRef(BaseModel):
    """An account as a task names it: enough to show, nothing to manage."""

    id: uuid.UUID
    name: str


def _user_ref(user: User | None) -> UserRef | None:
    if user is None:
        return None
    return UserRef(id=user.id, name=user.full_name or user.email)


class MachineRef(BaseModel):
    """The poste a task is about, as the task list shows it."""

    id: uuid.UUID
    hostname: str | None
    location: str | None
    room_name: str | None
    building_name: str | None


class CheckOut(BaseModel):
    id: uuid.UUID
    machine_id: uuid.UUID
    requested_by: str
    assigned_to: UserRef | None
    instructions: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    closed_by: str | None
    closing_note: str | None
    # Filled on the task lists, where the reader has no fiche open.
    machine: MachineRef | None = None


class CheckList(BaseModel):
    items: list[CheckOut]
    total: int
    page: int
    page_size: int


class CheckCreate(BaseModel):
    assigned_to_id: uuid.UUID | None = None
    instructions: str | None = Field(default=None, max_length=5000)


class CheckBulkCreate(CheckCreate):
    machine_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class CheckBulkOut(BaseModel):
    """What a bulk request did: created, and left alone because a request was
    already open on the poste."""

    created: int
    skipped: int


class CheckUpdate(BaseModel):
    """Reassign or reword. ``assigned_to_id`` set to null un-assigns."""

    assigned_to_id: uuid.UUID | None = None
    instructions: str | None = Field(default=None, max_length=5000)


class CheckClose(BaseModel):
    note: str | None = Field(default=None, max_length=5000)
    # Omitted = now. Backdatable like an intervention: the check happened
    # yesterday, the note is typed today.
    closed_at: datetime | None = None


def _already_open() -> AppError:
    return AppError(
        code=ErrorCode.CHECK_ALREADY_OPEN,
        status_code=409,
        message="A verification is already open on this machine",
    )


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    return cleaned or None


async def _require_machine(
    session: SessionDep, machine_id: uuid.UUID, scope: Scope | None
) -> Machine:
    machine = await session.get(Machine, machine_id)
    if machine is None or not await machine_visible(session, machine_id, scope):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    return machine


async def _require_check(
    session: SessionDep, check_id: uuid.UUID, scope: Scope | None
) -> MachineCheck:
    row = await crud.get(session, check_id)
    if row is None or not await machine_visible(session, row.machine_id, scope):
        raise AppError(
            code=ErrorCode.CHECK_NOT_FOUND, status_code=404, message="Check not found"
        )
    return row


async def _can_take(
    session: SessionDep, user_id: uuid.UUID, machine_ids: list[uuid.UUID]
) -> bool:
    """Whether the account can see these checks: check:read, and every poste
    within its scope. Anyone else would be mailed hostnames and instructions
    about postes kept out of their sight (audit S18)."""
    authority = await user_crud.user_authority(session, user_id)
    if authority.is_admin:
        return True
    if not has_permission(
        authority.permissions, Resource.CHECK.value, Action.READ.value
    ):
        return False
    clause = machine_clause(authority.scope)
    if clause is None or not machine_ids:
        return True
    seen = await session.scalar(
        select(func.count())
        .select_from(Machine)
        .where(col(Machine.id).in_(machine_ids))
        .where(clause)
    )
    return (seen or 0) == len(set(machine_ids))


async def _require_assignee(
    session: SessionDep, user_id: uuid.UUID | None, machine_ids: list[uuid.UUID]
) -> User | None:
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(
            code=ErrorCode.USER_NOT_FOUND, status_code=404, message="User not found"
        )
    if not await _can_take(session, user.id, machine_ids):
        raise AppError(
            code=ErrorCode.CHECK_ASSIGNEE_OUT_OF_REACH,
            status_code=422,
            message="This account cannot see these postes",
        )
    return user


async def _out(
    session: SessionDep, rows: list[MachineCheck], *, with_machine: bool
) -> list[CheckOut]:
    user_ids = {r.assigned_to_id for r in rows if r.assigned_to_id}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        found = await session.exec(select(User).where(col(User.id).in_(user_ids)))
        users = {u.id: u for u in found.all()}
    machines: dict[uuid.UUID, MachineRef] = {}
    if with_machine and rows:
        found_m = await session.exec(
            select(Machine).where(col(Machine.id).in_({r.machine_id for r in rows}))
        )
        machine_rows = list(found_m.all())
        placements = await room_crud.placements(
            session, [m.room_id for m in machine_rows]
        )
        for m in machine_rows:
            placement = placements.get(m.room_id) if m.room_id else None
            machines[m.id] = MachineRef(
                id=m.id,
                hostname=m.hostname,
                location=m.location,
                room_name=placement.room.name if placement and placement.room else None,
                building_name=(
                    placement.building.name
                    if placement and placement.building
                    else None
                ),
            )
    return [
        CheckOut(
            id=r.id,
            machine_id=r.machine_id,
            requested_by=r.requested_by,
            assigned_to=_user_ref(
                users.get(r.assigned_to_id) if r.assigned_to_id else None
            ),
            instructions=r.instructions,
            created_at=r.created_at,
            updated_at=r.updated_at,
            closed_at=r.closed_at,
            closed_by=r.closed_by,
            closing_note=r.closing_note,
            machine=machines.get(r.machine_id),
        )
        for r in rows
    ]


async def _one(session: SessionDep, row: MachineCheck) -> CheckOut:
    return (await _out(session, [row], with_machine=True))[0]


# --- Under a machine ----------------------------------------------------------


@machine_router.post(
    "/{machine_id}/check",
    response_model=CheckOut,
    status_code=201,
    dependencies=[_WRITE],
)
async def create_check(
    machine_id: uuid.UUID,
    payload: CheckCreate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> CheckOut:
    """Ask for a verification of this poste. One open request at a time."""
    machine = await _require_machine(session, machine_id, scope)
    if await crud.open_for_machine(session, machine.id) is not None:
        raise AppError(
            code=ErrorCode.CHECK_ALREADY_OPEN,
            status_code=409,
            message="A verification is already open on this machine",
        )
    assignee = await _require_assignee(session, payload.assigned_to_id, [machine.id])
    row = MachineCheck(
        machine_id=machine.id,
        requested_by=current.email,
        assigned_to_id=payload.assigned_to_id,
        instructions=_clean(payload.instructions),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        # Another request was opened on this poste between the check above
        # and this insert: the partial unique index said no (audit B21).
        await session.rollback()
        raise _already_open() from None
    # In the same transaction as the request: no mail for a request that
    # was rolled back, and none to oneself.
    if assignee is not None and assignee.id != current.id:
        task_mail.send_checks_assigned(
            session,
            assignee=assignee,
            machines=[machine],
            requested_by=current.email,
            instructions=row.instructions,
        )
    await session.commit()
    await session.refresh(row)
    return await _one(session, row)


@machine_router.get("/{machine_id}/checks", response_model=CheckList)
async def list_machine_checks(
    machine_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> CheckList:
    """A poste's requests, open first, then closed newest first."""
    await _require_machine(session, machine_id, scope)
    rows, total = await crud.list_checks(
        session,
        open_only=False,
        assigned_to_id=None,
        unassigned=False,
        machine_id=machine_id,
        page=page,
        page_size=page_size,
    )
    return CheckList(
        items=await _out(session, rows, with_machine=False),
        total=total,
        page=page,
        page_size=page_size,
    )


# --- The lists and the tasks --------------------------------------------------


@assignable_router.get("/assignable-users", response_model=list[UserRef])
async def assignable_users(
    session: SessionDep, machine_id: uuid.UUID | None = None
) -> list[UserRef]:
    """Active accounts, id and name only: who a task can be given to, without
    opening the accounts page to everyone who may assign. Also who may own a
    maintenance — so open to whoever sets one, not only to check:read (audit
    B35). Registered before ``router``, whose ``/{check_id}`` would take it."""
    rows = await session.exec(
        select(User).where(col(User.is_active).is_(True)).order_by(col(User.email))
    )
    users = list(rows.all())
    if machine_id is not None:
        # For a check on that poste: only who can see it (audit S18).
        users = [u for u in users if await _can_take(session, u.id, [machine_id])]
    return [ref for u in users if (ref := _user_ref(u)) is not None]


@router.post(
    "/bulk", response_model=CheckBulkOut, status_code=201, dependencies=[_WRITE]
)
async def create_checks_bulk(
    payload: CheckBulkCreate,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> CheckBulkOut:
    """One request per poste of a selection, skipping those already asked."""
    assignee = await _require_assignee(
        session, payload.assigned_to_id, list(set(payload.machine_ids))
    )
    found_machines = await session.exec(
        restrict(
            select(Machine).where(col(Machine.id).in_(payload.machine_ids)),
            machine_clause(scope),
        )
    )
    machines = {m.id: m for m in found_machines.all()}
    machine_ids = list(machines)
    if len(machine_ids) != len(set(payload.machine_ids)):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    already = await session.exec(
        select(MachineCheck.machine_id).where(
            col(MachineCheck.machine_id).in_(machine_ids),
            col(MachineCheck.closed_at).is_(None),
        )
    )
    open_ids = set(already.all())
    new_rows = [
        MachineCheck(
            machine_id=machine_id,
            requested_by=current.email,
            assigned_to_id=payload.assigned_to_id,
            instructions=_clean(payload.instructions),
        ).model_dump()
        for machine_id in machine_ids
        if machine_id not in open_ids
    ]
    inserted: set[uuid.UUID] = set()
    if new_rows:
        # A request opened meanwhile on one of them is skipped, not a failure
        # of the whole batch (audit B21): the partial unique index decides.
        result = await session.exec(
            pg_insert(MachineCheck)
            .values(new_rows)
            .on_conflict_do_nothing(
                index_elements=[col(MachineCheck.machine_id)],
                index_where=col(MachineCheck.closed_at).is_(None),
            )
            .returning(col(MachineCheck.machine_id))
        )
        inserted = set(result.scalars().all())
    created_machines = [machines[m] for m in machine_ids if m in inserted]
    created = len(created_machines)
    # One mail for the whole request, not one per poste.
    if assignee is not None and assignee.id != current.id and created_machines:
        task_mail.send_checks_assigned(
            session,
            assignee=assignee,
            machines=created_machines,
            requested_by=current.email,
            instructions=_clean(payload.instructions),
        )
    await session.commit()
    return CheckBulkOut(created=created, skipped=len(machine_ids) - created)


@router.get("", response_model=CheckList)
async def list_checks(
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
    open: bool = True,
    assigned_to: str | None = Query(
        None, description="An account id, or 'me'; 'none' for the unassigned"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> CheckList:
    """The task list: open requests, mine, somebody's, or nobody's yet."""
    assigned_to_id: uuid.UUID | None = None
    unassigned = False
    if assigned_to == "me":
        assigned_to_id = current.id
    elif assigned_to == "none":
        unassigned = True
    elif assigned_to:
        try:
            assigned_to_id = uuid.UUID(assigned_to)
        except ValueError:
            raise AppError(
                code=ErrorCode.REQUEST_VALIDATION_ERROR,
                status_code=422,
                message="assigned_to must be an account id, 'me' or 'none'",
            ) from None
    rows, total = await crud.list_checks(
        session,
        open_only=open,
        assigned_to_id=assigned_to_id,
        unassigned=unassigned,
        machine_id=None,
        where=machine_ids_clause(scope, col(MachineCheck.machine_id)),
        page=page,
        page_size=page_size,
    )
    return CheckList(
        items=await _out(session, rows, with_machine=True),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{check_id}", response_model=CheckOut)
async def get_check(
    check_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> CheckOut:
    return await _one(session, await _require_check(session, check_id, scope))


@router.patch("/{check_id}", response_model=CheckOut, dependencies=[_WRITE])
async def update_check(
    check_id: uuid.UUID,
    payload: CheckUpdate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> CheckOut:
    """Reassign or reword an open request."""
    row = await _require_check(session, check_id, scope)
    if row.closed_at is not None:
        raise AppError(
            code=ErrorCode.CHECK_CLOSED, status_code=409, message="This check is closed"
        )
    fields = payload.model_dump(exclude_unset=True)
    new_assignee: User | None = None
    if "assigned_to_id" in fields:
        # Unchanged is not a choice: a request whose assignee was deactivated
        # since can still be reworded (audit B08).
        if fields["assigned_to_id"] != row.assigned_to_id:
            new_assignee = await _require_assignee(
                session, fields["assigned_to_id"], [row.machine_id]
            )
        row.assigned_to_id = fields["assigned_to_id"]
    if "instructions" in fields:
        row.instructions = _clean(fields["instructions"])
    row.updated_at = utcnow()
    session.add(row)
    if new_assignee is not None and new_assignee.id != current.id:
        machine = await _require_machine(session, row.machine_id, scope)
        task_mail.send_checks_assigned(
            session,
            assignee=new_assignee,
            machines=[machine],
            requested_by=current.email,
            instructions=row.instructions,
        )
    audit.record(
        session,
        actor=current.email,
        action="check.update",
        resource_type="check",
        resource_id=str(row.id),
        details={
            "machine_id": str(row.machine_id),
            "fields": sorted(fields),
            **(
                {
                    "assigned_to_id": str(row.assigned_to_id)
                    if row.assigned_to_id
                    else None
                }
                if "assigned_to_id" in fields
                else {}
            ),
        },
    )
    await session.commit()
    await session.refresh(row)
    return await _one(session, row)


@router.post("/{check_id}/close", response_model=CheckOut, dependencies=[_WRITE])
async def close_check(
    check_id: uuid.UUID,
    payload: CheckClose,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> CheckOut:
    """Close a request with what was found. Writes the poste's journal."""
    row = await _require_check(session, check_id, scope)
    closed_at = payload.closed_at or utcnow()
    note = _clean(payload.note)
    # Closed in one statement, on the condition that it still is open: of two
    # closings at the same time, one wins and the other is told (audit B21) —
    # no second line in the journal.
    won = (
        await session.exec(
            update(MachineCheck)
            .where(
                col(MachineCheck.id) == row.id, col(MachineCheck.closed_at).is_(None)
            )
            .values(
                closed_at=closed_at,
                closed_by=current.email,
                closing_note=note,
                updated_at=utcnow(),
            )
            .returning(col(MachineCheck.id))
        )
    ).first()
    if won is None:
        raise AppError(
            code=ErrorCode.CHECK_CLOSED, status_code=409, message="This check is closed"
        )
    await session.refresh(row)
    session.add(
        Intervention(
            machine_id=row.machine_id,
            kind=InterventionKind.VERIFICATION.value,
            title="Vérification",
            note=note,
            performed_by=current.email,
            performed_at=closed_at,
            check_id=row.id,
        )
    )
    await session.commit()
    await session.refresh(row)
    return await _one(session, row)
