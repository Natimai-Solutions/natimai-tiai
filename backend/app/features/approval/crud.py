"""Approval requests (C10): creating them, who may decide them, and every
way they close.

Each transition — request, approve, reject, cancel, expire, fail — is
recorded in the audit log in the transaction that makes it. A request is
decided once: the deciding routes lock its row (``lock_for_decision``) and
require it pending. A failure found while approving closes the request: the
route commits that close, then answers the error (``CommitThenRaise``) —
``core.db.get_db`` would otherwise roll it back, and every retry would do it
all again.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Integer, and_, cast, delete, exists, false, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ErrorCode, violated_constraint
from app.features.approval import reach
from app.features.approval.models import (
    ApprovalKind,
    ApprovalRequest,
    ApprovalRequestMachine,
    ApprovalStatus,
)
from app.features.audit import crud as audit
from app.features.command.models import CommandType
from app.features.command.target import Target
from app.features.machine.models import Machine
from app.features.notification import approval_mail
from app.features.package import crud as package_crud
from app.features.package.models import Package
from app.features.schedule import crud as schedule_crud
from app.features.schedule.models import Schedule, ScheduleState
from app.features.setting.crud import ApprovalPolicy
from app.features.user import crud as user_crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import Scope, machine_clause
from app.features.webhook import emit

# At most this many requests pending per author (§2.2).
MAX_PENDING_PER_AUTHOR = 20
# The possible approvers mailed about a new request, by address.
MAIL_APPROVERS = 20
# Requests expired per transaction by ``mark_expired``.
EXPIRE_BATCH = 100
# The two-key advisory lock of ``lock_author``: this namespace ("TAPP" in
# ASCII), then the first 32 bits of the author's id.
_LOCK_SPACE = 0x54415050

UNIQUE_PENDING_KEY = "uq_approval_requests_pending_key"


class CommitThenRaise(Exception):
    """The request was closed (failed, expired) in the session: commit, then
    answer ``error``."""

    def __init__(self, error: AppError) -> None:
        super().__init__(error.message)
        self.error = error


# --- Creating -------------------------------------------------------------------


def request_key(
    requested_by_id: uuid.UUID,
    command_type: str,
    package_id: uuid.UUID | None,
    machine_ids: list[uuid.UUID],
    ttl_minutes: int | None,
) -> str:
    """What makes two requests the same one: sent twice, or by two
    simultaneous clicks, they are one request (``uq_approval_requests_pending_key``)."""
    document = [
        str(requested_by_id),
        command_type,
        str(package_id) if package_id else None,
        sorted(str(m) for m in set(machine_ids)),
        ttl_minutes,
    ]
    raw = json.dumps(document, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def lock_author(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialise the requests of one author until the transaction ends: the
    limit of pending requests is counted behind it."""
    key = int(user_id.hex[:8], 16)
    if key >= 1 << 31:
        key -= 1 << 32
    await session.exec(
        select(
            func.pg_advisory_xact_lock(cast(_LOCK_SPACE, Integer), cast(key, Integer))
        )
    )


def stored_target(target: Target) -> dict[str, Any]:
    """The target as a request keeps it: a list is the child table."""
    if target.kind == "machines":
        return {"kind": "machines"}
    return target.as_json()


def described_target(request: ApprovalRequest) -> dict[str, Any]:
    """The target as the audit log describes it (``Target.audit``)."""
    target = request.target or {}
    kind = target.get("kind")
    if kind == "machines":
        return {"target": "machines", "requested": request.machine_count}
    if kind == "all":
        return {"target": "all"}
    return {"target": kind, str(kind): target.get("value")}


def _no_approver() -> AppError:
    return AppError(
        code=ErrorCode.APPROVAL_NO_APPROVER,
        status_code=409,
        message=(
            "No other account could approve this request: aim at fewer postes, "
            "or have an administrator adjust the groups or the setting"
        ),
    )


async def _pending_of(session: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(
                col(ApprovalRequest.requested_by_id) == user_id,
                col(ApprovalRequest.status) == ApprovalStatus.PENDING,
            )
        )
        or 0
    )


async def _refuse_too_many(session: AsyncSession, user_id: uuid.UUID) -> None:
    if await _pending_of(session, user_id) >= MAX_PENDING_PER_AUTHOR:
        raise AppError(
            code=ErrorCode.APPROVAL_TOO_MANY_PENDING,
            status_code=409,
            message="Too many requests are waiting for approval",
            details={"max": MAX_PENDING_PER_AUTHOR},
        )


