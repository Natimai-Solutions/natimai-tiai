"""Who can own a maintenance, and whether they still can.

An owner is mailed the hostnames and rooms of what they own, and finds them
under « Mes tâches »: they must hold ``maintenance:read`` and
``maintenance:write``, and see the poste — for a room, the room; for the
parc's default owner, the whole parc (audit S18, T32).

The rule is asked in two places that must not disagree: when an owner is
chosen (the routes refuse one out of reach), and every time the owner of a
poste is resolved — rights are removed, a poste moves to another site, and
the account named months ago no longer qualifies. It then counts as no owner,
like a deactivated account, and the next level applies; nothing stored is
changed.

Resolving runs over the whole parc (the due list, the digest), so the rule is
answered from memory: the accounts' groups, permissions and scopes are read
once for all of them, and a scope is matched in Python against the poste's
site and room (``user.scope.machine_in_scope``) rather than by a query per
poste.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.machine.models import Machine
from app.features.room.models import Room
from app.features.user import crud as user_crud
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import (
    RoomPlace,
    Scope,
    machine_in_scope,
    room_in_scope,
    room_places,
)
from app.features.user.scope import union as scope_union


@dataclass(frozen=True)
class OwnerReach:
    """What each of a set of accounts can own. An account that was not asked
    about, or that holds neither permission, reaches nothing."""

    # Accounts holding maintenance:read and maintenance:write, with where
    # they may look (None: the whole parc).
    scopes: dict[uuid.UUID, Scope | None] = field(default_factory=dict)
    # Every room's place; empty when no account above is confined.
    places: dict[uuid.UUID, RoomPlace] = field(default_factory=dict)

    def parc(self, owner_id: uuid.UUID) -> bool:
        """The default owner's rule: any poste may fall to them."""
        return owner_id in self.scopes and self.scopes[owner_id] is None

    def room(self, owner_id: uuid.UUID, room_id: uuid.UUID) -> bool:
        """A room's owner sees the room — and so every poste filed in it."""
        if owner_id not in self.scopes:
            return False
        return room_in_scope(self.scopes[owner_id], room_id, self.places)

    def machine(self, owner_id: uuid.UUID, machine: Machine) -> bool:
        if owner_id not in self.scopes:
            return False
        return machine_in_scope(
            self.scopes[owner_id],
            location=machine.location,
            room_id=machine.room_id,
            places=self.places,
        )


async def owner_reach(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> OwnerReach:
    """The reach of ``user_ids``, from a fixed number of queries whatever
    their number: memberships, the groups' permissions, the groups' scopes,
    and — only when one of them is confined — the rooms."""
    ids = set(user_ids)
    if not ids:
        return OwnerReach()
    groups = await user_crud.groups_of_users(session, ids)
    group_ids = {g.id for memberships in groups.values() for g in memberships}
    permissions = await user_crud.permissions_of_groups(session, group_ids)
    group_scopes = await user_crud.scopes_of_groups(session, group_ids)

    scopes: dict[uuid.UUID, Scope | None] = {}
    for user_id, memberships in groups.items():
        held: set[str] = set()
        for group in memberships:
            held |= permissions.get(group.id, frozenset())
        if not all(
            has_permission(held, Resource.MAINTENANCE.value, action.value)
            for action in (Action.READ, Action.WRITE)
        ):
            continue
        # The administrators' group is unrestricted whatever rows it carries
        # (``scopes_of_groups``), and one unrestricted group lifts the rest.
        scopes[user_id] = scope_union(group_scopes[g.id] for g in memberships)
    confined = any(scope is not None for scope in scopes.values())
    return OwnerReach(
        scopes=scopes, places=await room_places(session) if confined else {}
    )


async def named_owner_ids(session: AsyncSession) -> set[uuid.UUID]:
    """Every account named owner of a poste or of a room."""
    on_machines = await session.exec(
        select(col(Machine.maintenance_owner_id))
        .where(col(Machine.maintenance_owner_id).is_not(None))
        .distinct()
    )
    on_rooms = await session.exec(
        select(col(Room.maintenance_owner_id))
        .where(col(Room.maintenance_owner_id).is_not(None))
        .distinct()
    )
    return {i for i in (*on_machines.all(), *on_rooms.all()) if i is not None}


__all__ = ["OwnerReach", "named_owner_ids", "owner_reach"]
