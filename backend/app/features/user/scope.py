"""Where an account may look: restricting groups to sites, buildings or rooms.

A group carries zero or more scope rows (``GroupScope``). **No row means the
whole parc** — the compatibility rule, and what every group created before
this module still is. An account's scope is the union of its groups':

* an administrator, or a member of *any* unrestricted group, sees everything
  (``None`` below);
* otherwise they see the machines matching at least one of their groups' rows.

The scope is per account, not per permission. A member of an unrestricted
read-only group and of a "Technicians — Taravao" group sees the whole parc and
can act on all of it as far as their permissions go: to confine somebody to a
site, every group they belong to must be restricted. That is the rule the
console states next to the scope editor, because it is the one a finer model
(scope per permission) would have to be explained against.

What a machine matching a row means (``machine_clause``):

* ``location``: the site the agent reports (``machines.location``) **or** the
  effective site of its room (``COALESCE(buildings.location, rooms.location)``).
  Either suffices: a poste whose GPO and room disagree shows on both sides,
  which is exactly when somebody needs to see it;
* ``building``: its room is in that building;
* ``room``: it is in that room.

An unknown or deleted building/room id matches nothing: a scope only ever
fails closed.
"""

import enum
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import false, func, or_
from sqlmodel import col, select

from app.features.machine.models import Machine
from app.features.room.models import Building, Room


class ScopeKind(enum.StrEnum):
    LOCATION = "location"
    BUILDING = "building"
    ROOM = "room"


@dataclass(frozen=True)
class Scope:
    """The places an account, or a group, is confined to. Never empty in
    practice: an empty scope is an unrestricted one, represented by ``None``
    wherever a scope is optional."""

    locations: frozenset[str] = field(default_factory=frozenset)
    buildings: frozenset[uuid.UUID] = field(default_factory=frozenset)
    rooms: frozenset[uuid.UUID] = field(default_factory=frozenset)

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[str, str]]) -> "Scope":
        """Build from ``(kind, value)`` pairs. A malformed id — which the API
        never writes — is dropped, so it matches nothing, like a deleted one."""
        locations: set[str] = set()
        buildings: set[uuid.UUID] = set()
        rooms: set[uuid.UUID] = set()
        for kind, value in rows:
            if kind == ScopeKind.LOCATION:
                locations.add(value)
                continue
            try:
                ident = uuid.UUID(value)
            except ValueError:
                continue
            if kind == ScopeKind.BUILDING:
                buildings.add(ident)
            elif kind == ScopeKind.ROOM:
                rooms.add(ident)
        return cls(frozenset(locations), frozenset(buildings), frozenset(rooms))

    def rows(self) -> list[tuple[str, str]]:
        """The ``(kind, value)`` pairs to store, in a stable order."""
        return [
            *((ScopeKind.LOCATION.value, v) for v in sorted(self.locations)),
            *((ScopeKind.BUILDING.value, str(v)) for v in sorted(self.buildings)),
            *((ScopeKind.ROOM.value, str(v)) for v in sorted(self.rooms)),
        ]

    def is_empty(self) -> bool:
        return not (self.locations or self.buildings or self.rooms)

    def __or__(self, other: "Scope") -> "Scope":
        return Scope(
            self.locations | other.locations,
            self.buildings | other.buildings,
            self.rooms | other.rooms,
        )

    def covers(self, other: "Scope") -> bool:
        """Whether every row of ``other`` is one of ours, kind by kind.

        Deliberately literal: a scope on a site does *not* cover a scope on one
        of its buildings here, although it covers its machines. What it guards
        is the escalation rule (``permissions.escalation``), where refusing a
        grant that would in fact have been harmless costs an administrator one
        click, and accepting one that was not would cost a site.
        """
        return (
            other.locations <= self.locations
            and other.buildings <= self.buildings
            and other.rooms <= self.rooms
        )


def union(scopes: Iterable[Scope | None]) -> Scope | None:
    """What several groups confine an account to together: ``None`` as soon
    as one of them is unrestricted. No group at all is no access whatsoever,
    which permissions already decide; it is returned as an empty scope so
    that it matches no machine rather than every machine."""
    out = Scope()
    for scope in scopes:
        if scope is None:
            return None
        out = out | scope
    return out


