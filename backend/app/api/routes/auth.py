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

import asyncio
import json
import logging
import math
import time
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Text, bindparam, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import col, select

from app.api.deps import (
    CurrentAuthSession,
    CurrentPermissions,
    CurrentUser,
    OptionalAuthSession,
    SessionDep,
)
from app.api.fields import Email, Password
from app.core import ratelimit, security
from app.core.config import settings
from app.core.control_chars import refuse_nul_in_form
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.features.audit import crud as audit
from app.features.auth_session import crud as auth_sessions
from app.features.auth_session.models import AuthSession
from app.features.base import utcnow
from app.features.user import addresses as login_addresses
from app.features.user import crud, emails, second_factor
from app.features.user.models import EmailPreference, Language, User

# The security log: authentication events, one greppable line each. Without it
# a brute-force attempt leaves no trace at all outside the rate limiter's 429s.
security_log = logging.getLogger("app.security")

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    """JWT access token response. The refresh token is never in a body: it
    only ever travels in the HttpOnly cookie."""

    access_token: str
    token_type: str = "bearer"


class SecondFactorChallenge(BaseModel):
    """A right password for an account with a second factor (C7): no session
    yet, a challenge to redeem with a code on ``/auth/login/second-factor``.
    Only ever answered to whoever typed the right password."""

    second_factor_required: bool = True
    challenge: str
    expires_in: int


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
    # A built-in group's stable key (``admin``, ``readonly``, ``technician``):
    # the console names such a group in its reader's language while its name
    # is still the one the installation gave it.
    builtin_key: str | None = None

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
    # The account's language, or None to follow the browser (and
    # DEFAULT_LANGUAGE for its mail).
    language: Language | None = None
    # The console's own per-account settings (the machine list's columns and
    # their order, ...), handed back as stored. Keys and shapes are the
    # console's vocabulary; the server only bounds their size.
    preferences: dict[str, Any]
    groups: list[GroupRef]
    permissions: list[str]
    # Second factor (C7): on, required by a group, how many backup codes are
    # left, and whether this session is for enrolment only.
    second_factor_enabled: bool = False
    second_factor_required: bool = False
    backup_codes_left: int = 0
    enrolment_only: bool = False
    # Where the account signs in from (C7): ``local`` or ``oidc``; and
    # whether a local one is linked to a directory identity.
    auth_source: str = "local"
    directory_linked: bool = False


async def _profile(
    session: SessionDep,
    user: User,
    permissions: frozenset[str],
    current: AuthSession | None = None,
    *,
    enrolment_only: bool | None = None,
) -> UserOut:
    groups = (await crud.groups_of_users(session, [user.id]))[user.id]
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        email_preference=user.email_preference,
        # A value written by hand that is not a language reads as no choice,
        # rather than failing the whole profile.
        language=user.language if user.language in set(Language) else None,
        # A value stored before its depth was bounded is left out rather
        # than served: the response would fail on it, and with it the whole
        # profile. The key stays in the database, where a write replaces or
        # removes it like any other.
        preferences={
            key: value
            for key, value in (user.preferences or {}).items()
            if unservable(value) is None
        },
        groups=[GroupRef.model_validate(g) for g in groups],
        permissions=sorted(permissions),
        second_factor_enabled=second_factor.enabled(user),
        auth_source=user.auth_source,
        directory_linked=user.oidc_subject is not None,
        second_factor_required=await second_factor.required(session, user.id),
        backup_codes_left=await second_factor.backup_codes_left(session, user.id),
        enrolment_only=(
            enrolment_only
            if enrolment_only is not None
            else (current.enrolment_only if current is not None else False)
        ),
    )


