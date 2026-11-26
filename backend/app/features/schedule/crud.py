"""Schedules beyond their routes: who may see one, how many postes it
reaches, and what a merge of postes does to them (plan §2, « Fusion de
postes »)."""

import uuid
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.command import target as target_crud
from app.features.command.target import Target
from app.features.machine.models import Machine
from app.features.schedule.models import Schedule
from app.features.user.scope import Scope, machine_clause, restrict


def targets_of(schedule: Schedule) -> list[Target]:
    """The schedule's target and each of its rings'."""
    return [Target.from_json(schedule.target)] + [
        Target.from_json(r["target"]) for r in schedule.rings or []
    ]


async def visible_to(
    session: AsyncSession,
    schedule: Schedule,
    scope: Scope | None,
    user_id: uuid.UUID,
) -> bool:
    """Whether an account may see ``schedule``: an unrestricted one sees all,
    its author sees it, and a restricted one sees those aimed at a room, a
    building or postes all within its scope — never one aimed at a whole
    domain, site or the parc written by someone else. The rule of the
    schedules' routes and of who may approve one (C10)."""
    if scope is None or schedule.created_by_id == user_id:
        return True
    for target in targets_of(schedule):
        if target.kind in ("room", "building"):
            if not await target_crud.place_visible(session, target, scope):
                return False
        elif target.kind == "machines":
            inside = await session.scalar(
                restrict(
                    select(func.count())
                    .select_from(Machine)
                    .where(col(Machine.id).in_(list(target.machine_ids))),
                    machine_clause(scope),
                )
            )
            if (inside or 0) < len(set(target.machine_ids)):
                return False
        else:
            return False
    return True


async def estimate(
    session: AsyncSession, schedule: Schedule, scope: Scope | None
) -> int:
    """How many postes the schedule reaches, every stage together, within
    ``scope`` (its author's), revoked tokens left out. The one count of the
    approval threshold: when written, turned back on, approved, and at each
    run (C10)."""
    reached: set[uuid.UUID] = set()
    for target in targets_of(schedule):
        resolved = await target_crud.resolve(session, target, scope)
        reached |= {machine_id for machine_id, revoked in resolved if not revoked}
    return len(reached)


def _replaced(target: dict[str, Any], source: str, kept: str) -> dict[str, Any] | None:
    if target.get("kind") != "machines":
        return None
    ids = list(target.get("machine_ids") or [])
    if source not in ids:
        return None
    return {
        **target,
        "machine_ids": list(dict.fromkeys(kept if i == source else i for i in ids)),
    }


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A schedule aimed at the duplicate's record is aimed at the kept one:
    it is the same poste. The run history names postes as they were, and is
    left as it is."""
    source, kept = str(source_id), str(target_id)
    for schedule in (await session.exec(select(Schedule))).all():
        changed = False
        replaced = _replaced(schedule.target, source, kept)
        if replaced is not None:
            schedule.target = replaced
            changed = True
        if schedule.rings:
            rings = []
            for ring in schedule.rings:
                moved = _replaced(ring.get("target") or {}, source, kept)
                rings.append({**ring, "target": moved} if moved is not None else ring)
                changed = changed or moved is not None
            schedule.rings = rings
        if changed:
            session.add(schedule)
