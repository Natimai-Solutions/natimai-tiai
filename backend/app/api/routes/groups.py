"""Groups: named permission sets an administrator composes in the console.

Reading and writing groups goes with the ``user`` resource — who may do what
is account management — so the same permission opens both pages.

The three built-in groups (``BuiltinGroup``) cannot be deleted; the
administrators' permissions cannot be edited because they are implicit.
Every other edit is subject to the same lock-out guard as the accounts:
a change that would leave no active account with ``user:write`` is refused.

And to the same rule against escalation (``users.reject_escalation``): a
non-administrator composes groups out of the permissions they hold, and
nothing else. A group already granting more than they hold — the
administrators' first of all — is out of their reach: they can neither edit
nor delete it, since either would change what more powerful accounts may do.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import CurrentAuthority, CurrentUser, SessionDep, require_permission
from app.api.fields import bounded_name, not_null
from app.api.routes.users import reject_escalation, reject_lockout
from app.core.errors import AppError, ErrorCode, violated_constraint
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.room import crud as room_crud
from app.features.room.models import Building, Room
from app.features.user import crud
from app.features.user.models import GROUP_NAME_MAX_LENGTH, Group
from app.features.user.permissions import (
    ALL_PERMISSIONS,
    PERMISSION_CATALOGUE,
    Action,
    Authority,
    Resource,
)
from app.features.user.scope import Scope

router = APIRouter(
    prefix="/groups",
    tags=["groups"],
    dependencies=[Depends(require_permission(Resource.USER, Action.READ))],
)

_WRITE = Depends(require_permission(Resource.USER, Action.WRITE))


class PermissionOut(BaseModel):
    """One entry of the catalogue, for the console's grid."""

    key: str
    resource: str
    action: str


class GroupOut(BaseModel):
    """A group with what it grants and how many accounts hold it."""

    id: uuid.UUID
    name: str
    description: str | None
    # Set on the three groups every installation has; null on a composed one.
    builtin_key: str | None
    # True on the administrators' group alone: its permissions are the whole
    # catalogue, shown but not editable.
    is_admin: bool
    permissions: list[str]
    # Where the group is confined (``user/scope.py``); null for the whole parc.
    scope: "ScopeBody | None"
    # The same places in words, for the reader of the groups page — who may
    # not hold room:read, and would otherwise see bare ids. Sites, then
    # buildings, then rooms; empty for the whole parc.
    scope_labels: list["ScopeLabel"] = []
    # Its members log in with a second factor (C7).
    mfa_required: bool = False
    # The directory groups (Entra object ids) whose members get this group
    # when they sign in through the directory (C7).
    idp_groups: list[str] = []
    member_count: int
    created_at: datetime
    updated_at: datetime


class ScopeBody(BaseModel):
    """The places a group is confined to. All three lists empty — or the
    field null — is the whole parc."""

    locations: list[str] = Field(default=[], max_length=200)
    buildings: list[uuid.UUID] = Field(default=[], max_length=200)
    rooms: list[uuid.UUID] = Field(default=[], max_length=500)

    def to_scope(self) -> Scope | None:
        scope = Scope(
            frozenset(v.strip() for v in self.locations if v.strip()),
            frozenset(self.buildings),
            frozenset(self.rooms),
        )
        return None if scope.is_empty() else scope

    @classmethod
    def of(cls, scope: Scope | None) -> "ScopeBody | None":
        if scope is None:
            return None
        return cls(
            locations=sorted(scope.locations),
            buildings=sorted(scope.buildings),
            rooms=sorted(scope.rooms),
        )


class ScopeLabel(BaseModel):
    """One place of a group's scope, named.

    ``id`` is the stored value — the site's name, a building's or a room's id.
    ``label`` reads « A101 — Bâtiment A » for a room in a building, the
    building's name (« — site » when it has one), the site's name. ``exists``
    is false for a building or room deleted since, and for a site no poste,
    building or room carries any more: such a place matches nothing, and the
    page says so instead of printing an id nobody can place.
    """

    kind: Literal["site", "building", "room"]
    id: str
    label: str
    exists: bool


GroupOut.model_rebuild()


