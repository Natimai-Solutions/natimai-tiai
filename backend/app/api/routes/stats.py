"""Console dashboard KPIs (plan §6, M3)."""

import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, true
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select

from app.api.deps import (
    CurrentPermissions,
    CurrentScope,
    ExportLanguage,
    SessionDep,
    require_permission,
)
from app.api.xlsx_export import Sheet, xlsx_workbook_response
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.alert.models import ALL_RULES, MachineAlert
from app.features.asset import crud as asset_crud
from app.features.asset import win11
from app.features.base import utcnow
from app.features.check.models import MachineCheck
from app.features.compliance import crud as compliance_crud
from app.features.inventory.models import MachineSoftware, Volume
from app.features.machine.agent_version import fleet_versions
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    agent_outdated_clause,
    low_disk_clause,
    reenroll_pending_clause,
    status_clause,
)
from app.features.maintenance import policy as maintenance_policy
from app.features.maintenance.policy import MaintenanceState
from app.features.room.models import Room
from app.features.setting import crud as setting_crud
from app.features.stats import counters
from app.features.threat.models import Threat
from app.features.trend import crud as trend_crud
from app.features.trend import failures, indicators
from app.features.trend import report as trend_report
from app.features.usage import crud as usage_crud
from app.features.user.models import Language
from app.features.user.permissions import Action, Resource, permission_key
from app.features.user.scope import (
    Scope,
    machine_clause,
    machine_ids_clause,
    restrict,
)

# What ``Win32_EncryptableVolume`` reports for a volume BitLocker has finished
# protecting. Anything else — in progress, decrypting, suspended, off — is a
# volume that is not protected right now, which is what the card counts.
# Shared with the daily photo's counters (``features/stats/counters.py``).
FULLY_ENCRYPTED = counters.FULLY_ENCRYPTED

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.READ))],
)


class StatsOverview(BaseModel):
    """Fleet KPIs for the dashboard cards."""

    total: int
    up_to_date: int
    outdated: int
    needs_verification: int
    inactive: int
    with_active_threats: int
    # Windows Update (Phase 2). Counted over the machines' own columns rather
    # than over ``windows_updates``: a machine that reports zero pending updates
    # has no rows there, so counting rows would say nothing about how many
    # machines are behind.
    machines_wu_pending: int
    machines_reboot_required: int
    # Inventory. Chosen to be *actionable*: each one is a list an administrator
    # can open and do something about, which is why "combien de Go de RAM au
    # total" is not among them.
    machines_low_disk: int
    machines_unencrypted: int
    machines_aging: int
    software_count: int
    # The threshold behind machines_low_disk, served rather than hardcoded in the
    # console: it is a server setting, and a card reading "moins de 10 %" while
    # the server counts at 15 would be a lie nobody could see.
    low_disk_free_percent: int
    hardware_aging_years: int
    # The agent itself: how many postes run something older than the
    # reference, and what the reference is — the deployment's progress bar,
    # on the wall screen the deployment is watched from.
    machines_agent_outdated: int
    # Verification requests waiting on somebody — the task the console can
    # hand out, as opposed to the findings above that the parc raised itself.
    open_checks: int
    # Postes past their maintenance due date, and within the "soon" window.
    machines_maintenance_overdue: int
    machines_maintenance_due_soon: int
    agent_latest_version: str | None
    # Usage over the console's window: the postes nobody seems to use, and the
    # ones that are never switched off. Same aggregate, same boundary and same
    # thresholds as the list filter each card opens.
    machines_usage_low: int
    machines_usage_high: int
    # The thresholds and window those two were counted with, as resolved
    # (``app_settings``, else the environment) — for the cards' captions, and
    # for the list links they build.
    usage_low_hours: int
    usage_high_hours: int
    usage_window_days: int
    # The first hour ever counted. Until it is a window old, a parc reading
    # « peu utilisé » everywhere is a parc counted since Tuesday: the console
    # says « comptage depuis le … » under the cards. None = nothing yet.
    usage_since: datetime | None
    # Postes waiting on an administrator: a re-enrollment held for approval,
    # and a revoked token (cut off until its re-enrollment is allowed).
    machines_reenroll_pending: int = 0
    machines_token_revoked: int = 0
    # Postes with at least one open alert, and the postes per rule — the
    # « Alertes » card and the links it opens (``/machines?alert=…``).
    machines_with_alerts: int = 0
    alerts_by_rule: dict[str, int] = {}
    # Postes the inventory says cannot take Windows 11, and the retired
    # ones — left out of every other count here, and out of the lists the
    # cards open (``in_parc=true`` on their links while there are any).
    machines_win11_blocked: int = 0
    # Compliance (C5), from the summary the worker keeps: postes passing
    # every known check, postes failing one, and the failures by check.
    machines_compliant: int = 0
    machines_noncompliant: int = 0
    compliance_by_check: dict[str, int] = {}
    machines_retired: int = 0


