import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, case, delete, func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.features.auth_session import crud as auth_sessions
from app.features.base import contains, utcnow
from app.features.user import addresses
from app.features.user.models import (
    Group,
    GroupIdpLink,
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


@dataclass(frozen=True)
class Lock:
    """A lock a failure just set: until when, and whether the slow counter
    set it (``slow``: it shuts out the addresses that failed since the slow
    window began, until it ends — a successful login does not lift it)."""

    until: datetime
    slow: bool = False


class AccountLockedError(Exception):
    """The account is locked after too many failed logins."""

    def __init__(
        self,
        user: User,
        locked_until: datetime,
        *,
        just_locked: bool,
        slow: bool = False,
    ):
        super().__init__(f"account locked until {locked_until.isoformat()}")
        self.user = user
        self.locked_until = locked_until
        # True on the failure that tripped the lock: the one worth auditing.
        self.just_locked = just_locked
        # The lock is the slow counter's (``Lock.slow``).
        self.slow = slow


async def lock_account(session: AsyncSession, user: User) -> User | None:
    """Lock the account's row until the transaction ends and return it as
    the database has it now (None if it is gone). Does not commit.

    The order of the rows a request locks, everywhere: **the account's,
    then its sessions', then its addresses'**. A password reset takes all
    three (``set_password``); a failed login the account's and an
    address's; a refresh a session's and an address's; a wrong current
    password all three. Taken in any other order by one of them, two
    requests at the same instant can each hold what the other waits for,
    and one is answered a 500.

    ``FOR NO KEY UPDATE``: what an UPDATE of the row takes — a login
    opening a session for the account (a row that refers to this one) does
    not wait for it.
    """
    result = await session.exec(
        select(User)
        .where(col(User.id) == user.id)
        .with_for_update(key_share=True)
        # ``user`` is in this session already, read before the lock.
        .execution_options(populate_existing=True)
    )
    return result.one_or_none()


def slow_lock_since(user: User, now: datetime) -> datetime | None:
    """The start of the slow window whose lock is running on ``user``, None
    when no slow lock is: what ``addresses.shut_out`` reads the failures
    since."""
    if user.slow_locked_until is None or user.slow_locked_until <= now:
        return None
    return user.slow_window_started_at


async def authenticate(
    session: AsyncSession,
    email: str,
    password: str,
    ip: str = "",
    *,
    finish: bool = True,
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
    the guessing comes from many addresses (``addresses.shut_out``): the lock
    then shuts out every address but those that opened the account recently,
    so spreading the guesses buys no more of them. Guesses spaced out to
    dodge that count — LOGIN_SLOW_MAX_FAILED_ATTEMPTS within
    LOGIN_SLOW_WINDOW_HOURS — set a second lock, for LOGIN_SLOW_WINDOW_HOURS,
    on the same terms over that longer window (audit T06): shut to the
    addresses that failed since the window began, and to every address but
    the usual ones once many did. Which addresses failed and
    which ones opened the account is in the database: a restart changes
    nothing to a lock. Raises
    ``AccountLockedError`` on the failure that locks it (to audit) and on an
    attempt refused by the lock (to log); the route answers both like any
    failure (audit S12). The counter moves in the database, so concurrent
    failures all count (audit S13). Nothing is committed — the caller does.

    ``finish=False`` stops at the password: the success's effects (counters
    back to zero, the address marked known) are left to
    ``note_login_success``, which the login calls once the whole login has
    succeeded — after the second factor, for an account that has one (C7).
    A stolen password alone must not lift the lock nor make its address
    « known ».
    """
    user = await get_by_email(session, email)
    # An account of the directory has no password (C7): refused at the same
    # cost as an unknown address.
    if user is None or not user.is_active or user.auth_source != "local":
        await security.burn_password_check_async(password)
        return None
    now = utcnow()
    quick = user.locked_until is not None and user.locked_until > now
    slow_since = slow_lock_since(user, now)
    if (quick or slow_since is not None) and await addresses.shut_out(
        session, user.id, ip, now, slow_since=slow_since
    ):
        await security.burn_password_check_async(password)
        until = [
            end
            for end in (user.locked_until, user.slow_locked_until)
            if end is not None and end > now
        ]
        raise AccountLockedError(
            user, max(until), just_locked=False, slow=slow_since is not None
        )
    if not await security.check_password(password, user.hashed_password):
        lock = await record_failure(session, user, ip)
        if lock is not None:
            raise AccountLockedError(user, lock.until, just_locked=True, slow=lock.slow)
        return None
    if finish:
        await note_login_success(session, user, ip)
    return user


async def note_login_success(session: AsyncSession, user: User, ip: str) -> None:
    """What a successful login does to the lock: the quick counter back to
    zero, the address marked known. Does not commit."""
    now = utcnow()
    # The slow counter, its window and its lock are left alone: the owner
    # logging in every morning would otherwise hand a slow guesser a fresh
    # budget every day (and the addresses the lock shuts out, a way back
    # in). Twenty typos of their own in a day is not a thing that happens.
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.last_failed_login_at = None
        user.locked_until = None
        session.add(user)
        # Written now: the account's row before the address's (``lock_account``).
        await session.flush()
    await addresses.note_success(session, user.id, ip, now)


async def record_failure(session: AsyncSession, user: User, ip: str) -> Lock | None:
    """Count a wrong password for ``user`` from ``ip``, in the database so
    that concurrent failures all count (audit S13). Returns the lock when
    this failure set it — of concurrent ones past a threshold, exactly one
    does. Does not commit.

    Two counters move together, each with its lock. The quick one: a failure
    more than LOGIN_LOCKOUT_MINUTES after the previous one counts as the
    first, so old failures do not add up; LOGIN_MAX_FAILED_ATTEMPTS lock the
    account for LOGIN_LOCKOUT_MINUTES. The slow one (audit T06): failures
    within LOGIN_SLOW_WINDOW_HOURS of the first of its window, however far
    apart — the quick counter let four guesses a quarter of an hour through
    for ever. LOGIN_SLOW_MAX_FAILED_ATTEMPTS set the slow lock, for
    LOGIN_SLOW_WINDOW_HOURS, once per window.

    The slow window is not restarted while its lock runs, nor by anything
    but a failure past both: the count stays at or above the threshold for
    as long as the lock does, so neither the lock ending early nor a login
    of the holder's hands the guesser a new budget before the lock's end,
    and "the addresses that failed since the window began" means the same
    thing from the first guess to the last hour of the lock. When both
    locks trip on one failure, the slow one is reported: it is the wider.
    """
    now = utcnow()
    stale = now - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    slow_stale = now - timedelta(hours=settings.LOGIN_SLOW_WINDOW_HOURS)
    last = col(User.last_failed_login_at)
    slow_start = col(User.slow_window_started_at)
    slow_locked_until = col(User.slow_locked_until)
    # Every right-hand side reads the row as it was: the window's start is
    # tested against the old value in both assignments.
    new_window = or_(
        slow_start.is_(None),
        and_(
            slow_start < slow_stale,
            or_(slow_locked_until.is_(None), slow_locked_until <= now),
        ),
    )
    failures, slow_failures = (
        await session.exec(
            update(User)
            .where(col(User.id) == user.id)
            .values(
                failed_login_attempts=case(
                    (or_(last.is_(None), last < stale), 1),
                    else_=col(User.failed_login_attempts) + 1,
                ),
                last_failed_login_at=now,
                slow_failed_login_attempts=case(
                    (new_window, 1),
                    else_=col(User.slow_failed_login_attempts) + 1,
                ),
                slow_window_started_at=case((new_window, now), else_=slow_start),
            )
            .returning(
                col(User.failed_login_attempts), col(User.slow_failed_login_attempts)
            )
        )
    ).one()
    # The address after the account, the order every request locks them in
    # (``lock_account``): a reset of the password holds the account's row
    # and forgets its addresses, and would deadlock with the reverse.
    await addresses.note_failure(session, user.id, ip, now)
    slow_lock: Lock | None = None
    if slow_failures >= settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS:
        until = now + timedelta(hours=settings.LOGIN_SLOW_WINDOW_HOURS)
        slow_locked = (
            await session.exec(
                update(User)
                .where(
                    col(User.id) == user.id,
                    col(User.slow_failed_login_attempts)
                    >= settings.LOGIN_SLOW_MAX_FAILED_ATTEMPTS,
                    # Once per window: a lock set during this window ends
                    # after the window began, an older one before.
                    or_(
                        slow_locked_until.is_(None),
                        slow_locked_until <= slow_start,
                    ),
                )
                .values(slow_locked_until=until)
                .returning(slow_locked_until)
            )
        ).first()
        if slow_locked is not None:
            slow_lock = Lock(until=slow_locked[0], slow=True)
    if failures < settings.LOGIN_MAX_FAILED_ATTEMPTS:
        return slow_lock
    locked_until = col(User.locked_until)
    locked = (
        await session.exec(
            update(User)
            .where(
                col(User.id) == user.id,
                col(User.failed_login_attempts) >= settings.LOGIN_MAX_FAILED_ATTEMPTS,
            )
            .values(
                failed_login_attempts=0,
                locked_until=now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES),
            )
            .returning(locked_until)
        )
    ).first()
    if slow_lock is not None:
        return slow_lock
    return Lock(until=locked[0]) if locked is not None else None


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
    # Trimmed: an address pasted with a trailing space must still be found.
    search = search.strip() if search else None
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


async def set_password(
    session: AsyncSession,
    user: User,
    password: str,
    *,
    chosen_from: str | None = None,
) -> None:
    """Hash and store a new password, ending every session of the account.

    Whoever changes a password — the user, a reset link, an administrator —
    does it because the old one may be known to someone else, who may well be
    logged in with it: all of the account's sessions are revoked, the caller's
    own included, and the addresses that opened the account with the old
    password stop counting as its owner's (``addresses.forget_known``).
    ``chosen_from`` is the address of the owner choosing the new one — the
    change of their own password, or a reset link redeemed — which stays (or
    becomes) known: it is how an owner locked out by guesses spread over many
    addresses gets back in. None for an administrator's reset. Does not
    commit — the caller decides the transaction boundary.
    """
    user.hashed_password = await security.hash_password(password)
    user.password_changed_at = utcnow()
    user.updated_at = utcnow()
    # A new password is also the way out of a lockout: the administrator who
    # resets it, or the owner who redeems a reset link, proved more than a guess.
    user.failed_login_attempts = 0
    user.last_failed_login_at = None
    user.locked_until = None
    user.slow_failed_login_attempts = 0
    user.slow_window_started_at = None
    user.slow_locked_until = None
    session.add(user)
    # The account's row, then its sessions', then its addresses': the order
    # every request locks them in (``lock_account``).
    await session.flush()
    await auth_sessions.revoke_all(session, user.id)
    await addresses.forget_known(session, user.id, keep=chosen_from)
    await addresses.forget_failures(session, user.id)
    if chosen_from is not None:
        await addresses.note_success(session, user.id, chosen_from, utcnow())


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


# The budget of « mot de passe oublié » is counted per account *and*
# requesting address (audit T34): from one address, no new link within
# PASSWORD_RESET_COOLDOWN_MINUTES of the last one, at most
# PASSWORD_RESET_MAX_LIVE_LINKS alive. Counted per account alone, three
# requests an hour from anybody left nothing for the owner's own. A request
# never voids a link still valid — the one its owner may be opening — so the
# links alive for the account are capped too, generously
# (PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS), against a botnet filling the
# inbox; a request from one of the owner's usual addresses is not held to
# that ceiling, and nobody's is while the slow lock runs: the link is then
# the way back in of a holder the lock refuses, and ten addresses keeping
# the ceiling full would close it — an inbox filled is the lesser harm.


async def reset_request_allowed(
    session: AsyncSession, user: User, ip: str | None = None
) -> bool:
    """Whether a new link may be issued and mailed to ``user`` now, asked
    from ``ip``: none asked from that address within the cooldown, fewer than
    PASSWORD_RESET_MAX_LIVE_LINKS of its links still usable, and the
    account's ceiling not reached (unless ``ip`` is a usual address, or the
    account is under its slow lock).

    Locks the account's row first, for the rest of the transaction: two
    requests for one account at the same instant are answered one after the
    other, the second seeing the link the first issued — the check and the
    insert are not atomic otherwise (audit T34). The caller ends the
    transaction (a commit, or the session closing) to release it.
    """
    locked = await session.exec(
        select(User.slow_locked_until).where(col(User.id) == user.id).with_for_update()
    )
    slow_locked_until = locked.one_or_none()
    now = utcnow()
    found = await session.exec(
        select(PasswordResetToken.created_at, PasswordResetToken.requested_ip)
        .where(col(PasswordResetToken.user_id) == user.id)
        .where(col(PasswordResetToken.used_at).is_(None))
        .where(col(PasswordResetToken.expires_at) > now)
    )
    live = list(found.all())
    address = addresses.stored_address(ip)
    mine = [created for created, asked_from in live if asked_from == address]
    if len(mine) >= settings.PASSWORD_RESET_MAX_LIVE_LINKS:
        return False
    cooldown = timedelta(minutes=settings.PASSWORD_RESET_COOLDOWN_MINUTES)
    if any(created > now - cooldown for created in mine):
        return False
    if len(live) >= settings.PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS:
        if slow_locked_until is not None and slow_locked_until > now:
            return True
        return await addresses.is_known(session, user.id, ip, now)
    return True


async def create_reset_token(
    session: AsyncSession, user: User, ip: str | None = None
) -> str:
    """Issue a single-use reset token, returning the clear value (mailed once).

    The links still valid are kept: a request — anyone may make one — must
    not void the link the account's owner is about to open (audit S14). The
    spent ones (used, expired) are dropped. Redeeming any link voids the
    others (``consume_reset_token``). The route calls
    ``reset_request_allowed`` first, with the same ``ip``: the link records
    the address it was asked from, which the budget is counted on.
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
            requested_ip=addresses.stored_address(ip),
            expires_at=utcnow()
            + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        )
    )
    return token