async def _scope_labels(
    session: SessionDep, scopes: dict[uuid.UUID, Scope | None]
) -> dict[uuid.UUID, list[ScopeLabel]]:
    """Every group's scope in words, in four queries whatever the number of
    groups: the buildings, the rooms (with theirs), the sites still in use."""
    sites = {v for sc in scopes.values() if sc is not None for v in sc.locations}
    building_ids = {v for sc in scopes.values() if sc is not None for v in sc.buildings}
    room_ids = {v for sc in scopes.values() if sc is not None for v in sc.rooms}

    buildings: dict[uuid.UUID, Building] = {}
    if building_ids:
        found = await session.exec(
            select(Building).where(col(Building.id).in_(building_ids))
        )
        buildings = {b.id: b for b in found.all()}
    rooms = await room_crud.placements(session, room_ids)
    used_sites: set[str] = set()
    if sites:
        for column in (Machine.location, Building.location, Room.location):
            found_sites = await session.exec(
                select(col(column)).where(col(column).in_(sites)).distinct()
            )
            used_sites |= {v for v in found_sites.all() if v is not None}

    def order(item: ScopeLabel) -> tuple[bool, str]:
        # Named ones first, alphabetically; the vanished after them.
        return (not item.exists, item.label.lower())

    def building_label(building: Building) -> str:
        if building.location:
            return f"{building.name} — {building.location}"
        return building.name

    out: dict[uuid.UUID, list[ScopeLabel]] = {}
    for group_id, scope in scopes.items():
        if scope is None:
            out[group_id] = []
            continue
        labels = [
            ScopeLabel(kind="site", id=v, label=v, exists=v in used_sites)
            for v in sorted(scope.locations)
        ]
        found_buildings = [
            ScopeLabel(
                kind="building",
                id=str(b),
                label=building_label(buildings[b]) if b in buildings else str(b),
                exists=b in buildings,
            )
            for b in scope.buildings
        ]
        found_rooms: list[ScopeLabel] = []
        for r in scope.rooms:
            placement = rooms.get(r)
            room = placement.room if placement is not None else None
            if room is None:
                found_rooms.append(
                    ScopeLabel(kind="room", id=str(r), label=str(r), exists=False)
                )
                continue
            building = placement.building if placement is not None else None
            label = f"{room.name} — {building.name}" if building else room.name
            found_rooms.append(
                ScopeLabel(kind="room", id=str(r), label=label, exists=True)
            )
        out[group_id] = (
            labels + sorted(found_buildings, key=order) + sorted(found_rooms, key=order)
        )
    return out


# Trimmed, not blank, within its column; unique whatever its capitalisation
# (``_reject_name_taken``, and the index behind it).
GroupName = Annotated[str, bounded_name(GROUP_NAME_MAX_LENGTH)]


# Directory groups one Tia'i group stands for, at most.
MAX_IDP_GROUPS = 50
# An Entra object id, or another provider's group name: letters, digits and
# a few separators — never a space nor anything a query would read.
IdpGroupId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$",
    ),
]


class GroupCreate(BaseModel):
    name: GroupName
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = []
    scope: ScopeBody | None = None
    mfa_required: bool = False
    idp_groups: list[IdpGroupId] = Field(default=[], max_length=MAX_IDP_GROUPS)


class GroupUpdate(BaseModel):
    """Partial update — only the supplied fields are changed. ``scope: null``
    lifts the restriction; leaving the field out keeps it."""

    name: Annotated[str | None, bounded_name(GROUP_NAME_MAX_LENGTH)] = None
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None
    scope: ScopeBody | None = None
    mfa_required: bool | None = None
    idp_groups: list[IdpGroupId] | None = Field(default=None, max_length=MAX_IDP_GROUPS)

    _not_null = not_null("name", "permissions", "mfa_required", "idp_groups")


async def _require_group(session: SessionDep, group_id: uuid.UUID) -> Group:
    group = await crud.get_group(session, group_id)
    if group is None:
        raise AppError(
            code=ErrorCode.GROUP_NOT_FOUND, status_code=404, message="Group not found"
        )
    return group


def _name_taken() -> AppError:
    return AppError(
        code=ErrorCode.GROUP_NAME_TAKEN,
        status_code=409,
        message="A group with this name already exists",
    )


async def _reject_name_taken(
    session: SessionDep, name: str, *, exclude: uuid.UUID | None = None
) -> None:
    """Raise if another group bears ``name``, whatever its capitalisation."""
    existing = await crud.get_group_by_name(session, name)
    if existing is not None and existing.id != exclude:
        raise _name_taken()


# The constraints that refuse a second group of a name: the migrated
# database's plain one, and the case-insensitive index.
_NAME_CONSTRAINTS = frozenset({"groups_name_key", "ix_groups_name_lower"})


