import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import case, delete, func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ratelimit, security
from app.core.config import settings
from app.features.auth_session import crud as auth_sessions
from app.features.base import contains, utcnow
from app.features.user.models import (
    Group,
    GroupPermission,
    GroupScope,
    PasswordResetToken,
    User,
    UserGroup,
    normalize_email,
)
from app.features.user.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_GROUP_DEFAULTS,
    Authority,
    BuiltinGroup,
)
from app.features.user.scope import Scope
from app.features.user.scope import union as scope_union


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    """Fetch a user by email, whatever its capitalisation.

    Compared on ``lower(email)``, the expression the unique index is built on,
    so the lookup is an index scan and agrees with what the index refuses.
    """
    result = await session.exec(
        select(User).where(func.lower(User.email) == normalize_email(email))
    )
    return result.one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
    groups: Sequence[uuid.UUID | BuiltinGroup] = (BuiltinGroup.READONLY,),
) -> User:
    """Create a user with a hashed password, member of ``groups``.

    A group given by its built-in key is created on the spot if the table does
    not hold it yet — the tests build their schema without running the
    migration that seeds the three, and the first admin is seeded the same way.
    """
    user = User(
        email=normalize_email(email),
        hashed_password=await security.hash_password(password),
        full_name=full_name,
    )
    session.add(user)
    await session.flush()
    group_ids: list[uuid.UUID] = []
    for ref in groups:
        if isinstance(ref, BuiltinGroup):
            group_ids.append((await builtin_group(session, ref)).id)
        else:
            group_ids.append(ref)
    await set_user_groups(session, user, group_ids)
    await session.commit()
    await session.refresh(user)
    return user


class AccountLockedError(Exception):
    """The account is locked after too many failed logins."""

    def __init__(self, user: User, locked_until: datetime, *, just_locked: bool):
        super().__init__(f"account locked until {locked_until.isoformat()}")
        self.user = user
        self.locked_until = locked_until
        # True on the failure that tripped the lock: the one worth auditing.
        self.just_locked = just_locked


async def authenticate(
    session: AsyncSession, email: str, password: str, ip: str = ""
) -> User | None:
    """Return the user if credentials are valid and the account is active.

    Every path costs one bcrypt check, the refusals included: an unknown or
    deactivated account is checked against a dummy hash, so how long the answer
    takes says nothing about which addresses have an account.

    LOGIN_MAX_FAILED_ATTEMPTS failures, from wherever, each within
    LOGIN_LOCKOUT_MINUTES of the previous one, lock the account for
    LOGIN_LOCKOUT_MINUTES. The lock shuts out the addresses that failed on it
    recently, not the account (audit S03): the right password from another
    address still opens it, so failing on purpose keeps nobody out. Unless
    the guessing comes from many addresses (``FailureMemory.besieged``): the
    lock then shuts out every address but those that opened the account
    recently, so spreading the guesses buys no more of them. Raises
    ``AccountLockedError`` on the failure that locks it (to audit) and on an
    attempt refused by the lock (to log); the route answers both like any
    failure (audit S12). The counter moves in the database, so concurrent
    failures all count (audit S13). Nothing is committed — the caller does.
    """
    user = await get_by_email(session, email)
    if user is None or not user.is_active:
        await security.burn_password_check_async(password)
        return None
    now = utcnow()
    account = str(user.id)
    failures = ratelimit.login_failures
    if (
        user.locked_until is not None
        and user.locked_until > now
        and (
            failures.failed_recently(account, ip)
            or (failures.besieged(account) and not failures.known(account, ip))
        )
    ):
        await security.burn_password_check_async(password)
        raise AccountLockedError(user, user.locked_until, just_locked=False)
    if not await security.check_password(password, user.hashed_password):
        until = await record_failure(session, user, ip)
        if until is not None:
            raise AccountLockedError(user, until, just_locked=True)
        return None
    failures.forget(account, ip)
    failures.succeeded(account, ip)
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.last_failed_login_at = None
        user.locked_until = None
        session.add(user)
    return user


