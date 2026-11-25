"""Sign-in through the directory: OpenID Connect (C7, Entra ID first).

``GET /auth/oidc/start`` sends the browser to the provider; the provider
sends it back to ``GET /auth/oidc/callback``, which opens the session as a
password login would — the refresh cookie set, then a redirect into the
console, whose silent refresh picks the session up. Every failure of the
callback lands on the login page with ``?sso_error=<code>``: a redirect, not
JSON, since the browser is the one following it.

Under ``/api/v1/auth`` on purpose: the console's proxy sends everything else
to the page, and the refresh cookie is scoped to this path.
"""

import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.auth import open_console_session, step_up
from app.core import ratelimit
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.oidc import client, crud
from app.features.oidc.client import OidcError
from app.features.user import crud as crud_users
from app.features.user import second_factor

security_log = logging.getLogger("app.security")

router = APIRouter(prefix="/auth", tags=["auth"])

BROWSER_COOKIE = "tiai_oidc"
BROWSER_COOKIE_PATH = f"{settings.API_V1_STR}/auth/oidc"


class AuthMethods(BaseModel):
    """What the login page offers beside the password."""

    oidc_enabled: bool
    oidc_label: str


@router.get("/methods", response_model=AuthMethods)
async def methods() -> AuthMethods:
    return AuthMethods(oidc_enabled=client.configured(), oidc_label=settings.OIDC_LABEL)