async def _count(
    session: SessionDep, scope: Any, clause: ColumnElement[bool] | None = None
) -> int:
    """Machines matching ``clause`` within ``scope`` (a ``machine_clause``)."""
    stmt = restrict(select(func.count()).select_from(Machine), scope).where(
        asset_crud.in_parc_clause()
    )
    if clause is not None:
        stmt = stmt.where(clause)
    return await session.scalar(stmt) or 0


@router.get("/overview", response_model=StatsOverview)
async def overview(session: SessionDep, scope: CurrentScope) -> StatsOverview:
    """Aggregate fleet status (total, freshness, verification, inactivity, threats).

    Every figure is the caller's scope's: an account confined to a site sees
    that site's dashboard, and the cards link to lists narrowed the same way.
    """
    now: datetime = utcnow()
    in_scope = machine_clause(scope)
    policies = await setting_crud.policies(session)
    fleet_policy = policies.fleet
    days = fleet_policy.inactive_after_days

    total = await _count(session, in_scope)
    # Judged on the signature age as it stands now, like the list's filter.
    up_to_date = await _count(
        session,
        in_scope,
        status_clause(
            MachineStatus.UP_TO_DATE, now, days, fleet_policy.signature_max_age_days
        ),
    )
    needs_verification = await _count(
        session, in_scope, status_clause(MachineStatus.NEEDS_VERIFICATION, now, days)
    )
    inactive = await _count(
        session, in_scope, status_clause(MachineStatus.INACTIVE, now, days)
    )

    machines_reenroll_pending = await _count(
        session, in_scope, reenroll_pending_clause()
    )
    machines_token_revoked = await _count(
        session, in_scope, col(Machine.token_revoked).is_(True)
    )

    machines_wu_pending = await _count(
        session, in_scope, col(Machine.wu_pending_count) > 0
    )
    machines_reboot_required = await _count(
        session, in_scope, col(Machine.wu_reboot_required).is_(True)
    )

    machines_low_disk = await _count(
        session, in_scope, low_disk_clause(fleet_policy.low_disk_free_percent)
    )
    machines_aging = await _count(
        session,
        in_scope,
        asset_crud.aging_clause(now, fleet_policy.hardware_aging_years),
    )
    # Machines whose *system* volume is not fully encrypted. Read off the volume
    # rows and not off a machine column, unlike the disk figure above: this is
    # not a number the list sorts on, it is a link to a list of postes, and one
    # EXISTS on the dashboard is cheaper than a column maintained on every
    # inventory.
    #
    # A NULL status does not count: BitLocker's WMI namespace is absent on some
    # SKUs and needs elevation, so "not read" would otherwise be reported as
    # "not encrypted" — an alarm on a machine that may well be encrypted is how
    # a dashboard gets ignored.
    machines_unencrypted = await _count(
        session,
        in_scope,
        exists().where(
            and_(
                col(Volume.machine_id) == col(Machine.id),
                col(Volume.is_system).is_(True),
                col(Volume.encryption_status).is_not(None),
                col(Volume.encryption_status) != FULLY_ENCRYPTED,
            )
        ),
    )
    # Distinct programs installed *somewhere*, which is the size of the
    # catalogue page. Counted through the link table rather than over
    # ``software``: an entry every machine has since dropped is history, not
    # something the parc runs.
    software_count = (
        await session.scalar(
            restrict(
                select(func.count(func.distinct(col(MachineSoftware.software_id)))),
                machine_ids_clause(scope, col(MachineSoftware.machine_id)),
            )
        )
        or 0
    )

    with_active_threats = (
        await session.scalar(
            restrict(
                select(func.count(func.distinct(Threat.machine_id))),
                machine_ids_clause(scope, col(Threat.machine_id)),
            ).where(
                col(Threat.status) == "active",
                asset_crud.in_parc_ids_clause(col(Threat.machine_id)),
            )
        )
        or 0
    )

    # Postes below the reference agent version. The reference and the list of
    # versions behind it are the machine list's own (``fleet_versions``), so
    # the card and the list it opens cannot disagree.
    fleet = await fleet_versions(session)
    machines_agent_outdated = (
        await _count(session, in_scope, agent_outdated_clause(fleet.outdated, True))
        if fleet.outdated
        else 0
    )

    open_checks_result = await session.exec(
        restrict(
            select(func.count()).select_from(MachineCheck),
            machine_ids_clause(scope, col(MachineCheck.machine_id)),
        ).where(
            col(MachineCheck.closed_at).is_(None),
            asset_crud.in_parc_ids_clause(col(MachineCheck.machine_id)),
        )
    )
    open_checks = open_checks_result.one() or 0

    policy = policies.maintenance
    joined = restrict(
        select(func.count())
        .select_from(Machine)
        .outerjoin(Room, col(Room.id) == col(Machine.room_id)),
        in_scope,
    ).where(asset_crud.in_parc_clause())
    overdue_result = await session.exec(
        joined.where(
            maintenance_policy.state_clause(MaintenanceState.OVERDUE, policy, now)
        )
    )
    due_soon_result = await session.exec(
        joined.where(
            maintenance_policy.state_clause(MaintenanceState.DUE_SOON, policy, now)
        )
    )

    # Both usage counts off one join: the aggregate over the window is the
    # expensive part, and two filtered COUNTs read it once.
    usage = policies.usage
    usage_start = usage_crud.window_start(now, usage.window_days)
    usage_seconds = usage_crud.seconds_by_machine(usage_start)
    usage_counts = await session.exec(
        select(
            func.count().filter(
                usage_crud.usage_clause(
                    usage_seconds, usage_start, hours_below=usage.low_hours
                )
            ),
            func.count().filter(
                usage_crud.usage_clause(
                    usage_seconds, usage_start, hours_above=usage.high_hours
                )
            ),
        )
        .select_from(Machine)
        .outerjoin(usage_seconds, usage_crud.join_condition(usage_seconds))
        .where(in_scope if in_scope is not None else true())
        .where(asset_crud.in_parc_clause())
    )
    usage_low, usage_high = usage_counts.one()

    # A retired poste's alerts resolve at the next evaluation; until then
    # they are not counted either.
    open_alert = and_(
        col(MachineAlert.resolved_at).is_(None),
        asset_crud.in_parc_ids_clause(col(MachineAlert.machine_id)),
    )
    machines_with_alerts = (
        await session.scalar(
            restrict(
                select(func.count(func.distinct(col(MachineAlert.machine_id)))),
                machine_ids_clause(scope, col(MachineAlert.machine_id)),
            ).where(open_alert)
        )
        or 0
    )
    by_rule = await session.exec(
        restrict(
            select(col(MachineAlert.rule), func.count()),
            machine_ids_clause(scope, col(MachineAlert.machine_id)),
        )
        .where(open_alert)
        .group_by(col(MachineAlert.rule))
    )
    alerts_by_rule = dict(by_rule.all())

    machines_win11_blocked = await _count(session, in_scope, win11.blocked_clause())
    machines_compliant = await _count(
        session, in_scope, compliance_crud.filter_clause("passing")
    )
    machines_noncompliant = await _count(
        session, in_scope, compliance_crud.filter_clause("failing")
    )
    failed_check = func.jsonb_array_elements_text(
        col(Machine.compliance_failed)
    ).table_valued("value")
    by_check = await session.exec(
        restrict(
            select(failed_check.c.value, func.count())
            .select_from(Machine)
            .join(failed_check, true()),
            in_scope,
        )
        .where(
            asset_crud.in_parc_clause(),
            func.jsonb_typeof(col(Machine.compliance_failed)) == "array",
        )
        .group_by(failed_check.c.value)
    )
    compliance_by_check = {str(k): int(v) for k, v in by_check.all()}
    machines_retired = (
        await session.scalar(
            restrict(select(func.count()).select_from(Machine), in_scope).where(
                asset_crud.retired_clause()
            )
        )
        or 0
    )

    return StatsOverview(
        machines_win11_blocked=machines_win11_blocked,
        machines_compliant=machines_compliant,
        machines_noncompliant=machines_noncompliant,
        compliance_by_check=compliance_by_check,
        machines_retired=machines_retired,
        machines_with_alerts=machines_with_alerts,
        alerts_by_rule={r.value: alerts_by_rule.get(r.value, 0) for r in ALL_RULES},
        total=total,
        up_to_date=up_to_date,
        outdated=total - up_to_date,
        needs_verification=needs_verification,
        inactive=inactive,
        with_active_threats=with_active_threats,
        machines_wu_pending=machines_wu_pending,
        machines_reboot_required=machines_reboot_required,
        machines_low_disk=machines_low_disk,
        machines_unencrypted=machines_unencrypted,
        machines_aging=machines_aging,
        software_count=software_count,
        low_disk_free_percent=fleet_policy.low_disk_free_percent,
        hardware_aging_years=fleet_policy.hardware_aging_years,
        machines_agent_outdated=machines_agent_outdated,
        open_checks=open_checks,
        machines_maintenance_overdue=overdue_result.one() or 0,
        machines_maintenance_due_soon=due_soon_result.one() or 0,
        agent_latest_version=fleet.latest,
        machines_usage_low=usage_low or 0,
        machines_usage_high=usage_high or 0,
        usage_low_hours=usage.low_hours,
        usage_high_hours=usage.high_hours,
        usage_window_days=usage.window_days,
        usage_since=await usage_crud.usage_since(session),
        machines_reenroll_pending=machines_reenroll_pending,
        machines_token_revoked=machines_token_revoked,
    )