async def record_failure(session: AsyncSession, user: User, ip: str) -> datetime | None:
    """Count a wrong password for ``user`` from ``ip``, in the database so
    that concurrent failures all count (audit S13). Returns the end of the
    lock when this failure set it — of concurrent ones past the threshold,
    exactly one does. A failure more than LOGIN_LOCKOUT_MINUTES after the
    previous one counts as the first: old failures do not add up. Does not
    commit."""
    ratelimit.login_failures.note(str(user.id), ip)
    now = utcnow()
    stale = now - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    last = col(User.last_failed_login_at)
    failures = (
        await session.exec(
            update(User)
            .where(col(User.id) == user.id)
            .values(
                failed_login_attempts=case(
                    (or_(last.is_(None), last < stale), 1),
                    else_=col(User.failed_login_attempts) + 1,
                ),
                last_failed_login_at=now,
            )
            .returning(col(User.failed_login_attempts))
        )
    ).scalar_one()
    if failures < settings.LOGIN_MAX_FAILED_ATTEMPTS:
        return None
    until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    locked = (
        await session.exec(
            update(User)
            .where(
                col(User.id) == user.id,
                col(User.failed_login_attempts) >= settings.LOGIN_MAX_FAILED_ATTEMPTS,
            )
            .values(failed_login_attempts=0, locked_until=until)
            .returning(col(User.id))
        )
    ).first()
    return until if locked is not None else None


# --- Console user management ------------------------------------------------


async def list_users(
    session: AsyncSession,
    *,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[User], int]:
    """List users (optionally filtered on email/full name), newest first."""
    stmt = select(User)
    if search:
        stmt = stmt.where(
            or_(
                contains(col(User.email), search), contains(col(User.full_name), search)
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # ``email`` behind the date: accounts seeded together share a creation
    # instant, and the list is paginated server-side — ties reordered between
    # two pages would show one account twice and another not at all.
    rows = await session.exec(
        stmt.order_by(col(User.created_at).desc(), col(User.email))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.all()), total or 0


async def set_password(session: AsyncSession, user: User, password: str) -> None:
    """Hash and store a new password, ending every session of the account.

    Whoever changes a password — the user, a reset link, an administrator —
    does it because the old one may be known to someone else, who may well be
    logged in with it: all of the account's sessions are revoked, the caller's
    own included. Does not commit — the caller decides the transaction boundary.
    """
    user.hashed_password = await security.hash_password(password)
    user.password_changed_at = utcnow()
    user.updated_at = utcnow()
    # A new password is also the way out of a lockout: the administrator who
    # resets it, or the owner who redeems a reset link, proved more than a guess.
    user.failed_login_attempts = 0
    user.locked_until = None
    ratelimit.login_failures.forget(str(user.id))
    session.add(user)
    await auth_sessions.revoke_all(session, user.id)


async def delete_user(session: AsyncSession, user: User) -> None:
    """Delete a user; the database takes their pending reset tokens with them.

    The tokens used to be deleted explicitly here, because the ``ON DELETE
    CASCADE`` existed in the migration and not in the schema SQLModel builds for
    the tests — so leaning on it would have behaved differently in each. The
    model now declares it too, which makes the constraint the single statement of
    the rule instead of one of two.
    """
    await session.delete(user)


# --- Password reset tokens --------------------------------------------------


# A link mailed less than this long ago is left alone: a second request,
# from whoever, neither voids it nor sends another mail (audit S14).
RESET_REQUEST_COOLDOWN = timedelta(minutes=5)
# Links alive at once for one account. A request never voids a link still
# valid — the one its owner may be opening — so the requests of whoever
# knows the address are capped here instead (audit S14, T34).
RESET_LIVE_LINKS_MAX = 3


async def reset_request_allowed(session: AsyncSession, user: User) -> bool:
    """Whether a new link may be issued and mailed to ``user`` now: none
    issued within the cooldown, fewer than ``RESET_LIVE_LINKS_MAX`` still
    usable.

    Locks the account's row first, for the rest of the transaction: two
    requests for one account at the same instant are answered one after the
    other, the second seeing the link the first issued — the check and the
    insert are not atomic otherwise (audit T34). The caller ends the
    transaction (a commit, or the session closing) to release it.
    """
    await session.exec(select(User.id).where(col(User.id) == user.id).with_for_update())
    now = utcnow()
    found = await session.exec(
        select(PasswordResetToken.created_at)
        .where(col(PasswordResetToken.user_id) == user.id)
        .where(col(PasswordResetToken.used_at).is_(None))
        .where(col(PasswordResetToken.expires_at) > now)
    )
    live = list(found.all())
    if len(live) >= RESET_LIVE_LINKS_MAX:
        return False
    return all(created <= now - RESET_REQUEST_COOLDOWN for created in live)


async def create_reset_token(session: AsyncSession, user: User) -> str:
    """Issue a single-use reset token, returning the clear value (mailed once).

    The links still valid are kept: a request — anyone may make one — must
    not void the link the account's owner is about to open (audit S14). The
    spent ones (used, expired) are dropped. Redeeming any link voids the
    others (``consume_reset_token``). The route calls
    ``reset_request_allowed`` first.
    """
    await session.exec(
        delete(PasswordResetToken)
        .where(col(PasswordResetToken.user_id) == user.id)
        .where(
            or_(
                col(PasswordResetToken.used_at).is_not(None),
                col(PasswordResetToken.expires_at) <= utcnow(),
            )
        )
    )
    token = security.generate_token()
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=security.hash_token(token),
            expires_at=utcnow()
            + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        )
    )
    return token


