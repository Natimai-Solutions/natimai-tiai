"""Running the schedules: the worker's job, every minute.

``run_due`` takes the schedules come due, one at a time, each claimed under
its row lock (``FOR UPDATE SKIP LOCKED``) and moved to its next occurrence in
the transaction that runs it: two workers never run one occurrence twice. A
run creates the commands on behalf of the author, whose account, rights and
scope are read again first — any of them lost, the schedule is suspended,
the run says why and the author is told.

``follow_runs`` then carries the runs still open:

* « éteindre ensuite »: the postes the run woke — those alone — are shut
  down once their command has finished, never before the agent's ten minutes
  after a boot (``agent/internal/agent/power.go``), never one with a session
  open;
* rings: once a stage has been observed for its delay, its failure rate
  decides — the next stage, or a halt the author is told of.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.features.audit import crud as audit
from app.features.command import dispatch
from app.features.command import target as target_crud
from app.features.command.models import (
    RISKY_COMMAND_TYPES,
    Command,
    CommandStatus,
    CommandType,
)
from app.features.command.target import Target
from app.features.machine.models import Machine
from app.features.notification import schedule_mail
from app.features.package.models import Package
from app.features.schedule import windows
from app.features.schedule.models import (
    Recurrence,
    RunStatus,
    Schedule,
    ScheduleRun,
    ScheduleState,
)
from app.features.user import crud as user_crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource, permission_key
from app.features.user.scope import Scope
from app.features.wol import dispatch as wol_dispatch

logger = logging.getLogger(__name__)

# How late an occurrence may still run: a worker down at 18:00 and back at
# 18:20 runs it, one back the next morning does not — a shutdown or an
# update install an hour late may land in class time.
MAX_LATENESS = timedelta(minutes=60)
# The agent refuses a shutdown in the ten minutes after a boot; a margin on
# top for the time the poste takes to start its agent.
AFTER_WAKE = timedelta(minutes=15)
# How long a shutdown queued after a run waits for its poste.
SHUTDOWN_TTL_MINUTES = 30
# The types that take a poste down: a schedule leaves alone a poste with a
# session open.
POWER_TYPES = frozenset({CommandType.SHUTDOWN.value, CommandType.REBOOT.value})


def _online(machine: Machine, now: datetime) -> bool:
    return machine.last_seen is not None and now - machine.last_seen <= timedelta(
        seconds=settings.OFFLINE_AFTER_SECONDS
    )


def required_permissions(schedule: Schedule) -> list[str]:
    """What the author must still hold for the schedule to run."""
    needed = [
        permission_key(Resource.SCHEDULE, Action.WRITE),
        permission_key(Resource.COMMAND, Action.EXECUTE),
    ]
    if schedule.command_type in RISKY_COMMAND_TYPES or schedule.shutdown_after:
        needed.append(permission_key(Resource.RISKY_COMMAND, Action.EXECUTE))
    return needed


@dataclass
class Authority:
    user: User
    scope: Scope | None


@dataclass
class Refusal:
    code: str
    params: dict[str, Any]


async def check_author(
    session: AsyncSession, schedule: Schedule
) -> Authority | Refusal:
    """The author as they are now: active, with every right the schedule
    needs. Their scope is returned for the targets to be resolved in."""
    user = (
        await session.get(User, schedule.created_by_id)
        if schedule.created_by_id
        else None
    )
    if user is None:
        return Refusal("author_gone", {})
    if not user.is_active:
        return Refusal("author_inactive", {})
    held = await user_crud.user_permissions(session, user.id)
    for permission in required_permissions(schedule):
        if permission not in held:
            return Refusal("permission_lost", {"permission": permission})
    return Authority(user, await user_crud.user_scope(session, user.id))


def next_occurrence(
    schedule: Schedule, policy: windows.SchedulePolicy, after: datetime
) -> datetime | None:
    if schedule.recurrence != Recurrence.WEEKLY:
        return None
    return windows.next_weekly(
        schedule.weekdays or [], schedule.time_of_day or "", policy.zone, after
    )


def stage_target(schedule: Schedule, stage: int) -> Target:
    if schedule.rings:
        return Target.from_json(schedule.rings[stage]["target"])
    return Target.from_json(schedule.target)


def _stop_run(
    run: ScheduleRun,
    status: RunStatus,
    code: str,
    params: dict[str, Any],
    now: datetime,
) -> None:
    run.status = status
    run.result_code = code
    run.result_params = params
    run.finished_at = now


async def _suspend(
    session: AsyncSession,
    schedule: Schedule,
    run: ScheduleRun,
    refusal: Refusal,
    now: datetime,
    author: User | None,
) -> None:
    schedule.state = ScheduleState.SUSPENDED
    schedule.suspended_code = refusal.code
    schedule.suspended_at = now
    schedule.next_run_at = None
    _stop_run(run, RunStatus.SUSPENDED, refusal.code, refusal.params, now)
    audit.record(
        session,
        actor=settings.PROJECT_NAME,
        action="schedule.suspend",
        resource_type="schedule",
        resource_id=str(schedule.id),
        details={"name": schedule.name, "cause": refusal.code, **refusal.params},
    )
    schedule_mail.queue_stop_mail(
        session, author, name=schedule.name, code=refusal.code, params=refusal.params
    )


async def run_stage(
    session: AsyncSession,
    schedule: Schedule,
    run: ScheduleRun,
    stage: int,
    authority: Authority,
    now: datetime,
) -> Refusal | None:
    """Wake, then queue the stage's commands. A refusal suspends the
    schedule; an error of the package fails the run."""
    target = stage_target(schedule, stage)
    if not await target_crud.place_visible(session, target, authority.scope):
        return Refusal("target_gone", {})
    resolved = await target_crud.resolve(session, target, authority.scope)
    ids = [machine_id for machine_id, revoked in resolved if not revoked]
    run.left_out += len(resolved) - len(ids)
    machines = (
        list(
            (await session.exec(select(Machine).where(col(Machine.id).in_(ids)))).all()
        )
        if ids
        else []
    )
    run.stage = stage
    run.stage_started_at = now
    author_email = authority.user.email

    command_type = CommandType(schedule.command_type)
    if schedule.wake_first or command_type == CommandType.WAKE_ON_LAN:
        asleep = [m for m in machines if not _online(m, now)]
        if asleep:
            results = await wol_dispatch.wake(
                session, asleep, created_by=author_email, schedule_run_id=run.id
            )
            woken = [str(r.machine.id) for r in results if r.ok]
            run.woken += len(woken)
            run.woken_ids = [*(run.woken_ids or []), *woken]
            run.woken_at = now
    if command_type == CommandType.WAKE_ON_LAN:
        return None

    if command_type.value in POWER_TYPES:
        # A scheduled restart or shutdown leaves a poste with a session open
        # alone: somebody is working on it.
        busy = {m.id for m in machines if m.session_user_present}
        run.kept_on_ids = [*(run.kept_on_ids or []), *(str(i) for i in busy)]
        ids = [i for i in ids if i not in busy]

    package: Package | None = None
    if schedule.package_id is not None or command_type.value in (
        CommandType.PACKAGE_INSTALL.value,
        CommandType.PACKAGE_UNINSTALL.value,
    ):
        if schedule.package_id is None:
            return Refusal("package_gone", {})
        package = await dispatch.deployable_package(
            session, command_type, schedule.package_id
        )
    queued = await dispatch.queue(
        session,
        command_type=command_type,
        machine_ids=ids,
        created_by=author_email,
        package=package,
        ttl_minutes=schedule.ttl_minutes,
        schedule_run_id=run.id,
        schedule_stage=stage,
    )
    run.created += len(queued.created)
    run.skipped += len(queued.skipped)
    return None


def _needs_following(schedule: Schedule, run: ScheduleRun) -> bool:
    if schedule.rings and run.stage < len(schedule.rings) - 1:
        return True
    return bool(schedule.shutdown_after and run.woken_ids)


async def run_one(
    session: AsyncSession, schedule: Schedule, now: datetime
) -> ScheduleRun:
    """Run one occurrence of ``schedule`` (claimed by the caller) and move it
    to its next one. The caller commits."""
    policy = await windows.schedule_policy(session)
    due = schedule.next_run_at or now
    schedule.last_run_at = now
    schedule.next_run_at = next_occurrence(schedule, policy, max(now, due))
    if schedule.recurrence == Recurrence.ONCE:
        schedule.state = ScheduleState.DONE
    schedule.updated_at = now

    run = ScheduleRun(schedule_id=schedule.id, started_at=now)
    session.add(run)
    await session.flush()

    if now - due > MAX_LATENESS:
        _stop_run(run, RunStatus.FAILED, "missed", {"due": due.isoformat()}, now)
        return run
    window = policy.forbidden_at(now)
    if window is not None and (
        schedule.command_type in RISKY_COMMAND_TYPES or schedule.shutdown_after
    ):
        # Written outside any window; one added since covers this occurrence.
        _stop_run(run, RunStatus.FAILED, "forbidden_window", window.as_json(), now)
        return run

    checked = await check_author(session, schedule)
    if isinstance(checked, Refusal):
        author = (
            await session.get(User, schedule.created_by_id)
            if schedule.created_by_id
            else None
        )
        await _suspend(session, schedule, run, checked, now, author)
        return run
    try:
        refusal = await run_stage(session, schedule, run, 0, checked, now)
    except AppError as exc:
        _stop_run(run, RunStatus.FAILED, exc.code, exc.details or {}, now)
        return run
    if refusal is not None:
        await _suspend(session, schedule, run, refusal, now, checked.user)
        return run
    if not _needs_following(schedule, run):
        run.status = RunStatus.DONE
        run.finished_at = now
    return run


async def run_due(session: AsyncSession, now: datetime, *, limit: int = 50) -> int:
    """Run the occurrences come due, each claimed and committed on its own.
    Returns how many ran."""
    count = 0
    for _ in range(limit):
        schedule = (
            await session.exec(
                select(Schedule)
                .where(
                    col(Schedule.state) == ScheduleState.ACTIVE,
                    col(Schedule.next_run_at).is_not(None),
                    col(Schedule.next_run_at) <= now,
                )
                .order_by(col(Schedule.next_run_at))
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).first()
        if schedule is None:
            break
        run = await run_one(session, schedule, now)
        # Read before the commit expires them.
        schedule_id, status = schedule.id, run.status
        await session.commit()
        logger.info("Schedule %s ran: %s", schedule_id, status)
        count += 1
    return count


# --- Following the open runs --------------------------------------------------


async def _shutdown_after(
    session: AsyncSession,
    schedule: Schedule,
    run: ScheduleRun,
    authority: Authority,
    now: datetime,
) -> bool:
    """Shut down the postes the run woke, once done with. True when every one
    of them is settled."""
    woken = [uuid.UUID(i) for i in run.woken_ids or []]
    settled = set(run.shutdown_ids or []) | set(run.kept_on_ids or [])
    pending = [m for m in woken if str(m) not in settled]
    if not pending:
        return True
    if run.woken_at is not None and now - run.woken_at < AFTER_WAKE:
        return False
    deadline = run.started_at + timedelta(minutes=schedule.ttl_minutes + 60)
    # Their command for this run: finished (or given up) means done with.
    open_rows = await session.exec(
        select(Command.machine_id).where(
            col(Command.schedule_run_id) == run.id,
            col(Command.machine_id).in_(pending),
            col(Command.type) != CommandType.WAKE_ON_LAN.value,
            col(Command.type) != CommandType.SHUTDOWN.value,
            col(Command.status).in_(
                [
                    CommandStatus.PENDING.value,
                    CommandStatus.DELIVERED.value,
                    CommandStatus.RUNNING.value,
                ]
            ),
            col(Command.expires_at) > now,
        )
    )
    busy = set(open_rows.all())
    machines = {
        m.id: m
        for m in (
            await session.exec(select(Machine).where(col(Machine.id).in_(pending)))
        ).all()
    }
    to_stop: list[uuid.UUID] = []
    shut = list(run.shutdown_ids or [])
    kept = list(run.kept_on_ids or [])
    for machine_id in pending:
        machine = machines.get(machine_id)
        if machine is None:
            kept.append(str(machine_id))
            continue
        if machine_id in busy and now < deadline:
            continue
        if machine.session_user_present:
            # Somebody sat down at it since: left on.
            kept.append(str(machine_id))
        elif not _online(machine, now):
            # Off already, or never woke: nothing to do.
            shut.append(str(machine_id))
        else:
            to_stop.append(machine_id)
    if to_stop:
        queued = await dispatch.queue(
            session,
            command_type=CommandType.SHUTDOWN,
            machine_ids=to_stop,
            created_by=authority.user.email,
            ttl_minutes=SHUTDOWN_TTL_MINUTES,
            schedule_run_id=run.id,
        )
        shut += [str(m) for m in to_stop]
        run.created += len(queued.created)
    run.shutdown_ids = shut
    run.kept_on_ids = kept
    return len(set(shut) | set(kept)) >= len(woken)


async def _stage_outcome(
    session: AsyncSession, run: ScheduleRun
) -> tuple[int, int, int]:
    """``(created, finished, failed)`` of the stage's commands."""
    rows = await session.exec(
        select(col(Command.status), func.count())
        .where(
            col(Command.schedule_run_id) == run.id,
            col(Command.schedule_stage) == run.stage,
        )
        .group_by(col(Command.status))
    )
    counts = dict(rows.all())
    created = sum(counts.values())
    failed = counts.get(CommandStatus.FAILED.value, 0)
    finished = failed + counts.get(CommandStatus.SUCCEEDED.value, 0)
    return created, finished, failed


