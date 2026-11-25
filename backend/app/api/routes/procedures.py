"""Procedure notes per hardware model (C11).

One plain-text note per ``machines.hw_model``, shown on the fiche of every
poste of that model. Reading takes ``procedure:read`` and follows the scope:
a confined account sees the notes of the models present on at least one
poste it sees — a model's name absent from its scope would tell it another
building's parc. Writing takes ``procedure:write`` and an account that sees
every poste: a note is shared between sites, and a confined reader of the
audit log would never see the entry (``routes/audit.py:_scope_clause``).

Concurrent writes do not lose one another: an edit or a deletion carries
the ``updated_at`` it was made from, and is a conditional ``UPDATE`` /
``DELETE``; a creation racing another for the same model meets the unique
index and answers 409, never 500. Every write is audited, with the text it
replaced (``previous``): the history of a note is the audit log.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, exists, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.api.routes.interventions import _require_machine
from app.core.errors import AppError, ErrorCode, violated_constraint
from app.features.asset import crud as asset_crud
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.procedure.models import BODY_MAX, HW_MODEL_MAX, Procedure
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope, machine_clause, restrict

_READ = Depends(require_permission(Resource.PROCEDURE, Action.READ))
_WRITE = Depends(require_permission(Resource.PROCEDURE, Action.WRITE))

router = APIRouter(prefix="/procedures", tags=["procedures"], dependencies=[_READ])
machine_router = APIRouter(
    prefix="/machines", tags=["procedures"], dependencies=[_READ]
)

# The number of models a parc has, and then some.
LIST_MAX = 500

_UNIQUE = "uq_procedures_hw_model"

HwModel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=HW_MODEL_MAX)
]
Body = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BODY_MAX)
]


class ProcedureOut(BaseModel):
    id: uuid.UUID
    hw_model: str
    body: str
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProcedureListItem(ProcedureOut):
    # Postes of the model in the caller's scope, retired ones excluded.
    machine_count: int


class MachineProcedure(BaseModel):
    # Null when the inventory has not reported one.
    hw_model: str | None
    procedure: ProcedureOut | None


class ProcedureCreate(BaseModel):
    hw_model: HwModel
    body: Body


class ProcedureUpdate(BaseModel):
    # Empty is refused: deleting is a gesture of its own.
    body: Body
    expected_updated_at: datetime


def _whole_parc(scope: Scope | None) -> None:
    if scope is not None:
        raise AppError(
            code=ErrorCode.PROCEDURE_SCOPE_LIMITED,
            status_code=403,
            message="Procedure notes are written by accounts that see every poste",
        )


def _not_found() -> AppError:
    return AppError(
        code=ErrorCode.PROCEDURE_NOT_FOUND,
        status_code=404,
        message="Procedure not found",
    )


def _changed() -> AppError:
    return AppError(
        code=ErrorCode.PROCEDURE_CHANGED,
        status_code=409,
        message="This procedure was changed by someone else: read it again",
    )


def _exists() -> AppError:
    return AppError(
        code=ErrorCode.PROCEDURE_EXISTS,
        status_code=409,
        message="This model already has its procedure",
    )


def _out(p: Procedure) -> ProcedureOut:
    return ProcedureOut.model_validate(p)


async def _locked(session: SessionDep, procedure_id: uuid.UUID) -> Procedure | None:
    """The note, its row locked until the transaction ends, read again from
    the database: what an edit replaces is what is audited."""
    return (
        await session.exec(
            select(Procedure)
            .where(col(Procedure.id) == procedure_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


@machine_router.get("/{machine_id}/procedure", response_model=MachineProcedure)
async def machine_procedure(
    machine_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> MachineProcedure:
    """The note of the poste's model, if it has one."""
    machine = await _require_machine(session, machine_id, scope)
    model = (machine.hw_model or "").strip() or None
    if model is None:
        return MachineProcedure(hw_model=None, procedure=None)
    found = (
        await session.exec(select(Procedure).where(col(Procedure.hw_model) == model))
    ).first()
    return MachineProcedure(
        hw_model=model, procedure=_out(found) if found is not None else None
    )