@router.post(
    "/login",
    response_model=Token | SecondFactorChallenge,
    dependencies=[
        Depends(ratelimit.rate_limit(ratelimit.login_limiter, "auth.login")),
        # The form is accepted as multipart too, which the control-character
        # middleware does not read: a NUL in it is refused here, not by the
        # database.
        Depends(refuse_nul_in_form),
    ],
)
async def login(
    request: Request,
    response: Response,
    session: SessionDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token | SecondFactorChallenge:
    """Authenticate with email (username) + password and open a session.

    Returns the access token; sets the refresh token as a cookie. For an
    account with a second factor, returns a challenge instead and opens
    nothing: the success's effects on the lock wait for the code (C7).
    """
    ip = client_ip(request)
    try:
        user = await crud.authenticate(
            session, form.username, form.password, ip, finish=False
        )
    except crud.AccountLockedError as exc:
        if exc.just_locked:
            details = {"locked_until": exc.locked_until.isoformat()}
            if exc.slow:
                # Failures spaced out over hours (audit T06): the audit log
                # says which counter locked, since this lock lasts
                # LOGIN_SLOW_WINDOW_HOURS and no login lifts it.
                details["via"] = "slow_attempts"
            audit.record(
                session,
                actor=exc.user.email,
                action="user.locked",
                resource_type="user",
                resource_id=str(exc.user.id),
                details=details,
            )
        # %r: the field is typed by whoever is at the keyboard; a line break in
        # it must not forge a second log line.
        security_log.warning(
            "login refused for %r from %s: %s until %s",
            form.username,
            ip,
            ("account locked (slow guessing)" if exc.slow else "account locked")
            if exc.just_locked
            else "address shut out of the locked account",
            exc.locked_until.isoformat(),
        )
        user = None
    else:
        if user is None:
            security_log.warning("login failed for %r from %s", form.username, ip)
    if user is None:
        # The failure counter, when the address has an account, is part of the
        # outcome: committed before answering. A lock answers the same 401 as
        # any failure: a 423 would tell which addresses have an account
        # (audit S12).
        await session.commit()
        raise AppError(
            code=ErrorCode.AUTH_CREDENTIALS_INVALID,
            status_code=401,
            message="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_agent = request.headers.get("user-agent")
    if second_factor.enabled(user):
        email = user.email
        token = await second_factor.issue_challenge(
            session, user, ip=ip, user_agent=user_agent
        )
        await session.commit()
        security_log.info("password ok for %s from %s, second factor asked", email, ip)
        return SecondFactorChallenge(
            challenge=token,
            expires_in=settings.SECOND_FACTOR_CHALLENGE_MINUTES * 60,
        )
    await crud.note_login_success(session, user, ip)
    # A group requires a second factor the account does not have: a session
    # for « Mon compte » only, until it enrols (``app.api.deps``).
    enrolment_only = await second_factor.required(session, user.id)
    security_log.info(
        "login ok for %s from %s%s",
        user.email,
        ip,
        ", enrolment only" if enrolment_only else "",
    )
    return await open_console_session(
        session,
        response,
        user,
        ip=ip,
        user_agent=user_agent,
        auth_method="password",
        enrolment_only=enrolment_only,
    )


async def open_console_session(
    session: SessionDep,
    response: Response,
    user: User,
    *,
    ip: str,
    user_agent: str | None,
    auth_method: str,
    enrolment_only: bool = False,
) -> Token:
    """The end of every login: the session, its tokens, the cookie, the
    commit. Password, password and code, and the directory all end here."""
    row, refresh_token = await auth_sessions.open_session(
        session,
        user.id,
        user_agent=user_agent,
        ip=ip,
        auth_method=auth_method,
        enrolment_only=enrolment_only,
    )
    access_token = security.create_access_token(user.id, session_id=row.id)
    _set_refresh_cookie(response, refresh_token, row.expires_at)
    await session.commit()
    return Token(access_token=access_token)


class SecondFactorIn(BaseModel):
    challenge: str = Field(min_length=1, max_length=200)
    # Six digits, or a backup code (« XXXXX-XXXXX »).
    code: str = Field(min_length=1, max_length=40)


@router.post(
    "/login/second-factor",
    response_model=Token,
    dependencies=[
        Depends(
            ratelimit.rate_limit(
                ratelimit.second_factor_limiter, "auth.login.second_factor"
            )
        )
    ],
)
async def login_second_factor(
    request: Request, response: Response, payload: SecondFactorIn, session: SessionDep
) -> Token:
    """Redeem a login challenge with a code and open the session.

    One answer for every refusal — wrong code, replayed code, expired, spent
    or exhausted challenge, locked second factor — since telling them apart
    helps only whoever is guessing.
    """
    ip = client_ip(request)
    outcome = await second_factor.redeem(session, payload.challenge, payload.code)
    if outcome.user is None:
        failed = outcome.failed_user
        failed_email = failed.email if failed is not None else None
        if failed is not None and outcome.just_locked:
            audit.record(
                session,
                actor=failed.email,
                action="user.second_factor_locked",
                resource_type="user",
                resource_id=str(failed.id),
                details={
                    "locked_until": failed.totp_locked_until.isoformat()
                    if failed.totp_locked_until
                    else None
                },
            )
        await session.commit()
        security_log.warning(
            "second factor refused for %s from %s%s",
            failed_email or "an unknown challenge",
            ip,
            " (locked)" if outcome.just_locked else "",
        )
        raise AppError(
            code=ErrorCode.AUTH_SECOND_FACTOR_INVALID,
            status_code=401,
            message="Invalid code, or the login has expired",
        )
    user = outcome.user
    await crud.note_login_success(session, user, ip)
    if outcome.used_backup:
        audit.record(
            session,
            actor=user.email,
            action="auth.backup_code_used",
            resource_type="user",
            resource_id=str(user.id),
            details={
                "remaining": await second_factor.backup_codes_left(session, user.id)
            },
        )
    security_log.info("login ok for %s from %s with a second factor", user.email, ip)
    return await open_console_session(
        session,
        response,
        user,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        auth_method="password+totp",
    )


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
    # A session in use keeps its address among the account's known ones
    # (written at most once a day): otherwise an owner who never logs out
    # would stop being known the day the session's ceiling makes them log in.
    await login_addresses.note_success(
        session, user.id, client_ip(request), utcnow(), proved=False
    )
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
    session: SessionDep,
    user: CurrentUser,
    permissions: CurrentPermissions,
    current: OptionalAuthSession,
) -> UserOut:
    """Return the current authenticated user."""
    return await _profile(session, user, permissions, current)


# Bounds on the preference document, generous for what the console stores
# (a few dozen column names) and tight enough that the endpoint cannot be used
# as free storage: so many keys, so many bytes once serialised.
PREFERENCES_MAX_KEYS = 50
PREFERENCES_MAX_BYTES = 16 * 1024
PREFERENCES_KEY_MAX_LENGTH = 64
# …and so many levels of lists and objects inside one value. A list of
# column names is one level; a value nested hundreds deep fits in the byte
# budget, was stored, and could not be served back: every ``GET /auth/me``
# of the account then failed, and its console no longer loaded.
PREFERENCES_MAX_DEPTH = 8


def unservable(value: Any) -> str | None:
    """Why a preference value cannot be stored and handed back, None when
    it can: nested beyond PREFERENCES_MAX_DEPTH, or holding what a JSON
    document cannot — a string that is not Unicode text (a lone surrogate,
    which ``"\\ud83d"`` in a body decodes to), a number that is not one
    (``NaN``, ``Infinity``: Python reads them, PostgreSQL refuses them).

    Walked with a stack, not by recursion: the depth is the caller's.
    """
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, dict | list):
            if depth >= PREFERENCES_MAX_DEPTH:
                return f"nested more than {PREFERENCES_MAX_DEPTH} levels deep"
            children = (
                [*item.keys(), *item.values()] if isinstance(item, dict) else item
            )
            pending.extend((child, depth + 1) for child in children)
        elif isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return "a string that is not valid Unicode text"
        elif isinstance(item, float) and not math.isfinite(item):
            return "a number that is not finite"
    return None


