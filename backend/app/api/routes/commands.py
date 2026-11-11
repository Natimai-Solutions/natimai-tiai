"""Console command dispatch and tracking.

Creating commands is an admin capability (command:execute); tracking them needs
only command:read. A command targets either an explicit list of machines or a
broadcast filter (all / by domain / by status) — each resolved to one row per
machine (plan §4).
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
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
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command.bulk import describe_command_target
from app.features.command.models import (
    PACKAGE_COMMAND_TYPES,
    RISKY_COMMAND_TYPES,
    Command,
    CommandStatus,
    CommandType,
)
from app.features.machine.models import Machine
from app.features.machine.status import MachineStatus, status_clause
from app.features.package import crud as package_crud
from app.features.package import manifest
from app.features.package.models import Package, PackageKind
from app.features.setting import crud as setting_crud
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import Scope, machine_clause, machine_ids_clause, restrict

router = APIRouter(prefix="/commands", tags=["commands"])


class CreateCommands(BaseModel):
    """Queue a command for an explicit machine list or a broadcast filter.

    Exactly one target must be given: ``machine_ids``, ``target_all``,
    ``target_domain``, ``target_location``, or ``target_status``.
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
        return value

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "CreateCommands":
        provided = [
            bool(self.machine_ids),
            self.target_all,
            self.target_domain is not None,
            self.target_location is not None,
            self.target_status is not None,
        ]
        if sum(provided) != 1:
            raise ValueError(
                "provide exactly one target: machine_ids, target_all, "
                "target_domain, target_location, or target_status"
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
    session: SessionDep, payload: CreateCommands, scope: Scope | None
) -> list[uuid.UUID]:
    """Resolve the payload's target into existing machine ids, within the
    caller's scope: "the whole parc" from an account confined to a site is
    that site, and a listed poste outside it is dropped like an unknown id."""
    stmt = restrict(select(Machine.id), machine_clause(scope))
    if payload.machine_ids:
        # Restrict to ids that actually exist (avoids FK violations on insert).
        stmt = stmt.where(col(Machine.id).in_(payload.machine_ids))
    elif payload.target_domain is not None:
        stmt = stmt.where(col(Machine.domain) == payload.target_domain)
    elif payload.target_location is not None:
        stmt = stmt.where(col(Machine.location) == payload.target_location)
    elif payload.target_status is not None:
        fleet = await setting_crud.fleet_policy(session)
        stmt = stmt.where(
            status_clause(payload.target_status, utcnow(), fleet.inactive_after_days)
        )
    # target_all → no predicate.
    rows = await session.exec(stmt)
    return list(rows.all())


async def _deployable_package(
    session: SessionDep, payload: CreateCommands
) -> Package | None:
    """The package a deployment command names, if it can be deployed.

    Retired packages are refused for an install and accepted for an
    uninstall — taking a program off the parc is exactly what one does with a
    package nobody should install any more. An incomplete ``files`` package is
    refused outright: no poste could run it.
    """
    if payload.type not in PACKAGE_COMMAND_TYPES:
        return None
    if payload.package_id is None:
        raise AppError(
            code=ErrorCode.PACKAGE_REQUIRED,
            status_code=422,
            message="A deployment command names its package",
        )
    package = await session.get(Package, payload.package_id)
    if package is None:
        raise AppError(
            code=ErrorCode.PACKAGE_NOT_FOUND,
            status_code=404,
            message="Package not found",
        )
    if package.retired_at is not None and payload.type == CommandType.PACKAGE_INSTALL:
        raise AppError(
            code=ErrorCode.PACKAGE_RETIRED,
            status_code=409,
            message="This package is retired",
        )
    if package.kind == PackageKind.FILES:
        files = await package_crud.files_of(session, package.id)
        problems = manifest.problems(package, files)
        if (
            payload.type == CommandType.PACKAGE_INSTALL
            and not problems
            and not manifest.runnable_somewhere(package, files)
        ):
            problems = [
                manifest.Problem(
                    "untrusted",
                    "Ni signé, ni lancé par un exécutable d'éditeur seul dans son "
                    "dossier : aucun poste ne l'exécutera. Signez le paquet.",
                )
            ]
        if payload.type == CommandType.PACKAGE_UNINSTALL and not package.uninstall_run:
            problems = [
                *problems,
                manifest.Problem("no_uninstall", "Pas de désinstallation définie"),
            ]
        if problems:
            raise AppError(
                code=ErrorCode.PACKAGE_NOT_READY,
                status_code=409,
                message="This package cannot be deployed yet",
                details={"problems": [p.message for p in problems]},
            )
    return package


@router.post(
    "",
    response_model=CreateCommandsResponse,
    dependencies=[Depends(require_permission(Resource.COMMAND, Action.EXECUTE))],
)
async def create_commands(
    payload: CreateCommands,
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    scope: CurrentScope,
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
    package = await _deployable_package(session, payload)
    machine_ids = await _resolve_targets(session, payload, scope)
    # Same sweep the tracking endpoint runs: a command left pending past its TTL
    # must not block the one an administrator is queueing now, on a poste that
    # was simply off the whole time.
    await command_crud.mark_expired(session)
    ttl_minutes = payload.ttl_minutes
    if ttl_minutes is None:
        ttl_minutes = (
            await setting_crud.fleet_policy(session)
        ).command_default_ttl_minutes
    expires_at = utcnow() + timedelta(minutes=ttl_minutes)
    # The package as approved now: what the postes will run, or nothing
    # (audit T08); and its files, kept for them meanwhile (T09).
    digest: str | None = None
    package_shas: list[str] | None = None
    if package is not None:
        package_files = await package_crud.files_of(session, package.id)
        digest = package_crud.fingerprint(package, package_files)
        package_shas = sorted({f.sha256 for f in package_files})
    created, skipped = await command_crud.create_for_machines(
        session,
        machine_ids=machine_ids,
        command_type=payload.type,
        created_by=user.email,
        expires_at=expires_at,
        package_id=package.id if package is not None else None,
        package_digest=digest,
        package_files=package_shas,
    )
    target = describe_command_target(
        machine_ids=payload.machine_ids,
        target_all=payload.target_all,
        target_domain=payload.target_domain,
        target_location=payload.target_location,
        target_status=payload.target_status,
    )
    if target is not None:
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
                **target,
                "created": len(created),
                "skipped": len(skipped),
                "ttl_minutes": ttl_minutes,
            },
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
    scope: CurrentScope,
    status: CommandStatus | None = None,
    machine_id: uuid.UUID | None = None,
    package_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> CommandList:
    """List/track commands, optionally filtered by status and machine."""
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

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # ``id`` behind the timestamp: a broadcast queues one row per poste in the
    # same instant, and ties reordered between two OFFSETs would duplicate a
    # command on one page and hide another.
    rows = await session.exec(
        stmt.order_by(col(Command.created_at).desc(), col(Command.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    commands = list(rows.all())
    names: dict[uuid.UUID, str | None] = {}
    ids = {c.machine_id for c in commands}
    if ids:
        found = await session.exec(
            select(Machine.id, Machine.hostname).where(col(Machine.id).in_(ids))
        )
        names = dict(found.all())
    items = []
    for c in commands:
        out = CommandOut.model_validate(c)
        out.machine_hostname = names.get(c.machine_id)
        items.append(out)
    return CommandList(items=items, total=total or 0, page=page, page_size=page_size)