def _package_name(package: Package | None) -> str | None:
    if package is None:
        return None
    return f"{package.name} {package.version}" if package.version else package.name


async def _announce(
    session: AsyncSession, request: ApprovalRequest, approvers: list[User]
) -> None:
    """The journal, the webhooks and the approvers' mails of a new request."""
    audit.record(
        session,
        actor=request.requested_by,
        action="approval.request",
        resource_type="approval",
        resource_id=str(request.id),
        details={
            "kind": request.kind,
            "command_type": request.command_type,
            **(
                {"package_id": str(request.package_id), "package": request.package_name}
                if request.package_id
                else {}
            ),
            **(
                {"schedule": request.schedule_name}
                if request.kind == ApprovalKind.SCHEDULE
                else {}
            ),
            **described_target(request),
            "count": request.machine_count,
            "threshold": request.threshold,
            "expires_at": request.expires_at.isoformat(),
        },
    )
    await emit.approval_requested(session, request)
    await approval_mail.queue_request_mails(session, request, approvers)


async def _find_pending_key(session: AsyncSession, key: str) -> ApprovalRequest | None:
    return (
        await session.exec(
            select(ApprovalRequest).where(
                col(ApprovalRequest.request_key) == key,
                col(ApprovalRequest.status) == ApprovalStatus.PENDING,
            )
        )
    ).first()


async def submit_command(
    session: AsyncSession,
    *,
    author_id: uuid.UUID,
    author_email: str,
    command_type: CommandType,
    package: Package | None,
    target: Target,
    machine_ids: list[uuid.UUID],
    ttl_minutes: int | None,
    policy: ApprovalPolicy,
    now: datetime,
) -> ApprovalRequest:
    """The request for a command at risk above the threshold, instead of its
    commands (§4.1). The same request already pending is returned as it is:
    no second mail, no second webhook. Does not commit."""
    await lock_author(session, author_id)
    key = request_key(
        author_id,
        command_type.value,
        package.id if package is not None else None,
        machine_ids,
        ttl_minutes,
    )
    existing = await _find_pending_key(session, key)
    if existing is not None:
        return existing
    approvers = await reach.command_approvers(
        session, machine_ids, author_id=author_id, limit=MAIL_APPROVERS
    )
    if not approvers:
        raise _no_approver()
    await _refuse_too_many(session, author_id)
    digest = None
    if package is not None:
        digest = package_crud.fingerprint(
            package, await package_crud.files_of(session, package.id)
        )
    request = ApprovalRequest(
        kind=ApprovalKind.COMMAND,
        request_key=key,
        command_type=command_type.value,
        package_id=package.id if package is not None else None,
        package_name=_package_name(package),
        package_digest=digest,
        target=stored_target(target),
        machine_count=len(set(machine_ids)),
        threshold=policy.threshold,
        ttl_minutes=ttl_minutes,
        requested_by_id=author_id,
        requested_by=author_email,
        requested_at=now,
        expires_at=now + timedelta(hours=policy.ttl_hours),
    )
    try:
        async with session.begin_nested():
            session.add(request)
            await session.flush()
            session.add_all(
                ApprovalRequestMachine(request_id=request.id, machine_id=m)
                for m in dict.fromkeys(machine_ids)
            )
            await session.flush()
    except IntegrityError as exc:
        if violated_constraint(exc) != UNIQUE_PENDING_KEY:
            raise
        found = await _find_pending_key(session, key)
        if found is None:  # pragma: no cover - closed in between
            raise
        return found
    await _announce(session, request, approvers)
    return request


async def submit_schedule(
    session: AsyncSession,
    schedule: Schedule,
    *,
    author_id: uuid.UUID,
    author_email: str,
    count: int,
    policy: ApprovalPolicy,
    now: datetime,
) -> ApprovalRequest:
    """The request for a schedule at risk above the threshold (§2.4). The
    schedule is flushed, its previous request closed. Does not commit."""
    await lock_author(session, author_id)
    approvers = await reach.schedule_approvers(
        session, schedule, author_id=author_id, limit=MAIL_APPROVERS
    )
    if not approvers:
        raise _no_approver()
    await _refuse_too_many(session, author_id)
    expires_at = now + timedelta(hours=policy.ttl_hours)
    if schedule.run_at is not None and schedule.run_at < expires_at:
        # A one-off is approved before it runs, or not at all.
        expires_at = schedule.run_at
    package = (
        await session.get(Package, schedule.package_id) if schedule.package_id else None
    )
    request = ApprovalRequest(
        kind=ApprovalKind.SCHEDULE,
        command_type=schedule.command_type,
        package_id=schedule.package_id,
        package_name=_package_name(package),
        target=stored_target(Target.from_json(schedule.target)),
        machine_count=count,
        threshold=policy.threshold,
        schedule_id=schedule.id,
        schedule_name=schedule.name,
        requested_by_id=author_id,
        requested_by=author_email,
        requested_at=now,
        expires_at=expires_at,
    )
    session.add(request)
    await session.flush()
    await _announce(session, request, approvers)
    return request


