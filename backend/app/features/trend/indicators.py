"""Indicators computed on read, month by month, off the history already in
the database (C9, §3).

Every aggregate is under ``machine_ids_clause(scope, …)`` and leaves the
retired postes out (``in_parc_ids_clause``): the placement and the parc of
**today**, unlike the trends' frozen cells.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Date, and_, cast, func, literal, or_, true
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.asset import crud as asset_crud
from app.features.check import crud as check_crud
from app.features.check.models import MachineCheck
from app.features.command import texts
from app.features.command.models import (
    PACKAGE_COMMAND_TYPES,
    SERVER_ONLY_COMMAND_TYPES,
    Command,
    CommandStatus,
)
from app.features.intervention.models import Intervention, InterventionKind
from app.features.machine.models import Machine
from app.features.maintenance import policy as maintenance_policy
from app.features.room.models import Room
from app.features.schedule.models import RunStatus, ScheduleRun
from app.features.setting import crud as setting_crud
from app.features.trend.crud import Period
from app.features.user.scope import Scope, machine_ids_clause, restrict

# Commands closed by an operator's gesture rather than by what the command
# did: a merge, a package deleted, retired, changed or replaced, a directory
# reader withdrawn. Built from the verdicts themselves (``command/texts.py``)
# so that a renamed code cannot silently slip back into the rate.
OPERATOR_CLOSURES: frozenset[str] = frozenset(
    {
        texts.merged().code,
        texts.package_deleted().code,
        texts.package_retired().code,
        texts.package_retired_after_queue().code,
        texts.package_changed_after_queue().code,
        texts.package_superseded().code,
        texts.directory_not_reader().code,
    }
)
# A command delivered and never answered: closed by the worker, outside the
# rate like the expired ones (the poste was off, not the command wrong).
UNANSWERED = texts.unanswered(0).code


def month_of(ts: Any, zone: str) -> ColumnElement[str]:
    """``AAAA-MM`` of a timestamp, in the console's zone."""
    return func.to_char(func.timezone(zone, ts), "YYYY-MM")


def _in(column: Any, period: Period) -> ColumnElement[bool]:
    return and_(column >= period.start, column < period.end)


# --- Verifications ------------------------------------------------------------


@dataclass
class CheckMonth:
    month: str
    closed: int = 0
    median_hours: float | None = None
    p90_hours: float | None = None
    with_due: int = 0
    on_time_due: int = 0


async def checks(
    session: AsyncSession, scope: Scope | None, period: Period
) -> list[CheckMonth]:
    """Closing delay of the verifications closed each month: median and 9th
    decile, in hours (a closing antedated before the creation counts 0), and
    how many of those with a due date were closed by it (local day). The
    ones closed by a merge are not closings anybody did."""
    closed_at = col(MachineCheck.closed_at)
    hours = func.greatest(
        func.extract("epoch", closed_at - col(MachineCheck.created_at)), 0
    ) / literal(3600.0)
    due = col(MachineCheck.due_date)
    month = month_of(closed_at, period.zone_name)
    columns: list[Any] = [
        month,
        func.count(),
        func.percentile_cont(0.5).within_group(hours),
        func.percentile_cont(0.9).within_group(hours),
        func.count().filter(due.is_not(None)),
        func.count().filter(
            and_(
                due.is_not(None),
                cast(func.timezone(period.zone_name, closed_at), Date) <= due,
            )
        ),
    ]
    rows = await session.exec(
        restrict(
            select(*columns),
            machine_ids_clause(scope, col(MachineCheck.machine_id)),
        )
        .where(
            _in(closed_at, period),
            or_(
                col(MachineCheck.closing_note_code).is_(None),
                col(MachineCheck.closing_note_code) != check_crud.CLOSED_BY_MERGE,
            ),
            asset_crud.in_parc_ids_clause(col(MachineCheck.machine_id)),
        )
        .group_by(month)
    )
    found = {
        r[0]: CheckMonth(
            month=r[0],
            closed=int(r[1]),
            median_hours=_round(r[2]),
            p90_hours=_round(r[3]),
            with_due=int(r[4]),
            on_time_due=int(r[5]),
        )
        for r in rows.all()
    }
    return [found.get(m) or CheckMonth(month=m) for m in period.months]


def _round(value: Any) -> float | None:
    return None if value is None else round(float(value), 1)


# --- Maintenance --------------------------------------------------------------


@dataclass
class MaintenanceMonth:
    month: str
    done: int = 0
    on_time: int = 0


