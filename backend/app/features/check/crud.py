"""Verification requests: the open one of a poste, the list of a person."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.check.models import MachineCheck
from app.features.machine.models import Machine
from app.features.user import crud as user_crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import RoomPlace, Scope, machine_in_scope, room_places
from app.features.user.scope import union as scope_union

# --- Who can take a check -----------------------------------------------------
#
# An assignee is mailed the poste's name and the instructions, and finds the
# request under « Mes tâches »: they must be active, read and close checks
# (check:read, check:write — closing is what doing the task means), and see
# the poste (audit S18). Asked when a check is given (the routes refuse an
# account out of reach) and every time an assigned check is read — rights are
# removed, a poste moves to another site, an account is deactivated: the
# assignee named then no longer qualifies, and the check counts as nobody's,
# in the lists, the badge and the mails alike, without anything stored being
# changed. The same rule as the maintenance owners (``maintenance.reach``).


@dataclass(frozen=True)
class AssigneeReach:
    """What each of a set of accounts can take. An account not asked about,
    deactivated, or short of either permission reaches nothing."""

    # Accounts that may take checks, with where they look (None: everywhere).
    scopes: dict[uuid.UUID, Scope | None] = field(default_factory=dict)
    # Every room's place; empty when no account above is confined.
    places: dict[uuid.UUID, RoomPlace] = field(default_factory=dict)

    def machine(
        self, user_id: uuid.UUID, location: str | None, room_id: uuid.UUID | None
    ) -> bool:
        if user_id not in self.scopes:
            return False
        return machine_in_scope(
            self.scopes[user_id], location=location, room_id=room_id, places=self.places
        )


async def assignee_reach(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> AssigneeReach:
    """The reach of ``user_ids``, from a fixed number of queries whatever
    their number: the active ones, memberships, the groups' permissions and
    scopes, and — only when one of them is confined — the rooms."""
    ids = set(user_ids)
    if not ids:
        return AssigneeReach()
    active = set(
        (
            await session.exec(
                select(User.id).where(
                    col(User.id).in_(ids), col(User.is_active).is_(True)
                )
            )
        ).all()
    )
    groups = await user_crud.groups_of_users(session, active)
    group_ids = {g.id for memberships in groups.values() for g in memberships}
    permissions = await user_crud.permissions_of_groups(session, group_ids)
    group_scopes = await user_crud.scopes_of_groups(session, group_ids)
    scopes: dict[uuid.UUID, Scope | None] = {}
    for user_id, memberships in groups.items():
        held: set[str] = set()
        for group in memberships:
            held |= permissions.get(group.id, frozenset())
        if not all(
            has_permission(held, Resource.CHECK.value, action.value)
            for action in (Action.READ, Action.WRITE)
        ):
            continue
        # The administrators' group is unrestricted (``scopes_of_groups``),
        # and one unrestricted group lifts the others.
        scopes[user_id] = scope_union(group_scopes[g.id] for g in memberships)
    confined = any(scope is not None for scope in scopes.values())
    return AssigneeReach(
        scopes=scopes, places=await room_places(session) if confined else {}
    )


async def orphaned_open_checks(
    session: AsyncSession,
    assignee_id: uuid.UUID | None = None,
    check_ids: Iterable[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """The open checks whose assignee no longer reaches the poste — all of
    them, ``assignee_id``'s, or those among ``check_ids``. One per poste at
    most is open, so this reads at most a parc's worth of small rows."""
    stmt = (
        select(
            col(MachineCheck.id),
            col(MachineCheck.assigned_to_id),
            col(Machine.location),
            col(Machine.room_id),
        )
        .join(Machine, col(Machine.id) == col(MachineCheck.machine_id))
        .where(
            col(MachineCheck.closed_at).is_(None),
            col(MachineCheck.assigned_to_id).is_not(None),
        )
    )
    if assignee_id is not None:
        stmt = stmt.where(col(MachineCheck.assigned_to_id) == assignee_id)
    if check_ids is not None:
        wanted = set(check_ids)
        if not wanted:
            return set()
        stmt = stmt.where(col(MachineCheck.id).in_(wanted))
    rows = list((await session.exec(stmt)).all())
    reach = await assignee_reach(session, {r[1] for r in rows if r[1] is not None})
    return {
        check_id
        for check_id, user_id, location, room_id in rows
        if user_id is None or not reach.machine(user_id, location, room_id)
    }