class ProfileUpdate(BaseModel):
    """Self-service profile update — only the supplied fields are changed."""

    email_preference: EmailPreference | None = None
    # Sent as null: back to « follow the browser ». Not sent: left alone.
    language: Language | None = None
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
        for key, item in value.items():
            if not key or len(key) > PREFERENCES_KEY_MAX_LENGTH:
                raise ValueError(
                    f"preference keys must be 1–{PREFERENCES_KEY_MAX_LENGTH} characters"
                )
            # Checked on what is sent, not on the merged document: an account
            # must never be able to store what its profile cannot serve.
            reason = unservable(key) or unservable(item)
            if reason is not None:
                raise ValueError(f"preference {key!a}: {reason}")
        return value


def check_preferences(merged: dict[str, Any]) -> None:
    """Raise ``AppError`` (422) when the merged document exceeds the bounds —
    measured on it rather than on the patch, since the caller's patch may be
    small and the accumulated document large."""
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


async def _merge_stored_preferences(
    session: SessionDep, user: User, patch: dict[str, Any]
) -> None:
    """Apply ``patch`` to the stored document in one statement.

    Merged by the database (``preferences || set - removed``) on the row as it
    is when the UPDATE takes its lock, not on the copy this request read: two
    pages saving different keys at the same instant both keep theirs. Read
    in Python and written back whole, the later write used to erase the
    earlier one's key. The bounds are checked on the merged document the
    statement returns; refusing raises, and the transaction is not committed.
    """
    to_set = {k: v for k, v in patch.items() if v is not None}
    to_drop = [k for k, v in patch.items() if v is None]
    stored = User.__table__.c.preferences  # type: ignore[attr-defined]
    merged_expr = stored.op("||", return_type=JSONB)(
        bindparam("to_set", to_set, type_=JSONB)
    ).op("-", return_type=JSONB)(bindparam("to_drop", to_drop, type_=ARRAY(Text)))
    result = await session.exec(
        update(User)
        .where(col(User.id) == user.id)
        .values(preferences=merged_expr, updated_at=utcnow())
        .returning(stored)
    )
    check_preferences(result.scalar_one())


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileUpdate,
    user: CurrentUser,
    session: SessionDep,
    permissions: CurrentPermissions,
    current: CurrentAuthSession,
) -> UserOut:
    """Update one's own profile.

    Self-service, and deliberately narrow: what an account may change about
    itself here is how much mail it receives. Its groups, its address and
    whether it is active stay with an administrator (``/users``) — a read-only
    operator who could edit their own row would not be read-only for long.
    """
    # Read before the commit, which expires the row.
    enrolment_only = current.enrolment_only
    if payload.preferences is not None:
        await _merge_stored_preferences(session, user, payload.preferences)
    if payload.email_preference is not None:
        user.email_preference = payload.email_preference
    if "language" in payload.model_fields_set:
        user.language = payload.language
    user.updated_at = utcnow()
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return await _profile(session, user, permissions, enrolment_only=enrolment_only)


