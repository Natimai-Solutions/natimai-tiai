"""The dashboard's counters as one source and one predicate per key (C9, §2.3).

``GET /stats/overview`` counts its cards one query at a time, under the
caller's scope. The daily photo (``trend.snapshot``) needs the same figures
for the whole parc *by cell* — the agent's site and the room — so that a
confined account later reads the sum of its own cells. This module is that
second reading: the same clauses as ``api/routes/stats.py``, laid over one
``FROM`` so that a single ``GROUP BY`` counts them all.

``overview`` is left as it is (plan §2.3): what keeps the two from drifting
apart is the parity test (``tests/test_trends.py``), which sums the photo's
cells under each scope and compares them with ``overview``'s answer.

Every key here is a number of postes, hence summable cell by cell: the
counters ``overview`` takes as ``COUNT(DISTINCT machine_id)`` over another
table (threats, alerts, verifications) become correlated ``EXISTS`` on
``machines.id``. ``software_count`` (distinct programs) is not summable and
is not here; ``outdated`` is ``total − up_to_date``.
"""

from datetime import datetime

from sqlalchemy import and_, exists, false, func, join, true
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import FromClause
from sqlmodel import col

from app.features.alert.models import ALL_RULES, MachineAlert
from app.features.asset import crud as asset_crud
from app.features.asset import win11
from app.features.check.models import MachineCheck
from app.features.compliance import crud as compliance_crud
from app.features.compliance.checks import ALL_CHECKS
from app.features.inventory.models import Volume
from app.features.machine.agent_version import FleetVersions
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
from app.features.room.models import Building, Room
from app.features.setting.crud import Policies
from app.features.threat.models import Threat
from app.features.usage import crud as usage_crud

# What ``Win32_EncryptableVolume`` reports for a volume BitLocker has finished
# protecting — the dashboard's own constant (``api/routes/stats.py``).
FULLY_ENCRYPTED = "FullyEncrypted"

# The keys counted by ``counter_source``, in the dashboard's order.
BASE_KEYS: tuple[str, ...] = (
    "total",
    "up_to_date",
    "needs_verification",
    "inactive",
    "with_active_threats",
    "machines_wu_pending",
    "machines_reboot_required",
    "machines_low_disk",
    "machines_unencrypted",
    "machines_aging",
    "machines_agent_outdated",
    "open_checks",
    "machines_maintenance_overdue",
    "machines_maintenance_due_soon",
    "machines_usage_low",
    "machines_usage_high",
    "machines_reenroll_pending",
    "machines_token_revoked",
    "machines_with_alerts",
    "machines_win11_blocked",
    "machines_compliant",
    "machines_noncompliant",
    "machines_retired",
)
ALERT_PREFIX = "alerts."
COMPLIANCE_PREFIX = "compliance."
ALERT_KEYS: tuple[str, ...] = tuple(f"{ALERT_PREFIX}{r.value}" for r in ALL_RULES)
COMPLIANCE_KEYS: tuple[str, ...] = tuple(
    f"{COMPLIANCE_PREFIX}{c.value}" for c in ALL_CHECKS
)
# Not stored: recomputed from two stored keys wherever it is read.
DERIVED_KEYS: tuple[str, ...] = ("outdated",)
# Every key a photo can carry, plus the derived one: the catalogue
# ``GET /stats/trends?keys=`` is validated against.
ALL_KEYS: tuple[str, ...] = BASE_KEYS + ALERT_KEYS + COMPLIANCE_KEYS + DERIVED_KEYS


def site_expr() -> ColumnElement[str | None]:
    """A room's effective site, as the scope rules read it (``user/scope.py``)."""
    return func.coalesce(col(Building.location), col(Room.location))