async def _advance_rings(
    session: AsyncSession,
    schedule: Schedule,
    run: ScheduleRun,
    authority: Authority,
    now: datetime,
) -> bool:
    """Start the next stage once the current one has been observed long
    enough and stayed under the failure threshold. True when no stage is left
    to start (or the run stopped)."""
    if not schedule.rings or run.stage >= len(schedule.rings) - 1:
        return True
    observed = timedelta(hours=schedule.ring_observe_hours or 0)
    if run.stage_started_at is None or now - run.stage_started_at < observed:
        return False
    created, finished, failed = await _stage_outcome(session, run)
    threshold = schedule.ring_failure_percent or 0
    stage_number = run.stage + 1
    if created and not finished:
        params: dict[str, Any] = {"stage": stage_number, "created": created}
        code = "ring_no_result"
    else:
        percent = round(100 * failed / finished) if finished else 0
        params = {
            "stage": stage_number,
            "failed": failed,
            "finished": finished,
            "percent": percent,
            "threshold": threshold,
        }
        code = "ring_failed" if percent > threshold else ""
    if code:
        _stop_run(run, RunStatus.HALTED, code, params, now)
        audit.record(
            session,
            actor=settings.PROJECT_NAME,
            action="schedule.halt",
            resource_type="schedule",
            resource_id=str(schedule.id),
            details={"name": schedule.name, "cause": code, **params},
        )
        schedule_mail.queue_stop_mail(
            session, authority.user, name=schedule.name, code=code, params=params
        )
        return True
    try:
        refusal = await run_stage(session, schedule, run, run.stage + 1, authority, now)
    except AppError as exc:
        _stop_run(run, RunStatus.FAILED, exc.code, exc.details or {}, now)
        return True
    if refusal is not None:
        await _suspend(session, schedule, run, refusal, now, authority.user)
        return True
    return run.stage >= len(schedule.rings) - 1