# --- Trends, indicators, recurring failures, report (C9) ----------------------

TrendMonths = Annotated[int, Query(ge=1, le=24, description="1 to 24 months")]


def _trend_keys(raw: str | None) -> list[str]:
    """``keys=total,open_checks`` → the keys, in order, without repeats; an
    unknown one is a 422 rather than a series silently missing."""
    if not raw:
        return list(trend_crud.DEFAULT_KEYS)
    keys = list(dict.fromkeys(p.strip() for p in raw.split(",") if p.strip()))
    unknown = sorted(set(keys) - set(counters.ALL_KEYS))
    if unknown or not keys:
        raise AppError(
            code=ErrorCode.REQUEST_VALIDATION_ERROR,
            status_code=422,
            message=f"Unknown key in keys: {', '.join(unknown)}",
        )
    return keys


class PolicyChange(BaseModel):
    day: date
    key: str
    before: Any = None
    after: Any = None


class TrendsOut(BaseModel):
    """The daily photo summed over the caller's scope (plan C9 §2.5)."""

    days: list[date]
    # One value per day of ``days``: the sum over the cells in scope (0 when
    # none carries the key), or null for a day never photographed — a gap.
    series: dict[str, list[int | None]]
    step: Literal["day", "week"]
    # Today, when it is on the axis: its point is redrawn every hour.
    provisional_day: date | None
    # The first day ever photographed; null before the first photo.
    since: date | None
    policy_changes: list[PolicyChange]


