"""Console authentication: login (OAuth2 password flow), current user, and the
password lifecycle — self-service change, and the "forgot password" flow.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep
from app.api.fields import Email, Password
from app.core import security
from app.core.errors import AppError, ErrorCode
from app.features.user import crud, emails

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    """JWT access token response."""

    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """Authenticated user info."""

    id: uuid.UUID
    email: str
    full_name: str | None
    role: str

    model_config = {"from_attributes": True}


@router.post("/login", response_model=Token)
async def login(
    session: SessionDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Authenticate with email (username) + password, return a JWT."""
    user = await crud.authenticate(session, form.username, form.password)
    if user is None:
        raise AppError(
            code=ErrorCode.AUTH_CREDENTIALS_INVALID,
            status_code=401,
            message="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=security.create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    """Return the current authenticated user."""
    return UserOut.model_validate(user)


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


@router.post("/password-reset/request", status_code=204)
async def request_password_reset(
    payload: PasswordResetRequest, session: SessionDep
) -> None:
    """Mail a reset link to the account, if it exists.

    Public endpoint. It answers 204 whatever happens — unknown address,
    deactivated account, mail failure — so it cannot be used to find out which
    e-mails have a console account.

    Note: not rate-limited yet (plan §M5 lists rate limiting as outstanding).
    Anyone reaching the API can trigger mail to a known address.
    """
    user = await crud.get_by_email(session, payload.email)
    if user is None or not user.is_active:
        return
    token = await crud.create_reset_token(session, user)
    # Read before committing: the session expires instances on commit
    # (expire_on_commit default), and touching an expired attribute afterwards
    # would lazy-load synchronously inside async — MissingGreenlet.
    email = user.email
    await session.commit()
    await emails.send_password_reset(email, token)


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
