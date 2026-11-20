"""Compliance (C5): the facts the checks need, loaded for many postes at
once, and the summary the worker keeps on ``machines`` for the list's
filter and the dashboard."""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.asset import crud as asset_crud
from app.features.compliance.checks import (
    Check,
    Facts,
    Result,
    evaluate,
    summarize,
)
from app.features.inventory.models import Volume
from app.features.machine.agent_version import fleet_versions
from app.features.machine.models import Machine
from app.features.setting.crud import CompliancePolicy, compliance_policy
from app.features.windows_update.models import WindowsUpdate

# The severities the « correctifs » check counts, as stored (lowercased).
COUNTED_SEVERITIES = ("critical", "important")
BATCH = 500


async def load_facts(
    session: AsyncSession,
    machines: Sequence[Machine],
    policy: CompliancePolicy,
    now: datetime,
    outdated: frozenset[str] | None = None,
) -> dict[uuid.UUID, Facts]:
    ids = [m.id for m in machines]
    if outdated is None:
        outdated = frozenset((await fleet_versions(session)).outdated)
    encryption: dict[uuid.UUID, str | None] = {}
    rows = await session.exec(
        select(col(Volume.machine_id), col(Volume.encryption_status)).where(
            col(Volume.machine_id).in_(ids), col(Volume.is_system).is_(True)
        )
    )
    for machine_id, status in rows.all():
        encryption[machine_id] = status

    cutoff = now - timedelta(days=policy.patch_grace_days)
    overdue: dict[uuid.UUID, list[str]] = {}
    updates = await session.exec(
        select(
            col(WindowsUpdate.machine_id),
            col(WindowsUpdate.kb),
            col(WindowsUpdate.title),
        )
        .where(
            col(WindowsUpdate.machine_id).in_(ids),
            col(WindowsUpdate.type) == "software",
            func.lower(col(WindowsUpdate.severity)).in_(COUNTED_SEVERITIES),
            col(WindowsUpdate.first_seen) <= cutoff,
        )
        .order_by(col(WindowsUpdate.machine_id), col(WindowsUpdate.first_seen))
    )
    for machine_id, kb, title in updates.all():
        overdue.setdefault(machine_id, []).append(kb or title)

    return {
        m.id: Facts(
            system_encryption=encryption.get(m.id),
            overdue_patches=(
                None if m.wu_pending_count is None else overdue.get(m.id, [])
            ),
            outdated_agents=outdated,
        )
        for m in machines
    }


async def for_machine(
    session: AsyncSession, machine: Machine, now: datetime
) -> list[Result]:
    """The checks of one poste, live — the fiche's."""
    policy = await compliance_policy(session)
    facts = await load_facts(session, [machine], policy, now)
    return evaluate(machine, facts[machine.id], policy, now)


async def refresh(session: AsyncSession, now: datetime) -> int:
    """Recompute the summary of every poste, by batches. A retired poste has
    none: it is out of the counters. Commits. Returns the postes changed."""
    policy = await compliance_policy(session)
    outdated = frozenset((await fleet_versions(session)).outdated)
    retired_rows = await session.exec(
        select(col(Machine.id)).where(asset_crud.retired_clause())
    )
    retired = set(retired_rows.all())
    changed = 0
    last: uuid.UUID | None = None
    while True:
        stmt = select(Machine).order_by(col(Machine.id)).limit(BATCH)
        if last is not None:
            stmt = stmt.where(col(Machine.id) > last)
        machines = list((await session.exec(stmt)).all())
        if not machines:
            break
        last = machines[-1].id
        facts = await load_facts(session, machines, policy, now, outdated)
        for m in machines:
            if m.id in retired:
                values: tuple[Any, Any, Any] = (None, None, None)
            else:
                s = summarize(evaluate(m, facts[m.id], policy, now))
                values = (s.passed, s.total, s.failed)
            if (m.compliance_passed, m.compliance_total, m.compliance_failed) != values:
                m.compliance_passed, m.compliance_total, m.compliance_failed = values
                session.add(m)
                changed += 1
        await session.commit()
    return changed


def filter_clause(state: str) -> Any:
    """The list's ``compliance`` filter: « failing » (a known check failed),
    « passing » (every known check passed), « unknown » (none known)."""
    total = col(Machine.compliance_total)
    passed = col(Machine.compliance_passed)
    if state == "failing":
        return and_(total > 0, passed < total)
    if state == "passing":
        return and_(total > 0, passed == total)
    return or_(total.is_(None), total == 0)


def check_clause(check: Check) -> Any:
    """Postes failing one check."""
    return col(Machine.compliance_failed).contains([check.value])
