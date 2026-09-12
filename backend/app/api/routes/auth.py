"""Console authentication: login (OAuth2 password flow), current user, and the
password lifecycle — self-service change, and the "forgot password" flow.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.api.deps import CurrentPermissions, CurrentUser, SessionDep
from app.api.fields import Email, Password
from app.core import ratelimit, security
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.features.base import utcnow
from app.features.user import crud, emails
from app.features.user.models import EmailPreference, User

# The security log: authentication events, one greppable line each. Without it
# a brute-force attempt leaves no trace at all outside the rate limiter's 429s.
security_log = logging.getLogger("app.security")

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    """JWT access token response."""

    access_token: str
    token_type: str = "bearer"


class GroupRef(BaseModel):
    """A group as the profile names it: enough to display, not to edit."""

    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    """Authenticated user info, with what the account may do.

    ``permissions`` is what the console reads to decide which buttons and
    pages to show — cosmetic: the backend re-checks every call.
    """

    id: uuid.UUID
    email: str
    full_name: str | None
    email_preference: str
    groups: list[GroupRef]
    permissions: list[str]


async def _profile(
    session: SessionDep, user: User, permissions: frozenset[str]
) -> UserOut:
    groups = (await crud.groups_of_users(session, [user.id]))[user.id]
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        email_preference=user.email_preference,
        groups=[GroupRef.model_validate(g) for g in groups],
        permissions=sorted(permissions),
    )


@router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(ratelimit.rate_limit(ratelimit.login_limiter, "auth.login"))],
)
async def login(
    request: Request,
    session: SessionDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Authenticate with email (username) + password, return a JWT."""
    user = await crud.authenticate(session, form.username, form.password)
    if user is None:
        security_log.warning(
            "login failed for %s from %s", form.username, client_ip(request)
        )
        raise AppError(
            code=ErrorCode.AUTH_CREDENTIALS_INVALID,
            status_code=401,
            message="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    security_log.info("login ok for %s from %s", user.email, client_ip(request))
    return Token(access_token=security.create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(
    session: SessionDep, user: CurrentUser, permissions: CurrentPermissions
) -> UserOut:
    """Return the current authenticated user."""
    return await _profile(session, user, permissions)


class ProfileUpdate(BaseModel):
    """Self-service profile update — only the supplied fields are changed."""

    email_preference: EmailPreference | None = None


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileUpdate,
    user: CurrentUser,
    session: SessionDep,
    permissions: CurrentPermissions,
) -> UserOut:
    """Update one's own profile.

    Self-service, and deliberately narrow: what an account may change about
    itself here is how much mail it receives. Its groups, its address and
    whether it is active stay with an administrator (``/users``) — a read-only
    operator who could edit their own row would not be read-only for long.
    """
    if payload.email_preference is not None:
        user.email_preference = payload.email_preference
    user.updated_at = utcnow()
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return await _profile(session, user, permissions)


# --- Password lifecycle -----------------------------------------------------


class PasswordChange(BaseModel):
    """Self-service password change: the current password is the proof."""

    current_password: str
    new_password: Password


@router.post("/password", status_code=204)
async def change_password(
    payload: PasswordChange, user: CurrentUser, session: SessionDep
) -> None:
    """Change one's own password.

    The caller's other sessions are cut off (tokens issued before now stop
    being accepted), so the token used for *this* request is invalidated too —
    the console re-authenticates right after.
    """
    if not security.verify_password(payload.current_password, user.hashed_password):
        raise AppError(
            code=ErrorCode.PASSWORD_CURRENT_INVALID,
            status_code=400,
            message="Current password is incorrect",
        )
    await crud.set_password(session, user, payload.new_password)
    await crud.purge_reset_tokens(session, user.id)
    await session.commit()


class PasswordResetRequest(BaseModel):
    """Ask for a reset link to be mailed."""

    email: Email


@router.post(
    "/password-reset/request",
    status_code=204,
    dependencies=[
        Depends(
            ratelimit.rate_limit(
                ratelimit.password_reset_limiter, "auth.password_reset"
            )
        )
    ],
)
async def request_password_reset(
    request: Request, payload: PasswordResetRequest, session: SessionDep
) -> None:
    """Mail a reset link to the account, if it exists.

    Public endpoint. It answers 204 whatever happens — unknown address,
    deactivated account, mail failure — so it cannot be used to find out which
    e-mails have a console account. Rate-limited per source address: each
    accepted call can put a mail in a known operator's inbox.
    """
    security_log.info(
        "password reset requested for %s from %s",
        payload.email,
        client_ip(request),
    )
    user = await crud.get_by_email(session, payload.email)
    if user is None or not user.is_active:
        return
    token = await crud.create_reset_token(session, user)
    # Queued before the commit, so the mail and the token it links to are one
    # transaction: no link mailed for a token that was rolled back, no token
    # whose mail was lost to a Mailgun outage — the worker sends with retries.
    emails.send_password_reset(session, user.email, token)
    await session.commit()


class PasswordResetConfirm(BaseModel):
    """Redeem a reset token and set the new password."""

    token: str
    new_password: Password


@router.post("/password-reset/confirm", status_code=204)
async def confirm_password_reset(
    payload: PasswordResetConfirm, session: SessionDep
) -> None:
    """Set a new password from a valid reset link. Public endpoint."""
    user = await crud.consume_reset_token(session, payload.token)
    if user is None:
        raise AppError(
            code=ErrorCode.PASSWORD_RESET_TOKEN_INVALID,
            status_code=400,
            message="This reset link is invalid or has expired",
        )
    await crud.set_password(session, user, payload.new_password)
    await session.commit()