def counter_source(
    now: datetime, policies: Policies, fleet: FleetVersions
) -> tuple[FromClause, dict[str, ColumnElement[bool]]]:
    """``machines ⟕ rooms ⟕ buildings ⟕ usage`` and, per key, the predicate
    a poste of that join must meet to be counted under it.

    ``rooms`` serves the maintenance cycle of the room, ``buildings`` the
    effective site the photo groups on; the usage aggregate over the
    console's window is joined the way ``overview`` joins it, so both usage
    counts read it once. ``fleet`` is ``fleet_versions(session)``.
    """
    fleet_policy = policies.fleet
    days = fleet_policy.inactive_after_days
    usage = policies.usage
    usage_start = usage_crud.window_start(now, usage.window_days)
    usage_seconds = usage_crud.seconds_by_machine(usage_start)
    source = (
        join(Machine, Room, col(Room.id) == col(Machine.room_id), isouter=True)
        .join(Building, col(Building.id) == col(Room.building_id), isouter=True)
        .join(usage_seconds, usage_crud.join_condition(usage_seconds), isouter=True)
    )

    policy = policies.maintenance
    by_key: dict[str, ColumnElement[bool]] = {
        "total": true(),
        "up_to_date": status_clause(
            MachineStatus.UP_TO_DATE, now, days, fleet_policy.signature_max_age_days
        ),
        "needs_verification": status_clause(
            MachineStatus.NEEDS_VERIFICATION, now, days
        ),
        "inactive": status_clause(MachineStatus.INACTIVE, now, days),
        "with_active_threats": exists().where(
            col(Threat.machine_id) == col(Machine.id),
            col(Threat.status) == "active",
        ),
        "machines_wu_pending": col(Machine.wu_pending_count) > 0,
        "machines_reboot_required": col(Machine.wu_reboot_required).is_(True),
        "machines_low_disk": low_disk_clause(fleet_policy.low_disk_free_percent),
        # A NULL status does not count, as on the dashboard: « not read » is
        # not « not encrypted ».
        "machines_unencrypted": exists().where(
            col(Volume.machine_id) == col(Machine.id),
            col(Volume.is_system).is_(True),
            col(Volume.encryption_status).is_not(None),
            col(Volume.encryption_status) != FULLY_ENCRYPTED,
        ),
        "machines_aging": asset_crud.aging_clause(
            now, fleet_policy.hardware_aging_years
        ),
        "machines_agent_outdated": (
            agent_outdated_clause(fleet.outdated, True) if fleet.outdated else false()
        ),
        # One open verification per poste at most (``uq_machine_checks_open``):
        # the poste count is the dashboard's row count.
        "open_checks": exists().where(
            col(MachineCheck.machine_id) == col(Machine.id),
            col(MachineCheck.closed_at).is_(None),
        ),
        "machines_maintenance_overdue": maintenance_policy.state_clause(
            MaintenanceState.OVERDUE, policy, now
        ),
        "machines_maintenance_due_soon": maintenance_policy.state_clause(
            MaintenanceState.DUE_SOON, policy, now
        ),
        "machines_usage_low": usage_crud.usage_clause(
            usage_seconds, usage_start, hours_below=usage.low_hours
        ),
        "machines_usage_high": usage_crud.usage_clause(
            usage_seconds, usage_start, hours_above=usage.high_hours
        ),
        "machines_reenroll_pending": reenroll_pending_clause(),
        "machines_token_revoked": col(Machine.token_revoked).is_(True),
        "machines_with_alerts": exists().where(
            col(MachineAlert.machine_id) == col(Machine.id),
            col(MachineAlert.resolved_at).is_(None),
        ),
        "machines_win11_blocked": win11.blocked_clause(),
        "machines_compliant": compliance_crud.filter_clause("passing"),
        "machines_noncompliant": compliance_crud.filter_clause("failing"),
    }
    in_parc = asset_crud.in_parc_clause()
    predicates = {key: and_(clause, in_parc) for key, clause in by_key.items()}
    # The one count that is about the retired postes themselves.
    predicates["machines_retired"] = asset_crud.retired_clause()
    return source, predicates