async def consume_reset_token(session: AsyncSession, token: str) -> User | None:
    """Validate a reset token and return its user, marking the token used.

    Returns None when the token is unknown, already used, expired, or belongs to
    a deactivated account. Does not commit.
    """
    result = await session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == security.hash_token(token)
        )
    )
    row = result.one_or_none()
    if row is None or row.used_at is not None:
        return None
    if row.expires_at < utcnow():
        return None

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None

    row.used_at = utcnow()
    session.add(row)
    # The other links of the account die with this one: the password they
    # would reset has just been chosen.
    await session.exec(
        delete(PasswordResetToken)
        .where(col(PasswordResetToken.user_id) == user.id)
        .where(col(PasswordResetToken.id) != row.id)
    )
    return user


async def purge_reset_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Drop every reset token of a user (called after a password change)."""
    await session.exec(
        delete(PasswordResetToken).where(col(PasswordResetToken.user_id) == user_id)
    )


# --- Groups and permissions -------------------------------------------------


async def builtin_group(session: AsyncSession, key: BuiltinGroup) -> Group:
    """The built-in group for ``key``, created with its defaults if missing.

    Does not commit. Idempotent, so the seed script can call it at every start
    and a migrated database is left as it is.
    """
    result = await session.exec(select(Group).where(Group.builtin_key == key.value))
    group = result.one_or_none()
    if group is not None:
        return group
    name, description, permissions = BUILTIN_GROUP_DEFAULTS[key]
    group = Group(name=name, description=description, builtin_key=key.value)
    session.add(group)
    await session.flush()
    for permission in sorted(permissions):
        session.add(GroupPermission(group_id=group.id, permission=permission))
    return group


async def ensure_builtin_groups(session: AsyncSession) -> None:
    """Create whichever built-in groups are missing. Does not commit."""
    for key in BuiltinGroup:
        await builtin_group(session, key)


def is_admin_group(group: Group) -> bool:
    """The one group whose permissions are implicit: all of them, always."""
    return group.builtin_key == BuiltinGroup.ADMIN.value


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> Group | None:
    return await session.get(Group, group_id)


async def get_group_by_name(session: AsyncSession, name: str) -> Group | None:
    result = await session.exec(select(Group).where(Group.name == name))
    return result.one_or_none()


async def list_groups(session: AsyncSession) -> list[Group]:
    """Every group, built-in ones first, then by name."""
    result = await session.exec(select(Group))
    groups = list(result.all())
    groups.sort(key=lambda g: (g.builtin_key is None, _builtin_rank(g), g.name))
    return groups


def _builtin_rank(group: Group) -> int:
    order = [k.value for k in BuiltinGroup]
    return order.index(group.builtin_key) if group.builtin_key in order else len(order)


async def group_permissions(session: AsyncSession, group: Group) -> frozenset[str]:
    """What the group grants — the full catalogue for the administrators."""
    if is_admin_group(group):
        return ALL_PERMISSIONS
    result = await session.exec(
        select(GroupPermission.permission).where(GroupPermission.group_id == group.id)
    )
    return frozenset(result.all())


async def permissions_of_groups(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, frozenset[str]]:
    """Stored permissions of several groups at once. The administrators' group
    is reported as the full catalogue, like ``group_permissions``."""
    ids = list(group_ids)
    if not ids:
        return {}
    granted: dict[uuid.UUID, set[str]] = {gid: set() for gid in ids}
    rows = await session.exec(
        select(GroupPermission.group_id, GroupPermission.permission).where(
            col(GroupPermission.group_id).in_(ids)
        )
    )
    for gid, permission in rows.all():
        granted[gid].add(permission)
    admins = await session.exec(
        select(Group.id).where(
            col(Group.id).in_(ids), Group.builtin_key == BuiltinGroup.ADMIN.value
        )
    )
    for gid in admins.all():
        granted[gid] = set(ALL_PERMISSIONS)
    return {gid: frozenset(perms) for gid, perms in granted.items()}


async def set_group_permissions(
    session: AsyncSession, group: Group, permissions: Iterable[str]
) -> None:
    """Replace the group's permission set. Does not commit; refuses nothing —
    the route validates against the catalogue before calling."""
    await session.exec(
        delete(GroupPermission).where(col(GroupPermission.group_id) == group.id)
    )
    for permission in sorted(set(permissions)):
        session.add(GroupPermission(group_id=group.id, permission=permission))
    group.updated_at = utcnow()
    session.add(group)


async def member_counts(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    ids = list(group_ids)
    if not ids:
        return {}
    rows = await session.exec(
        select(UserGroup.group_id, func.count())
        .where(col(UserGroup.group_id).in_(ids))
        .group_by(col(UserGroup.group_id))
    )
    counts = dict.fromkeys(ids, 0)
    for gid, n in rows.all():
        counts[gid] = n
    return counts


async def group_member_ids(
    session: AsyncSession, group_id: uuid.UUID
) -> list[uuid.UUID]:
    result = await session.exec(
        select(UserGroup.user_id).where(UserGroup.group_id == group_id)
    )
    return list(result.all())


async def user_group_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await session.exec(
        select(UserGroup.group_id).where(UserGroup.user_id == user_id)
    )
    return list(result.all())


async def groups_of_users(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[Group]]:
    """The groups of several users at once, for a list page: one query, not one
    per row."""
    ids = list(user_ids)
    out: dict[uuid.UUID, list[Group]] = {uid: [] for uid in ids}
    if not ids:
        return out
    rows = await session.exec(
        select(UserGroup.user_id, Group)
        .join(Group, col(Group.id) == col(UserGroup.group_id))
        .where(col(UserGroup.user_id).in_(ids))
        .order_by(col(Group.name))
    )
    for uid, group in rows.all():
        out[uid].append(group)
    return out


async def set_user_groups(
    session: AsyncSession, user: User, group_ids: Iterable[uuid.UUID]
) -> None:
    """Replace the user's memberships. Does not commit."""
    await session.exec(delete(UserGroup).where(col(UserGroup.user_id) == user.id))
    for gid in set(group_ids):
        session.add(UserGroup(user_id=user.id, group_id=gid))
    await session.flush()