@router.get("", response_model=list[ProcedureListItem])
async def list_procedures(
    session: SessionDep, scope: CurrentScope
) -> list[ProcedureListItem]:
    """Every note the caller may see, by model, with its postes in service
    in the caller's scope."""
    stmt = select(Procedure)
    clause = machine_clause(scope)
    if clause is not None:
        # A model present on a poste in reach — a retired one counts: it may
        # come back into service.
        stmt = stmt.where(
            exists().where(col(Machine.hw_model) == col(Procedure.hw_model), clause)
        )
    rows = list(
        (
            await session.exec(stmt.order_by(col(Procedure.hw_model)).limit(LIST_MAX))
        ).all()
    )
    counts: dict[str, int] = {}
    if rows:
        count_stmt = (
            select(col(Machine.hw_model), func.count())
            .where(col(Machine.hw_model).in_([p.hw_model for p in rows]))
            .where(asset_crud.in_parc_clause())
            .group_by(col(Machine.hw_model))
        )
        result = await session.exec(restrict(count_stmt, clause))
        counts = {model: n for model, n in result.all() if model is not None}
    return [
        ProcedureListItem(
            **_out(p).model_dump(), machine_count=counts.get(p.hw_model, 0)
        )
        for p in rows
    ]


@router.post("", response_model=ProcedureOut, status_code=201, dependencies=[_WRITE])
async def create_procedure(
    payload: ProcedureCreate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> ProcedureOut:
    """In this order: an account that sees every poste, a model the parc
    knows (retired postes included), and only then a model without its note
    — the 409 never answers before the model is checked."""
    _whole_parc(scope)
    model = payload.hw_model
    known = (
        await session.exec(
            select(Machine.id).where(col(Machine.hw_model) == model).limit(1)
        )
    ).first()
    if known is None:
        raise AppError(
            code=ErrorCode.PROCEDURE_MODEL_UNKNOWN,
            status_code=422,
            message="No poste has this model",
            details={"hw_model": model},
        )
    taken = (
        await session.exec(select(Procedure.id).where(col(Procedure.hw_model) == model))
    ).first()
    if taken is not None:
        raise _exists()
    now = utcnow()
    actor = current.email
    row = Procedure(
        hw_model=model,
        body=payload.body,
        created_by=actor,
        created_at=now,
        updated_by=actor,
        updated_at=now,
    )
    session.add(row)
    out = _out(row)
    audit.record(
        session,
        actor=actor,
        action="procedure.create",
        resource_type="procedure",
        resource_id=str(out.id),
        details={"hw_model": model, "length": len(out.body)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == _UNIQUE:
            raise _exists() from None
        raise
    return out


@router.patch("/{procedure_id}", response_model=ProcedureOut, dependencies=[_WRITE])
async def update_procedure(
    procedure_id: uuid.UUID,
    payload: ProcedureUpdate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> ProcedureOut:
    _whole_parc(scope)
    current_row = await _locked(session, procedure_id)
    if current_row is None:
        raise _not_found()
    before = _out(current_row)
    now = utcnow()
    actor = current.email
    result = await session.exec(
        update(Procedure)
        .where(col(Procedure.id) == procedure_id)
        .where(col(Procedure.updated_at) == payload.expected_updated_at)
        .values(body=payload.body, updated_by=actor, updated_at=now)
    )
    if not result.rowcount:
        raise _changed()
    audit.record(
        session,
        actor=actor,
        action="procedure.update",
        resource_type="procedure",
        resource_id=str(procedure_id),
        details={
            "hw_model": before.hw_model,
            "previous": before.body,
            "length": len(payload.body),
        },
    )
    await session.commit()
    return before.model_copy(
        update={"body": payload.body, "updated_by": actor, "updated_at": now}
    )


@router.delete("/{procedure_id}", status_code=204, dependencies=[_WRITE])
async def delete_procedure(
    procedure_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
    expected_updated_at: datetime = Query(...),
) -> None:
    _whole_parc(scope)
    current_row = await _locked(session, procedure_id)
    if current_row is None:
        raise _not_found()
    before = _out(current_row)
    result = await session.exec(
        delete(Procedure)
        .where(col(Procedure.id) == procedure_id)
        .where(col(Procedure.updated_at) == expected_updated_at)
    )
    if not result.rowcount:
        raise _changed()
    audit.record(
        session,
        actor=current.email,
        action="procedure.delete",
        resource_type="procedure",
        resource_id=str(procedure_id),
        details={"hw_model": before.hw_model, "previous": before.body},
    )
    await session.commit()