async def follow_one(session: AsyncSession, run: ScheduleRun, now: datetime) -> None:
    schedule = await session.get(Schedule, run.schedule_id)
    if schedule is None:
        return
    checked = await check_author(session, schedule)
    if isinstance(checked, Refusal):
        # No shutdown, no next stage on behalf of an author who lost the
        # right: the run ends, the schedule is suspended.
        author = (
            await session.get(User, schedule.created_by_id)
            if schedule.created_by_id
            else None
        )
        await _suspend(session, schedule, run, checked, now, author)
        return
    rings_done = await _advance_rings(session, schedule, run, checked, now)
    if run.status != RunStatus.RUNNING:
        return
    shutdown_done = True
    if schedule.shutdown_after and run.woken_ids:
        shutdown_done = await _shutdown_after(session, schedule, run, checked, now)
    if rings_done and shutdown_done:
        run.status = RunStatus.DONE
        run.finished_at = now


async def follow_runs(session: AsyncSession, now: datetime, *, limit: int = 100) -> int:
    """Carry the open runs a step further, each under its row lock."""
    ids = list(
        (
            await session.exec(
                select(ScheduleRun.id)
                .where(col(ScheduleRun.status) == RunStatus.RUNNING)
                .order_by(col(ScheduleRun.started_at))
                .limit(limit)
            )
        ).all()
    )
    for run_id in ids:
        run = (
            await session.exec(
                select(ScheduleRun)
                .where(
                    col(ScheduleRun.id) == run_id,
                    col(ScheduleRun.status) == RunStatus.RUNNING,
                )
                .with_for_update(skip_locked=True)
            )
        ).first()
        if run is None:
            continue
        await follow_one(session, run, now)
        await session.commit()
    return len(ids)


async def purge_runs(session: AsyncSession, cutoff: datetime) -> int:
    """Drop the finished runs started before ``cutoff``. Commits."""
    from sqlalchemy import delete

    result = await session.exec(
        delete(ScheduleRun).where(
            col(ScheduleRun.status) != RunStatus.RUNNING,
            col(ScheduleRun.started_at) < cutoff,
        )
    )
    await session.commit()
    return result.rowcount or 0