@router.get("/trends", response_model=TrendsOut)
async def trends(
    session: SessionDep,
    scope: CurrentScope,
    months: TrendMonths = 12,
    step: Literal["day", "week"] | None = None,
    keys: str | None = Query(
        None, description="Comma-separated counter keys; the default series when absent"
    ),
) -> TrendsOut:
    """The dashboard's counters over the past months, for the caller's scope:
    one point a day, or a week (its last day photographed) beyond 3 months."""
    wanted = _trend_keys(keys)
    period = await trend_crud.period(session, months, utcnow())
    chosen_step = step or ("day" if months <= 3 else "week")
    result = await trend_crud.series(
        session,
        scope,
        start=period.first_day,
        end=period.today,
        step=chosen_step,
        keys=wanted,
        today=period.today,
    )
    return TrendsOut(
        days=result.days,
        series=result.series,
        step=chosen_step,
        provisional_day=result.provisional_day,
        since=result.since,
        policy_changes=[PolicyChange(**c) for c in result.policy_changes],
    )


class CheckMonthOut(BaseModel):
    month: str
    closed: int
    median_hours: float | None
    p90_hours: float | None
    with_due: int
    on_time_due: int


class MaintenanceMonthOut(BaseModel):
    month: str
    done: int
    on_time: int