async def reset_token_usable(session: AsyncSession, token: str) -> bool:
    """Whether ``consume_reset_token`` would accept ``token`` now: known,
    unused, unexpired, of an active account. Reads only — no lock, nothing
    marked."""
    found = await session.exec(
        select(PasswordResetToken, User)
        .join(User, col(User.id) == col(PasswordResetToken.user_id))
        .where(PasswordResetToken.token_hash == security.hash_token(token))
    )
    pair = found.one_or_none()
    if pair is None:
        return False
    row, user = pair
    return user.is_active and row.used_at is None and row.expires_at >= utcnow()


async def consume_reset_token(session: AsyncSession, token: str) -> User | None:
    """Validate a reset token and return its user, marking the token used.

    Returns None when the token is unknown, already used, expired, or belongs to
    a deactivated account. Does not commit.

    The account's row is locked first, then its tokens — the order a reset
    request takes them in (``reset_request_allowed``). Taken the other way
    round, a link redeemed while a request for the same account came in could
    deadlock, and one of the two answered a 500; and a link issued by a
    request still in flight would have outlived the password just chosen.
    """
    token_hash = security.hash_token(token)
    found = await session.exec(
        select(PasswordResetToken.user_id).where(
            PasswordResetToken.token_hash == token_hash
        )
    )
    user_id = found.one_or_none()
    if user_id is None:
        return None
    locked = await session.exec(
        # FOR NO KEY UPDATE: a login of the account must still insert its
        # session (KEY SHARE through the foreign key), or the two deadlock.
        select(User).where(col(User.id) == user_id).with_for_update(key_share=True)
    )
    user = locked.one_or_none()
    if user is None or not user.is_active:
        return None
    # Read under the lock: two redemptions of one link are answered one after
    # the other, the second seeing it used.
    result = await session.exec(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None or row.used_at is not None:
        return None
    if row.expires_at < utcnow():
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
    """The group of this name, whatever its capitalisation — the comparison
    the unique index ``ix_groups_name_lower`` makes."""
    result = await session.exec(
        select(Group).where(func.lower(Group.name) == name.strip().lower())
    )
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


# The key of the transaction-scoped advisory lock every change that may take
# ``user:write`` away from somebody takes before counting who still holds it
# (``routes/users.reject_lockout``). Any constant would do; this one spells
# "tiai-usr" in ASCII so that it reads as what it is in ``pg_locks``.
ACCOUNT_MANAGEMENT_LOCK = 0x746961692D757372


async def lock_account_management(session: AsyncSession) -> None:
    """Wait for, then hold until the transaction ends, the lock that
    serialises the last-administrator guard. Does not commit."""
    await session.exec(select(func.pg_advisory_xact_lock(ACCOUNT_MANAGEMENT_LOCK)))


async def users_holding(
    session: AsyncSession, permission: str, *, local_only: bool = False
) -> int:
    """How many *active* accounts hold ``permission`` through any group. What
    the lock-out guard on group edits reads. ``local_only``: accounts of the
    console only (C7) — those an outage of the directory leaves usable."""
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
    if local_only:
        direct = direct.where(col(User.auth_source) == "local")
    result = await session.exec(direct)
    return result.one() or 0


async def idp_links_of_groups(
    session: AsyncSession, group_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    """The directory groups each group stands for (C7)."""
    if not group_ids:
        return {}
    rows = await session.exec(
        select(GroupIdpLink).where(col(GroupIdpLink.group_id).in_(group_ids))
    )
    out: dict[uuid.UUID, set[str]] = {}
    for link in rows.all():
        out.setdefault(link.group_id, set()).add(link.idp_group_id)
    return out


async def set_group_idp_links(
    session: AsyncSession, group: Group, idp_group_ids: Iterable[str]
) -> None:
    """Replace the directory groups a group stands for. Does not commit."""
    await session.exec(
        delete(GroupIdpLink).where(col(GroupIdpLink.group_id) == group.id)
    )
    for idp_id in {i.lower() for i in idp_group_ids}:
        session.add(GroupIdpLink(group_id=group.id, idp_group_id=idp_id))
    await session.flush()