async def is_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the user belongs to the administrators' group.

    Not the same as holding every permission: a composed group may grant the
    whole catalogue, but only the administrators' group grants what the
    catalogue will hold tomorrow — and only an administrator may make another.
    """
    admin = await session.exec(
        select(func.count())
        .select_from(UserGroup)
        .join(Group, col(Group.id) == col(UserGroup.group_id))
        .where(
            UserGroup.user_id == user_id,
            Group.builtin_key == BuiltinGroup.ADMIN.value,
        )
    )
    return (admin.one() or 0) > 0


async def user_permissions(session: AsyncSession, user_id: uuid.UUID) -> frozenset[str]:
    """The union of the user's groups' permissions — what ``require_permission``
    decides on. Membership of the administrators' group is the whole catalogue."""
    if await is_admin(session, user_id):
        return ALL_PERMISSIONS
    result = await session.exec(
        select(GroupPermission.permission)
        .join(UserGroup, col(UserGroup.group_id) == col(GroupPermission.group_id))
        .where(UserGroup.user_id == user_id)
        .distinct()
    )
    return frozenset(result.all())


async def scopes_of_groups(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Scope | None]:
    """Each group's scope — ``None`` for an unrestricted one, which includes
    the administrators' group whatever rows it may carry."""
    ids = list(group_ids)
    if not ids:
        return {}
    rows: dict[uuid.UUID, list[tuple[str, str]]] = {gid: [] for gid in ids}
    result = await session.exec(
        select(GroupScope.group_id, GroupScope.kind, GroupScope.value).where(
            col(GroupScope.group_id).in_(ids)
        )
    )
    for gid, kind, value in result.all():
        rows[gid].append((kind, value))
    admins = set(
        (
            await session.exec(
                select(Group.id).where(
                    col(Group.id).in_(ids),
                    Group.builtin_key == BuiltinGroup.ADMIN.value,
                )
            )
        ).all()
    )
    return {
        gid: None if gid in admins or not pairs else Scope.from_rows(pairs)
        for gid, pairs in rows.items()
    }