class CommandMonthOut(BaseModel):
    month: str
    succeeded: int
    failed: int
    expired: int
    unanswered: int


class DeploymentsOut(BaseModel):
    direct: list[CommandMonthOut]
    scheduled: list[CommandMonthOut]
    # Null for a confined account, or one that does not read the schedules.
    halted_runs: list[int] | None


class RetentionOut(BaseModel):
    # Null when nothing is purged (``COMMAND_RETENTION_DAYS = 0``).
    commands_days: int | None
    schedule_runs_days: int


class IndicatorsOut(BaseModel):
    """Monthly indicators read off the history (plan C9 §3). A section is
    null when the caller may not read its source."""

    months: list[str]
    checks: list[CheckMonthOut] | None
    maintenance: list[MaintenanceMonthOut] | None
    commands: list[CommandMonthOut] | None
    deployments: DeploymentsOut | None
    retention: RetentionOut


def _can(permissions: frozenset[str], resource: Resource) -> bool:
    return permission_key(resource, Action.READ) in permissions


async def _indicators(
    session: SessionDep,
    scope: Scope | None,
    permissions: frozenset[str],
    period: trend_crud.Period,
) -> tuple[
    list[indicators.CheckMonth] | None,
    list[indicators.MaintenanceMonth] | None,
    list[indicators.CommandMonth] | None,
    indicators.Deployments | None,
]:
    checks = (
        await indicators.checks(session, scope, period)
        if _can(permissions, Resource.CHECK)
        else None
    )
    maintenance = (
        await indicators.maintenance(session, scope, period)
        if _can(permissions, Resource.MAINTENANCE)
        else None
    )
    commands = (
        await indicators.commands(session, scope, period)
        if _can(permissions, Resource.COMMAND)
        else None
    )
    deployments = (
        await indicators.deployments(
            session,
            scope,
            period,
            can_read_schedules=_can(permissions, Resource.SCHEDULE),
        )
        if _can(permissions, Resource.COMMAND) and _can(permissions, Resource.PACKAGE)
        else None
    )
    return checks, maintenance, commands, deployments


