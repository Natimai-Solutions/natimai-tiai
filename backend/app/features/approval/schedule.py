"""Approving a schedule (C10, §2.4): once, for every run and every stage of
its rings, for its author and a number of postes.

Checked again at the approval, as at a run (``schedule.runner``): the
author's account and rights, a one-off's date, the forbidden windows, the
package. A refusal closes the request as failed and suspends the schedule
with the same code, committed before the answer (``crud.CommitThenRaise``).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.features.approval import crud
from app.features.approval.models import ApprovalRequest, ApprovalStatus
from app.features.audit import crud as audit
from app.features.command.models import (
    PACKAGE_COMMAND_TYPES,
    RISKY_COMMAND_TYPES,
)
from app.features.notification import approval_mail
from app.features.schedule import crud as schedule_crud
from app.features.schedule import runner, windows
from app.features.schedule.models import Recurrence, Schedule, ScheduleState
from app.features.setting.crud import ApprovalPolicy
from app.features.user.models import User
from app.features.user.permissions import has_permission
from app.features.user.scope import Scope


def at_risk(schedule: Schedule) -> bool:
    """What C3 already treats as at risk: what asks ``risky_command:execute``."""
    return schedule.command_type in RISKY_COMMAND_TYPES or schedule.shutdown_after


def clear_approval(schedule: Schedule) -> None:
    schedule.approved_by_id = None
    schedule.approved_by = None
    schedule.approved_at = None
    schedule.approved_for_id = None
    schedule.approved_count = None


async def gate(
    session: AsyncSession,
    schedule: Schedule,
    *,
    author_id: uuid.UUID,
    author_email: str,
    scope: Scope | None,
    policy: ApprovalPolicy,
    now: datetime,
    keep_approval: bool = False,
) -> ApprovalRequest | None:
    """After a write or a reactivation: a schedule at risk above the
    threshold waits for its approval — unless ``keep_approval`` and the
    approval it carries still covers its author and its postes. The
    schedule is flushed (it may be new). Does not commit."""
    if not policy.enabled or not at_risk(schedule):
        return None
    count = await schedule_crud.estimate(session, schedule, scope)
    if count <= policy.threshold:
        return None
    if (
        keep_approval
        and schedule.approved_at is not None
        and schedule.approved_for_id == author_id
        and count <= (schedule.approved_count or 0)
    ):
        return None
    clear_approval(schedule)
    schedule.state = ScheduleState.TO_APPROVE
    schedule.next_run_at = None
    session.add(schedule)
    await session.flush()
    return await crud.submit_schedule(
        session,
        schedule,
        author_id=author_id,
        author_email=author_email,
        count=count,
        policy=policy,
        now=now,
    )


async def approve_schedule(
    session: AsyncSession,
    request: ApprovalRequest,
    *,
    approver_id: uuid.UUID,
    approver_email: str,
    approver_permissions: frozenset[str],
    now: datetime,
) -> None:
    """Approve ``request`` (locked and pending): the schedule becomes
    active. Does not commit."""

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

    # Locked after the request, always in this order.
    schedule = (
        await session.exec(
            select(Schedule)
            .where(col(Schedule.id) == request.schedule_id)
            .with_for_update()
        )
        if request.schedule_id is not None
        else None
    )
    found = schedule.first() if schedule is not None else None
    if found is None or found.state != ScheduleState.TO_APPROVE:
        # Rewritten, turned off or deleted under the request.
        await crud.cancel(
            session, request, actor=approver_email, now=now, cause="schedule_changed"
        )
        raise crud.CommitThenRaise(crud.not_pending())
    sched = found

    checked = await runner.check_author(session, sched)
    if isinstance(checked, runner.Refusal):
        raise await failed(
            checked.code,
            checked.params,
            crud.author_not_allowed(checked.code, checked.params),
        )
    for needed in runner.required_permissions(sched):
        resource, action = needed.split(":", 1)
        if not has_permission(approver_permissions, resource, action):
            raise AppError(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                status_code=403,
                message=f"Missing permission: {needed}",
                details={"resource": resource, "action": action},
            )
    policy = await windows.schedule_policy(session)
    if sched.recurrence == Recurrence.ONCE:
        if sched.run_at is None or sched.run_at <= now:
            raise await failed(
                "in_past",
                {},
                AppError(
                    code=ErrorCode.SCHEDULE_IN_PAST,
                    status_code=422,
                    message="This date and time are past",
                ),
            )
        window = policy.forbidden_at(sched.run_at)
    else:
        window = windows.weekly_in_forbidden(
            sched.weekdays or [], sched.time_of_day or "", policy
        )
    if window is not None:
        raise await failed(
            "forbidden_window",
            window.as_json(),
            AppError(
                code=ErrorCode.SCHEDULE_FORBIDDEN_WINDOW,
                status_code=409,
                message="This schedule would run inside a forbidden window",
                details=windows.window_details(window),
            ),
        )
    if sched.command_type in PACKAGE_COMMAND_TYPES and sched.package_id is None:
        raise await failed(
            "package_gone",
            {},
            AppError(
                code=ErrorCode.APPROVAL_PACKAGE_GONE,
                status_code=409,
                message="The package was deleted since the request",
            ),
        )

    count = await schedule_crud.estimate(session, sched, checked.scope)
    sched.state = ScheduleState.ACTIVE
    sched.suspended_code = None
    sched.suspended_at = None
    sched.next_run_at = (
        sched.run_at
        if sched.recurrence == Recurrence.ONCE
        else runner.next_occurrence(sched, policy, now)
    )
    sched.approved_by_id = approver_id
    sched.approved_by = approver_email
    sched.approved_at = now
    sched.approved_for_id = sched.created_by_id
    sched.approved_count = count
    sched.updated_at = now
    session.add(sched)

    request.status = ApprovalStatus.APPROVED
    request.decided_by_id = approver_id
    request.decided_by = approver_email
    request.decided_at = now
    session.add(request)
    audit.record(
        session,
        actor=approver_email,
        action="approval.approve",
        resource_type="approval",
        resource_id=str(request.id),
        details={
            "requested_by": request.requested_by,
            "schedule": sched.name,
            "approved_count": count,
        },
    )
    author: User = checked.user
    await approval_mail.queue_outcome_mail(session, request, author)
