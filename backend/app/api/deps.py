import hmac
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.features.auth_session import crud as auth_sessions
from app.features.auth_session.models import AuthSession
from app.features.base import utcnow
from app.features.machine import token_rotation
from app.features.machine.models import Machine
from app.features.user import crud as user_crud
from app.features.user.models import User
from app.features.user.permissions import (
    Action,
    Authority,
    Resource,
    has_permission,
)

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
    """Resolve the calling machine from its Bearer token (per-machine auth).

    The current token or, during a rotation, the one offered on a heartbeat —
    whose first use promotes it (``features/machine/token_rotation.py``).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code=ErrorCode.AUTH_TOKEN_MISSING,
            status_code=401,
            message="Missing bearer token",
        )
    token = authorization.removeprefix("Bearer ").strip()

    machine = await token_rotation.machine_for_token(session, token, utcnow())
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


async def _authenticate(
    session: SessionDep,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> tuple[AuthSession, User]:
    """Resolve the console session a bearer access token belongs to, and its
    account.

    A valid signature is not enough. The token must be an *access* token, and
    the session it names (``sid``) must still be live — this is the check that
    makes a logout, a « fermer cette session » or a password reset take effect
    on the very next request instead of when the token expires.

    One query: the session row and its account, joined, by primary key.
    """
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
    if payload.get("type") != security.ACCESS_TOKEN_TYPE:
        raise credentials_error

    try:
        # A validly-signed token with a malformed subject or session is still
        # a bad credential (401), not a server error (500).
        user_id = uuid.UUID(str(payload.get("sub")))
        session_id = uuid.UUID(str(payload.get("sid")))
    except ValueError:
        raise credentials_error from None

    result = await session.exec(
        select(AuthSession, User)
        .join(User, col(User.id) == col(AuthSession.user_id))
        .where(AuthSession.id == session_id)
    )
    row = result.one_or_none()
    if row is None:
        raise credentials_error
    auth_session, user = row
    if user.id != user_id or not user.is_active:
        raise credentials_error
    if not auth_sessions.is_live(auth_session):
        raise AppError(
            code=ErrorCode.AUTH_SESSION_INVALID,
            status_code=401,
            message="This session has ended",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The older, stateless line behind the session check: a password change
    # revokes every session in its own transaction, and also stamps the
    # instant, before which no access token is accepted whatever its session.
    if user.password_changed_at is not None:
        issued_at = payload.get("iat")
        # Compare whole seconds: `iat` is second-granular, so a token minted
        # microseconds after the change must not be read as predating it.
        changed_at = int(user.password_changed_at.timestamp())
        if issued_at is None or int(issued_at) < changed_at:
            raise credentials_error
    return auth_session, user


# FastAPI caches a dependency's value for the request: the two below share one
# ``_authenticate`` call, hence one query, whichever a route asks for.
_Authenticated = Annotated[tuple[AuthSession, User], Depends(_authenticate)]


async def get_current_auth_session(auth: _Authenticated) -> AuthSession:
    """The console session the request's access token belongs to."""
    return auth[0]


async def get_current_user(auth: _Authenticated) -> User:
    """The account behind the request's session."""
    return auth[1]


CurrentAuthSession = Annotated[AuthSession, Depends(get_current_auth_session)]


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


async def get_current_authority(
    session: SessionDep, user: CurrentUser, permissions: CurrentPermissions
) -> Authority:
    """What the caller may hand out to others: their permissions, and whether
    they are an administrator (``permissions.escalation``). Only the routes
    that grant rights or touch accounts ask for it."""
    return Authority(
        is_admin=await user_crud.is_admin(session, user.id), permissions=permissions
    )


CurrentAuthority = Annotated[Authority, Depends(get_current_authority)]


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