@router.get("/indicators", response_model=IndicatorsOut)
async def indicators_route(
    session: SessionDep,
    scope: CurrentScope,
    permissions: CurrentPermissions,
    months: TrendMonths = 12,
) -> IndicatorsOut:
    """Closing delays, maintenance on time, command and deployment outcomes,
    month by month, for the caller's scope."""
    period = await trend_crud.period(session, months, utcnow())
    checks, maintenance, commands, deployments = await _indicators(
        session, scope, permissions, period
    )
    return IndicatorsOut(
        months=period.months,
        checks=(
            [CheckMonthOut(**asdict(m)) for m in checks] if checks is not None else None
        ),
        maintenance=(
            [MaintenanceMonthOut(**asdict(m)) for m in maintenance]
            if maintenance is not None
            else None
        ),
        commands=(
            [CommandMonthOut(**asdict(m)) for m in commands]
            if commands is not None
            else None
        ),
        deployments=(
            DeploymentsOut(
                direct=[CommandMonthOut(**asdict(m)) for m in deployments.direct],
                scheduled=[CommandMonthOut(**asdict(m)) for m in deployments.scheduled],
                halted_runs=deployments.halted_runs,
            )
            if deployments is not None
            else None
        ),
        retention=RetentionOut(
            commands_days=settings.COMMAND_RETENTION_DAYS or None,
            schedule_runs_days=settings.SCHEDULE_RUN_RETENTION_DAYS,
        ),
    )


class FailureRowOut(BaseModel):
    # By model: the model (null = unknown). By room: the room shown (null =
    # no room, or the anonymous « other room » row when ``out_of_scope``).
    hw_model: str | None = None
    room_id: uuid.UUID | None = None
    room_name: str | None = None
    building_name: str | None = None
    out_of_scope: bool = False
    incidents: int
    machines: int
    parc: int
    per_100: float | None
    retired_incidents: int
    retired_machines: int
    last_at: datetime | None


@router.get(
    "/recurring-failures",
    response_model=list[FailureRowOut],
    dependencies=[Depends(require_permission(Resource.INTERVENTION, Action.READ))],
)
async def recurring_failures(
    session: SessionDep,
    scope: CurrentScope,
    months: TrendMonths = 12,
    by: Literal["hw_model", "room"] = "hw_model",
    min_incidents: int = Query(2, ge=1, le=1000),
    limit: int = Query(50, ge=1, le=500),
) -> list[FailureRowOut]:
    """The ``incident`` interventions of the period, by model or by room,
    against the size of that model's or room's parc."""
    period = await trend_crud.period(session, months, utcnow())
    rows = await failures.recurring_failures(
        session, scope, period, by=by, min_incidents=min_incidents, limit=limit
    )
    return [FailureRowOut(**asdict(r)) for r in rows]


@router.get("/report.xlsx")
async def trends_report(
    session: SessionDep,
    scope: CurrentScope,
    permissions: CurrentPermissions,
    months: TrendMonths = 12,
    lang: ExportLanguage = Language.FR,
) -> Response:
    """The Tendances page as a workbook: the counters month by month, the
    indicators and the recurring failures the caller may read."""
    now = utcnow()
    period = await trend_crud.period(session, months, now)
    fleet = await trend_crud.month_ends(
        session,
        scope,
        start=period.first_day,
        end=period.today,
        keys=list(trend_report.REPORT_KEYS),
    )
    checks, maintenance, commands, deployments = await _indicators(
        session, scope, permissions, period
    )
    by_model = by_room = None
    if _can(permissions, Resource.INTERVENTION):
        by_model = await failures.recurring_failures(
            session, scope, period, by="hw_model", min_incidents=2, limit=500
        )
        by_room = await failures.recurring_failures(
            session, scope, period, by="room", min_incidents=2, limit=500
        )
    sheets = trend_report.sheets(
        trend_report.ReportData(
            months=period.months,
            fleet=fleet,
            checks=checks,
            maintenance=maintenance,
            commands=commands,
            deployments=deployments,
            by_model=by_model,
            by_room=by_room,
        ),
        lang,
        now=now,
        zone_name=period.zone_name,
        zone=period.zone,
    )
    texts = trend_report.REPORT_TEXTS[lang]
    return await xlsx_workbook_response(
        f"{texts.filename}-{period.today.isoformat()}.xlsx",
        [Sheet(s.title, s.header, s.rows, s.caption) for s in sheets],
    )
