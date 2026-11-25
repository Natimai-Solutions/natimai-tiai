"""Standardized API error contract (plan §2.14).

Every error response carries the envelope ``{"error": {code, message, details}}``.
The ``code`` is a stable, namespaced, machine-readable string — it, never the
message text, is what the console maps to a localized message. Keep this catalog
in sync with the frontend tables (``frontend/src/i18n/messages/errorCodes.ts``,
one per language of the console).
"""

from __future__ import annotations

import enum
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.validation import PREFIX as VALIDATION_PREFIX

logger = logging.getLogger(__name__)


class ErrorCode(enum.StrEnum):
    """Stable API error codes, mirrored by the frontend."""

    # Authentication / authorization
    AUTH_CREDENTIALS_INVALID = "auth.credentials.invalid"
    AUTH_REQUIRED = "auth.required"
    AUTH_PERMISSION_DENIED = "auth.permission.denied"
    # Refused because it would hand out, or reach, more than the caller holds:
    # a permission they lack, the administrators' group, or an account that is
    # more powerful than they are.
    AUTH_PERMISSION_ESCALATION = "auth.permission.escalation"
    # The account is confined to some sites (``user/scope.py``) and the
    # action reaches beyond them, or is parc-wide by nature.
    AUTH_SCOPE_RESTRICTED = "auth.scope.restricted"
    # The console session is over (logged out, revoked, expired) or the refresh
    # token presented does not open one: log in again.
    AUTH_SESSION_INVALID = "auth.session.invalid"
    AUTH_SESSION_NOT_FOUND = "auth.session.not_found"
    AUTH_TOKEN_MISSING = "auth.token.missing"
    AUTH_TOKEN_INVALID = "auth.token.invalid"
    AUTH_TOKEN_REVOKED = "auth.token.revoked"
    AUTH_ENROLLMENT_SECRET_INVALID = "auth.enrollment_secret.invalid"
    # Passwords
    PASSWORD_CURRENT_INVALID = "password.current.invalid"
    PASSWORD_RESET_TOKEN_INVALID = "password.reset_token.invalid"
    # The new password is the one the account already has.
    PASSWORD_UNCHANGED = "password.unchanged"
    # Resources
    MACHINE_NOT_FOUND = "machine.not_found"
    MACHINE_MERGE_SELF = "machine.merge.self"
    MACHINE_ENROLLMENT_REVOKED = "machine.enrollment.revoked"
    MACHINE_ENROLLMENT_APPROVAL_REQUIRED = "machine.enrollment.approval_required"
    # The poste's token was revoked: nothing can be queued for it until an
    # administrator allows its re-enrollment.
    MACHINE_TOKEN_REVOKED = "machine.token_revoked"
    USER_NOT_FOUND = "user.not_found"
    USER_EMAIL_TAKEN = "user.email.taken"
    USER_SELF_FORBIDDEN = "user.self.forbidden"
    # Refused because it would leave no active account able to manage accounts.
    USER_LOCKOUT = "user.lockout"
    GROUP_NOT_FOUND = "group.not_found"
    GROUP_NAME_TAKEN = "group.name.taken"
    # The built-in groups cannot be deleted, and the administrators' permissions
    # cannot be edited: they are implicit.
    GROUP_BUILTIN_PROTECTED = "group.builtin.protected"
    GROUP_PERMISSION_UNKNOWN = "group.permission.unknown"
    GROUP_SCOPE_UNKNOWN = "group.scope.unknown"
    # The SMTP host or the Mailgun URL changed and the stored secret would
    # follow it: it must be typed again in the same request.
    SETTINGS_EMAIL_SECRET_REQUIRED = "settings.email.secret_required"
    PACKAGE_NOT_FOUND = "package.not_found"
    PACKAGE_INVALID = "package.invalid"
    PACKAGE_FILE_TOO_LARGE = "package.file.too_large"
    PACKAGE_FILE_NAME_INVALID = "package.file.name_invalid"
    # The package exists, the file named does not (any more) — audit B36.
    PACKAGE_FILE_NOT_FOUND = "package.file.not_found"
    PACKAGE_SIGNATURE_INVALID = "package.signature.invalid"
    PACKAGE_NOT_READY = "package.not_ready"
    PACKAGE_RETIRED = "package.retired"
    PACKAGE_REQUIRED = "package.required"
    BUILDING_NOT_FOUND = "building.not_found"
    BUILDING_NAME_TAKEN = "building.name.taken"
    ROOM_NOT_FOUND = "room.not_found"
    ASSET_NOT_FOUND = "asset.not_found"
    # The number on the sticker is already another asset's.
    ASSET_INVENTORY_NUMBER_TAKEN = "asset.inventory_number.taken"
    # A poste has one asset; a second would say two purchase dates.
    ASSET_MACHINE_TAKEN = "asset.machine.taken"
    # An import file that cannot be read: not CSV or Excel, no serial column.
    ASSET_IMPORT_UNREADABLE = "asset.import.unreadable"
    # An import file over the limits — rows or bytes: to be split.
    ASSET_IMPORT_TOO_LARGE = "asset.import.too_large"
    # A command at risk for several postes, inside a forbidden window: sent
    # only once confirmed (``schedule.windows``).
    COMMAND_FORBIDDEN_WINDOW = "command.forbidden_window"
    # Reports (C4): the form is off, the label names no asset, the report
    # is gone, already handled, or names no poste to open a verification on.
    REPORT_DISABLED = "report.disabled"
    REPORT_LABEL_INVALID = "report.label.invalid"
    REPORT_NOT_FOUND = "report.not_found"
    REPORT_ALREADY_HANDLED = "report.already_handled"
    REPORT_NO_MACHINE = "report.no_machine"
    # Reading the directory (plan-lecture-annuaire.md).
    DIRECTORY_READING_REFUSED = "directory.reading_refused"
    DIRECTORY_OFF = "directory.off"
    DIRECTORY_NOT_ELIGIBLE = "directory.not_eligible"
    DIRECTORY_DOMAIN_NOT_FOUND = "directory.domain_not_found"
    DIRECTORY_NOTHING_PENDING = "directory.nothing_pending"
    DIRECTORY_PENDING_CHANGED = "directory.pending_changed"
    REPORT_NO_OPEN_CHECK = "report.no_open_check"
    LICENSE_NOT_FOUND = "license.not_found"
    # Second factor (C7). One code for every refusal of the login step.
    AUTH_SECOND_FACTOR_INVALID = "auth.second_factor.invalid"
    # The session was opened for enrolment only: « Mon compte » until then.
    AUTH_SECOND_FACTOR_NOT_ENROLLED = "auth.second_factor.not_enrolled"
    AUTH_SECOND_FACTOR_REQUIRED_BY_GROUP = "auth.second_factor.required_by_group"
    AUTH_SECOND_FACTOR_ALREADY_ENABLED = "auth.second_factor.already_enabled"
    AUTH_SECOND_FACTOR_NOT_ENABLED = "auth.second_factor.not_enabled"
    # A code typed in « Mon compte » that does not match.
    AUTH_SECOND_FACTOR_CODE_INVALID = "auth.second_factor.code_invalid"
    LICENSE_TOO_MANY = "license.too_many"
    # An account of the directory (C7): no password, no address, no second
    # factor of the console's to change — they live in the directory.
    USER_EXTERNAL_ACCOUNT = "user.external_account"
    # Sign-in through the directory not configured, or the link refused.
    AUTH_OIDC_DISABLED = "auth.oidc.disabled"
    AUTH_OIDC_ALREADY_LINKED = "auth.oidc.already_linked"
    # Webhooks (C8): unknown, destination refused (the detail says why).
    WEBHOOK_NOT_FOUND = "webhook.not_found"
    WEBHOOK_DESTINATION_REFUSED = "webhook.destination_refused"
    WEBHOOK_TOO_MANY = "webhook.too_many"
    # Personal API tokens (C8).
    API_TOKEN_NOT_FOUND = "api_token.not_found"
    API_TOKEN_TOO_MANY = "api_token.too_many"
    # A token used where only the account's own sign-in may act: its
    # password, sessions, second factor, tokens, directory link.
    API_TOKEN_FORBIDDEN_HERE = "api_token.forbidden_here"
    API_TOKEN_SIGN_IN_AGAIN = "api_token.sign_in_again"
    SCHEDULE_NOT_FOUND = "schedule.not_found"
    # A schedule that would run inside a forbidden window.
    SCHEDULE_FORBIDDEN_WINDOW = "schedule.forbidden_window"
    # A one-off planned in the past.
    SCHEDULE_IN_PAST = "schedule.in_past"
    # Two-person approval of mass actions (C10).
    APPROVAL_NOT_FOUND = "approval.not_found"
    # Decided, cancelled or expired already (expired at this very moment
    # included: recorded before the answer).
    APPROVAL_NOT_PENDING = "approval.not_pending"
    APPROVAL_OWN_REQUEST = "approval.own_request"
    # No other account could approve it: nothing is asked.
    APPROVAL_NO_APPROVER = "approval.no_approver"
    APPROVAL_TOO_MANY_PENDING = "approval.too_many_pending"
    # Turning approval on with fewer than two accounts able to approve.
    APPROVAL_NOT_ENOUGH_APPROVERS = "approval.not_enough_approvers"
    # The approval failed — the request is closed, recorded before the
    # answer: the author lost their account or rights, the package was
    # deleted or changed, no poste of the list is left.
    APPROVAL_AUTHOR_NOT_ALLOWED = "approval.author_not_allowed"
    APPROVAL_PACKAGE_GONE = "approval.package_gone"
    APPROVAL_PACKAGE_CHANGED = "approval.package_changed"
    APPROVAL_NOTHING_LEFT = "approval.nothing_left"
    ROOM_NAME_TAKEN = "room.name.taken"
    # ROOM_SOURCE is a directory mode: postes are filed by the directory, and
    # a placement made by hand here would be undone on the next inventory.
    ROOM_PLACEMENT_LOCKED = "room.placement.locked"
    # A room or a building a group's scope names cannot be deleted: the scope
    # would name nothing, and dropping the row could widen the group (C11).
    ROOM_IN_GROUP_SCOPE = "room.in_group_scope"
    INTERVENTION_NOT_FOUND = "intervention.not_found"
    CHECK_NOT_FOUND = "check.not_found"
    CHECK_ALREADY_OPEN = "check.already_open"
    CHECK_CLOSED = "check.closed"
    # The account a check is given to cannot read checks, or does not see
    # the poste (audit S18).
    CHECK_ASSIGNEE_OUT_OF_REACH = "check.assignee.out_of_reach"
    MAINTENANCE_NOT_FOUND = "maintenance.not_found"
    # The owner given to a poste's or a room's maintenance cannot read and
    # record maintenance, or does not see the poste or the room (audit T32).
    MAINTENANCE_OWNER_OUT_OF_REACH = "maintenance.owner.out_of_reach"
    # A visit recorded for a room names postes that are not in it.
    MAINTENANCE_ITEMS_NOT_IN_ROOM = "maintenance.items.not_in_room"
    # A visit with no poste done that says nothing of why (audit T30).
    MAINTENANCE_SESSION_EMPTY = "maintenance.session.empty"
    # Postes added to a visit by someone other than its author.
    MAINTENANCE_SESSION_NOT_AUTHOR = "maintenance.session.not_author"
    # The id a console chose for a new visit is another account's visit.
    MAINTENANCE_SESSION_ID_TAKEN = "maintenance.session.id_taken"
    # Request / generic
    REQUEST_VALIDATION_ERROR = "request.validation_error"
    RATE_LIMITED = "request.rate_limited"
    HTTP_NOT_FOUND = "http.not_found"
    HTTP_ERROR = "http.error"
    INTERNAL_SERVER_ERROR = "internal.server_error"