# --- Who may decide -------------------------------------------------------------


async def decidable(
    session: AsyncSession,
    scope: Scope | None,
    user_id: uuid.UUID,
    permissions: frozenset[str],
    *,
    pending: bool = True,
    only_id: uuid.UUID | None = None,
) -> Any:
    """The requests ``user_id`` may decide: another's, with the rights the
    action asks for, every poste of the list in their scope (for a
    schedule: the schedule visible to them). The one rule of the list, the
    badge, the detail and the decisions. ``pending=False`` keeps the closed
    ones (a decision on one answers « not pending », not « not found »)."""
    if not all(
        has_permission(permissions, *p.split(":", 1)) for p in reach.BASE_PERMISSIONS
    ):
        return false()
    clauses: list[Any] = [
        or_(
            col(ApprovalRequest.requested_by_id).is_(None),
            col(ApprovalRequest.requested_by_id) != user_id,
        )
    ]
    if pending:
        clauses.append(col(ApprovalRequest.status) == ApprovalStatus.PENDING)
    if only_id is not None:
        clauses.append(col(ApprovalRequest.id) == only_id)
    command_ok: Any = col(ApprovalRequest.kind) == ApprovalKind.COMMAND
    in_scope = machine_clause(scope)
    if in_scope is not None:
        child = aliased(ApprovalRequestMachine)
        command_ok = and_(
            command_ok,
            ~exists(
                select(col(child.request_id)).where(
                    col(child.request_id) == col(ApprovalRequest.id),
                    col(child.machine_id).not_in(
                        select(col(Machine.id)).where(in_scope).correlate(None)
                    ),
                )
            ),
        )
    schedule_ok: Any = false()
    if has_permission(permissions, Resource.SCHEDULE.value, Action.WRITE.value):
        schedule_ok = col(ApprovalRequest.kind) == ApprovalKind.SCHEDULE
        if scope is not None:
            # A confined reader: the pending schedule requests are one per
            # schedule at most — a short list, judged by the schedules' rule.
            stmt = select(ApprovalRequest, Schedule).join(
                Schedule, col(Schedule.id) == col(ApprovalRequest.schedule_id)
            )
            if pending:
                stmt = stmt.where(col(ApprovalRequest.status) == ApprovalStatus.PENDING)
            if only_id is not None:
                stmt = stmt.where(col(ApprovalRequest.id) == only_id)
            visible = [
                request.id
                for request, schedule in (await session.exec(stmt)).all()
                if await schedule_crud.visible_to(session, schedule, scope, user_id)
            ]
            schedule_ok = col(ApprovalRequest.id).in_(visible) if visible else false()
    return and_(*clauses, or_(command_ok, schedule_ok))


def _not_found() -> AppError:
    return AppError(
        code=ErrorCode.APPROVAL_NOT_FOUND,
        status_code=404,
        message="Approval request not found",
    )


def not_pending() -> AppError:
    return AppError(
        code=ErrorCode.APPROVAL_NOT_PENDING,
        status_code=409,
        message="This request is no longer pending",
    )


async def _locked(
    session: AsyncSession, request_id: uuid.UUID
) -> ApprovalRequest | None:
    return (
        await session.exec(
            select(ApprovalRequest)
            .where(col(ApprovalRequest.id) == request_id)
            .with_for_update()
        )
    ).first()


async def lock_for_decision(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    user_email: str,
    permissions: frozenset[str],
    scope: Scope | None,
    now: datetime,
) -> ApprovalRequest:
    """The request, locked, that ``user_id`` is about to approve or reject:
    not their own, with the rights, decidable by them, pending, not past its
    expiry — one found expired is expired here, and the route commits that
    before answering (``CommitThenRaise``)."""
    request = await _locked(session, request_id)
    if request is None:
        raise _not_found()
    if request.requested_by_id == user_id:
        raise AppError(
            code=ErrorCode.APPROVAL_OWN_REQUEST,
            status_code=403,
            message="A request is approved by another account",
        )
    for needed in sorted(reach.needed_for(request.kind)):
        resource, action = needed.split(":", 1)
        if not has_permission(permissions, resource, action):
            raise AppError(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                status_code=403,
                message=f"Missing permission: {needed}",
                details={"resource": resource, "action": action},
            )
    clause = await decidable(
        session, scope, user_id, permissions, pending=False, only_id=request.id
    )
    if (
        await session.exec(select(col(ApprovalRequest.id)).where(clause))
    ).first() is None:
        raise _not_found()
    if request.status != ApprovalStatus.PENDING:
        raise not_pending()
    if request.expires_at <= now:
        await expire(session, request, now, actor=user_email)
        raise CommitThenRaise(not_pending())
    return request


