"""Console user management: list, create, update, delete, admin password reset.

Every route requires the ``user`` resource permission, which the built-in
administrators hold and any group may be granted
(app.features.user.permissions).

Two guards keep the console manageable. A caller may not delete, deactivate
or change the groups of **their own** account. And no change may leave the
console without an active account able to manage accounts (``user:write``):
the last one standing cannot be deactivated or deleted, from here or by way
of a group edit (``routes/groups.py``).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.fields import Email, Password
from app.core import security
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.user import crud
from app.features.user.models import EmailPreference, User
from app.features.user.permissions import Action, Resource, permission_key

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_permission(Resource.USER, Action.READ))],
)

_WRITE = Depends(require_permission(Resource.USER, Action.WRITE))

USER_WRITE = permission_key(Resource.USER, Action.WRITE)


class GroupRef(BaseModel):
    """A group as a user row names it."""

    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    """A console account as shown in the users list."""

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    # Visible to an administrator because "who gets told when a poste catches
    # something" is a property of the parc's supervision, not a private setting:
    # an account left on « aucun e-mail » is how a fleet ends up unwatched.
    email_preference: str
    groups: list[GroupRef]
    created_at: datetime
    updated_at: datetime


class UserList(BaseModel):
    """Paginated user list."""

    items: list[UserOut]
    total: int
    page: int
    page_size: int


class UserCreate(BaseModel):
    """New account. The password is set by the admin and sent out of band.

    No groups is a valid account: it can log in and see nothing, which is
    what an account created ahead of its assignment should be.
    """

    email: Email
    password: Password
    full_name: str | None = None
    group_ids: list[uuid.UUID] = []


class UserUpdate(BaseModel):
    """Partial update — only the supplied fields are changed."""

    email: Email | None = None
    full_name: str | None = None
    group_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None
    email_preference: EmailPreference | None = None


class PasswordReset(BaseModel):
    """Admin-driven reset. Omit ``password`` to have one generated."""

    password: Password | None = None


class PasswordResetOut(BaseModel):
    """The new password, returned once so the admin can pass it on."""

    password: str


async def _require_user(session: SessionDep, user_id: uuid.UUID) -> User:
    """Fetch a user or raise the stable not-found error."""
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(
            code=ErrorCode.USER_NOT_FOUND, status_code=404, message="User not found"
        )
    return user


async def _reject_email_taken(
    session: SessionDep, email: str, *, exclude: uuid.UUID | None = None
) -> None:
    """Raise if ``email`` already belongs to another account."""
    existing = await crud.get_by_email(session, email)
    if existing is not None and existing.id != exclude:
        raise AppError(
            code=ErrorCode.USER_EMAIL_TAKEN,
            status_code=409,
            message="This email is already in use",
        )


async def _require_groups_exist(
    session: SessionDep, group_ids: list[uuid.UUID]
) -> None:
    for gid in set(group_ids):
        if await crud.get_group(session, gid) is None:
            raise AppError(
                code=ErrorCode.GROUP_NOT_FOUND,
                status_code=404,
                message="Group not found",
                details={"group_id": str(gid)},
            )


def _reject_self(current: User, target: User, action: str) -> None:
    """Refuse an operation an admin would apply to their own account."""
    if current.id == target.id:
        raise AppError(
            code=ErrorCode.USER_SELF_FORBIDDEN,
            status_code=400,
            message=f"You cannot {action} your own account",
            details={"action": action},
        )


async def reject_lockout(session: SessionDep) -> None:
    """Refuse the pending change if it leaves nobody able to manage accounts.

    Called after the change is flushed and before it is committed, so the
    count reflects the state the commit would produce; the error rolls the
    transaction back. Shared with the groups routes, whose edits can have the
    same effect one step removed.
    """
    await session.flush()
    if await crud.users_holding(session, USER_WRITE) == 0:
        raise AppError(
            code=ErrorCode.USER_LOCKOUT,
            status_code=409,
            message="This would leave no active account able to manage accounts",
        )


async def _out(session: SessionDep, users: list[User]) -> list[UserOut]:
    groups = await crud.groups_of_users(session, [u.id for u in users])
    return [
        UserOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            email_preference=u.email_preference,
            groups=[GroupRef.model_validate(g) for g in groups[u.id]],
            created_at=u.created_at,
            updated_at=u.updated_at,
        )
        for u in users
    ]


async def _one(session: SessionDep, user: User) -> UserOut:
    return (await _out(session, [user]))[0]


@router.get("", response_model=UserList)
async def list_users(
    session: SessionDep,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> UserList:
    """List console accounts, optionally filtered on email or full name."""
    users, total = await crud.list_users(
        session, search=search, page=page, page_size=page_size
    )
    return UserList(
        items=await _out(session, users), total=total, page=page, page_size=page_size
    )


@router.post("", response_model=UserOut, status_code=201, dependencies=[_WRITE])
async def create_user(
    payload: UserCreate, session: SessionDep, current: CurrentUser
) -> UserOut:
    """Create an account with an admin-chosen password."""
    await _reject_email_taken(session, payload.email)
    await _require_groups_exist(session, payload.group_ids)
    # Read before the commit inside ``create_user`` expires the caller's row:
    # touching it afterwards would lazy-load from an async session, which
    # cannot be done outside an await.
    actor = current.email
    user = await crud.create_user(
        session,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        groups=payload.group_ids,
    )
    audit.record(
        session,
        actor=actor,
        action="user.create",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "group_ids": [str(g) for g in payload.group_ids]},
    )
    await session.commit()
    await session.refresh(user)
    return await _one(session, user)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, session: SessionDep) -> UserOut:
    """Fetch a single account."""
    return await _one(session, await _require_user(session, user_id))


@router.patch("/{user_id}", response_model=UserOut, dependencies=[_WRITE])
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    session: SessionDep,
    current: CurrentUser,
) -> UserOut:
    """Update an account's email, name, groups, activation or e-mail cadence."""
    user = await _require_user(session, user_id)
    fields = payload.model_dump(exclude_unset=True)

    if "is_active" in fields and not fields["is_active"]:
        _reject_self(current, user, "deactivate")
    if "group_ids" in fields:
        _reject_self(current, user, "change the groups of")
        await _require_groups_exist(session, fields["group_ids"])
    if "email" in fields and fields["email"] != user.email:
        await _reject_email_taken(session, fields["email"], exclude=user.id)

    group_ids = fields.pop("group_ids", None)
    for name, value in fields.items():
        # The str enum is the vocabulary of a plain string column: stored as
        # its value so a read never has to know the enum existed.
        stored = value.value if isinstance(value, EmailPreference) else value
        setattr(user, name, stored)
    user.updated_at = utcnow()
    session.add(user)
    if group_ids is not None:
        await crud.set_user_groups(session, user, group_ids)
    audit.record(
        session,
        actor=current.email,
        action="user.update",
        resource_type="user",
        resource_id=str(user.id),
        details={
            "email": user.email,
            "fields": sorted(fields),
            **(
                {"group_ids": [str(g) for g in group_ids]}
                if group_ids is not None
                else {}
            ),
        },
    )
    await reject_lockout(session)
    await session.commit()
    await session.refresh(user)
    return await _one(session, user)


@router.delete("/{user_id}", status_code=204, dependencies=[_WRITE])
async def delete_user(
    user_id: uuid.UUID, session: SessionDep, current: CurrentUser
) -> None:
    """Delete an account for good (prefer deactivation to keep the trail)."""
    user = await _require_user(session, user_id)
    _reject_self(current, user, "delete")
    audit.record(
        session,
        actor=current.email,
        action="user.delete",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email},
    )
    await crud.delete_user(session, user)
    await reject_lockout(session)
    await session.commit()


@router.post(
    "/{user_id}/reset-password", response_model=PasswordResetOut, dependencies=[_WRITE]
)
async def reset_password(
    user_id: uuid.UUID, payload: PasswordReset, session: SessionDep
) -> PasswordResetOut:
    """Set a new password for an account and return it once.

    Resetting logs the account out everywhere: tokens issued before now stop
    being accepted, and any pending "forgot password" link is dropped.
    """
    user = await _require_user(session, user_id)
    password = payload.password or security.generate_password()
    await crud.set_password(session, user, password)
    await crud.purge_reset_tokens(session, user.id)
    await session.commit()
    return PasswordResetOut(password=password)
