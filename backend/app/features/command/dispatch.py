"""Queueing commands on postes: what ``POST /commands`` does once the caller's
rights are checked, shared with a schedule's run (``features.schedule``).

The rights are the caller's to check — the route's dependencies for a person,
the schedule's run for its author, read again from the database.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command.models import PACKAGE_COMMAND_TYPES, CommandType
from app.features.package import crud as package_crud
from app.features.package import manifest
from app.features.package.models import Package
from app.features.setting import crud as setting_crud


async def deployable_package(
    session: AsyncSession, command_type: CommandType, package_id: uuid.UUID | None
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
    if command_type not in PACKAGE_COMMAND_TYPES:
        return None
    if package_id is None:
        raise AppError(
            code=ErrorCode.PACKAGE_REQUIRED,
            status_code=422,
            message="A deployment command names its package",
        )
    # Locked exclusively, not shared: two deployments of one package queued
    # at once would otherwise both find no open command on the postes and
    # both queue one (audit: six identical requests, six installations per
    # poste). Behind the lock the second one sees what the first committed.
    package = await package_crud.locked(session, package_id)
    if package is None:
        raise AppError(
            code=ErrorCode.PACKAGE_NOT_FOUND,
            status_code=404,
            message="Package not found",
        )
    if package.retired_at is not None and command_type == CommandType.PACKAGE_INSTALL:
        raise AppError(
            code=ErrorCode.PACKAGE_RETIRED,
            status_code=409,
            message="This package is retired",
        )
    # The agent's rule for the step it would run (audit B30, U04): what no
    # poste would accept is refused here rather than queued to fail — the
    # same list the package payload gives as ``install_blockers``.
    step = "uninstall" if command_type == CommandType.PACKAGE_UNINSTALL else "install"
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


@dataclass
class Queued:
    created: list[uuid.UUID]
    # Postes that already carried an unfinished command of this type.
    skipped: list[uuid.UUID]
    ttl_minutes: int
    # Deployments of an older version of the package replaced by these.
    superseded: int = 0


async def queue(
    session: AsyncSession,
    *,
    command_type: CommandType,
    machine_ids: list[uuid.UUID],
    created_by: str,
    package: Package | None = None,
    ttl_minutes: int | None = None,
    schedule_run_id: uuid.UUID | None = None,
    schedule_stage: int | None = None,
) -> Queued:
    """Queue one command per poste, skipping those that already have it open
    (``command_crud.create_for_machines``). The caller has resolved the
    postes, checked the rights and the package (``deployable_package``), and
    commits."""
    # A command left pending past its TTL must not block the one queued now,
    # on a poste that was simply off the whole time.
    await command_crud.mark_expired(session)
    if ttl_minutes is None:
        ttl_minutes = (
            await setting_crud.fleet_policy(session)
        ).command_default_ttl_minutes
    now = utcnow()
    expires_at = now + timedelta(minutes=ttl_minutes)
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
            command_type=command_type.value,
            digest=digest,
            machine_ids=machine_ids,
            now=now,
        )
    created, skipped = await command_crud.create_for_machines(
        session,
        machine_ids=machine_ids,
        command_type=command_type,
        created_by=created_by,
        expires_at=expires_at,
        package_id=package.id if package is not None else None,
        package_digest=digest,
        package_files=package_shas,
        schedule_run_id=schedule_run_id,
        schedule_stage=schedule_stage,
    )
    return Queued(
        created=created, skipped=skipped, ttl_minutes=ttl_minutes, superseded=superseded
    )