async def open_for_machine(
    session: AsyncSession, machine_id: uuid.UUID
) -> MachineCheck | None:
    result = await session.exec(
        select(MachineCheck).where(
            col(MachineCheck.machine_id) == machine_id,
            col(MachineCheck.closed_at).is_(None),
        )
    )
    return result.one_or_none()


async def get(session: AsyncSession, check_id: uuid.UUID) -> MachineCheck | None:
    return await session.get(MachineCheck, check_id)


async def list_checks(
    session: AsyncSession,
    *,
    open_only: bool,
    assigned_to_id: uuid.UUID | None,
    unassigned: bool,
    machine_id: uuid.UUID | None,
    page: int,
    page_size: int,
    where: Any = None,
) -> tuple[list[MachineCheck], int]:
    """Open first, oldest open first (the one waiting longest is the one to
    do), then closed newest first."""
    stmt = select(MachineCheck)
    if where is not None:
        # The caller's scope (``user/scope.py``), as a predicate on the rows.
        stmt = stmt.where(where)
    if open_only:
        stmt = stmt.where(col(MachineCheck.closed_at).is_(None))
    if assigned_to_id is not None:
        # An open request its assignee can no longer take (``assignee_reach``)
        # is not theirs any more: out of their list and of their badge.
        orphans = await orphaned_open_checks(session, assigned_to_id)
        stmt = stmt.where(col(MachineCheck.assigned_to_id) == assigned_to_id)
        if orphans:
            stmt = stmt.where(col(MachineCheck.id).not_in(orphans))
    if unassigned:
        # A request given to an account deactivated since is nobody's either:
        # it must show under « À prendre » (audit B08) — and so is an open one
        # whose assignee lost the rights or the sight of the poste.
        orphans = await orphaned_open_checks(session)
        stmt = stmt.where(
            or_(
                col(MachineCheck.assigned_to_id).is_(None),
                col(MachineCheck.assigned_to_id).in_(
                    select(User.id).where(col(User.is_active).is_(False))
                ),
                col(MachineCheck.id).in_(orphans),
            )
        )
    if machine_id is not None:
        stmt = stmt.where(col(MachineCheck.machine_id) == machine_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.exec(
        stmt.order_by(
            col(MachineCheck.closed_at).is_not(None),
            col(MachineCheck.closed_at).desc().nulls_last(),
            col(MachineCheck.created_at),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.all()), total or 0


# The note the server writes on a request closed by a merge, and its code: the
# console words the code in the reader's language (plan console bilingue), the
# French staying in ``closing_note`` for an older console.
CLOSED_BY_MERGE = "check.closed.merged"
CLOSED_BY_MERGE_NOTE = "Fermée par la fusion du poste dans un autre."


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge: the source's requests follow it onto the kept record. If both
    carry an open one, the source's is closed as superseded rather than
    violating "one open per poste" — the kept record's is the one somebody
    is already looking at. Does not commit."""
    if await open_for_machine(session, target_id) is not None:
        source_open = await open_for_machine(session, source_id)
        if source_open is not None:
            source_open.closed_at = utcnow()
            source_open.closed_by = "system"
            source_open.closing_note = CLOSED_BY_MERGE_NOTE
            source_open.closing_note_code = CLOSED_BY_MERGE
            source_open.updated_at = utcnow()
            session.add(source_open)
            await session.flush()
    await session.exec(
        update(MachineCheck)
        .where(col(MachineCheck.machine_id) == source_id)
        .values(machine_id=target_id)
    )
