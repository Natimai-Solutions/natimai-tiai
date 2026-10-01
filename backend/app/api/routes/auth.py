"""Console authentication: login (OAuth2 password flow), sessions, current
user, and the password lifecycle — self-service change, and the "forgot
password" flow.

A login opens a server-side session (``app.features.auth_session``) seen
through two tokens. The access token — a JWT of ``ACCESS_TOKEN_EXPIRE_MINUTES``
— is returned in the body; the console keeps it in memory and sends it as a
bearer. The refresh token travels in an HttpOnly cookie scoped to this router
(``/api/v1/auth``), out of reach of the page's scripts and never sent to any
other route; ``POST /auth/refresh`` trades it for a new access token, and a
new refresh token with it. ``POST /auth/logout`` ends the session for good.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, Field, field_validator

from app.api.deps import (
    CurrentAuthSession,
    CurrentPermissions,
    CurrentUser,
    SessionDep,
)
from app.api.fields import Email, Password
from app.core import ratelimit, security
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.features.audit import crud as audit
from app.features.auth_session import crud as auth_sessions
from app.features.auth_session.models import AuthSession
from app.features.base import utcnow
from app.features.user import crud, emails
from app.features.user.models import EmailPreference, User

# The security log: authentication events, one greppable line each. Without it
# a brute-force attempt leaves no trace at all outside the rate limiter's 429s.
security_log = logging.getLogger("app.security")

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    """JWT access token response. The refresh token is never in a body: it
    only ever travels in the HttpOnly cookie."""

    access_token: str
    token_type: str = "bearer"


# --- The refresh cookie -------------------------------------------------------

REFRESH_COOKIE = "tiai_refresh"
# Sent back on the auth routes only — login, refresh, logout, sessions — and
# never alongside the hundreds of calls the rest of the console makes.
REFRESH_COOKIE_PATH = f"{settings.API_V1_STR}/auth"


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    """Hand the browser its refresh token.

    ``HttpOnly``: no script reads it, an injected one included. ``SameSite=
    Strict``: no other site can make the browser send it, which is what makes
    a cookie safe to authenticate a POST with. ``Secure`` everywhere but
    ``local`` (``Settings.refresh_cookie_secure``). Its lifetime follows the
    session's, so the browser drops it when the server would refuse it.
    """
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=max(0, round((expires_at - utcnow()).total_seconds())),
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _session_ended() -> AppError:
    """The refusal of a refresh, which also tells the browser to drop a cookie
    that will never open anything again.

    The header is built on a scratch response: an ``AppError`` is rendered by
    its own handler, and the route's response — where the cookie would
    otherwise be cleared — is thrown away with it.
    """
    scratch = Response()
    _clear_refresh_cookie(scratch)
    return AppError(
        code=ErrorCode.AUTH_SESSION_INVALID,
        status_code=401,
        message="No valid session: log in again",
        headers={"set-cookie": scratch.headers["set-cookie"]},
    )


RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


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
    # The console's own per-account settings (the machine list's columns and
    # their order, ...), handed back as stored. Keys and shapes are the
    # console's vocabulary; the server only bounds their size.
    preferences: dict[str, Any]
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
        preferences=dict(user.preferences or {}),
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
    response: Response,
    session: SessionDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Authenticate with email (username) + password and open a session.

    Returns the access token; sets the refresh token as a cookie.
    """
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
    ip = client_ip(request)
    security_log.info("login ok for %s from %s", user.email, ip)
    row, refresh_token = await auth_sessions.open_session(
        session, user.id, user_agent=request.headers.get("user-agent"), ip=ip
    )
    access_token = security.create_access_token(user.id, session_id=row.id)
    _set_refresh_cookie(response, refresh_token, row.expires_at)
    await session.commit()
    return Token(access_token=access_token)


@router.post("/refresh", response_model=Token)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    refresh_token: RefreshCookie = None,
) -> Token:
    """Trade the refresh cookie for a new access token — and a new cookie.

    Refresh tokens are single-use. Presenting one that was already traded
    (outside the few seconds two tabs may race for it) means a copy is in
    other hands: the session is revoked for both holders, and logged.
    """
    if not refresh_token:
        raise _session_ended()
    result = await auth_sessions.refresh(session, refresh_token)
    row = result.session
    if result.outcome is auth_sessions.RefreshOutcome.REUSED and row is not None:
        security_log.warning(
            "refresh token reused for session %s of user %s from %s: "
            "presumed theft, session revoked",
            row.id,
            row.user_id,
            client_ip(request),
        )
        await session.commit()
        raise _session_ended()
    if row is None:
        raise _session_ended()

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        # Deactivation revokes every session already; this is the backstop
        # for a row that escaped it.
        auth_sessions.revoke(session, row)
        await session.commit()
        raise _session_ended()

    access_token = security.create_access_token(user.id, session_id=row.id)
    if result.refresh_token is not None:
        _set_refresh_cookie(response, result.refresh_token, row.expires_at)
    await session.commit()
    return Token(access_token=access_token)


