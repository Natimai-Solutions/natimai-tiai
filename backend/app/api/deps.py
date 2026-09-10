import hmac
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.features.machine.models import Machine
from app.features.user import crud as user_crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource, has_permission

security_log = logging.getLogger("app.security")

SessionDep = Annotated[AsyncSession, Depends(get_db)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


async def verify_enrollment_secret(
    x_enrollment_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Guard for POST /agent/enroll — validates the shared enrollment secret."""
    if x_enrollment_secret is None or not hmac.compare_digest(
        x_enrollment_secret.encode("utf-8"),
        settings.ENROLLMENT_SECRET.encode("utf-8"),
    ):
        raise AppError(
            code=ErrorCode.AUTH_ENROLLMENT_SECRET_INVALID,
            status_code=401,
            message="Invalid enrollment secret",
        )


async def get_current_machine(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Machine:
    """Resolve the calling machine from its Bearer token (per-machine auth)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code=ErrorCode.AUTH_TOKEN_MISSING,
            status_code=401,
            message="Missing bearer token",
        )
    token = authorization.removeprefix("Bearer ").strip()
    token_hash = security.hash_token(token)

    result = await session.exec(select(Machine).where(Machine.token_hash == token_hash))
    machine = result.one_or_none()
    if machine is None:
        raise AppError(
            code=ErrorCode.AUTH_TOKEN_INVALID, status_code=401, message="Invalid token"
        )
    if machine.token_revoked:
        raise AppError(
            code=ErrorCode.AUTH_TOKEN_REVOKED, status_code=401, message="Token revoked"
        )
    return machine


CurrentMachine = Annotated[Machine, Depends(get_current_machine)]


# --- Console user auth (JWT) -----------------------------------------------


async def get_current_user(
    session: SessionDep,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    """Resolve the authenticated console user from a JWT bearer token."""
    credentials_error = AppError(
        code=ErrorCode.AUTH_CREDENTIALS_INVALID,
        status_code=401,
        message="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = security.decode_access_token(token)
    except InvalidTokenError:
        raise credentials_error from None

    sub = payload.get("sub")
    if sub is None:
        raise credentials_error
    try:
        user_id = uuid.UUID(str(sub))
    except ValueError:
        # A validly-signed token with a malformed subject is still a bad
        # credential (401), not a server error (500).
        raise credentials_error from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error

    # A password change (self-service or admin reset) ends earlier sessions:
    # without this, resetting a compromised account's password would leave the
    # attacker's token valid until it expires — up to 8h by default.
    if user.password_changed_at is not None:
        issued_at = payload.get("iat")
        # Compare whole seconds: `iat` is second-granular, so a token minted
        # microseconds after the change must not be read as predating it.
        changed_at = int(user.password_changed_at.timestamp())
        if issued_at is None or int(issued_at) < changed_at:
            raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_permissions(
    session: SessionDep, user: CurrentUser
) -> frozenset[str]:
    """The caller's permission set — the union of their groups' grants.

    Read once per request: FastAPI caches a dependency's value for the
    request, so a route guarded by ``require_permission`` and a handler that
    asks for ``CurrentPermissions`` share the same query.
    """
    return await user_crud.user_permissions(session, user.id)


CurrentPermissions = Annotated[frozenset[str], Depends(get_current_permissions)]


def require_permission(
    resource: Resource, action: Action
) -> Callable[..., Awaitable[User]]:
    """Build a dependency that authorizes the current user for (resource, action)."""

    async def checker(user: CurrentUser, permissions: CurrentPermissions) -> User:
        if not has_permission(permissions, resource.value, action.value):
            # A read-only operator poking at admin endpoints is exactly what a
            # security review greps for after the fact.
            security_log.warning(
                "permission denied: %s asked for %s:%s",
                user.email,
                resource.value,
                action.value,
            )
            raise AppError(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                status_code=403,
                message=f"Missing permission: {resource.value}:{action.value}",
                details={"resource": resource.value, "action": action.value},
            )
        return user

    return checker
