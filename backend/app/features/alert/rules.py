"""The rules: for each one, which postes it holds for right now, and why.

Each function returns ``{machine_id: detail}`` — the detail being the values
the console words (a percentage, a volume letter, a program name), stored on
the alert and refreshed while it stays open. Set-based SQL reusing the
clauses the list and the dashboard already filter with, so that an alert, the
card that counts it and the list it opens agree on the same postes.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.alert.models import AlertRule
from app.features.alert.os_support import support_of
from app.features.inventory.models import Disk, MachineSoftware, Software, Volume
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    disk_free_percent,
    low_disk_clause,
    status_clause,
)
from app.features.setting.crud import AlertPolicy, FleetPolicy

Matches = dict[Any, dict[str, Any]]

# What BitLocker reports for a volume nothing is left to encrypt on (the
# dashboard's card reads the same constant).
FULLY_ENCRYPTED = "FullyEncrypted"
HEALTHY = "Healthy"
# The chassis that leave the building, for the « portables » scope.
MOBILE_CHASSIS = ("laptop", "tablet")
# Programs named in a single alert at most: a poste carrying forty matches
# of a broad pattern is one finding, not a list to scroll.
MAX_PROGRAMS = 10


async def disk_low(
    session: AsyncSession, fleet: FleetPolicy, alerts: AlertPolicy, now: datetime
) -> Matches:
    rows = await session.exec(
        select(
            col(Machine.id),
            disk_free_percent(),
            col(Machine.system_volume_free_mb),
        ).where(low_disk_clause(fleet.low_disk_free_percent))
    )
    return {
        machine_id: {
            "free_percent": round(float(percent), 1) if percent is not None else None,
            "free_mb": free_mb,
            "threshold_percent": fleet.low_disk_free_percent,
        }
        for machine_id, percent, free_mb in rows.all()
    }


async def disk_unhealthy(
    session: AsyncSession, fleet: FleetPolicy, alerts: AlertPolicy, now: datetime
) -> Matches:
    # A removable drive is a USB stick someone left in: its health is not
    # the poste's.
    rows = await session.exec(
        select(col(Disk.machine_id), col(Disk.model), col(Disk.health_status))
        .where(
            col(Disk.health_status).is_not(None),
            col(Disk.health_status) != HEALTHY,
            col(Disk.is_removable).is_(False),
        )
        .order_by(col(Disk.machine_id), col(Disk.device_id))
    )
    found: Matches = {}
    for machine_id, model, health in rows.all():
        found.setdefault(machine_id, {"disks": []})["disks"].append(
            {"model": model, "health": health}
        )
    return found


async def volume_unencrypted(
    session: AsyncSession, fleet: FleetPolicy, alerts: AlertPolicy, now: datetime
) -> Matches:
    # Never on a status that was not read: BitLocker's namespace is absent
    # on some editions, and « unknown » is not « not encrypted ».
    stmt = (
        select(
            col(Volume.machine_id), col(Volume.letter), col(Volume.encryption_status)
        )
        .join(Machine, col(Machine.id) == col(Volume.machine_id))
        .where(
            col(Volume.is_system).is_(True),
            col(Volume.encryption_status).is_not(None),
            col(Volume.encryption_status) != FULLY_ENCRYPTED,
        )
    )
    if alerts.unencrypted_scope == "laptops":
        stmt = stmt.where(col(Machine.hw_chassis_type).in_(MOBILE_CHASSIS))
    rows = await session.exec(stmt)
    return {
        machine_id: {"letter": letter, "status": status}
        for machine_id, letter, status in rows.all()
    }


async def reboot_pending(
    session: AsyncSession, fleet: FleetPolicy, alerts: AlertPolicy, now: datetime
) -> Matches:
    cutoff = now - timedelta(days=alerts.reboot_pending_days)
    rows = await session.exec(
        select(col(Machine.id), col(Machine.wu_reboot_required_since)).where(
            col(Machine.wu_reboot_required).is_(True),
            col(Machine.wu_reboot_required_since) <= cutoff,
        )
    )
    return {
        machine_id: {
            "since": since.isoformat() if since else None,
            "threshold_days": alerts.reboot_pending_days,
        }
        for machine_id, since in rows.all()
    }


async def os_unsupported(
    session: AsyncSession, fleet: FleetPolicy, alerts: AlertPolicy, now: datetime
) -> Matches:
    # Read in Python: the support table lives in the code, and a parc has a
    # few distinct OS strings for hundreds of postes — parsed once each.
    rows = await session.exec(
        select(col(Machine.id), col(Machine.os_version)).where(
            col(Machine.os_version).is_not(None)
        )
    )
    today = now.date()
    parsed: dict[str, Any] = {}
    found: Matches = {}
    for machine_id, os_version in rows.all():
        if os_version is None:
            continue
        if os_version not in parsed:
            parsed[os_version] = support_of(os_version)
        support = parsed[os_version]
        if support is not None and support.ended(today):
            found[machine_id] = {
                "os_version": os_version,
                "end_of_support": support.end.isoformat() if support.end else None,
            }
    return found


def _escape_like(pattern: str) -> str:
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def forbidden_software(
    session: AsyncSession, fleet: FleetPolicy, alerts: AlertPolicy, now: datetime
) -> Matches:
    patterns = [p.strip() for p in alerts.forbidden_software if p.strip()]
    if not patterns:
        return {}
    # A pattern is a plain substring of the program name, not a LIKE
    # expression: « 100% » must not match everything.
    matches_any = or_(
        *(
            col(Software.name).ilike(f"%{_escape_like(p)}%", escape="\\")
            for p in patterns
        )
    )
    rows = await session.exec(
        select(
            col(MachineSoftware.machine_id), col(Software.name), col(Software.version)
        )
        .join(Software, col(Software.id) == col(MachineSoftware.software_id))
        .where(matches_any)
        .order_by(col(MachineSoftware.machine_id), func.lower(col(Software.name)))
    )
    found: Matches = {}
    for machine_id, name, version in rows.all():
        entry = found.setdefault(machine_id, {"programs": [], "count": 0})
        entry["count"] += 1
        if len(entry["programs"]) < MAX_PROGRAMS:
            entry["programs"].append({"name": name, "version": version or None})
    return found


async def inactive(
    session: AsyncSession, fleet: FleetPolicy, alerts: AlertPolicy, now: datetime
) -> Matches:
    rows = await session.exec(
        select(col(Machine.id), col(Machine.last_seen)).where(
            and_(status_clause(MachineStatus.INACTIVE, now, fleet.inactive_after_days))
        )
    )
    return {
        machine_id: {
            "last_seen": last_seen.isoformat(),
            "threshold_days": fleet.inactive_after_days,
        }
        for machine_id, last_seen in rows.all()
    }


Rule = Callable[[AsyncSession, FleetPolicy, AlertPolicy, datetime], Awaitable[Matches]]

RULES: dict[AlertRule, Rule] = {
    AlertRule.DISK_LOW: disk_low,
    AlertRule.DISK_UNHEALTHY: disk_unhealthy,
    AlertRule.VOLUME_UNENCRYPTED: volume_unencrypted,
    AlertRule.REBOOT_PENDING: reboot_pending,
    AlertRule.OS_UNSUPPORTED: os_unsupported,
    AlertRule.FORBIDDEN_SOFTWARE: forbidden_software,
    AlertRule.INACTIVE: inactive,
}
