"""Evaluating the rules into alerts, and the alerts' life around a poste.

``evaluate`` is the worker's job: run every rule turned on, open an alert for
each (poste, rule) that holds and has none open, refresh the detail of those
still holding, resolve those that no longer hold. Idempotent — run twice in a
row, the second run changes nothing — and safe against a second evaluator:
the insert leans on the partial unique index of the open alerts.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.alert.models import AlertRule, MachineAlert
from app.features.alert.rules import RULES
from app.features.alert.texts import check_instructions
from app.features.asset.models import Asset, AssetStatus
from app.features.check.models import MachineCheck
from app.features.setting import crud as setting_crud

# Rows per INSERT: PostgreSQL takes at most 65,535 parameters in a statement,
# and the first evaluation on a large parc — every rule on, every Windows 10
# poste out of support — opens thousands of alerts at once.
CHUNK = 1000


def _chunks(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [rows[i : i + CHUNK] for i in range(0, len(rows), CHUNK)]


@dataclass(frozen=True)
class OpenedAlert:
    id: uuid.UUID
    machine_id: uuid.UUID
    rule: str
    detail: dict[str, Any]


@dataclass
class Evaluation:
    opened: list[OpenedAlert] = field(default_factory=list)
    resolved: int = 0
    # (machine id, rule) of the alerts resolved, for the webhooks (C8).
    resolved_keys: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    refreshed: int = 0
    checks_opened: int = 0


async def current_matches(
    session: AsyncSession, now: datetime
) -> dict[tuple[uuid.UUID, str], dict[str, Any]]:
    """Every (poste, rule) that holds right now, with its detail — the rules
    turned off left out."""
    values = await setting_crud.get_all(session)
    fleet = await setting_crud.fleet_policy(session, values)
    policy = await setting_crud.alert_policy(session, values)
    # A retired poste is out of the parc: nothing is raised about it, and
    # what was open resolves.
    retired = set(
        (
            await session.exec(
                select(col(Asset.machine_id)).where(
                    col(Asset.machine_id).is_not(None),
                    col(Asset.status) == AssetStatus.RETIRED,
                )
            )
        ).all()
    )
    current: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}
    for rule, run in RULES.items():
        if rule.value not in policy.enabled_rules:
            continue
        for machine_id, detail in (await run(session, fleet, policy, now)).items():
            if machine_id not in retired:
                current[(machine_id, rule.value)] = detail
    return current


async def evaluate(session: AsyncSession, now: datetime) -> Evaluation:
    """Bring the open alerts in line with the rules. Does not commit."""
    current = await current_matches(session, now)
    result = Evaluation()

    open_rows = (
        await session.exec(
            select(MachineAlert).where(col(MachineAlert.resolved_at).is_(None))
        )
    ).all()
    open_keys: set[tuple[uuid.UUID, str]] = set()
    for alert in open_rows:
        key = (alert.machine_id, alert.rule)
        open_keys.add(key)
        if key not in current:
            # A rule that no longer holds — or that was turned off: an alert
            # nobody evaluates any more is not one that still holds.
            alert.resolved_at = now
            session.add(alert)
            result.resolved += 1
            result.resolved_keys.append(key)
        elif alert.detail != current[key]:
            alert.detail = current[key]
            session.add(alert)
            result.refreshed += 1

    new_rows: list[dict[str, Any]] = [
        {
            "id": uuid.uuid4(),
            "machine_id": machine_id,
            "rule": rule,
            "opened_at": now,
            "detail": detail,
        }
        for (machine_id, rule), detail in current.items()
        if (machine_id, rule) not in open_keys
    ]
    if new_rows:
        kept: set[uuid.UUID] = set()
        for chunk in _chunks(new_rows):
            inserted = await session.exec(
                pg_insert(MachineAlert)
                .values(chunk)
                .on_conflict_do_nothing(
                    index_elements=[
                        col(MachineAlert.machine_id),
                        col(MachineAlert.rule),
                    ],
                    index_where=col(MachineAlert.resolved_at).is_(None),
                )
                .returning(col(MachineAlert.id))
            )
            kept.update(inserted.scalars().all())
        result.opened = [
            OpenedAlert(r["id"], r["machine_id"], r["rule"], r["detail"])
            for r in new_rows
            if r["id"] in kept
        ]

    if result.opened:
        result.checks_opened = await _open_checks(session, result.opened)
    return result


async def _open_checks(session: AsyncSession, opened: list[OpenedAlert]) -> int:
    """Open a verification for the new alerts whose rule asks for one.

    One per poste: a poste can have a single open verification, and one
    already open — asked by somebody, or for another alert — is left as it
    is: the alert stays visible on the fiche and does not open a second.
    """
    policy = await setting_crud.alert_policy(session)
    wanted: dict[uuid.UUID, OpenedAlert] = {}
    for alert in opened:
        if alert.rule in policy.auto_check_rules and alert.machine_id not in wanted:
            wanted[alert.machine_id] = alert
    if not wanted:
        return 0
    rows = []
    for machine_id, alert in wanted.items():
        code, params, french = check_instructions(alert.rule, alert.detail)
        rows.append(
            MachineCheck(
                machine_id=machine_id,
                requested_by=settings.PROJECT_NAME,
                instructions=french,
                instructions_code=code,
                instructions_params=params,
            ).model_dump()
        )
    created: list[tuple[uuid.UUID, uuid.UUID]] = []
    instructions_of = {r["machine_id"]: r["instructions"] for r in rows}
    for chunk in _chunks(rows):
        result = await session.exec(
            pg_insert(MachineCheck)
            .values(chunk)
            .on_conflict_do_nothing(
                index_elements=[col(MachineCheck.machine_id)],
                index_where=col(MachineCheck.closed_at).is_(None),
            )
            .returning(col(MachineCheck.id), col(MachineCheck.machine_id))
        )
        created.extend((check_id, machine_id) for check_id, machine_id in result.all())
    for check_id, machine_id in created:
        await session.exec(
            update(MachineAlert)
            .where(col(MachineAlert.id) == wanted[machine_id].id)
            .values(check_id=check_id)
        )
    if created:
        # To the webhooks (C8): the verifications the alerts opened.
        from app.features.machine.models import Machine
        from app.features.webhook import emit as webhook_emit

        machines = (
            await session.exec(
                select(Machine).where(col(Machine.id).in_([m for _, m in created]))
            )
        ).all()
        for machine in machines:
            await webhook_emit.checks_created(
                session,
                [machine],
                requested_by=settings.PROJECT_NAME,
                instructions=instructions_of.get(machine.id),
            )
    return len(created)


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge: the duplicate's resolved alerts are the poste's history and
    follow it; its open ones are dropped — the next evaluation finds on the
    kept record whatever still holds, and two open alerts of one rule cannot
    sit on one poste."""
    await session.exec(
        delete(MachineAlert).where(
            col(MachineAlert.machine_id) == source_id,
            col(MachineAlert.resolved_at).is_(None),
        )
    )
    await session.exec(
        update(MachineAlert)
        .where(col(MachineAlert.machine_id) == source_id)
        .values(machine_id=target_id)
    )


async def purge_before(session: AsyncSession, cutoff: datetime) -> int:
    """Drop the alerts resolved before ``cutoff``. Commits; returns how many.
    An open alert is never purged, however old."""
    result = await session.exec(
        delete(MachineAlert).where(
            col(MachineAlert.resolved_at).is_not(None),
            col(MachineAlert.resolved_at) < cutoff,
        )
    )
    await session.commit()
    return result.rowcount or 0


def is_known_rule(rule: str) -> bool:
    return rule in {r.value for r in AlertRule}
