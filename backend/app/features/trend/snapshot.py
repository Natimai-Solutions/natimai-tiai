"""Taking the daily photo (C9, §2.3 and §6.1).

``record`` is what the worker's ``snapshot_trends`` runs every hour: within
the caller's transaction it takes ``TREND_SNAPSHOT_LOCK``, writes (or
rewrites) the day's ``trend_days`` row, drops the day's cells and inserts the
ones ``take`` computes. The day's row is updated, never deleted: a failure
half-way rolls everything back and leaves the previous photo of the day —
cells and thresholds — as it was.

The figure of a day is therefore the last one taken that day (~23 h local).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, join, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.alert.models import ALL_RULES, MachineAlert
from app.features.asset import crud as asset_crud
from app.features.compliance.checks import ALL_CHECKS
from app.features.machine.agent_version import fleet_versions
from app.features.machine.models import Machine
from app.features.room.models import Building, Room
from app.features.schedule import windows
from app.features.setting import crud as setting_crud
from app.features.setting.crud import Policies
from app.features.stats.counters import (
    ALERT_PREFIX,
    COMPLIANCE_PREFIX,
    counter_source,
    site_expr,
)
from app.features.trend.models import TrendDay, TrendSnapshot

# Serialises two photos taken at once (a second worker started by mistake):
# the second waits for the first to commit, then replaces its cells. A fixed
# value, like ``ACCOUNT_MANAGEMENT_LOCK`` and ``QUOTA_LOCK``: « tiai-trd ».
TREND_SNAPSHOT_LOCK = 0x746961692D747264

# (location, room_id, building_id, site)
CellKey = tuple[str | None, uuid.UUID | None, uuid.UUID | None, str | None]


@dataclass(frozen=True)
class Cell:
    location: str | None
    room_id: uuid.UUID | None
    building_id: uuid.UUID | None
    site: str | None
    counters: dict[str, int]


def policy_values(
    policies: Policies, compliance: setting_crud.CompliancePolicy
) -> dict[str, Any]:
    """The thresholds a photo is taken with, under their settings' keys —
    what ``policy_changes`` compares from one day to the next."""
    fleet = policies.fleet
    usage = policies.usage
    maintenance = policies.maintenance
    return {
        setting_crud.KEY_LOW_DISK: fleet.low_disk_free_percent,
        setting_crud.KEY_HARDWARE_AGING: fleet.hardware_aging_years,
        setting_crud.KEY_INACTIVE_AFTER: fleet.inactive_after_days,
        setting_crud.KEY_SIGNATURE_MAX_AGE: fleet.signature_max_age_days,
        setting_crud.KEY_AGENT_VERSION: fleet.agent_expected_version,
        setting_crud.KEY_USAGE_WINDOW: usage.window_days,
        setting_crud.KEY_USAGE_LOW: usage.low_hours,
        setting_crud.KEY_USAGE_HIGH: usage.high_hours,
        "maintenance.cycle_days": maintenance.cycle_days,
        setting_crud.KEY_DUE_SOON: maintenance.due_soon_days,
        setting_crud.KEY_COMPLIANCE_PATCH_GRACE: compliance.patch_grace_days,
        "compliance.unencrypted_scope": compliance.unencrypted_scope,
    }


def _cell_columns() -> list[Any]:
    return [
        col(Machine.location),
        col(Machine.room_id),
        col(Room.building_id),
        site_expr(),
    ]


async def take(session: AsyncSession, now: datetime, policies: Policies) -> list[Cell]:
    """The counters of every cell of the parc, as ``overview`` would count
    them at ``now``: one grouped query over ``counter_source``, then one per
    breakdown (open alerts by rule, failed compliance checks)."""
    fleet = await fleet_versions(session)
    source, predicates = counter_source(now, policies, fleet)
    cell = _cell_columns()
    keys = list(predicates)
    columns: list[Any] = [*cell, *(func.count().filter(p) for p in predicates.values())]
    rows = await session.exec(select(*columns).select_from(source).group_by(*cell))
    cells: dict[CellKey, dict[str, int]] = {}
    for row in rows.all():
        key: CellKey = (row[0], row[1], row[2], row[3])
        cells[key] = {k: int(v) for k, v in zip(keys, row[4:], strict=True) if v}

    places = join(
        Machine, Room, col(Room.id) == col(Machine.room_id), isouter=True
    ).join(Building, col(Building.id) == col(Room.building_id), isouter=True)
    columns = [*cell, col(MachineAlert.rule), func.count()]
    by_rule = await session.exec(
        select(*columns)
        .select_from(
            places.join(MachineAlert, col(MachineAlert.machine_id) == col(Machine.id))
        )
        .where(
            col(MachineAlert.resolved_at).is_(None),
            col(MachineAlert.rule).in_([r.value for r in ALL_RULES]),
            asset_crud.in_parc_clause(),
        )
        .group_by(*cell, col(MachineAlert.rule))
    )
    for row in by_rule.all():
        key = (row[0], row[1], row[2], row[3])
        if row[5]:
            cells.setdefault(key, {})[f"{ALERT_PREFIX}{row[4]}"] = int(row[5])

    failed = func.jsonb_array_elements_text(
        col(Machine.compliance_failed)
    ).table_valued("value")
    columns = [*cell, failed.c.value, func.count()]
    by_check = await session.exec(
        select(*columns)
        .select_from(places.join(failed, true()))
        .where(
            asset_crud.in_parc_clause(),
            func.jsonb_typeof(col(Machine.compliance_failed)) == "array",
            failed.c.value.in_([c.value for c in ALL_CHECKS]),
        )
        .group_by(*cell, failed.c.value)
    )
    for row in by_check.all():
        key = (row[0], row[1], row[2], row[3])
        if row[5]:
            cells.setdefault(key, {})[f"{COMPLIANCE_PREFIX}{row[4]}"] = int(row[5])

    return [
        Cell(location, room_id, building_id, site, counters)
        for (location, room_id, building_id, site), counters in cells.items()
        if counters
    ]


async def record(session: AsyncSession, now: datetime) -> int:
    """Take today's photo and put it in place of the previous one of the
    day, in the caller's transaction (not committed). Returns the cells."""
    await session.exec(select(func.pg_advisory_xact_lock(TREND_SNAPSHOT_LOCK)))
    values = await setting_crud.get_all(session)
    zone = await windows.schedule_policy(session, values)
    day: date = now.astimezone(zone.zone).date()
    policies = Policies(
        maintenance=await setting_crud.maintenance_policy(session, values),
        usage=await setting_crud.usage_policy(session, values),
        fleet=await setting_crud.fleet_policy(session, values),
    )
    compliance = await setting_crud.compliance_policy(session, values)
    thresholds = policy_values(policies, compliance)

    upsert = pg_insert(TrendDay).values(
        day=day, taken_at=now, zone=zone.zone_name, policies=thresholds
    )
    await session.exec(
        upsert.on_conflict_do_update(
            index_elements=[col(TrendDay.day)],
            set_={
                "taken_at": upsert.excluded.taken_at,
                "zone": upsert.excluded.zone,
                "policies": upsert.excluded.policies,
            },
        )
    )
    await session.exec(delete(TrendSnapshot).where(col(TrendSnapshot.day) == day))
    cells = await take(session, now, policies)
    if cells:
        await session.exec(
            pg_insert(TrendSnapshot).values(
                [
                    {
                        "id": uuid.uuid4(),
                        "day": day,
                        "location": c.location,
                        "room_id": c.room_id,
                        "building_id": c.building_id,
                        "site": c.site,
                        "counters": c.counters,
                    }
                    for c in cells
                ]
            )
        )
    return len(cells)


async def purge_before(session: AsyncSession, cutoff: date) -> int:
    """Drop the days before ``cutoff``, their cells with them (cascade).
    Commits; returns the days gone."""
    result = await session.exec(delete(TrendDay).where(col(TrendDay.day) < cutoff))
    await session.commit()
    return result.rowcount or 0