def violated_constraint(exc: BaseException) -> str | None:
    """The name of the unique constraint (or unique index) an
    ``IntegrityError`` broke, or None for any other integrity failure.

    What turns a race the routes' own checks cannot close — two requests
    creating the same address at the same instant both find it free — into
    the 409 the check would have answered, instead of a 500.
    """
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) != "23505":  # unique_violation
        return None
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name if isinstance(name, str) else ""


class AppError(Exception):
    """Application error carrying a stable, machine-readable code."""

    def __init__(
        self,
        *,
        code: ErrorCode | str,
        status_code: int = 400,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = str(code)
        self.status_code = status_code
        self.message = message or self.code
        self.details = details or {}
        self.headers = headers
        super().__init__(self.message)


def _envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


# Map framework HTTPException statuses to stable codes.
_STATUS_CODE_MAP: dict[int, ErrorCode] = {
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.AUTH_PERMISSION_DENIED,
    404: ErrorCode.HTTP_NOT_FOUND,
}


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render an AppError as the standard envelope."""
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, exc.details),
        headers=exc.headers,
    )


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render request validation failures (422) in the envelope."""
    assert isinstance(exc, RequestValidationError)
    # Slim, JSON-safe view of the errors (drop unserializable ctx). A refusal
    # of ours (``core.validation.invalid``) hands its parameters on, for the
    # console to word it in its reader's language.
    errors = []
    for e in exc.errors():
        item: dict[str, Any] = {
            "loc": list(e.get("loc", ())),
            "msg": e.get("msg"),
            "type": e.get("type"),
        }
        if "params" in e:  # built by hand: ``core.validation.refusal``
            item["params"] = e["params"]
        elif str(e.get("type", "")).startswith(VALIDATION_PREFIX):
            item["params"] = dict(e.get("ctx") or {})
        errors.append(item)
    return JSONResponse(
        status_code=422,
        content=_envelope(
            ErrorCode.REQUEST_VALIDATION_ERROR,
            "Request validation failed",
            {"errors": errors},
        ),
    )


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Wrap framework HTTPExceptions (404, oauth2 401, …) in the envelope."""
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_CODE_MAP.get(exc.status_code, ErrorCode.HTTP_ERROR)
    message = exc.detail if isinstance(exc.detail, str) else str(code)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message, {}),
        headers=getattr(exc, "headers", None),
    )


async def unexpected_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Hide internal details for unexpected 500s outside the local environment."""
    logger.exception("Unhandled server exception", exc_info=exc)
    if settings.ENVIRONMENT == "local":
        message = str(exc).strip() or type(exc).__name__
        return JSONResponse(
            status_code=500,
            content=_envelope(
                ErrorCode.INTERNAL_SERVER_ERROR,
                message,
                {"exception_type": type(exc).__name__},
            ),
        )
    return JSONResponse(
        status_code=500,
        content=_envelope(ErrorCode.INTERNAL_SERVER_ERROR, "Internal server error", {}),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register the API-wide exception handlers."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)
