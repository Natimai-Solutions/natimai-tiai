"""Console command dispatch and tracking.

Creating commands is an admin capability (command:execute); tracking them needs
only command:read. A command targets either an explicit list of machines or a
broadcast filter (all / by domain / by status) — each resolved to one row per
machine (plan §4).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    CurrentPermissions,
    CurrentScope,
    CurrentUser,
    SessionDep,
    require_permission,
)
from app.core.errors import AppError, ErrorCode
from app.features.approval import crud as approval_crud
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command import dispatch
from app.features.command import target as target_crud
from app.features.command.models import (
    PACKAGE_COMMAND_TYPES,
    RISKY_COMMAND_TYPES,
    Command,
    CommandStatus,
    CommandType,
)
from app.features.command.target import Target
from app.features.machine.models import Machine
from app.features.machine.status import MachineStatus
from app.features.package import crud as package_crud
from app.features.package.models import Package
from app.features.schedule import windows
from app.features.setting import crud as setting_crud
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import machine_ids_clause, restrict

router = APIRouter(prefix="/commands", tags=["commands"])


class CreateCommands(BaseModel):
    """Queue a command for an explicit machine list or a broadcast filter.

    Exactly one target must be given: ``machine_ids``, ``target_all``,
    ``target_domain``, ``target_location``, ``target_status``,
    ``target_room_id`` or ``target_building_id``.
    """

    type: CommandType
    # Omitted, the deployment decides: COMMAND_DEFAULT_TTL_MINUTES. The default
    # is not spelled out here because a Pydantic default is frozen at import,
    # and publishing it in the OpenAPI schema would give it as *the* applied
    # value on a server that applies another one.
    ttl_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)
    machine_ids: list[uuid.UUID] | None = None
    target_all: bool = False
    target_domain: str | None = None
    # A site, as the agents report it: "every poste of Taravao". Exact, like
    # the domain.
    target_location: str | None = None
    target_status: MachineStatus | None = None
    # Every poste of a room, or of a building's rooms.
    target_room_id: uuid.UUID | None = None
    target_building_id: uuid.UUID | None = None
    # A command at risk sent to several postes inside a forbidden window
    # (Paramètres, « Plages interdites ») is refused unless this says the
    # person saw the warning and goes on (``command.forbidden_window``).
    confirm_forbidden_window: bool = False
    # The package to install or remove: required by the two deployment types,
    # refused on every other.
    package_id: uuid.UUID | None = None

    @field_validator("type")
    @classmethod
    def _not_a_wake(cls, value: CommandType) -> CommandType:
        """A wake has its own endpoint, and could not go through this one.

        Queued here it would sit on the target as a command its own agent
        never picks up — the target is off, and the pickup skips the type —
        with nothing to say who is meant to emit it. ``POST /machines/wake``
        decides that, and records it.
        """
        if value == CommandType.WAKE_ON_LAN:
            raise ValueError("wake_on_lan is not queued here: use POST /machines/wake")
        if value == CommandType.DIRECTORY_READ:
            raise ValueError("directory_read is queued by the server alone")
        return value

    def target(self) -> Target:
        if self.machine_ids:
            return Target("machines", machine_ids=tuple(self.machine_ids))
        if self.target_all:
            return Target("all")
        if self.target_domain is not None:
            return Target("domain", value=self.target_domain)
        if self.target_location is not None:
            return Target("location", value=self.target_location)
        if self.target_status is not None:
            return Target("status", value=self.target_status.value)
        if self.target_room_id is not None:
            return Target("room", value=str(self.target_room_id))
        return Target("building", value=str(self.target_building_id))

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "CreateCommands":
        provided = [
            bool(self.machine_ids),
            self.target_all,
            self.target_domain is not None,
            self.target_location is not None,
            self.target_status is not None,
            self.target_room_id is not None,
            self.target_building_id is not None,
        ]
        if sum(provided) != 1:
            raise ValueError(
                "provide exactly one target: machine_ids, target_all, "
                "target_domain, target_location, target_status, "
                "target_room_id or target_building_id"
            )
        if self.package_id is not None and self.type not in PACKAGE_COMMAND_TYPES:
            raise ValueError("package_id only goes with package_install/uninstall")
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
    # Targets left alone because their token is revoked: nothing reaches such
    # a poste until its re-enrollment is allowed, and a command queued for
    # it would only sit there until it expired. Not counted in ``skipped``.
    revoked: int = 0
    # A command on one poste only: why nothing was created — the status of
    # the unfinished command already there. None when one was created, and
    # on a request aimed at several postes. ("gone" is answered as a 404.)
    reason: Literal["pending", "delivered", "running", "gone"] | None = None
    # Answered with 202 (C10): nothing was sent — a command at risk above
    # the approval threshold waits for a second account. ``count`` is then
    # 0 and does not mean « nothing to do »: the request is ``approval_id``,
    # it expires at ``approval_expires_at``, and ``pending_approval`` postes
    # wait for it.
    approval_id: uuid.UUID | None = None
    approval_expires_at: datetime | None = None
    pending_approval: int | None = None


class CommandOut(BaseModel):
    """A command row for the console tracking view."""

    id: uuid.UUID
    machine_id: uuid.UUID
    type: str
    status: str
    # The poste that emitted a relayed wake on behalf of ``machine_id``; null
    # on every other row (``Command.relay_machine_id``).
    relay_machine_id: uuid.UUID | None = None
    # The package a deployment command installs or removes.
    package_id: uuid.UUID | None = None
    # The poste's name, so that a list across postes (a package's
    # deployments) reads without a lookup per row.
    machine_hostname: str | None = None
    # The package's name and version (« 7-Zip 23.01 »), so that a poste's
    # list says what a deployment installs; null on every other row, and on a
    # deployment whose package is gone.
    package_name: str | None = None
    created_by: str | None
    created_at: datetime
    expires_at: datetime
    delivered_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    result_output: str | None
    error: str | None
    # What the console words the verdict from (``command.texts``): the
    # ``error`` of a failed command, the ``result_output`` of a succeeded one.
    # Null on an older row, and wherever the text is a tool's own output.
    result_code: str | None = None
    result_params: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class CommandList(BaseModel):
    """Paginated command list."""

    items: list[CommandOut]
    total: int
    page: int
    page_size: int


@router.post(
    "",
    response_model=CreateCommandsResponse,
    dependencies=[Depends(require_permission(Resource.COMMAND, Action.EXECUTE))],
    responses={
        202: {
            "model": CreateCommandsResponse,
            "description": "En attente d'approbation",
        }
    },
)
async def create_commands(
    payload: CreateCommands,
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    scope: CurrentScope,
    response: Response,
) -> CreateCommandsResponse:
    """Queue one command per resolved target machine.

    ``command:execute`` opens this route; the types in ``RISKY_COMMAND_TYPES``
    ask for ``risky_command:execute`` on top, checked here because the type is
    in the body. A machine that already has an unfinished command of the same
    type is skipped, not queued twice: see ``command_crud.create_for_machines``.

    A request aimed at a set of postes — a filter, or a list of several — is
    also written to the audit log as ``command.bulk``, in the same
    transaction: the rows say which postes received the command, the entry
    says what was asked and how much of it was skipped. A command on a single
    poste is traced by its row's ``created_by`` alone, as it always was.

    With two-person approval on (C10), a command at risk on more postes than
    the threshold is not queued: a request waits for a second account, and
    the answer is 202 with its ``approval_id``.
    """
    if payload.type in RISKY_COMMAND_TYPES and not has_permission(
        permissions, Resource.RISKY_COMMAND, Action.EXECUTE
    ):
        raise AppError(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            status_code=403,
            message=f"Missing permission: {Resource.RISKY_COMMAND}:{Action.EXECUTE}",
            details={
                "resource": Resource.RISKY_COMMAND.value,
                "action": Action.EXECUTE.value,
            },
        )
    target = payload.target()
    if not await target_crud.place_visible(session, target, scope):
        raise AppError(
            code=ErrorCode.ROOM_NOT_FOUND
            if target.kind == "room"
            else ErrorCode.BUILDING_NOT_FOUND,
            status_code=404,
            message="Room or building not found",
        )
    package = await dispatch.deployable_package(
        session, payload.type, payload.package_id
    )
    targets = await target_crud.resolve(session, target, scope)
    # One poste named alone: the console's button on a fiche or a row. What
    # stops it is said as an error rather than as an empty success — the
    # poste is gone (deleted, merged away), or cut off.
    single = payload.machine_ids is not None and len(set(payload.machine_ids)) == 1
    if single and not targets:
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    if single and targets[0][1]:
        raise AppError(
            code=ErrorCode.MACHINE_TOKEN_REVOKED,
            status_code=409,
            message="This machine's token is revoked; allow its re-enrollment first",
        )
    machine_ids = [machine_id for machine_id, revoked in targets if not revoked]
    revoked_count = len(targets) - len(machine_ids)
    if len(machine_ids) > 1 and payload.type in RISKY_COMMAND_TYPES:
        await windows.require_outside_forbidden(
            session, utcnow(), confirmed=payload.confirm_forbidden_window
        )
    if payload.type in RISKY_COMMAND_TYPES and len(machine_ids) > 1:
        policy = await setting_crud.approval_policy(session)
        if policy.enabled and len(machine_ids) > policy.threshold:
            request = await approval_crud.submit_command(
                session,
                author_id=user.id,
                author_email=user.email,
                command_type=payload.type,
                package=package,
                target=target,
                machine_ids=machine_ids,
                ttl_minutes=payload.ttl_minutes,
                policy=policy,
                now=utcnow(),
            )
            out = CreateCommandsResponse(
                created=[],
                count=0,
                revoked=revoked_count,
                approval_id=request.id,
                approval_expires_at=request.expires_at,
                pending_approval=request.machine_count,
            )
            await session.commit()
            response.status_code = 202
            return out
    queued = await dispatch.queue(
        session,
        command_type=payload.type,
        machine_ids=machine_ids,
        created_by=user.email,
        package=package,
        ttl_minutes=payload.ttl_minutes,
    )
    created, skipped = queued.created, queued.skipped
    superseded, ttl_minutes = queued.superseded, queued.ttl_minutes
    described = target.audit()
    if described is not None:
        audit.record(
            session,
            actor=user.email,
            action="command.bulk",
            resource_type="command",
            # The type, so the log can be filtered on "every bulk reboot"
            # without opening the details.
            resource_id=payload.type.value,
            details={
                "command_type": payload.type.value,
                **(
                    {"package_id": str(package.id), "package": package.name}
                    if package is not None
                    else {}
                ),
                **described,
                "created": len(created),
                "skipped": len(skipped),
                # Postes cut off by a revoked token, left out of the request.
                **({"revoked": revoked_count} if revoked_count else {}),
                "ttl_minutes": ttl_minutes,
                **({"superseded": superseded} if superseded else {}),
            },
        )
    reason = None
    if single and skipped:
        status = await command_crud.open_command_status(
            session,
            machine_id=skipped[0],
            command_type=payload.type,
            package_id=package.id if package is not None else None,
        )
        if status in ("pending", "delivered", "running"):
            reason = status
    await session.commit()
    if superseded:
        # A replaced deployment may have been the last one holding a file
        # changed in the package since (audit S09).
        await package_crud.sweep_store(session)
    return CreateCommandsResponse(
        created=created,
        count=len(created),
        skipped=len(skipped),
        revoked=revoked_count,
        reason=reason,
    )


class PackageSummary(BaseModel):
    """Where a package stands on the postes: for each poste, its latest
    command for that package, counted by status — and by action, since an
    install followed by an uninstall leaves the poste « désinstallé »."""

    postes: int
    by_status: dict[str, int]
    by_action: dict[str, int]
    # Installations no poste has received yet, every one of them (not only
    # each poste's latest): what retiring the package cancels — the console
    # says how many before it asks.
    pending_installs: int = 0


@router.get(
    "/package-summary",
    response_model=PackageSummary,
    dependencies=[Depends(require_permission(Resource.COMMAND, Action.READ))],
)
async def package_summary(
    package_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> PackageSummary:
    """The tally above a package's deployments (audit B14): the table pages
    through every command, this says how the postes stand."""
    await command_crud.mark_expired(session)
    await session.commit()
    latest = (
        restrict(
            select(Command.machine_id, Command.type, Command.status)
            .where(col(Command.package_id) == package_id)
            .distinct(col(Command.machine_id))
            .order_by(
                col(Command.machine_id),
                col(Command.created_at).desc(),
                col(Command.id).desc(),
            ),
            machine_ids_clause(scope, col(Command.machine_id)),
        )
    ).subquery()
    rows = (
        await session.exec(
            select(latest.c.type, latest.c.status, func.count()).group_by(
                latest.c.type, latest.c.status
            )
        )
    ).all()
    by_status: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for kind, status, n in rows:
        by_status[status] = by_status.get(status, 0) + n
        by_action[kind] = by_action.get(kind, 0) + n
    pending_installs = await session.scalar(
        restrict(
            select(func.count())
            .select_from(Command)
            .where(col(Command.package_id) == package_id)
            .where(col(Command.type) == CommandType.PACKAGE_INSTALL.value)
            .where(col(Command.status) == CommandStatus.PENDING.value),
            machine_ids_clause(scope, col(Command.machine_id)),
        )
    )
    return PackageSummary(
        postes=sum(by_status.values()),
        by_status=by_status,
        by_action=by_action,
        pending_installs=pending_installs or 0,
    )


@router.get(
    "",
    response_model=CommandList,
    dependencies=[Depends(require_permission(Resource.COMMAND, Action.READ))],
)
async def list_commands(
    session: SessionDep,
    scope: CurrentScope,
    status: CommandStatus | None = None,
    machine_id: uuid.UUID | None = None,
    package_id: uuid.UUID | None = None,
    latest: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> CommandList:
    """List/track commands, optionally filtered by status and machine.

    ``latest`` (with ``package_id``): each poste's latest command for that
    package only — the rows the package summary counts, so that its chip
    « En attente : 9 » lists nine rows, not every attempt behind them."""
    # Lazy sweep so stale pending commands read as EXPIRED (cron takes over in M5).
    await command_crud.mark_expired(session)
    await session.commit()

    stmt = restrict(select(Command), machine_ids_clause(scope, col(Command.machine_id)))
    if status is not None:
        stmt = stmt.where(col(Command.status) == status)
    if machine_id is not None:
        stmt = stmt.where(col(Command.machine_id) == machine_id)
    if package_id is not None:
        stmt = stmt.where(col(Command.package_id) == package_id)
        if latest:
            stmt = stmt.where(
                col(Command.id).in_(
                    select(Command.id)
                    .where(col(Command.package_id) == package_id)
                    .distinct(col(Command.machine_id))
                    .order_by(
                        col(Command.machine_id),
                        col(Command.created_at).desc(),
                        col(Command.id).desc(),
                    )
                )
            )

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # ``id`` behind the timestamp: a broadcast queues one row per poste in the
    # same instant, and ties reordered between two OFFSETs would duplicate a
    # command on one page and hide another.
    order: list[Any] = [col(Command.created_at).desc(), col(Command.id)]
    if package_id is not None:
        # A package's deployments read batch by batch, each batch by poste
        # name: its rows differ by microseconds of creation, in no order a
        # reader can follow. One request's rows share their expiry, author
        # and type — the batch — which sorts by its newest row.
        batch = func.max(col(Command.created_at)).over(
            partition_by=(
                col(Command.type),
                col(Command.expires_at),
                col(Command.created_by),
            )
        )
        stmt = stmt.outerjoin(Machine, col(Machine.id) == col(Command.machine_id))
        order = [batch.desc(), col(Machine.hostname), col(Command.id)]
    rows = await session.exec(
        stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
    )
    commands = list(rows.all())
    names: dict[uuid.UUID, str | None] = {}
    ids = {c.machine_id for c in commands}
    if ids:
        found = await session.exec(
            select(Machine.id, Machine.hostname).where(col(Machine.id).in_(ids))
        )
        names = dict(found.all())
    package_names: dict[uuid.UUID, str] = {}
    package_ids = {c.package_id for c in commands if c.package_id is not None}
    if package_ids:
        found_packages = await session.exec(
            select(Package.id, Package.name, Package.version).where(
                col(Package.id).in_(package_ids)
            )
        )
        package_names = {
            pid: f"{name} {version}" if version else name
            for pid, name, version in found_packages.all()
        }
    items = []
    for c in commands:
        out = CommandOut.model_validate(c)
        out.machine_hostname = names.get(c.machine_id)
        if c.package_id is not None:
            out.package_name = package_names.get(c.package_id)
        items.append(out)
    return CommandList(items=items, total=total or 0, page=page, page_size=page_size)