async def maintenance(
    session: AsyncSession, scope: Scope | None, period: Period
) -> list[MaintenanceMonth]:
    """Maintenances done each month, and how many were on time: by the
    previous maintenance of the poste (over its whole journal, before the
    period included), else its first sight, plus today's cycle of the poste
    (poste, room, parc). A poste excluded from maintenance (cycle ≤ 0) is
    left out."""
    policy = await setting_crud.maintenance_policy(session)
    performed = col(Intervention.performed_at)
    journal = (
        restrict(
            select(
                col(Intervention.machine_id).label("machine_id"),
                performed.label("performed_at"),
                func.lag(performed)
                .over(
                    partition_by=col(Intervention.machine_id),
                    order_by=performed,
                )
                .label("previous"),
            ),
            machine_ids_clause(scope, col(Intervention.machine_id)),
        )
        .where(
            col(Intervention.kind) == InterventionKind.MAINTENANCE,
            performed < period.end,
        )
        .subquery("journal")
    )
    cycle = maintenance_policy.cycle_expr(policy)
    reference = func.coalesce(journal.c.previous, col(Machine.first_seen))
    on_time = journal.c.performed_at <= reference + func.make_interval(0, 0, 0, cycle)
    month = month_of(journal.c.performed_at, period.zone_name)
    rows = await session.exec(
        select(month, func.count(), func.count().filter(on_time))
        .select_from(journal)
        .join(Machine, col(Machine.id) == journal.c.machine_id)
        .outerjoin(Room, col(Room.id) == col(Machine.room_id))
        .where(
            _in(journal.c.performed_at, period),
            cycle > 0,
            asset_crud.in_parc_clause(),
        )
        .group_by(month)
    )
    found = {
        r[0]: MaintenanceMonth(month=r[0], done=int(r[1]), on_time=int(r[2]))
        for r in rows.all()
    }
    return [found.get(m) or MaintenanceMonth(month=m) for m in period.months]


# --- Commands and deployments -------------------------------------------------


@dataclass
class CommandMonth:
    month: str
    succeeded: int = 0
    failed: int = 0
    expired: int = 0
    unanswered: int = 0


async def _command_counts(
    session: AsyncSession,
    scope: Scope | None,
    period: Period,
    where: ColumnElement[bool],
    split: ColumnElement[Any] | None = None,
) -> dict[Any, dict[str, CommandMonth]]:
    """Commands closed each month (``finished_at``, or ``expires_at`` for an
    expired one, which keeps ``finished_at`` NULL), by outcome. Selected in
    two ranges so that both indexes serve. ``split`` groups them further."""
    finished = col(Command.finished_at)
    status = col(Command.status)
    code = col(Command.result_code)
    closed = func.coalesce(finished, col(Command.expires_at))
    month = month_of(closed, period.zone_name)
    unanswered = and_(status == CommandStatus.FAILED, code == UNANSWERED)
    groups = [split] if split is not None else []
    columns: list[Any] = [
        month,
        func.count().filter(status == CommandStatus.SUCCEEDED),
        func.count().filter(
            and_(
                status == CommandStatus.FAILED,
                or_(code.is_(None), code != UNANSWERED),
            )
        ),
        func.count().filter(status == CommandStatus.EXPIRED),
        func.count().filter(unanswered),
        *groups,
    ]
    rows = await session.exec(
        restrict(
            select(*columns),
            machine_ids_clause(scope, col(Command.machine_id)),
        )
        .where(
            or_(
                _in(finished, period),
                and_(
                    status == CommandStatus.EXPIRED,
                    finished.is_(None),
                    _in(col(Command.expires_at), period),
                ),
            ),
            status.in_(
                [
                    CommandStatus.SUCCEEDED,
                    CommandStatus.FAILED,
                    CommandStatus.EXPIRED,
                ]
            ),
            col(Command.type).not_in(sorted(SERVER_ONLY_COMMAND_TYPES)),
            or_(code.is_(None), code.not_in(sorted(OPERATOR_CLOSURES))),
            asset_crud.in_parc_ids_clause(col(Command.machine_id)),
            where,
        )
        .group_by(month, *groups)
    )
    out: dict[Any, dict[str, CommandMonth]] = {}
    for m, ok, ko, expired, lost, *g in rows.all():
        out.setdefault(g[0] if g else None, {})[m] = CommandMonth(
            month=m,
            succeeded=int(ok),
            failed=int(ko),
            expired=int(expired),
            unanswered=int(lost),
        )
    return out


def _months(found: dict[str, CommandMonth], period: Period) -> list[CommandMonth]:
    return [found.get(m) or CommandMonth(month=m) for m in period.months]


async def commands(
    session: AsyncSession, scope: Scope | None, period: Period
) -> list[CommandMonth]:
    found = await _command_counts(session, scope, period, true())
    return _months(found.get(None, {}), period)


@dataclass
class Deployments:
    direct: list[CommandMonth]
    scheduled: list[CommandMonth]
    # Runs in rings stopped on their threshold, by the month they stopped;
    # None for a confined account (a run spans several places) or one that
    # does not read the schedules.
    halted_runs: list[int] | None


async def deployments(
    session: AsyncSession,
    scope: Scope | None,
    period: Period,
    *,
    can_read_schedules: bool,
) -> Deployments:
    """The deployments' outcomes, direct (no schedule stage) apart from
    scheduled (every command a schedule queues carries a stage, 0 without
    rings)."""
    scheduled = col(Command.schedule_stage).is_not(None)
    found = await _command_counts(
        session,
        scope,
        period,
        col(Command.type).in_(sorted(PACKAGE_COMMAND_TYPES)),
        split=scheduled,
    )
    halted: list[int] | None = None
    if scope is None and can_read_schedules:
        finished = col(ScheduleRun.finished_at)
        month = month_of(finished, period.zone_name)
        rows = await session.exec(
            select(month, func.count())
            .where(col(ScheduleRun.status) == RunStatus.HALTED, _in(finished, period))
            .group_by(month)
        )
        by_month = {m: int(n) for m, n in rows.all()}
        halted = [by_month.get(m, 0) for m in period.months]
    return Deployments(
        direct=_months(found.get(False, {}), period),
        scheduled=_months(found.get(True, {}), period),
        halted_runs=halted,
    )
