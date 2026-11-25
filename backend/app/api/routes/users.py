"""Console user management: list, create, update, delete, admin password reset.

Every route requires the ``user`` resource permission, which the built-in
administrators hold and any group may be granted
(app.features.user.permissions).

Two guards keep the console manageable. A caller may not delete, deactivate
or change the groups of **their own** account. And no change may leave the
console without an active account able to manage accounts (``user:write``):
the last one standing cannot be deactivated or deleted, from here or by way
of a group edit (``routes/groups.py``).

A third keeps ``user:write`` from being administrator in disguise: an account
only grants, and only reaches, what it holds itself (``reject_escalation``).
A non-administrator cannot put an account in a group granting more than they
have, nor in the administrators' group, and cannot edit, deactivate, delete
or reset the password of an account holding more than they do — the reset
being the shortest path of all, since it hands the new password back.
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentAuthority, CurrentUser, SessionDep, require_permission
from app.api.fields import Email, Password, bounded_name, not_null
from app.core import security
from app.core.errors import AppError, ErrorCode, violated_constraint
from app.features.api_token import crud as api_tokens
from app.features.audit import crud as audit
from app.features.auth_session import crud as auth_sessions
from app.features.base import utcnow
from app.features.user import crud, second_factor
from app.features.user.models import FULL_NAME_MAX_LENGTH, EmailPreference, User
from app.features.user.permissions import (
    Action,
    Authority,
    Resource,
    escalation,
    permission_key,
)

security_log = logging.getLogger("app.security")

async def _not_own_account_by_token(request: Request, current: CurrentUser) -> None:
    """A personal API token never acts on its own account (C8): not through
    « Mon compte », and not through the accounts page either — its email,
    password, second factor, groups or deactivation."""
    if getattr(request.state, "api_token", None) is None:
        return
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    raw = request.path_params.get("user_id")
    try:
        target = uuid.UUID(str(raw))
    except ValueError:
        return
    if target == current.id:
        raise AppError(
            code=ErrorCode.API_TOKEN_FORBIDDEN_HERE,
            status_code=403,
            message="An API token cannot act on the account itself",
        )


router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[
        Depends(require_permission(Resource.USER, Action.READ)),
        Depends(_not_own_account_by_token),
    ],
)

_WRITE = Depends(require_permission(Resource.USER, Action.WRITE))

USER_WRITE = permission_key(Resource.USER, Action.WRITE)


class GroupRef(BaseModel):
    """A group as a user row names it."""

    id: uuid.UUID
    name: str
    # A built-in group's stable key (``admin``, ``readonly``, ``technician``):
    # the console names such a group in its reader's language while its name
    # is still the one the installation gave it.
    builtin_key: str | None = None

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
    # Set while the account is locked after failed logins — the later of
    # the quick lock and the slow one; resetting its password lifts both.
    locked_until: datetime | None
    # A second factor is active on the account (C7).
    second_factor_enabled: bool = False
    # ``local`` or ``oidc`` (signs in through the directory), and whether a
    # local account is linked to a directory identity.
    auth_source: str = "local"
    directory_linked: bool = False
    created_at: datetime
    updated_at: datetime


class UserList(BaseModel):
    """Paginated user list."""

    items: list[UserOut]
    total: int
    page: int
    page_size: int


# Trimmed, not blank, within its column (``User.full_name``).
FullName = Annotated[str | None, bounded_name(FULL_NAME_MAX_LENGTH)]


class UserCreate(BaseModel):
    """New account. The password is set by the admin and sent out of band.

    No groups is a valid account: it can log in and see nothing, which is
    what an account created ahead of its assignment should be.
    """

    email: Email
    password: Password
    full_name: FullName = None
    group_ids: list[uuid.UUID] = []


class UserUpdate(BaseModel):
    """Partial update — only the supplied fields are changed."""

    email: Email | None = None
    full_name: FullName = None
    group_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None
    email_preference: EmailPreference | None = None

    _not_null = not_null("email", "is_active", "email_preference", "group_ids")


class PasswordReset(BaseModel):
    """Admin-driven reset. Omit ``password`` to have one generated."""

    password: Password | None = None


class PasswordResetOut(BaseModel):
    """The new password, returned once so the admin can pass it on."""

    password: str


async def _require_user(
    session: SessionDep, user_id: uuid.UUID, *, for_write: bool = False
) -> User:
    """Fetch a user or raise the stable not-found error.

    ``for_write`` locks the row until the transaction ends: an edit and a
    deletion of one account at the same instant are answered one after the
    other. Unlocked, the edit read the row, the deletion committed, and the
    edit's write matched nothing — a 500 where the answer is « not found »,
    or the edit then the deletion.

    FOR NO KEY UPDATE, as ``crud.lock_account``: it still orders two writes
    of the account, and lets a login of that account insert its session —
    whose foreign key takes KEY SHARE on this row. A plain FOR UPDATE made
    an administrator's reset and a successful login of the same account
    deadlock (verification of 2026-11-18).
    """
    user = await session.get(
        User, user_id, with_for_update={"key_share": True} if for_write else None
    )
    if user is None:
        raise AppError(
            code=ErrorCode.USER_NOT_FOUND, status_code=404, message="User not found"
        )
    return user


def _email_taken() -> AppError:
    return AppError(
        code=ErrorCode.USER_EMAIL_TAKEN,
        status_code=409,
        message="This email is already in use",
    )


async def _reject_email_taken(
    session: SessionDep, email: str, *, exclude: uuid.UUID | None = None
) -> None:
    """Raise if ``email`` already belongs to another account."""
    existing = await crud.get_by_email(session, email)
    if existing is not None and existing.id != exclude:
        raise _email_taken()


# The index that says « this address has an account already » when two
# requests race past ``_reject_email_taken`` together.
_EMAIL_INDEX = "ix_users_email_lower"


async def _email_race(session: SessionDep, exc: IntegrityError) -> AppError | None:
    """The 409 a lost race on an address deserves, after rolling the
    transaction back; None (nothing rolled back) for any other failure."""
    if violated_constraint(exc) != _EMAIL_INDEX:
        return None
    await session.rollback()
    return _email_taken()


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


def _reject_external(user: User) -> None:
    """An account of the directory has no password here to set (C7)."""
    if user.auth_source != "local":
        raise AppError(
            code=ErrorCode.USER_EXTERNAL_ACCOUNT,
            status_code=409,
            message="This account signs in through the directory",
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


def reject_escalation(
    actor: Authority, target: Authority, *, actor_email: str, action: str
) -> None:
    """Refuse when ``target`` grants more than the actor holds.

    ``action`` names what was attempted, for the log and the console: ``grant``
    (handing out a group or a permission), ``edit``, ``delete``,
    ``reset_password``. Shared with the groups routes.
    """
    found = escalation(actor, target)
    if found is None:
        return
    # Someone with account management trying to reach past it is the event a
    # security review wants to find without reading the audit log end to end.
    security_log.warning(
        "privilege escalation refused: %s tried to %s beyond their rights "
        "(missing %s%s%s)",
        actor_email,
        action,
        ", ".join(sorted(found.missing)) or "nothing",
        ", administrators' group" if found.admin else "",
        ", places outside their scope" if found.wider_scope else "",
    )
    raise AppError(
        code=ErrorCode.AUTH_PERMISSION_ESCALATION,
        status_code=403,
        message="You cannot grant or reach rights you do not hold yourself",
        details={
            "action": action,
            "missing": sorted(found.missing),
            "admin": found.admin,
            "wider_scope": found.wider_scope,
        },
    )


async def reject_lockout(session: SessionDep) -> None:
    """Refuse the pending change if it leaves nobody able to manage accounts.

    Called after the change is flushed and before it is committed, so the
    count reflects the state the commit would produce; the error rolls the
    transaction back. Shared with the groups routes, whose edits can have the
    same effect one step removed.
    """
    await session.flush()
    # Serialised: two last administrators deactivating each other at the same
    # instant would each count the other as still active — neither change is
    # committed yet — and the console would be left with none. Under this
    # lock, held to the end of the transaction, the second one counts after
    # the first has committed (READ COMMITTED: the count below is a fresh
    # snapshot), and is refused.
    await crud.lock_account_management(session)
    # Counted among the console's own accounts (C7): one signing in through
    # the directory is shut out with it when the directory cannot be reached.
    if await crud.users_holding(session, USER_WRITE, local_only=True) == 0:
        raise AppError(
            code=ErrorCode.USER_LOCKOUT,
            status_code=409,
            message="This would leave no active local account able to manage accounts",
        )


def _locked_until(user: User) -> datetime | None:
    """When the account's locks end: the later of the two. The slow one
    (audit T06) outlives a successful login, which clears the other."""
    ends = [end for end in (user.locked_until, user.slow_locked_until) if end]
    return max(ends) if ends else None


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
            locked_until=_locked_until(u),
            second_factor_enabled=second_factor.enabled(u),
            auth_source=u.auth_source,
            directory_linked=u.oidc_subject is not None,
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
    payload: UserCreate,
    session: SessionDep,
    current: CurrentUser,
    authority: CurrentAuthority,
) -> UserOut:
    """Create an account with an admin-chosen password."""
    await _reject_email_taken(session, payload.email)
    await _require_groups_exist(session, payload.group_ids)
    reject_escalation(
        authority,
        await crud.groups_authority(session, payload.group_ids),
        actor_email=current.email,
        action="grant",
    )
    # Read before the commit inside ``create_user`` expires the caller's row:
    # touching it afterwards would lazy-load from an async session, which
    # cannot be done outside an await.
    actor = current.email
    try:
        user = await crud.create_user(
            session,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            groups=payload.group_ids,
        )
    except IntegrityError as exc:
        # Another request created the same address since the check above.
        if (taken := await _email_race(session, exc)) is not None:
            raise taken from None
        raise
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
    authority: CurrentAuthority,
) -> UserOut:
    """Update an account's email, name, groups, activation or e-mail cadence.

    Deactivating an account ends its sessions in the same transaction: a
    deactivation is how an operator who has left is shut out, and it must not
    wait for anything to expire.
    """
    user = await _require_user(session, user_id, for_write=True)
    fields = payload.model_dump(exclude_unset=True)

    reject_escalation(
        authority,
        await crud.user_authority(session, user.id),
        actor_email=current.email,
        action="edit",
    )
    deactivating = "is_active" in fields and not fields["is_active"]
    if deactivating:
        _reject_self(current, user, "deactivate")
    if "group_ids" in fields:
        _reject_self(current, user, "change the groups of")
        await _require_groups_exist(session, fields["group_ids"])
        reject_escalation(
            authority,
            await crud.groups_authority(session, fields["group_ids"]),
            actor_email=current.email,
            action="grant",
        )
    email_changed = "email" in fields and fields["email"] != user.email
    previous_email = user.email
    if email_changed:
        # The address of an account of the directory is the directory's (C7).
        _reject_external(user)
        await _reject_email_taken(session, fields["email"], exclude=user.id)
        # A link mailed to the old address must not outlive it: the address
        # is often changed because the old box is no longer its owner's
        # (audit S15).
        await crud.purge_reset_tokens(session, user.id)

    group_ids = fields.pop("group_ids", None)
    for name, value in fields.items():
        # The str enum is the vocabulary of a plain string column: stored as
        # its value so a read never has to know the enum existed.
        stored = value.value if isinstance(value, EmailPreference) else value
        setattr(user, name, stored)
    user.updated_at = utcnow()
    session.add(user)
    if email_changed:
        try:
            await session.flush()
        except IntegrityError as exc:
            # Another account took this address since the check above.
            if (taken := await _email_race(session, exc)) is not None:
                raise taken from None
            raise
    if group_ids is not None:
        await crud.set_user_groups(session, user, group_ids)
        # A group now requiring a second factor the account lacks: its open
        # sessions become enrolment sessions at once (C7).
        await second_factor.enforce_on_members(session, [user.id])
    if deactivating:
        await auth_sessions.revoke_all(session, user.id)
        await api_tokens.revoke_all(session, user.id)
    audit.record(
        session,
        actor=current.email,
        action="user.update",
        resource_type="user",
        resource_id=str(user.id),
        details={
            "email": user.email,
            "fields": sorted(fields),
            **({"previous_email": previous_email} if email_changed else {}),
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
    user_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    authority: CurrentAuthority,
) -> None:
    """Delete an account for good (prefer deactivation to keep the trail).

    Its sessions go with it — ``ON DELETE CASCADE`` — and with them any access
    still open on it, at the next request.
    """
    user = await _require_user(session, user_id, for_write=True)
    _reject_self(current, user, "delete")
    reject_escalation(
        authority,
        await crud.user_authority(session, user.id),
        actor_email=current.email,
        action="delete",
    )
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


@router.post("/{user_id}/reset-second-factor", status_code=204, dependencies=[_WRITE])
async def reset_second_factor(
    user_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    authority: CurrentAuthority,
) -> None:
    """Remove an account's second factor and backup codes (C7): its phone
    is lost and its codes with it. Every session of the account ends; it
    enrols again at its next login if a group requires it.

    Refused on an account holding more than the caller, and on one's own:
    lifting a second factor is the first half of a takeover.
    """
    user = await _require_user(session, user_id, for_write=True)
    _reject_self(current, user, "reset the second factor of")
    reject_escalation(
        authority,
        await crud.user_authority(session, user.id),
        actor_email=current.email,
        action="reset_second_factor",
    )
    await second_factor.clear(session, user)
    await auth_sessions.revoke_all(session, user.id)
    # A lost or stolen second factor: the account's scripts too (C8).
    await api_tokens.revoke_all(session, user.id)
    audit.record(
        session,
        actor=current.email,
        action="user.second_factor_reset",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email},
    )
    await session.commit()


@router.post(
    "/{user_id}/reset-password", response_model=PasswordResetOut, dependencies=[_WRITE]
)
async def reset_password(
    user_id: uuid.UUID,
    payload: PasswordReset,
    session: SessionDep,
    current: CurrentUser,
    authority: CurrentAuthority,
) -> PasswordResetOut:
    """Set a new password for an account and return it once.

    Resetting logs the account out everywhere: every session is revoked, and
    any pending "forgot password" link is dropped.

    Refused on an account holding more than the caller (``reject_escalation``):
    the answer carries the new password, so a reset is a takeover. Audited for
    the same reason — the trace says who did it and to whom. Never the password
    itself: only whether it was generated or typed by the administrator.
    """
    user = await _require_user(session, user_id, for_write=True)
    _reject_external(user)
    reject_escalation(
        authority,
        await crud.user_authority(session, user.id),
        actor_email=current.email,
        action="reset_password",
    )
    password = payload.password or security.generate_password()
    await crud.set_password(session, user, password)
    # Reset by an administrator — a compromised account: its tokens end (C8).
    await api_tokens.revoke_all(session, user.id)
    await crud.purge_reset_tokens(session, user.id)
    audit.record(
        session,
        actor=current.email,
        action="user.reset_password",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "generated": payload.password is None},
    )
    await session.commit()
    return PasswordResetOut(password=password)