async def _flush_name(session: SessionDep) -> None:
    """Write the pending group now, turning a name taken by a concurrent
    request since ``_reject_name_taken`` into its 409 rather than a 500."""
    try:
        await session.flush()
    except IntegrityError as exc:
        if violated_constraint(exc) not in _NAME_CONSTRAINTS:
            raise
        await session.rollback()
        raise _name_taken() from None


def _validate_permissions(permissions: list[str]) -> set[str]:
    unknown = sorted(set(permissions) - ALL_PERMISSIONS)
    if unknown:
        raise AppError(
            code=ErrorCode.GROUP_PERMISSION_UNKNOWN,
            status_code=422,
            message="Unknown permission",
            details={"permissions": unknown},
        )
    return set(permissions)


async def _validate_scope(session: SessionDep, body: ScopeBody | None) -> Scope | None:
    """The scope to store, refusing a building or room that does not exist —
    a typo would otherwise confine a group to nothing, silently."""
    scope = body.to_scope() if body is not None else None
    if scope is None:
        return None
    unknown = [
        str(b)
        for b in sorted(scope.buildings)
        if await room_crud.get_building(session, b) is None
    ] + [
        str(r)
        for r in sorted(scope.rooms)
        if await room_crud.get_room(session, r) is None
    ]
    if unknown:
        raise AppError(
            code=ErrorCode.GROUP_SCOPE_UNKNOWN,
            status_code=422,
            message="Unknown building or room in scope",
            details={"ids": unknown},
        )
    return scope


async def _out(session: SessionDep, groups: list[Group]) -> list[GroupOut]:
    ids = [g.id for g in groups]
    permissions = await crud.permissions_of_groups(session, ids)
    scopes = await crud.scopes_of_groups(session, ids)
    idp_links = await crud.idp_links_of_groups(session, ids)
    counts = await crud.member_counts(session, ids)
    labels = await _scope_labels(session, scopes)
    return [
        GroupOut(
            id=g.id,
            name=g.name,
            description=g.description,
            builtin_key=g.builtin_key,
            is_admin=crud.is_admin_group(g),
            permissions=sorted(permissions.get(g.id, frozenset())),
            scope=ScopeBody.of(scopes.get(g.id)),
            scope_labels=labels.get(g.id, []),
            mfa_required=g.mfa_required,
            idp_groups=sorted(idp_links.get(g.id, set())),
            member_count=counts.get(g.id, 0),
            created_at=g.created_at,
            updated_at=g.updated_at,
        )
        for g in groups
    ]


async def _one(session: SessionDep, group: Group) -> GroupOut:
    return (await _out(session, [group]))[0]


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions() -> list[PermissionOut]:
    """The catalogue: every permission a group may be granted, in grid order.

    Declared before ``/{group_id}`` so the path is not read as an id.
    """
    return [
        PermissionOut(key=f"{r}:{a}", resource=r.value, action=a.value)
        for r, a in PERMISSION_CATALOGUE
    ]


@router.get("", response_model=list[GroupOut])
async def list_groups(session: SessionDep) -> list[GroupOut]:
    """Every group, built-in ones first. Not paginated: a console has a
    handful, not a directory's worth."""
    return await _out(session, await crud.list_groups(session))


@router.post("", response_model=GroupOut, status_code=201, dependencies=[_WRITE])
async def create_group(
    payload: GroupCreate,
    session: SessionDep,
    current: CurrentUser,
    authority: CurrentAuthority,
) -> GroupOut:
    await _reject_name_taken(session, payload.name)
    permissions = _validate_permissions(payload.permissions)
    scope = await _validate_scope(session, payload.scope)
    reject_escalation(
        authority,
        Authority(is_admin=False, permissions=frozenset(permissions), scope=scope),
        actor_email=current.email,
        action="grant",
    )
    group = Group(
        name=payload.name,
        description=payload.description,
        mfa_required=payload.mfa_required,
    )
    session.add(group)
    await _flush_name(session)
    await crud.set_group_permissions(session, group, permissions)
    await crud.set_group_scope(session, group, scope)
    await crud.set_group_idp_links(session, group, payload.idp_groups)
    audit.record(
        session,
        actor=current.email,
        action="group.create",
        resource_type="group",
        resource_id=str(group.id),
        details={
            "name": group.name,
            "permissions": sorted(permissions),
            **({"scope": scope.rows()} if scope is not None else {}),
            **({"mfa_required": True} if group.mfa_required else {}),
            **(
                {"idp_groups": sorted(set(payload.idp_groups))}
                if payload.idp_groups
                else {}
            ),
        },
    )
    await session.commit()
    await session.refresh(group)
    return await _one(session, group)


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: uuid.UUID, session: SessionDep) -> GroupOut:
    return await _one(session, await _require_group(session, group_id))