async def lock_own(
    session: AsyncSession, request_id: uuid.UUID, *, user_id: uuid.UUID, now: datetime
) -> ApprovalRequest:
    """The author's own request, locked, to cancel it."""
    request = await _locked(session, request_id)
    if request is None or request.requested_by_id != user_id:
        raise _not_found()
    if request.status != ApprovalStatus.PENDING:
        raise not_pending()
    if request.expires_at <= now:
        await expire(session, request, now)
        raise CommitThenRaise(not_pending())
    return request


# --- Closing --------------------------------------------------------------------


async def _author(session: AsyncSession, request: ApprovalRequest) -> User | None:
    if request.requested_by_id is None:
        return None
    return await session.get(User, request.requested_by_id)


async def suspend_schedule(
    session: AsyncSession,
    schedule_id: uuid.UUID | None,
    code: str,
    now: datetime,
) -> None:
    """A schedule waiting for its approval is suspended with ``code``: the
    page says why, and « Réactiver » asks again."""
    if schedule_id is None:
        return
    schedule = (
        await session.exec(
            select(Schedule).where(col(Schedule.id) == schedule_id).with_for_update()
        )
    ).first()
    if schedule is None or schedule.state != ScheduleState.TO_APPROVE:
        return
    schedule.state = ScheduleState.SUSPENDED
    schedule.suspended_code = code
    schedule.suspended_at = now
    schedule.next_run_at = None
    schedule.updated_at = now
    session.add(schedule)


async def expire(
    session: AsyncSession,
    request: ApprovalRequest,
    now: datetime,
    *,
    actor: str | None = None,
) -> None:
    """The request ran out of time: closed, journalled, its author told,
    its schedule suspended. Does not commit."""
    request.status = ApprovalStatus.EXPIRED
    request.decided_at = now
    session.add(request)
    audit.record(
        session,
        actor=actor or settings.PROJECT_NAME,
        action="approval.expire",
        resource_type="approval",
        resource_id=str(request.id),
        details={"requested_by": request.requested_by},
    )
    await approval_mail.queue_outcome_mail(
        session, request, await _author(session, request)
    )
    if request.kind == ApprovalKind.SCHEDULE:
        await suspend_schedule(session, request.schedule_id, "approval_expired", now)


async def fail(
    session: AsyncSession,
    request: ApprovalRequest,
    code: str,
    params: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    actor_email: str,
    now: datetime,
) -> None:
    """The approval was refused by what is checked again then: the request
    is closed as failed, its author told, its schedule suspended with the
    same code. Does not commit — the route commits, then answers."""
    request.status = ApprovalStatus.FAILED
    request.result_code = code
    request.result_params = params or None
    request.decided_by_id = actor_id
    request.decided_by = actor_email
    request.decided_at = now
    session.add(request)
    audit.record(
        session,
        actor=actor_email,
        action="approval.fail",
        resource_type="approval",
        resource_id=str(request.id),
        details={"requested_by": request.requested_by, "cause": code, **params},
    )
    await approval_mail.queue_outcome_mail(
        session, request, await _author(session, request)
    )
    if request.kind == ApprovalKind.SCHEDULE:
        await suspend_schedule(session, request.schedule_id, code, now)


async def cancel(
    session: AsyncSession,
    request: ApprovalRequest,
    *,
    actor: str,
    now: datetime,
    cause: str | None = None,
) -> None:
    """Closed by its author, or by a change of its schedule (``cause``).
    Does not commit."""
    request.status = ApprovalStatus.CANCELLED
    request.decided_at = now
    request.result_code = cause
    session.add(request)
    audit.record(
        session,
        actor=actor,
        action="approval.cancel",
        resource_type="approval",
        resource_id=str(request.id),
        details={
            "requested_by": request.requested_by,
            **({"cause": cause} if cause else {}),
        },
    )