# --- Password lifecycle -----------------------------------------------------


class PasswordChange(BaseModel):
    """Self-service password change: the current password is the proof."""

    current_password: str
    new_password: Password


# Wrong current passwords one session may type on « changer mon mot de
# passe » before it is ended (audit S04, T07).
PASSWORD_CHANGE_SESSION_FAILURES = 5


@router.post("/password", status_code=204)
async def change_password(
    request: Request,
    payload: PasswordChange,
    user: CurrentUser,
    current: CurrentAuthSession,
    session: SessionDep,
) -> None:
    """Change one's own password.

    Every session of the account is revoked — the one this request came
    through included — so the console re-authenticates right after.
    """
    _reject_external(user)
    # Keyed on the session, not the account (audit T07): a stolen session
    # guesses from anywhere, and each check is a bcrypt the whole API would
    # wait for (audit S04) — but an account-wide budget was one the thief
    # spent for the owner, whose own sessions then could not change the
    # password either. A session cannot beget another without the password,
    # so per session bounds the thief all the same.
    ratelimit.check_account(
        ratelimit.password_change_limiter, str(current.id), "auth.password"
    )
    # That limiter is this process's, and can be switched off: the budget
    # that holds is the count on the session's row, read under its lock
    # before any check. Guesses sent together through one session queue
    # here; once five have failed, the others find the session ended and
    # cost no bcrypt. The rows are locked in the order every request takes
    # them in (``crud.lock_account``) — the account's, the session's, and
    # later the address's: a wrong password used to take them the other way
    # round, and could deadlock with a refresh of the same session from
    # another tab, or with a reset of the password.
    account = await crud.lock_account(session, user)
    locked = (
        await auth_sessions.lock_row(session, current) if account is not None else None
    )
    if (
        locked is None
        or not auth_sessions.is_live(locked)
        or locked.password_failures >= PASSWORD_CHANGE_SESSION_FAILURES
    ):
        if locked is not None:
            auth_sessions.revoke(session, locked)
            await session.commit()
        raise AppError(
            code=ErrorCode.AUTH_SESSION_INVALID,
            status_code=401,
            message="This session has ended",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not await security.check_password(
        payload.current_password, user.hashed_password
    ):
        # Guessing the password of an open session is guessing at a login:
        # it counts towards the lock like one. The session that spends its
        # budget, or whose failure locks the account, is ended — the
        # guesser's token with it — and the owner's other sessions are left
        # alone: they never typed a wrong password.
        ip = client_ip(request)
        failures = await auth_sessions.note_password_failure(session, current)
        lock = await crud.record_failure(session, user, ip)
        if lock is not None:
            details: dict[str, Any] = {
                "locked_until": lock.until.isoformat(),
                "via": "password_change",
            }
            if lock.slow:
                details["slow"] = True
            audit.record(
                session,
                actor=user.email,
                action="user.locked",
                resource_type="user",
                resource_id=str(user.id),
                details=details,
            )
        if lock is not None or failures >= PASSWORD_CHANGE_SESSION_FAILURES:
            auth_sessions.revoke(session, current)
            audit.record(
                session,
                actor=user.email,
                action="auth.session_revoked",
                resource_type="user",
                resource_id=str(user.id),
                details={
                    "current": True,
                    "via": "password_change",
                    "failures": failures,
                    "user_agent": current.user_agent,
                    "ip": current.ip,
                    "created_at": current.created_at.isoformat(),
                },
            )
            security_log.warning(
                "password change: %d wrong current passwords for %s from %s, "
                "session %s ended",
                failures,
                user.email,
                ip,
                current.id,
            )
        await session.commit()
        raise AppError(
            code=ErrorCode.PASSWORD_CURRENT_INVALID,
            status_code=400,
            message="Current password is incorrect",
        )
    if payload.new_password == payload.current_password:
        # Checked once the current password is proved, so it tells nothing to
        # whoever is guessing it. Changing a password to itself would end
        # every session for nothing — and is mostly a form filled in the
        # wrong order.
        raise AppError(
            code=ErrorCode.PASSWORD_UNCHANGED,
            status_code=400,
            message="The new password must differ from the current one",
        )
    # The owner, proved by the current password: this address stays known.
    await crud.set_password(
        session, user, payload.new_password, chosen_from=client_ip(request)
    )
    await crud.purge_reset_tokens(session, user.id)
    await session.commit()


class PasswordPolicy(BaseModel):
    """What the password forms must say and check: configured on the server
    (PASSWORD_MIN_LENGTH, PASSWORD_RESET_EXPIRE_MINUTES), not fixed in the
    console (audit B24)."""

    min_length: int
    # bcrypt reads no further (``security.PASSWORD_MAX_BYTES``): UTF-8 bytes,
    # not characters.
    max_bytes: int
    reset_expire_minutes: int


@router.get("/password-policy", response_model=PasswordPolicy)
async def password_policy() -> PasswordPolicy:
    """Public: the reset page needs it before anyone is logged in."""
    return PasswordPolicy(
        min_length=settings.PASSWORD_MIN_LENGTH,
        max_bytes=security.PASSWORD_MAX_BYTES,
        reset_expire_minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES,
    )


# How long « mot de passe oublié » takes to answer, whatever it did (audit
# T34). Well above what issuing a link costs (a few writes, tens of
# milliseconds), so that the known and the unknown address answer alike; a
# person waiting for a mail does not notice half a second.
PASSWORD_RESET_REQUEST_SECONDS = 0.5


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
    deactivated account, budget spent, mail failure — so it cannot be used to
    find out which e-mails have a console account; and it answers after the
    same time whatever happens (``PASSWORD_RESET_REQUEST_SECONDS``): issuing
    a link writes to the database where an unknown address only reads, and
    the difference showed (audit T34). Rate-limited per source address: each
    accepted call can put a mail in a known operator's inbox; the link budget
    itself is per account and address (``crud.reset_request_allowed``).
    """
    started = time.monotonic()
    ip = client_ip(request)
    security_log.info("password reset requested for %s from %s", payload.email, ip)
    try:
        await _issue_reset_link(session, payload.email, ip)
    finally:
        elapsed = time.monotonic() - started
        if elapsed > PASSWORD_RESET_REQUEST_SECONDS:
            # Past the floor, the answer's delay tells again what it hides:
            # worth an operator's eye (a database this slow is news anyway).
            security_log.warning(
                "password reset request took %.3f s, above its %.3f s floor",
                elapsed,
                PASSWORD_RESET_REQUEST_SECONDS,
            )
        await asyncio.sleep(max(0.0, PASSWORD_RESET_REQUEST_SECONDS - elapsed))


async def _issue_reset_link(session: SessionDep, email: str, ip: str) -> None:
    """The work behind a reset request. Every path ends its transaction the
    same way (a commit), so none has a step of its own left to time."""
    user = await crud.get_by_email(session, email)
    # An account of the directory has no password to reset (C7).
    if user is None or not user.is_active or user.auth_source != "local":
        await session.commit()
        return
    if not await crud.reset_request_allowed(session, user, ip):
        # From this address, a link mailed less than five minutes ago or
        # three still valid — or ten for the account, from anywhere: nothing
        # voided, nothing sent (audit S14, T34). Same 204 as any request.
        security_log.info(
            "password reset for %s from %s: budget spent, nothing sent",
            user.email,
            ip,
        )
        await session.commit()
        return
    token = await crud.create_reset_token(session, user, ip)
    # Queued before the commit, so the mail and the token it links to are one
    # transaction: no link mailed for a token that was rolled back, no token
    # whose mail was lost to a Mailgun outage — the worker sends with retries.
    emails.send_password_reset(session, user.email, token, language=user.language)
    await session.commit()


class PasswordResetCheck(BaseModel):
    """A reset token to look at, not to redeem."""

    token: str


@router.post(
    "/password-reset/check",
    status_code=204,
    dependencies=[
        Depends(
            ratelimit.rate_limit(
                ratelimit.password_reset_check_limiter, "auth.password_reset_check"
            )
        )
    ],
)
async def check_password_reset(
    payload: PasswordResetCheck, session: SessionDep
) -> None:
    """Whether a reset link can still be redeemed, without redeeming it.

    Public, for the reset page to say « ce lien a expiré » before the owner
    types a new password twice for nothing. 204 when the confirm route would
    accept it, the confirm route's own 400 otherwise. Nothing is consumed,
    locked or written. Rate-limited per address like the reset requests (a
    budget of its own, so reloading the page does not spend theirs): it
    answers whether a token is live, which is what guessing tokens would ask.

    A POST, the token in the body: in a query string, the access log wrote
    down a link that was still good for an hour.
    """
    if not await crud.reset_token_usable(session, payload.token):
        raise AppError(
            code=ErrorCode.PASSWORD_RESET_TOKEN_INVALID,
            status_code=400,
            message="This reset link is invalid or has expired",
        )


class PasswordResetConfirm(BaseModel):
    """Redeem a reset token and set the new password."""

    token: str
    new_password: Password


@router.post("/password-reset/confirm", status_code=204)
async def confirm_password_reset(
    request: Request, payload: PasswordResetConfirm, session: SessionDep
) -> None:
    """Set a new password from a valid reset link. Public endpoint.

    The address the link is redeemed from becomes one of the account's known
    ones: whoever holds the owner's mailbox is the owner, and that is the way
    back in for an owner the lock shuts out (``addresses.shut_out``).
    """
    user = await crud.consume_reset_token(session, payload.token)
    if user is None:
        raise AppError(
            code=ErrorCode.PASSWORD_RESET_TOKEN_INVALID,
            status_code=400,
            message="This reset link is invalid or has expired",
        )
    await crud.set_password(
        session, user, payload.new_password, chosen_from=client_ip(request)
    )
    await session.commit()


# --- Second factor, from « Mon compte » (C7) ----------------------------------


class TotpSetupOut(BaseModel):
    # Shown as text beside the QR code, for an app that cannot scan.
    secret: str
    otpauth_uri: str


class TotpCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


class TotpSetupIn(BaseModel):
    # Proven again: a stolen session must not put a second factor of its
    # own on the account, shutting its owner out.
    current_password: str = Field(min_length=1, max_length=1024)


class TotpDisableIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=1, max_length=40)


class BackupCodesOut(BaseModel):
    # Shown once: the server keeps only their hashes.
    backup_codes: list[str]


def _reject_external(user: User) -> None:
    if user.auth_source != "local":
        raise AppError(
            code=ErrorCode.USER_EXTERNAL_ACCOUNT,
            status_code=409,
            message="This account signs in through the directory",
        )


def _limit_second_factor(current: AuthSession) -> None:
    ratelimit.check_account(
        ratelimit.second_factor_account_limiter, str(current.id), "auth.totp"
    )


def _code_invalid() -> AppError:
    return AppError(
        code=ErrorCode.AUTH_SECOND_FACTOR_CODE_INVALID,
        status_code=400,
        message="This code does not match",
    )


async def _locked_account(session: SessionDep, user: User) -> User:
    account = await crud.lock_account(session, user)
    if account is None:
        raise AppError(
            code=ErrorCode.AUTH_SESSION_INVALID,
            status_code=401,
            message="This session has ended",
        )
    return account


async def step_up(
    session: SessionDep,
    request: Request,
    account: User,
    *,
    password: str | None,
    code: str | None,
    allow_backup: bool = True,
) -> None:
    """Prove the holder again before an action a stolen session must not
    take: the current password (a wrong one counts towards the password's
    lock) and, when given, a code — checked by ``second_factor.verify_code``,
    which counts towards the second factor's lock like a login. The account
    row is locked by the caller. Commits the counters on a refusal."""
    if password is not None and not await security.check_password(
        password, account.hashed_password
    ):
        await crud.record_failure(session, account, client_ip(request))
        await session.commit()
        raise AppError(
            code=ErrorCode.PASSWORD_CURRENT_INVALID,
            status_code=400,
            message="Current password is incorrect",
        )
    if code is None:
        return
    checked = await second_factor.verify_code(
        session, account, code, utcnow(), allow_backup=allow_backup
    )
    if checked.ok:
        return
    if checked.just_locked:
        audit.record(
            session,
            actor=account.email,
            action="user.second_factor_locked",
            resource_type="user",
            resource_id=str(account.id),
            details={
                "locked_until": account.totp_locked_until.isoformat()
                if account.totp_locked_until
                else None,
                "via": "account",
            },
        )
    await session.commit()
    raise _code_invalid()


@router.post("/totp/setup", response_model=TotpSetupOut)
async def totp_setup(
    request: Request,
    payload: TotpSetupIn,
    user: CurrentUser,
    current: CurrentAuthSession,
    session: SessionDep,
) -> TotpSetupOut:
    """Start an enrolment: a fresh secret, pending until a code confirms it.
    Refused while one is active — disable it first — and for an account of
    the directory, whose second factor is the directory's (C7)."""
    _limit_second_factor(current)
    _reject_external(user)
    account = await _locked_account(session, user)
    if second_factor.enabled(account):
        raise AppError(
            code=ErrorCode.AUTH_SECOND_FACTOR_ALREADY_ENABLED,
            status_code=409,
            message="A second factor is already active on this account",
        )
    await step_up(
        session, request, account, password=payload.current_password, code=None
    )
    secret, uri = second_factor.start_enrolment(account)
    session.add(account)
    await session.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=uri)


