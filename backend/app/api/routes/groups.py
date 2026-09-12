"""Groups: named permission sets an administrator composes in the console.

Reading and writing groups goes with the ``user`` resource — who may do what
is account management — so the same permission opens both pages.

The three built-in groups (``BuiltinGroup``) cannot be deleted; the
administrators' permissions cannot be edited because they are implicit.
Every other edit is subject to the same lock-out guard as the accounts:
a change that would leave no active account with ``user:write`` is refused.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.routes.users import reject_lockout
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.user import crud
from app.features.user.models import Group
from app.features.user.permissions import (
    ALL_PERMISSIONS,
    PERMISSION_CATALOGUE,
    Action,
    Resource,
)

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
    member_count: int
    created_at: datetime
    updated_at: datetime


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = []


class GroupUpdate(BaseModel):
    """Partial update — only the supplied fields are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None


async def _require_group(session: SessionDep, group_id: uuid.UUID) -> Group:
    group = await crud.get_group(session, group_id)
    if group is None:
        raise AppError(
            code=ErrorCode.GROUP_NOT_FOUND, status_code=404, message="Group not found"
        )
    return group


async def _reject_name_taken(
    session: SessionDep, name: str, *, exclude: uuid.UUID | None = None
) -> None:
    existing = await crud.get_group_by_name(session, name)
    if existing is not None and existing.id != exclude:
        raise AppError(
            code=ErrorCode.GROUP_NAME_TAKEN,
            status_code=409,
            message="A group with this name already exists",
        )


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


async def _out(session: SessionDep, groups: list[Group]) -> list[GroupOut]:
    ids = [g.id for g in groups]
    permissions = await crud.permissions_of_groups(session, ids)
    counts = await crud.member_counts(session, ids)
    return [
        GroupOut(
            id=g.id,
            name=g.name,
            description=g.description,
            builtin_key=g.builtin_key,
            is_admin=crud.is_admin_group(g),
            permissions=sorted(permissions.get(g.id, frozenset())),
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
    payload: GroupCreate, session: SessionDep, current: CurrentUser
) -> GroupOut:
    await _reject_name_taken(session, payload.name)
    permissions = _validate_permissions(payload.permissions)
    group = Group(name=payload.name, description=payload.description)
    session.add(group)
    await session.flush()
    await crud.set_group_permissions(session, group, permissions)
    audit.record(
        session,
        actor=current.email,
        action="group.create",
        resource_type="group",
        resource_id=str(group.id),
        details={"name": group.name, "permissions": sorted(permissions)},
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
) -> GroupOut:
    group = await _require_group(session, group_id)
    fields = payload.model_dump(exclude_unset=True)

    if "permissions" in fields and crud.is_admin_group(group):
        raise AppError(
            code=ErrorCode.GROUP_BUILTIN_PROTECTED,
            status_code=400,
            message="The administrators' permissions are implicit and cannot be edited",
        )
    if "name" in fields and fields["name"] != group.name:
        await _reject_name_taken(session, fields["name"], exclude=group.id)

    permissions = (
        _validate_permissions(fields.pop("permissions"))
        if "permissions" in fields
        else None
    )
    for name, value in fields.items():
        setattr(group, name, value)
    group.updated_at = utcnow()
    session.add(group)
    if permissions is not None:
        await crud.set_group_permissions(session, group, permissions)
    audit.record(
        session,
        actor=current.email,
        action="group.update",
        resource_type="group",
        resource_id=str(group.id),
        details={
            "name": group.name,
            "fields": sorted(fields),
            **({"permissions": sorted(permissions)} if permissions is not None else {}),
        },
    )
    await reject_lockout(session)
    await session.commit()
    await session.refresh(group)
    return await _one(session, group)


@router.delete("/{group_id}", status_code=204, dependencies=[_WRITE])
async def delete_group(
    group_id: uuid.UUID, session: SessionDep, current: CurrentUser
) -> None:
    """Delete a composed group; its members simply lose what it granted."""
    group = await _require_group(session, group_id)
    if group.builtin_key is not None:
        raise AppError(
            code=ErrorCode.GROUP_BUILTIN_PROTECTED,
            status_code=400,
            message="Built-in groups cannot be deleted",
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