async def set_group_scope(
    session: AsyncSession, group: Group, scope: Scope | None
) -> None:
    """Replace the group's scope; ``None`` lifts the restriction. Does not
    commit."""
    await session.exec(delete(GroupScope).where(col(GroupScope.group_id) == group.id))
    for kind, value in scope.rows() if scope is not None else []:
        session.add(GroupScope(group_id=group.id, kind=kind, value=value))
    group.updated_at = utcnow()
    session.add(group)


async def user_scope(session: AsyncSession, user_id: uuid.UUID) -> Scope | None:
    """Where the account may look (``scope.union`` of its groups). ``None`` is
    the whole parc: administrators, and members of any unrestricted group."""
    if await is_admin(session, user_id):
        return None
    group_ids = await user_group_ids(session, user_id)
    scopes = await scopes_of_groups(session, group_ids)
    return scope_union(scopes.values())


async def user_authority(session: AsyncSession, user_id: uuid.UUID) -> Authority:
    """What an existing account holds — what editing it would lay hands on."""
    return Authority(
        is_admin=await is_admin(session, user_id),
        permissions=await user_permissions(session, user_id),
        scope=await user_scope(session, user_id),
    )


async def groups_authority(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> Authority:
    """What membership of ``group_ids`` together grants. Unknown ids grant
    nothing (the routes refuse them before asking)."""
    ids = list(set(group_ids))
    if not ids:
        return Authority(is_admin=False, permissions=frozenset(), scope=Scope())
    admins = await session.exec(
        select(func.count())
        .select_from(Group)
        .where(col(Group.id).in_(ids), Group.builtin_key == BuiltinGroup.ADMIN.value)
    )
    permissions = await permissions_of_groups(session, ids)
    scopes = await scopes_of_groups(session, ids)
    is_admin_ = (admins.one() or 0) > 0
    return Authority(
        is_admin=is_admin_,
        permissions=frozenset().union(*permissions.values()),
        scope=None if is_admin_ else scope_union(scopes.values()),
    )


async def users_holding(session: AsyncSession, permission: str) -> int:
    """How many *active* accounts hold ``permission`` through any group. What
    the lock-out guard on group edits reads."""
    direct = (
        select(func.count(func.distinct(col(UserGroup.user_id))))
        .select_from(UserGroup)
        .join(User, col(User.id) == col(UserGroup.user_id))
        .join(Group, col(Group.id) == col(UserGroup.group_id))
        .outerjoin(
            GroupPermission,
            (col(GroupPermission.group_id) == col(Group.id))
            & (col(GroupPermission.permission) == permission),
        )
        .where(
            col(User.is_active).is_(True),
            or_(
                col(GroupPermission.permission).is_not(None),
                col(Group.builtin_key) == BuiltinGroup.ADMIN.value,
            ),
        )
    )
    result = await session.exec(direct)
    return result.one() or 0
