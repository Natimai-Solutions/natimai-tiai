import uuid
from collections.abc import Iterable, Sequence
from datetime import timedelta

from sqlalchemy import delete, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.features.base import utcnow
from app.features.user.models import (
    Group,
    GroupPermission,
    PasswordResetToken,
    User,
    UserGroup,
)
from app.features.user.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_GROUP_DEFAULTS,
    BuiltinGroup,
)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    """Fetch a user by email (case-sensitive)."""
    result = await session.exec(select(User).where(User.email == email))
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
        email=email,
        hashed_password=security.get_password_hash(password),
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


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if credentials are valid and the account is active."""
    user = await get_by_email(session, email)
    if user is None or not user.is_active:
        return None
    if not security.verify_password(password, user.hashed_password):
        return None
    return user


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
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                col(User.email).ilike(pattern),
                col(User.full_name).ilike(pattern),
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
    """Hash and store a new password, cutting off sessions opened before now.

    Does not commit — the caller decides the transaction boundary.
    """
    user.hashed_password = security.get_password_hash(password)
    user.password_changed_at = utcnow()
    user.updated_at = utcnow()
    session.add(user)


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


async def create_reset_token(session: AsyncSession, user: User) -> str:
    """Issue a single-use reset token, returning the clear value (mailed once).

    Any previous token for the user is dropped, so the newest link is the only
    one that works.
    """
    await session.exec(
        delete(PasswordResetToken).where(col(PasswordResetToken.user_id) == user.id)
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


async def user_permissions(session: AsyncSession, user_id: uuid.UUID) -> frozenset[str]:
    """The union of the user's groups' permissions — what ``require_permission``
    decides on. Membership of the administrators' group is the whole catalogue."""
    admin = await session.exec(
        select(func.count())
        .select_from(UserGroup)
        .join(Group, col(Group.id) == col(UserGroup.group_id))
        .where(
            UserGroup.user_id == user_id,
            Group.builtin_key == BuiltinGroup.ADMIN.value,
        )
    )
    if (admin.one() or 0) > 0:
        return ALL_PERMISSIONS
    result = await session.exec(
        select(GroupPermission.permission)
        .join(UserGroup, col(UserGroup.group_id) == col(GroupPermission.group_id))
        .where(UserGroup.user_id == user_id)
        .distinct()
    )
    return frozenset(result.all())


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
