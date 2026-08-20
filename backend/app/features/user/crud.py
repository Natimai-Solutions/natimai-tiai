import uuid
from datetime import timedelta

from sqlalchemy import delete, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.features.base import utcnow
from app.features.user.models import PasswordResetToken, Role, User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    """Fetch a user by email (case-sensitive)."""
    result = await session.exec(select(User).where(User.email == email))
    return result.one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    role: Role = Role.READONLY,
    full_name: str | None = None,
) -> User:
    """Create a user with a hashed password."""
    user = User(
        email=email,
        hashed_password=security.get_password_hash(password),
        role=role.value,
        full_name=full_name,
    )
    session.add(user)
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
    """Delete a user and any reset token issued to them.

    Tokens are removed explicitly rather than relying on ``ON DELETE CASCADE``:
    the constraint exists in the migration but not in the schema SQLModel builds
    for the tests, so leaning on it would behave differently in each.
    """
    await session.execute(
        delete(PasswordResetToken).where(col(PasswordResetToken.user_id) == user.id)
    )
    await session.delete(user)


# --- Password reset tokens --------------------------------------------------


async def create_reset_token(session: AsyncSession, user: User) -> str:
    """Issue a single-use reset token, returning the clear value (mailed once).

    Any previous token for the user is dropped, so the newest link is the only
    one that works.
    """
    await session.execute(
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
    await session.execute(
        delete(PasswordResetToken).where(col(PasswordResetToken.user_id) == user_id)
    )