async def reject(
    session: AsyncSession,
    request: ApprovalRequest,
    *,
    actor_id: uuid.UUID,
    actor_email: str,
    note: str | None,
    now: datetime,
) -> None:
    request.status = ApprovalStatus.REJECTED
    request.decided_by_id = actor_id
    request.decided_by = actor_email
    request.decided_at = now
    request.note = note
    session.add(request)
    audit.record(
        session,
        actor=actor_email,
        action="approval.reject",
        resource_type="approval",
        resource_id=str(request.id),
        details={
            "requested_by": request.requested_by,
            **({"note": note} if note else {}),
        },
    )
    await approval_mail.queue_outcome_mail(
        session, request, await _author(session, request)
    )
    if request.kind == ApprovalKind.SCHEDULE:
        await suspend_schedule(session, request.schedule_id, "approval_rejected", now)


async def close_for_schedule(
    session: AsyncSession,
    schedule_id: uuid.UUID,
    *,
    actor: str,
    cause: str,
    now: datetime,
) -> bool:
    """Cancel the pending request of a schedule rewritten, turned back on or
    off. Flushes, so that a new request may take its place."""
    request = (
        await session.exec(
            select(ApprovalRequest)
            .where(
                col(ApprovalRequest.schedule_id) == schedule_id,
                col(ApprovalRequest.status) == ApprovalStatus.PENDING,
            )
            .with_for_update()
        )
    ).first()
    if request is None:
        return False
    await cancel(session, request, actor=actor, now=now, cause=cause)
    await session.flush()
    return True


async def check_requester(
    session: AsyncSession, request: ApprovalRequest
) -> tuple[User | None, str | None, dict[str, Any]]:
    """The author of a command request as they are now: ``(user, None, {})``
    when they may still send it, else the refusal's code and parameters —
    the codes of the schedules' runs (``runner.check_author``)."""
    user = await _author(session, request)
    if user is None:
        return None, "author_gone", {}
    if not user.is_active:
        return user, "author_inactive", {}
    held = await user_crud.user_permissions(session, user.id)
    for permission in sorted(reach.BASE_PERMISSIONS):
        if permission not in held:
            return user, "permission_lost", {"permission": permission}
    return user, None, {}


def author_not_allowed(code: str, params: dict[str, Any]) -> AppError:
    return AppError(
        code=ErrorCode.APPROVAL_AUTHOR_NOT_ALLOWED,
        status_code=409,
        message="The author of this request may no longer send it",
        details={"cause": code, **params},
    )


# --- The worker and the housekeeping ------------------------------------------


async def mark_expired(session: AsyncSession, now: datetime) -> int:
    """Expire the pending requests past their time, a hundred per
    transaction. A request an approver holds locked is skipped: they find it
    expired themselves. Commits."""
    total = 0
    while True:
        rows = list(
            (
                await session.exec(
                    select(ApprovalRequest)
                    .where(
                        col(ApprovalRequest.status) == ApprovalStatus.PENDING,
                        col(ApprovalRequest.expires_at) <= now,
                    )
                    .order_by(col(ApprovalRequest.expires_at))
                    .limit(EXPIRE_BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for request in rows:
            await expire(session, request, now)
        await session.commit()
        total += len(rows)
        if len(rows) < EXPIRE_BATCH:
            return total


async def purge_before(session: AsyncSession, cutoff: datetime) -> int:
    """Drop the requests closed before ``cutoff`` — their lists with them.
    Commits."""
    result = await session.exec(
        delete(ApprovalRequest).where(
            col(ApprovalRequest.status) != ApprovalStatus.PENDING,
            col(ApprovalRequest.decided_at) < cutoff,
        )
    )
    await session.commit()
    return result.rowcount or 0


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge of postes: in the pending requests, the duplicate is the
    kept poste — named once. The closed ones lose the duplicate with it
    (cascade); their counts stay what they were."""
    pending = select(col(ApprovalRequest.id)).where(
        col(ApprovalRequest.status) == ApprovalStatus.PENDING
    )
    kept = aliased(ApprovalRequestMachine)
    await session.exec(
        delete(ApprovalRequestMachine).where(
            col(ApprovalRequestMachine.machine_id) == source_id,
            col(ApprovalRequestMachine.request_id).in_(pending),
            col(ApprovalRequestMachine.request_id).in_(
                select(col(kept.request_id)).where(col(kept.machine_id) == target_id)
            ),
        )
    )
    await session.exec(
        update(ApprovalRequestMachine)
        .where(
            col(ApprovalRequestMachine.machine_id) == source_id,
            col(ApprovalRequestMachine.request_id).in_(pending),
        )
        .values(machine_id=target_id)
    )
