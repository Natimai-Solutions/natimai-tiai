"""Console command dispatch and tracking.

Creating commands is an admin capability (command:execute); tracking them needs
only command:read. A command targets either an explicit list of machines or a
broadcast filter (all / by domain / by status) — each resolved to one row per
machine (plan §4).
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.core.config import settings
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command.models import Command, CommandStatus, CommandType
from app.features.machine.models import Machine
from app.features.machine.status import MachineStatus, status_clause
from app.features.user.permissions import Action, Resource

router = APIRouter(prefix="/commands", tags=["commands"])


class CreateCommands(BaseModel):
    """Queue a command for an explicit machine list or a broadcast filter.

    Exactly one target must be given: ``machine_ids``, ``target_all``,
    ``target_domain``, or ``target_status``.
    """

    type: CommandType
    ttl_minutes: int = Field(default=60, ge=1, le=60 * 24 * 30)
    machine_ids: list[uuid.UUID] | None = None
    target_all: bool = False
    target_domain: str | None = None
    target_status: MachineStatus | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "CreateCommands":
        provided = [
            bool(self.machine_ids),
            self.target_all,
            self.target_domain is not None,
            self.target_status is not None,
        ]
        if sum(provided) != 1:
            raise ValueError(
                "provide exactly one target: machine_ids, target_all, "
                "target_domain, or target_status"
            )
        return self


class CreateCommandsResponse(BaseModel):
    """Ids of the created command rows, and what was left alone.

    ``skipped`` counts the targets that already carried an unfinished command of
    the same type. It is not an error — re-pressing a button on a poste that has
    not answered yet is the normal way this happens — but the console has to be
    able to say so rather than claim it sent something.
    """

    created: list[uuid.UUID]
    count: int
    skipped: int = 0


class CommandOut(BaseModel):
    """A command row for the console tracking view."""

    id: uuid.UUID
    machine_id: uuid.UUID
    type: str
    status: str
    created_by: str | None
    created_at: datetime
    expires_at: datetime
    delivered_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    result_output: str | None
    error: str | None

    model_config = {"from_attributes": True}


class CommandList(BaseModel):
    """Paginated command list."""

    items: list[CommandOut]
    total: int
    page: int
    page_size: int


async def _resolve_targets(
    session: SessionDep, payload: CreateCommands
) -> list[uuid.UUID]:
    """Resolve the payload's target into existing machine ids."""
    stmt = select(Machine.id)
    if payload.machine_ids:
        # Restrict to ids that actually exist (avoids FK violations on insert).
        stmt = stmt.where(col(Machine.id).in_(payload.machine_ids))
    elif payload.target_domain is not None:
        stmt = stmt.where(col(Machine.domain) == payload.target_domain)
    elif payload.target_status is not None:
        stmt = stmt.where(
            status_clause(payload.target_status, utcnow(), settings.INACTIVE_AFTER_DAYS)
        )
    # target_all → no predicate.
    rows = await session.exec(stmt)
    return list(rows.all())


@router.post(
    "",
    response_model=CreateCommandsResponse,
    dependencies=[Depends(require_permission(Resource.COMMAND, Action.EXECUTE))],
)
async def create_commands(
    payload: CreateCommands, session: SessionDep, user: CurrentUser
) -> CreateCommandsResponse:
    """Queue one command per resolved target machine (admin only).

    A machine that already has an unfinished command of the same type is
    skipped, not queued twice: see ``command_crud.create_for_machines``.
    """
    machine_ids = await _resolve_targets(session, payload)
    # Same sweep the tracking endpoint runs: a command left pending past its TTL
    # must not block the one an administrator is queueing now, on a poste that
    # was simply off the whole time.
    await command_crud.mark_expired(session)
    expires_at = utcnow() + timedelta(minutes=payload.ttl_minutes)
    created, skipped = await command_crud.create_for_machines(
        session,
        machine_ids=machine_ids,
        command_type=payload.type,
        created_by=user.email,
        expires_at=expires_at,
    )
    await session.commit()
    return CreateCommandsResponse(
        created=created, count=len(created), skipped=len(skipped)
    )


@router.get(
    "",
    response_model=CommandList,
    dependencies=[Depends(require_permission(Resource.COMMAND, Action.READ))],
)
async def list_commands(
    session: SessionDep,
    status: CommandStatus | None = None,
    machine_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> CommandList:
    """List/track commands, optionally filtered by status and machine."""
    # Lazy sweep so stale pending commands read as EXPIRED (cron takes over in M5).
    await command_crud.mark_expired(session)
    await session.commit()

    stmt = select(Command)
    if status is not None:
        stmt = stmt.where(col(Command.status) == status)
    if machine_id is not None:
        stmt = stmt.where(col(Command.machine_id) == machine_id)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # ``id`` behind the timestamp: a broadcast queues one row per poste in the
    # same instant, and ties reordered between two OFFSETs would duplicate a
    # command on one page and hide another.
    rows = await session.exec(
        stmt.order_by(col(Command.created_at).desc(), col(Command.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [CommandOut.model_validate(c) for c in rows.all()]
    return CommandList(items=items, total=total or 0, page=page, page_size=page_size)