def _bearer_session_id(authorization: str | None) -> uuid.UUID | None:
    """The session a bearer access token names, if it is a genuine one."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = security.decode_access_token(
            authorization.removeprefix("Bearer ").strip()
        )
    except InvalidTokenError:
        return None
    if payload.get("type") != security.ACCESS_TOKEN_TYPE:
        return None
    try:
        return uuid.UUID(str(payload.get("sid")))
    except ValueError:
        return None


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session: SessionDep,
    refresh_token: RefreshCookie = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """End the current session and clear the cookie.

    Needs no valid access token: logging out must work with one that has just
    expired. Either credential identifies the session — the refresh cookie
    (current or just-rotated token), or a genuine access token — and either is
    proof enough to end it. Always 204: there is nothing useful to tell a
    client whose session was already over.
    """
    rows: list[AuthSession] = []
    if refresh_token:
        row = await auth_sessions.find_by_refresh_token(session, refresh_token)
        if row is not None:
            rows.append(row)
    bearer_sid = _bearer_session_id(authorization)
    if bearer_sid is not None:
        row = await session.get(AuthSession, bearer_sid)
        if row is not None:
            rows.append(row)
    for row in rows:
        auth_sessions.revoke(session, row)
    if rows:
        security_log.info("logout of session %s", rows[0].id)
    await session.commit()
    _clear_refresh_cookie(response)


class SessionOut(BaseModel):
    """One open session, as « Mon compte » lists it."""

    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip: str | None
    # The session this very request belongs to: closing it is logging out.
    current: bool


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    session: SessionDep, user: CurrentUser, current: CurrentAuthSession
) -> list[SessionOut]:
    """The caller's open sessions, most recently active first."""
    rows = await auth_sessions.list_live(session, user.id)
    return [
        SessionOut(
            id=r.id,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            expires_at=r.expires_at,
            user_agent=r.user_agent,
            ip=r.ip,
            current=r.id == current.id,
        )
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def close_session(
    session_id: uuid.UUID,
    response: Response,
    session: SessionDep,
    user: CurrentUser,
    current: CurrentAuthSession,
) -> None:
    """Close one of the caller's sessions — a workstation left logged in.

    Only one's own: another account's session, like one already over, is
    « not found » rather than « forbidden », so the endpoint says nothing about
    sessions that are not the caller's. Audited: the trace of « I closed the
    session on the reception PC » is the trace of a suspected compromise.
    """
    row = await session.get(AuthSession, session_id)
    if row is None or row.user_id != user.id or not auth_sessions.is_live(row):
        raise AppError(
            code=ErrorCode.AUTH_SESSION_NOT_FOUND,
            status_code=404,
            message="Session not found",
        )
    is_current = row.id == current.id
    auth_sessions.revoke(session, row)
    # The account is the resource, not the session: a session id authorizes
    # a refresh attempt on its own, and has no business in a log that others
    # read. What lets a reader recognise the session is kept instead.
    audit.record(
        session,
        actor=user.email,
        action="auth.session_revoked",
        resource_type="user",
        resource_id=str(user.id),
        details={
            "current": is_current,
            "user_agent": row.user_agent,
            "ip": row.ip,
            "created_at": row.created_at.isoformat(),
        },
    )
    await session.commit()
    if is_current:
        _clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(
    session: SessionDep, user: CurrentUser, permissions: CurrentPermissions
) -> UserOut:
    """Return the current authenticated user."""
    return await _profile(session, user, permissions)


# Bounds on the preference document, generous for what the console stores
# (a few dozen column names) and tight enough that the endpoint cannot be used
# as free storage: so many keys, so many bytes once serialised.
PREFERENCES_MAX_KEYS = 50
PREFERENCES_MAX_BYTES = 16 * 1024
PREFERENCES_KEY_MAX_LENGTH = 64


class ProfileUpdate(BaseModel):
    """Self-service profile update — only the supplied fields are changed."""

    email_preference: EmailPreference | None = None
    # Merged into the stored document key by key: a key sent with ``null``
    # is removed, a key not sent is left alone. So the page that remembers
    # the machine list's columns never overwrites what another page stored.
    preferences: dict[str, Any] | None = Field(
        default=None, max_length=PREFERENCES_MAX_KEYS
    )

    @field_validator("preferences")
    @classmethod
    def _bounded_keys(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        for key in value:
            if not key or len(key) > PREFERENCES_KEY_MAX_LENGTH:
                raise ValueError(
                    f"preference keys must be 1–{PREFERENCES_KEY_MAX_LENGTH} characters"
                )
        return value


def merge_preferences(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """The stored document after ``patch``: keys set, null keys removed.

    Raises ``AppError`` (422) when the result exceeds the bounds — measured on
    the merged document, since the caller's patch may be small and the
    accumulated document large.
    """
    merged = {**current}
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    too_many = len(merged) > PREFERENCES_MAX_KEYS
    too_big = len(json.dumps(merged, separators=(",", ":"))) > PREFERENCES_MAX_BYTES
    if too_many or too_big:
        raise AppError(
            code=ErrorCode.REQUEST_VALIDATION_ERROR,
            status_code=422,
            message=(
                f"Preferences are limited to {PREFERENCES_MAX_KEYS} keys and "
                f"{PREFERENCES_MAX_BYTES} bytes"
            ),
        )
    return merged


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
    if payload.preferences is not None:
        # A new dict and not an in-place update: SQLAlchemy only notices a
        # JSONB column changing when the attribute is reassigned.
        user.preferences = merge_preferences(
            user.preferences or {}, payload.preferences
        )
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

    Every session of the account is revoked — the one this request came
    through included — so the console re-authenticates right after.
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