@router.post("/totp/confirm", response_model=BackupCodesOut)
async def totp_confirm(
    payload: TotpCodeIn,
    user: CurrentUser,
    current: CurrentAuthSession,
    session: SessionDep,
) -> BackupCodesOut:
    """Confirm the pending secret with a first code: the second factor is on,
    and the ten backup codes are handed out. An enrolment-only session
    becomes a full one."""
    _limit_second_factor(current)
    account = await _locked_account(session, user)
    if second_factor.enabled(account) or account.totp_secret is None:
        raise AppError(
            code=ErrorCode.AUTH_SECOND_FACTOR_NOT_ENABLED,
            status_code=409,
            message="No enrolment is pending: start it again",
        )
    now = utcnow()
    step = second_factor.check_code(account, payload.code, now)
    if step is None:
        raise _code_invalid()
    account.totp_enabled_at = now
    account.totp_last_step = step
    account.totp_failed_attempts = 0
    account.totp_locked_until = None
    session.add(account)
    codes = await second_factor.new_backup_codes(session, account.id)
    if current.enrolment_only:
        current.enrolment_only = False
        session.add(current)
    audit.record(
        session,
        actor=account.email,
        action="user.second_factor_enabled",
        resource_type="user",
        resource_id=str(account.id),
        details={},
    )
    await session.commit()
    return BackupCodesOut(backup_codes=codes)