def _set_browser_cookie(response: Response, value: str) -> None:
    # Lax, not Strict: the provider's redirect back is a top-level navigation
    # from another site, on which a Strict cookie is not sent.
    response.set_cookie(
        BROWSER_COOKIE,
        value,
        max_age=crud.LOGIN_MINUTES * 60,
        path=BROWSER_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _login_error(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?sso_error={quote(code)}", status_code=303)
    response.delete_cookie(BROWSER_COOKIE, path=BROWSER_COOKIE_PATH)
    return response


_START_LIMIT = Depends(ratelimit.rate_limit(ratelimit.oidc_limiter, "auth.oidc"))


@router.get("/oidc/start", dependencies=[_START_LIMIT])
async def oidc_start(
    session: SessionDep, redirect: Annotated[str | None, Query(max_length=2000)] = None
) -> RedirectResponse:
    """Send the browser to the provider."""
    if not client.configured():
        return _login_error(ErrorCode.AUTH_OIDC_DISABLED)
    try:
        url, browser = await crud.start(session, redirect=redirect)
    except OidcError as exc:
        security_log.warning("directory sign-in could not start: %s", exc)
        return _login_error(exc.code)
    response = RedirectResponse(url, status_code=303)
    _set_browser_cookie(response, browser)
    return response


class LinkOut(BaseModel):
    # Where the console sends the browser to link the account.
    url: str


class LinkIn(BaseModel):
    # Proven again: a stolen session must not bind the account to a
    # directory identity that then signs in without password nor code.
    current_password: str = Field(min_length=1, max_length=1024)
    # Required when the account has a second factor.
    code: str | None = Field(default=None, max_length=40)


@router.post("/oidc/link", response_model=LinkOut, dependencies=[_START_LIMIT])
async def oidc_link(
    request: Request, payload: LinkIn, session: SessionDep, user: CurrentUser
) -> JSONResponse:
    """« Associer mon compte » from a local account signed in by password:
    the sign-in that follows binds this account to the directory identity
    instead of opening another."""
    if not client.configured():
        raise AppError(
            code=ErrorCode.AUTH_OIDC_DISABLED,
            status_code=409,
            message="Sign-in through the directory is not configured",
        )
    if user.auth_source != "local":
        raise AppError(
            code=ErrorCode.USER_EXTERNAL_ACCOUNT,
            status_code=409,
            message="This account signs in through the directory",
        )
    if user.oidc_subject is not None:
        raise AppError(
            code=ErrorCode.AUTH_OIDC_ALREADY_LINKED,
            status_code=409,
            message="This account is already linked",
        )
    account = await crud_users.lock_account(session, user)
    if account is None:
        raise AppError(
            code=ErrorCode.AUTH_SESSION_INVALID, status_code=401, message="Gone"
        )
    if second_factor.enabled(account) and not payload.code:
        raise AppError(
            code=ErrorCode.AUTH_SECOND_FACTOR_CODE_INVALID,
            status_code=400,
            message="A code is needed for an account with a second factor",
        )
    await step_up(
        session,
        request,
        account,
        password=payload.current_password,
        code=payload.code if second_factor.enabled(account) else None,
    )
    user_id = account.id
    changed_at = account.password_changed_at
    email = account.email
    audit.record(
        session,
        actor=email,
        action="user.directory_link_started",
        resource_type="user",
        resource_id=str(user_id),
        details={},
    )
    try:
        url, browser = await crud.start(
            session,
            redirect="/account",
            link_user_id=user_id,
            link_password_changed_at=changed_at,
        )
    except OidcError as exc:
        raise AppError(code=exc.code, status_code=502, message=str(exc)) from None
    response = JSONResponse({"url": url})
    _set_browser_cookie(response, browser)
    return response


@router.delete("/oidc/link", status_code=204)
async def oidc_unlink(session: SessionDep, user: CurrentUser) -> None:
    """Undo the link of a local account; the password stays what it was."""
    if user.auth_source != "local":
        raise AppError(
            code=ErrorCode.USER_EXTERNAL_ACCOUNT,
            status_code=409,
            message="This account signs in through the directory",
        )
    if user.oidc_subject is None:
        return
    user.oidc_issuer = None
    user.oidc_subject = None
    user.updated_at = utcnow()
    session.add(user)
    audit.record(
        session,
        actor=user.email,
        action="user.directory_unlinked",
        resource_type="user",
        resource_id=str(user.id),
        details={},
    )
    await session.commit()


@router.get("/oidc/callback", dependencies=[_START_LIMIT])
async def oidc_callback(
    request: Request,
    session: SessionDep,
    code: Annotated[str | None, Query(max_length=4000)] = None,
    state: Annotated[str | None, Query(max_length=200)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
    browser: Annotated[str | None, Cookie(alias=BROWSER_COOKIE)] = None,
) -> RedirectResponse:
    """The provider's answer: check it, find the account, open the session."""
    ip = client_ip(request)
    if error is not None:
        # Cancelled on the provider's page, or refused by its policy.
        security_log.info("directory sign-in refused by the provider: %s", error)
        return _login_error(crud.DENIED)
    if not client.configured():
        return _login_error(ErrorCode.AUTH_OIDC_DISABLED)
    if not code or not state:
        return _login_error(client.INVALID)
    try:
        result = await crud.finish(session, state=state, code=code, browser=browser)
    except crud.NoGroupLeft as exc:
        email = exc.user.email
        audit.record(
            session,
            actor=f"oidc:{email}",
            action="user.groups_synced",
            resource_type="user",
            resource_id=str(exc.user.id),
            details={"added": [], "removed": exc.removed, "source": "oidc"},
        )
        await session.commit()
        security_log.warning("directory sign-in refused for %s: no mapped group", email)
        return _login_error(exc.code)
    except OidcError as exc:
        await session.rollback()
        # Refused: the state is spent all the same, never good twice.
        await crud.spend(session, state)
        security_log.warning(
            "directory sign-in refused from %s: %s (%s)", ip, exc.code, exc
        )
        return _login_error(exc.code)
    except IntegrityError:
        # Two callbacks for one new identity at the same instant: the second
        # one finds the account the first just created — at its next try.
        await session.rollback()
        await crud.spend(session, state)
        security_log.warning("directory sign-in raced from %s", ip)
        return _login_error(client.INVALID)

    user = result.user
    email = user.email
    user_id = str(user.id)
    if result.provisioned:
        audit.record(
            session,
            actor=f"oidc:{email}",
            action="user.directory_provisioned",
            resource_type="user",
            resource_id=user_id,
            details={"email": email, "groups": result.added},
        )
    elif result.linked:
        audit.record(
            session,
            actor=email,
            action="user.directory_linked",
            resource_type="user",
            resource_id=user_id,
            details={},
        )
    elif result.added or result.removed:
        audit.record(
            session,
            actor=f"oidc:{email}",
            action="user.groups_synced",
            resource_type="user",
            resource_id=user_id,
            details={
                "added": result.added,
                "removed": result.removed,
                "source": "oidc",
            },
        )
    target = "/account?linked=1" if result.linked else (result.redirect or "/")
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(BROWSER_COOKIE, path=BROWSER_COOKIE_PATH)
    if result.linked:
        # The account was already signed in: the link is the whole outcome.
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return _login_error(crud.ALREADY_LINKED)
        security_log.info("%s linked to a directory identity from %s", email, ip)
        return response
    security_log.info("login ok for %s from %s through the directory", email, ip)
    await open_console_session(
        session,
        response,
        user,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        auth_method="oidc",
    )
    return response
