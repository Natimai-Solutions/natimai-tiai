"""What a command is aimed at, resolved into postes within a scope.

One definition for the two paths that queue commands: the console's
``POST /commands``, resolved at once, and a schedule's run, resolved when it
comes due on behalf of its author (``features.schedule``). Stored with the
schedule as JSON (``as_json`` / ``from_json``).
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.machine.status import MachineStatus, status_clause
from app.features.room.models import Building, Room
from app.features.setting import crud as setting_crud
from app.features.user.scope import (
    Scope,
    building_clause,
    machine_clause,
    restrict,
    room_clause,
)

KINDS = ("machines", "all", "domain", "location", "status", "room", "building")


@dataclass(frozen=True)
class Target:
    """Exactly one of: a list of postes, the whole parc, a domain, a site, a
    status, a room, a building."""

    kind: str
    machine_ids: tuple[uuid.UUID, ...] = field(default=())
    value: str | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.kind == "machines":
            out["machine_ids"] = [str(m) for m in self.machine_ids]
        elif self.kind != "all":
            out["value"] = self.value
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Target":
        kind = str(data.get("kind"))
        if kind == "machines":
            return cls(
                kind,
                machine_ids=tuple(uuid.UUID(m) for m in data.get("machine_ids") or []),
            )
        if kind == "all":
            return cls(kind)
        return cls(kind, value=data.get("value"))

    @property
    def room_id(self) -> uuid.UUID | None:
        return uuid.UUID(self.value) if self.kind == "room" and self.value else None

    @property
    def building_id(self) -> uuid.UUID | None:
        return uuid.UUID(self.value) if self.kind == "building" and self.value else None

    def audit(self) -> dict[str, Any] | None:
        """What the audit line of a request on this target says it aimed at,
        or None for one poste (traced by its command row)."""
        if self.kind == "machines":
            distinct = len(set(self.machine_ids))
            return (
                {"target": "machines", "requested": distinct} if distinct > 1 else None
            )
        if self.kind == "all":
            return {"target": "all"}
        return {"target": self.kind, self.kind: self.value}


async def place_visible(
    session: AsyncSession, target: Target, scope: Scope | None
) -> bool:
    """Whether the room or building a target names exists and is within
    ``scope`` — always true for the other kinds."""
    if target.room_id is not None:
        stmt = restrict(
            select(Room.id).where(col(Room.id) == target.room_id), room_clause(scope)
        )
        return (await session.exec(stmt)).first() is not None
    if target.building_id is not None:
        stmt = restrict(
            select(Building.id).where(col(Building.id) == target.building_id),
            building_clause(scope),
        )
        return (await session.exec(stmt)).first() is not None
    return True


async def resolve(
    session: AsyncSession, target: Target, scope: Scope | None
) -> list[tuple[uuid.UUID, bool]]:
    """The postes the target names now, within ``scope`` — « the whole parc »
    from an account confined to a site is that site, and a listed poste out
    of it is dropped like an unknown id — each with whether its token is
    revoked."""
    stmt = restrict(select(Machine.id, Machine.token_revoked), machine_clause(scope))
    if target.kind == "machines":
        stmt = stmt.where(col(Machine.id).in_(list(target.machine_ids)))
    elif target.kind == "domain":
        stmt = stmt.where(col(Machine.domain) == target.value)
    elif target.kind == "location":
        stmt = stmt.where(col(Machine.location) == target.value)
    elif target.kind == "status":
        fleet = await setting_crud.fleet_policy(session)
        stmt = stmt.where(
            status_clause(
                MachineStatus(target.value or ""),
                utcnow(),
                fleet.inactive_after_days,
                fleet.signature_max_age_days,
            )
        )
    elif target.kind == "room":
        stmt = stmt.where(col(Machine.room_id) == target.room_id)
    elif target.kind == "building":
        stmt = stmt.where(
            col(Machine.room_id).in_(
                select(Room.id).where(col(Room.building_id) == target.building_id)
            )
        )
    # « all »: no predicate.
    rows = await session.exec(stmt)
    return [(machine_id, revoked) for machine_id, revoked in rows.all()]