@router.patch("/{group_id}", response_model=GroupOut, dependencies=[_WRITE])
async def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdate,
    session: SessionDep,
    current: CurrentUser,
    authority: CurrentAuthority,
) -> GroupOut:
    group = await _require_group(session, group_id)
    fields = payload.model_dump(exclude_unset=True)

    reject_escalation(
        authority,
        await crud.groups_authority(session, [group.id]),
        actor_email=current.email,
        action="edit",
    )
    if "permissions" in fields and crud.is_admin_group(group):
        raise AppError(
            code=ErrorCode.GROUP_BUILTIN_PROTECTED,
            status_code=400,
            message="The administrators' permissions are implicit and cannot be edited",
        )
    renamed = "name" in fields and fields["name"] != group.name
    if renamed:
        await _reject_name_taken(session, fields["name"], exclude=group.id)

    permissions = (
        _validate_permissions(fields.pop("permissions"))
        if "permissions" in fields
        else None
    )
    scope_changed = "scope" in fields
    if scope_changed and crud.is_admin_group(group):
        raise AppError(
            code=ErrorCode.GROUP_BUILTIN_PROTECTED,
            status_code=400,
            message="The administrators' group sees the whole parc",
        )
    fields.pop("scope", None)
    scope = await _validate_scope(session, payload.scope) if scope_changed else None
    # Linking directory groups hands the group to their members (C7): a
    # grant, as much as adding them one by one.
    idp_groups = fields.pop("idp_groups", None)
    if idp_groups is not None:
        reject_escalation(
            authority,
            await crud.groups_authority(session, [group.id]),
            actor_email=current.email,
            action="grant",
        )
    if permissions is not None or scope_changed:
        current_scope = (await crud.scopes_of_groups(session, [group.id]))[group.id]
        reject_escalation(
            authority,
            Authority(
                is_admin=False,
                permissions=(
                    frozenset(permissions)
                    if permissions is not None
                    else await crud.group_permissions(session, group)
                ),
                scope=scope if scope_changed else current_scope,
            ),
            actor_email=current.email,
            action="grant",
        )
        # A member's reach is the union of all its groups: one unrestricted
        # group elsewhere and the permissions given here apply to the whole
        # parc. So the caller must reach every member, as PATCH /users
        # requires (audit S05).
        if not authority.is_admin:
            for member_id in await crud.group_member_ids(session, group.id):
                reject_escalation(
                    authority,
                    await crud.user_authority(session, member_id),
                    actor_email=current.email,
                    action="edit_members",
                )
    for name, value in fields.items():
        setattr(group, name, value)
    group.updated_at = utcnow()
    session.add(group)
    if renamed:
        await _flush_name(session)
    if permissions is not None:
        await crud.set_group_permissions(session, group, permissions)
    if scope_changed:
        await crud.set_group_scope(session, group, scope)
    if idp_groups is not None:
        await crud.set_group_idp_links(session, group, idp_groups)
    audit.record(
        session,
        actor=current.email,
        action="group.update",
        resource_type="group",
        resource_id=str(group.id),
        details={
            "name": group.name,
            "fields": sorted(fields),
            **(
                {"mfa_required": group.mfa_required} if "mfa_required" in fields else {}
            ),
            **(
                {"idp_groups": sorted(set(idp_groups))}
                if idp_groups is not None
                else {}
            ),
            **({"permissions": sorted(permissions)} if permissions is not None else {}),
            **(
                {"scope": scope.rows() if scope is not None else None}
                if scope_changed
                else {}
            ),
        },
    )
    await reject_lockout(session)
    await session.commit()
    await session.refresh(group)
    return await _one(session, group)


@router.delete("/{group_id}", status_code=204, dependencies=[_WRITE])
async def delete_group(
    group_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    authority: CurrentAuthority,
) -> None:
    """Delete a composed group; its members simply lose what it granted."""
    group = await _require_group(session, group_id)
    if group.builtin_key is not None:
        raise AppError(
            code=ErrorCode.GROUP_BUILTIN_PROTECTED,
            status_code=400,
            message="Built-in groups cannot be deleted",
        )
    reject_escalation(
        authority,
        await crud.groups_authority(session, [group.id]),
        actor_email=current.email,
        action="delete",
    )
    audit.record(
        session,
        actor=current.email,
        action="group.delete",
        resource_type="group",
        resource_id=str(group.id),
        details={"name": group.name},
    )
    await session.delete(group)
    await reject_lockout(session)
    await session.commit()