@router.post("/totp/disable", status_code=204)
async def totp_disable(
    request: Request,
    payload: TotpDisableIn,
    user: CurrentUser,
    current: CurrentAuthSession,
    session: SessionDep,
) -> None:
    """Turn the second factor off: the current password and a code (or a
    backup code), as for a password change. Refused while a group of the
    account requires it."""
    _limit_second_factor(current)
    account = await _locked_account(session, user)
    if not second_factor.enabled(account):
        raise AppError(
            code=ErrorCode.AUTH_SECOND_FACTOR_NOT_ENABLED,
            status_code=409,
            message="No second factor is active on this account",
        )
    if await second_factor.required(session, account.id):
        raise AppError(
            code=ErrorCode.AUTH_SECOND_FACTOR_REQUIRED_BY_GROUP,
            status_code=409,
            message="A group of this account requires a second factor",
        )
    await step_up(
        session,
        request,
        account,
        password=payload.current_password,
        code=payload.code,
    )
    await second_factor.clear(session, account)
    audit.record(
        session,
        actor=account.email,
        action="user.second_factor_disabled",
        resource_type="user",
        resource_id=str(account.id),
        details={},
    )
    await session.commit()


@router.post("/totp/backup-codes", response_model=BackupCodesOut)
async def totp_backup_codes(
    request: Request,
    payload: TotpCodeIn,
    user: CurrentUser,
    current: CurrentAuthSession,
    session: SessionDep,
) -> BackupCodesOut:
    """Ten new backup codes against a current code; the old ones stop
    working."""
    _limit_second_factor(current)
    account = await _locked_account(session, user)
    if not second_factor.enabled(account):
        raise AppError(
            code=ErrorCode.AUTH_SECOND_FACTOR_NOT_ENABLED,
            status_code=409,
            message="No second factor is active on this account",
        )
    # The app's code only: a backup code must not buy ten new ones.
    await step_up(
        session, request, account, password=None, code=payload.code, allow_backup=False
    )
    codes = await second_factor.new_backup_codes(session, account.id)
    audit.record(
        session,
        actor=account.email,
        action="user.backup_codes_regenerated",
        resource_type="user",
        resource_id=str(account.id),
        details={},
    )
    await session.commit()
    return BackupCodesOut(backup_codes=codes)