def wider(actor: Scope | None, target: Scope | None) -> bool:
    """Whether ``target`` reaches beyond ``actor`` — the scope half of the
    escalation rule: a confined account cannot hand out, nor lay hands on,
    anything less confined than itself."""
    if actor is None:
        return False
    if target is None:
        return True
    return not actor.covers(target)


def _room_ids_in(scope: Scope) -> Any:
    """``SELECT rooms.id`` of the rooms this scope covers."""
    site = func.coalesce(col(Building.location), col(Room.location))
    conditions: list[Any] = []
    if scope.locations:
        conditions.append(site.in_(sorted(scope.locations)))
    if scope.buildings:
        conditions.append(col(Room.building_id).in_(sorted(scope.buildings)))
    if scope.rooms:
        conditions.append(col(Room.id).in_(sorted(scope.rooms)))
    # ``correlate(None)``: these subqueries land in statements that already
    # join ``rooms``, ``buildings`` or ``machines`` (the machine list does all
    # three), and SQLAlchemy's auto-correlation would otherwise strip those
    # tables from the subquery's FROM and bind it to the outer row — silently
    # turning "machines whose room is in scope" into something else.
    return (
        select(col(Room.id))
        .outerjoin(Building, col(Building.id) == col(Room.building_id))
        .where(or_(*conditions) if conditions else false())
        .correlate(None)
    )


def machine_clause(scope: Scope | None) -> Any:
    """The ``WHERE`` predicate on ``machines`` for an account's scope, or
    ``None`` when there is nothing to restrict. Subqueries rather than joins,
    so it drops into any statement that already selects from ``machines``
    without disturbing its own joins."""
    if scope is None:
        return None
    conditions: list[Any] = []
    if scope.locations:
        conditions.append(col(Machine.location).in_(sorted(scope.locations)))
    if not scope.is_empty():
        conditions.append(col(Machine.room_id).in_(_room_ids_in(scope)))
    return or_(*conditions) if conditions else false()


def room_clause(scope: Scope | None) -> Any:
    """The predicate on ``rooms`` for the rooms an account may see, or None."""
    if scope is None:
        return None
    return col(Room.id).in_(_room_ids_in(scope))


def building_clause(scope: Scope | None) -> Any:
    """The predicate on ``buildings``: a building on an allowed site, allowed
    itself, or holding an allowed room (so a room's building can be named)."""
    if scope is None:
        return None
    conditions: list[Any] = []
    if scope.locations:
        conditions.append(col(Building.location).in_(sorted(scope.locations)))
    if scope.buildings:
        conditions.append(col(Building.id).in_(sorted(scope.buildings)))
    if scope.rooms:
        conditions.append(
            col(Building.id).in_(
                select(col(Room.building_id))
                .where(col(Room.id).in_(sorted(scope.rooms)))
                .correlate(None)
            )
        )
    return or_(*conditions) if conditions else false()


def machine_ids_clause(scope: Scope | None, machine_id_column: Any) -> Any:
    """The predicate for a table hanging off ``machines`` (threats, commands,
    checks…): its ``machine_id`` is one of the machines in scope."""
    clause = machine_clause(scope)
    if clause is None:
        return None
    return machine_id_column.in_(select(col(Machine.id)).where(clause).correlate(None))


def restrict(stmt: Any, clause: Any) -> Any:
    """``stmt.where(clause)`` unless there is nothing to restrict."""
    return stmt if clause is None else stmt.where(clause)


async def machine_visible(session: Any, machine_id: Any, scope: Scope | None) -> bool:
    """Whether ``machine_id`` is in ``scope`` — for the routes that fetched the
    machine by id and must answer 404 when it is out of reach. Always true
    for an unrestricted account, without a query."""
    clause = machine_clause(scope)
    if clause is None:
        return True
    found = await session.exec(
        select(col(Machine.id)).where(col(Machine.id) == machine_id).where(clause)
    )
    return found.first() is not None
