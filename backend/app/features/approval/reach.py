"""Who can approve (C10, §2.2).

An approver holds the rights the action asks for — ``command:execute`` and
``risky_command:execute``, plus ``schedule:write`` for a schedule — and sees
every poste of the request (for a schedule: sees the schedule, the rule of
the schedules' routes). Read for every active account in a fixed number of
queries, on the model of ``maintenance.reach``: memberships, the groups'
permissions and scopes, then the postes' places matched in Python.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.machine.models import Machine
from app.features.schedule import crud as schedule_crud
from app.features.schedule.models import Schedule
from app.features.user import crud as user_crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource, permission_key
from app.features.user.scope import Scope, machine_in_scope, room_places
from app.features.user.scope import union as scope_union

# What approving any request asks for.
BASE_PERMISSIONS = frozenset(
    {
        permission_key(Resource.COMMAND, Action.EXECUTE),
        permission_key(Resource.RISKY_COMMAND, Action.EXECUTE),
    }
)


@dataclass(frozen=True)
class Holder:
    """An active account, what it holds and where it may look."""

    user: User
    permissions: frozenset[str]
    scope: Scope | None


async def _holders(
    session: AsyncSession, needed: Iterable[str], *, exclude: uuid.UUID | None = None
) -> list[Holder]:
    """The active accounts holding every permission of ``needed``, by
    e-mail address."""
    wanted = frozenset(needed)
    users = list(
        (
            await session.exec(
                select(User)
                .where(col(User.is_active).is_(True))
                .order_by(col(User.email))
            )
        ).all()
    )
    users = [u for u in users if u.id != exclude]
    if not users:
        return []
    groups = await user_crud.groups_of_users(session, [u.id for u in users])
    group_ids = {g.id for memberships in groups.values() for g in memberships}
    permissions = await user_crud.permissions_of_groups(session, group_ids)
    scopes = await user_crud.scopes_of_groups(session, group_ids)
    out: list[Holder] = []
    for user in users:
        memberships = groups.get(user.id, [])
        if not memberships:
            continue
        held: frozenset[str] = frozenset().union(
            *(permissions.get(g.id, frozenset()) for g in memberships)
        )
        if not wanted <= held:
            continue
        out.append(
            Holder(
                user=user,
                permissions=held,
                scope=scope_union(scopes[g.id] for g in memberships),
            )
        )
    return out


async def eligible_count(session: AsyncSession) -> int:
    """How many active accounts could approve a command at risk — places not
    considered: what turning approval on asks for at least two of."""
    return len(await _holders(session, BASE_PERMISSIONS))


def needed_for(kind: str) -> frozenset[str]:
    if kind == "schedule":
        return BASE_PERMISSIONS | {permission_key(Resource.SCHEDULE, Action.WRITE)}
    return BASE_PERMISSIONS


async def command_approvers(
    session: AsyncSession,
    machine_ids: Iterable[uuid.UUID],
    *,
    author_id: uuid.UUID | None,
    limit: int | None = None,
) -> list[User]:
    """The other accounts that could approve a command on ``machine_ids``:
    the rights, and every one of these postes in their scope."""
    holders = await _holders(session, BASE_PERMISSIONS, exclude=author_id)
    ids = list(set(machine_ids))
    confined = [h for h in holders if h.scope is not None]
    machines: list[tuple[str | None, uuid.UUID | None]] = []
    places = {}
    if confined and ids:
        machines = list(
            (
                await session.exec(
                    select(Machine.location, Machine.room_id).where(
                        col(Machine.id).in_(ids)
                    )
                )
            ).all()
        )
        places = await room_places(session)
    out: list[User] = []
    for holder in holders:
        if holder.scope is not None and not all(
            machine_in_scope(
                holder.scope, location=location, room_id=room_id, places=places
            )
            for location, room_id in machines
        ):
            continue
        out.append(holder.user)
        if limit is not None and len(out) >= limit:
            break
    return out


async def schedule_approvers(
    session: AsyncSession,
    schedule: Schedule,
    *,
    author_id: uuid.UUID | None,
    limit: int | None = None,
) -> list[User]:
    """The other accounts that could approve ``schedule``: the rights its
    run needs, and the sight of it (``schedule_crud.visible_to``)."""
    from app.features.schedule import runner

    holders = await _holders(
        session,
        set(runner.required_permissions(schedule)) | needed_for("schedule"),
        exclude=author_id,
    )
    out: list[User] = []
    for holder in holders:
        if not await schedule_crud.visible_to(
            session, schedule, holder.scope, holder.user.id
        ):
            continue
        out.append(holder.user)
        if limit is not None and len(out) >= limit:
            break
    return out