# --- Personal API tokens (C8) -------------------------------------------------


class ApiTokenOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    can_write: bool
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    last_used_ip: str | None
    revoked_at: datetime | None


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Read-only unless asked.
    can_write: bool = False
    days: int = Field(default=90, ge=1, le=365)

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ApiTokenCreated(ApiTokenOut):
    # Shown now and never again.
    token: str


def _token_out(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "can_write": row.can_write,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "last_used_at": row.last_used_at,
        "last_used_ip": row.last_used_ip,
        "revoked_at": row.revoked_at,
    }


@router.get("/api-tokens", response_model=list[ApiTokenOut])
async def list_api_tokens(
    session: SessionDep, user: CurrentUser, current: CurrentAuthSession
) -> list[ApiTokenOut]:
    """The account's own tokens, live ones first, newest first."""
    from app.features.api_token.models import ApiToken

    rows = await session.exec(
        select(ApiToken)
        .where(col(ApiToken.user_id) == user.id)
        .order_by(col(ApiToken.created_at).desc())
        .limit(100)
    )
    return [ApiTokenOut(**_token_out(r)) for r in rows.all()]


@router.post("/api-tokens", response_model=ApiTokenCreated, status_code=201)
async def create_api_token(
    payload: ApiTokenCreate,
    session: SessionDep,
    user: CurrentUser,
    current: CurrentAuthSession,
    permissions: CurrentPermissions,
) -> ApiTokenCreated:
    """A token for a script acting on behalf of this account: with at most
    its rights and scope, read-only unless asked, for 1 to 365 days. The
    clear value is returned once. From a console session only — a token
    does not make tokens."""
    from app.features.api_token import crud as api_tokens
    from app.features.user.permissions import Action, Resource, has_permission

    if not has_permission(permissions, Resource.API_TOKEN.value, Action.WRITE.value):
        raise AppError(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            status_code=403,
            message="Making API tokens is not granted to this account",
        )
    if await api_tokens.active_count(session, user.id) >= api_tokens.MAX_ACTIVE:
        raise AppError(
            code=ErrorCode.API_TOKEN_TOO_MANY,
            status_code=409,
            message=f"{api_tokens.MAX_ACTIVE} live tokens at most",
        )
    row, clear = api_tokens.create(
        session,
        user.id,
        name=payload.name,
        can_write=payload.can_write,
        days=payload.days,
    )
    audit.record(
        session,
        actor=user.email,
        action="api_token.create",
        resource_type="user",
        resource_id=str(user.id),
        details={
            "name": payload.name,
            "prefix": row.prefix,
            "can_write": payload.can_write,
            "expires_at": row.expires_at.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(row)
    return ApiTokenCreated(**_token_out(row), token=clear)


@router.delete("/api-tokens/{token_id}", status_code=204)
async def revoke_api_token(
    token_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    current: CurrentAuthSession,
) -> None:
    from app.features.api_token.models import ApiToken

    row = await session.get(ApiToken, token_id, with_for_update=True)
    if row is None or row.user_id != user.id:
        raise AppError(
            code=ErrorCode.API_TOKEN_NOT_FOUND, status_code=404, message="No such token"
        )
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        session.add(row)
        audit.record(
            session,
            actor=user.email,
            action="api_token.revoke",
            resource_type="user",
            resource_id=str(user.id),
            details={"name": row.name, "prefix": row.prefix},
        )
    await session.commit()
