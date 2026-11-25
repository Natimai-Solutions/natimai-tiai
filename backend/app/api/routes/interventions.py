"""The journal of a poste: interventions, by hand.

Reading takes ``intervention:read``; writing — adding, editing, deleting —
``intervention:write``. Editing is not restricted to the author: a colleague
correcting a note is the everyday case, and the audit log says who did.
Deletion is audited for the same reason an edit is not refused: the journal
is a record, and a record that vanishes must leave a trace.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.validation import refusal
from app.features.attachment import crud as attachment_crud
from app.features.attachment.schemas import AttachmentOut
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.intervention import crud
from app.features.intervention.models import Intervention, InterventionKind
from app.features.machine.models import Machine
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope, machine_visible

_READ = Depends(require_permission(Resource.INTERVENTION, Action.READ))
_WRITE = Depends(require_permission(Resource.INTERVENTION, Action.WRITE))

# Two routers: the journal is read and added to *under* a machine, edited
# and deleted by its own id.
machine_router = APIRouter(
    prefix="/machines", tags=["interventions"], dependencies=[_READ]
)
router = APIRouter(
    prefix="/interventions", tags=["interventions"], dependencies=[_READ]
)


class InterventionOut(BaseModel):
    id: uuid.UUID
    machine_id: uuid.UUID
    kind: str
    title: str | None
    # Set when the server wrote the title itself (« Maintenance non faite —
    # A101 »): the console words it from the code and its parameters, in the
    # reader's language, ``title`` keeping the French. Null on a typed title.
    title_code: str | None = None
    title_params: dict[str, Any] | None = None
    note: str | None
    performed_by: str
    performed_at: datetime
    check_id: uuid.UUID | None
    maintenance_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    # Its attachments (C11), oldest first: filled by the journal's page, empty
    # in the answers to a creation or an edit (the console reads the page).
    attachments: list[AttachmentOut] = []

    model_config = {"from_attributes": True}


class InterventionList(BaseModel):
    items: list[InterventionOut]
    total: int
    page: int
    page_size: int


class InterventionCreate(BaseModel):
    kind: InterventionKind
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=5000)
    # Omitted = now. Any past instant is accepted: a journal can be started
    # from before the console existed. Not a future one (audit B06).
    performed_at: crud.PastDatetime | None = None


class InterventionUpdate(BaseModel):
    """Partial update — only the supplied fields are changed."""

    kind: InterventionKind | None = None
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=5000)
    performed_at: crud.PastDatetime | None = None


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


async def _require_intervention(
    session: SessionDep, intervention_id: uuid.UUID, scope: Scope | None
) -> Intervention:
    row = await crud.get(session, intervention_id)
    if row is None or not await machine_visible(session, row.machine_id, scope):
        raise AppError(
            code=ErrorCode.INTERVENTION_NOT_FOUND,
            status_code=404,
            message="Intervention not found",
        )
    return row


@machine_router.get("/{machine_id}/interventions", response_model=InterventionList)
async def list_interventions(
    machine_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> InterventionList:
    """A poste's journal, newest first."""
    await _require_machine(session, machine_id, scope)
    rows, total = await crud.list_for_machine(
        session, machine_id, page=page, page_size=page_size
    )
    # The whole page's attachments in one query.
    attached = await attachment_crud.of_interventions(session, [r.id for r in rows])
    items = []
    for r in rows:
        item = InterventionOut.model_validate(r)
        item.attachments = [AttachmentOut.model_validate(a) for a in attached[r.id]]
        items.append(item)
    return InterventionList(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@machine_router.post(
    "/{machine_id}/interventions",
    response_model=InterventionOut,
    status_code=201,
    dependencies=[_WRITE],
)
async def create_intervention(
    machine_id: uuid.UUID,
    payload: InterventionCreate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> InterventionOut:
    machine = await _require_machine(session, machine_id, scope)
    now = utcnow()
    row = Intervention(
        machine_id=machine.id,
        kind=payload.kind.value,
        title=_clean(payload.title),
        note=_clean(payload.note),
        performed_by=current.email,
        performed_at=payload.performed_at or now,
        # The same instant for both: "edited" is read off their difference.
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    # A maintenance entered by hand counts towards the cycle (audit B17).
    await crud.recompute_last_maintenance(session, [machine.id])
    await session.commit()
    await session.refresh(row)
    return InterventionOut.model_validate(row)


@router.patch(
    "/{intervention_id}", response_model=InterventionOut, dependencies=[_WRITE]
)
async def update_intervention(
    intervention_id: uuid.UUID,
    payload: InterventionUpdate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> InterventionOut:
    row = await _require_intervention(session, intervention_id, scope)
    fields = payload.model_dump(exclude_unset=True)
    becomes_maintenance = (
        payload.kind == InterventionKind.MAINTENANCE
        and row.kind != InterventionKind.MAINTENANCE.value
    )
    if becomes_maintenance and fields.get("performed_at") is None:
        # The date is not sent, so the request model did not check it: a
        # line dated in the future (an old check closing, a legacy entry)
        # turned into a maintenance would push the cycle out (audit B06).
        # The coded refusal the request model would give (« Value error, »
        # once, its code for the console), not the validator's own text: a
        # PydanticCustomError already reads « Value error, … ».
        try:
            crud.not_in_the_future(row.performed_at)
        except ValueError:
            raise RequestValidationError(
                [
                    refusal(
                        ["body", "performed_at"],
                        "date_in_future",
                        "la date ne peut pas être dans le futur",
                    )
                ]
            ) from None
    if "kind" in fields:
        row.kind = payload.kind.value if payload.kind else row.kind
    if "title" in fields and _clean(fields["title"]) != row.title:
        row.title = _clean(fields["title"])
        # Typed by someone now: no longer the server's words. Sent back as
        # it was (an older console, a script PATCHing the whole line), it
        # still is: the line keeps reading in the reader's language.
        row.title_code = None
        row.title_params = None
    if "note" in fields:
        row.note = _clean(fields["note"])
    if "performed_at" in fields and fields["performed_at"] is not None:
        row.performed_at = fields["performed_at"]
    row.updated_at = utcnow()
    session.add(row)
    # Edits by someone other than the author are the ones worth a trace: the
    # journal shows the author, not the editor.
    if current.email != row.performed_by:
        audit.record(
            session,
            actor=current.email,
            action="intervention.update",
            resource_type="intervention",
            resource_id=str(row.id),
            details={
                "machine_id": str(row.machine_id),
                "author": row.performed_by,
                "fields": sorted(fields),
            },
        )
    # Redated, or turned into (or out of) a maintenance: the cycle follows.
    await crud.recompute_last_maintenance(session, [row.machine_id])
    await session.commit()
    await session.refresh(row)
    return InterventionOut.model_validate(row)


@router.delete("/{intervention_id}", status_code=204, dependencies=[_WRITE])
async def delete_intervention(
    intervention_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> None:
    row = await _require_intervention(session, intervention_id, scope)
    # Locked before its attachments are read: an upload in progress holds
    # the line ``FOR SHARE`` until it commits, and is counted then (C11).
    await session.exec(
        select(Intervention)
        .where(col(Intervention.id) == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    shas = await attachment_crud.shas_of(session, [row.id])
    audit.record(
        session,
        actor=current.email,
        action="intervention.delete",
        resource_type="intervention",
        resource_id=str(row.id),
        details={
            "machine_id": str(row.machine_id),
            "kind": row.kind,
            "title": row.title,
            "author": row.performed_by,
            "performed_at": row.performed_at.isoformat(),
            "attachments": len(shas),
        },
    )
    machine_id = row.machine_id
    await session.delete(row)
    # A deleted visit no longer counts: the due date goes back (audit B06).
    await crud.recompute_last_maintenance(session, [machine_id])
    await session.commit()
    # Its attachments went with it (cascade): their files too, unless
    # another line names them.
    for sha in set(shas):
        await attachment_crud.discard_if_orphan(session, sha)
