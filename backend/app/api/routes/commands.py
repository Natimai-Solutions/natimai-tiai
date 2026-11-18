"""Console command dispatch and tracking.

Creating commands is an admin capability (command:execute); tracking them needs
only command:read. A command targets either an explicit list of machines or a
broadcast filter (all / by domain / by status) — each resolved to one row per
machine (plan §4).
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

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
from app.features.package.models import Package
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
    # Targets left alone because their token is revoked: nothing reaches such
    # a poste until its re-enrollment is allowed, and a command queued for
    # it would only sit there until it expired. Not counted in ``skipped``.
    revoked: int = 0
    # A command on one poste only: why nothing was created — the status of
    # the unfinished command already there. None when one was created, and
    # on a request aimed at several postes. ("gone" is answered as a 404.)
    reason: Literal["pending", "delivered", "running", "gone"] | None = None


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

    model_config = {"from_attributes": True}


class CommandList(BaseModel):
    """Paginated command list."""

    items: list[CommandOut]
    total: int
    page: int
    page_size: int


async def _resolve_targets(
    session: SessionDep, payload: CreateCommands, scope: Scope | None
) -> list[tuple[uuid.UUID, bool]]:
    """Resolve the payload's target into existing machine ids, within the
    caller's scope: "the whole parc" from an account confined to a site is
    that site, and a listed poste outside it is dropped like an unknown id.
    Each with whether its token is revoked."""
    stmt = restrict(select(Machine.id, Machine.token_revoked), machine_clause(scope))
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
            status_clause(
                payload.target_status,
                utcnow(),
                fleet.inactive_after_days,
                fleet.signature_max_age_days,
            )
        )
    # target_all → no predicate.
    rows = await session.exec(stmt)
    return [(machine_id, revoked) for machine_id, revoked in rows.all()]


async def _deployable_package(
    session: SessionDep, payload: CreateCommands
) -> Package | None:
    """The package a deployment command names, if it can be deployed.

    Retired packages are refused for an install and accepted for an
    uninstall — taking a program off the parc is exactly what one does with a
    package nobody should install any more. An incomplete ``files`` package is
    refused outright: no poste could run it.

    An uninstallation is refused for what the agent would refuse it for, no
    more (``manifest.Problem.blocks_uninstall``, which the console reads from
    the package payload): a package without an install step is uninstalled
    all the same, as the agent would.

    The package row is locked (``package_crud.locked``) until the commands
    are committed: a change of the package or its retirement waits for them,
    and so sees them — the fingerprint taken here is the package's, and a
    retirement cancels these installations too — and so does another
    deployment of the same package, which then finds them open.
    """
    if payload.type not in PACKAGE_COMMAND_TYPES:
        return None
    if payload.package_id is None:
        raise AppError(
            code=ErrorCode.PACKAGE_REQUIRED,
            status_code=422,
            message="A deployment command names its package",
        )
    # Locked exclusively, not shared: two deployments of one package queued
    # at once would otherwise both find no open command on the postes and
    # both queue one (audit: six identical requests, six installations per
    # poste). Behind the lock the second one sees what the first committed.
    package = await package_crud.locked(session, payload.package_id)
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
    # The agent's rule for the step it would run (audit B30, U04): what no
    # poste would accept is refused here rather than queued to fail — the
    # same list the package payload gives as ``install_blockers``.
    step = "uninstall" if payload.type == CommandType.PACKAGE_UNINSTALL else "install"
    problems = manifest.step_blockers(
        package, await package_crud.files_of(session, package.id), step
    )
    if problems:
        raise AppError(
            code=ErrorCode.PACKAGE_NOT_READY,
            status_code=409,
            message="This package cannot be deployed yet",
            details={
                "problems": [p.message for p in problems],
                # What the console words them from (plan console bilingue).
                "causes": [{"code": p.code, "params": p.params} for p in problems],
            },
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
    targets = await _resolve_targets(session, payload, scope)
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
    superseded = 0
    if package is not None:
        package_files = await package_crud.files_of(session, package.id)
        digest = package_crud.fingerprint(package, package_files)
        package_shas = sorted({f.sha256 for f in package_files})
        # A deployment still waiting for an older version of the package is
        # replaced by this one, not counted as already pending.
        superseded = await package_crud.supersede_stale_pending(
            session,
            package_id=package.id,
            command_type=payload.type.value,
            digest=digest,
            machine_ids=machine_ids,
            now=utcnow(),
        )
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
