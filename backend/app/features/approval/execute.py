"""Approving a command request (C10, §2.3): everything checked again, at the
time of the approval, in this order — the author, the package, the postes,
the forbidden windows — then the frozen list queued on the author's behalf.

A refusal of the author, the package or the postes closes the request as
failed (``crud.fail``) and raises ``crud.CommitThenRaise``: the route commits
the close, then answers the error. A forbidden window only asks the approver
to confirm, as it asked the author: the request stays pending.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.features.approval import crud
from app.features.approval.models import (
    ApprovalRequest,
    ApprovalRequestMachine,
    ApprovalStatus,
)
from app.features.audit import crud as audit
from app.features.command import dispatch
from app.features.command import target as target_crud
from app.features.command.models import PACKAGE_COMMAND_TYPES, CommandType
from app.features.command.target import Target
from app.features.notification import approval_mail
from app.features.package import crud as package_crud
from app.features.schedule import windows
from app.features.user import crud as user_crud


@dataclass
class Approved:
    # Deployments of an older version of the package replaced by these: the
    # route sweeps the package store once committed.
    superseded: int


async def approve_command(
    session: AsyncSession,
    request: ApprovalRequest,
    *,
    approver_id: uuid.UUID,
    approver_email: str,
    confirm_forbidden_window: bool,
    now: datetime,
) -> Approved:
    """Queue what ``request`` asked, checked again now. ``request`` is
    locked and pending (``crud.lock_for_decision``). Does not commit."""

    async def failed(
        code: str, params: dict[str, Any], error: AppError
    ) -> crud.CommitThenRaise:
        await crud.fail(
            session,
            request,
            code,
            params,
            actor_id=approver_id,
            actor_email=approver_email,
            now=now,
        )
        return crud.CommitThenRaise(error)

    # The author: still there, active, with the rights.
    author, refusal, params = await crud.check_requester(session, request)
    if refusal is not None or author is None:
        code = refusal or "author_gone"
        raise await failed(code, params, crud.author_not_allowed(code, params))
    author_email = author.email
    author_scope = await user_crud.user_scope(session, author.id)

    # The package: not deleted, still deployable, unchanged.
    command_type = CommandType(request.command_type)
    package = None
    if command_type in PACKAGE_COMMAND_TYPES:
        if request.package_id is None:
            raise await failed(
                "package_gone",
                {},
                AppError(
                    code=ErrorCode.APPROVAL_PACKAGE_GONE,
                    status_code=409,
                    message="The package was deleted since the request",
                ),
            )
        try:
            package = await dispatch.deployable_package(
                session, command_type, request.package_id
            )
        except AppError as exc:
            raise await failed(exc.code, dict(exc.details or {}), exc) from None
        assert package is not None
        digest = package_crud.fingerprint(
            package, await package_crud.files_of(session, package.id)
        )
        if digest != request.package_digest:
            raise await failed(
                "package_changed",
                {},
                AppError(
                    code=ErrorCode.APPROVAL_PACKAGE_CHANGED,
                    status_code=409,
                    message="The package changed since the request",
                ),
            )

    # The postes of the list, within the author's scope as it is now.
    listed = list(
        (
            await session.exec(
                select(col(ApprovalRequestMachine.machine_id)).where(
                    col(ApprovalRequestMachine.request_id) == request.id
                )
            )
        ).all()
    )
    resolved = (
        await target_crud.resolve(
            session, Target("machines", machine_ids=tuple(listed)), author_scope
        )
        if listed
        else []
    )
    machine_ids = [m for m, revoked in resolved if not revoked]
    left_out = max(request.machine_count - len(machine_ids), 0)
    if not machine_ids:
        raise await failed(
            "nothing_left",
            {},
            AppError(
                code=ErrorCode.APPROVAL_NOTHING_LEFT,
                status_code=409,
                message="None of the postes of the request is left",
            ),
        )

    # The forbidden windows, at the hour of the approval.
    await windows.require_outside_forbidden(
        session, now, confirmed=confirm_forbidden_window
    )

    queued = await dispatch.queue(
        session,
        command_type=command_type,
        machine_ids=machine_ids,
        created_by=author_email,
        package=package,
        ttl_minutes=request.ttl_minutes,
    )
    audit.record(
        session,
        actor=author_email,
        action="command.bulk",
        resource_type="command",
        resource_id=command_type.value,
        details={
            "command_type": command_type.value,
            **(
                {"package_id": str(package.id), "package": package.name}
                if package is not None
                else {}
            ),
            **crud.described_target(request),
            "created": len(queued.created),
            "skipped": len(queued.skipped),
            **({"left_out": left_out} if left_out else {}),
            "ttl_minutes": queued.ttl_minutes,
            **({"superseded": queued.superseded} if queued.superseded else {}),
            "approval_id": str(request.id),
            "approved_by": approver_email,
        },
    )
    request.status = ApprovalStatus.APPROVED
    request.decided_by_id = approver_id
    request.decided_by = approver_email
    request.decided_at = now
    request.created = len(queued.created)
    request.skipped = len(queued.skipped)
    request.left_out = left_out
    session.add(request)
    audit.record(
        session,
        actor=approver_email,
        action="approval.approve",
        resource_type="approval",
        resource_id=str(request.id),
        details={
            "requested_by": request.requested_by,
            "created": request.created,
            "skipped": request.skipped,
            "left_out": left_out,
        },
    )
    await approval_mail.queue_outcome_mail(session, request, author)
    return Approved(superseded=queued.superseded)
