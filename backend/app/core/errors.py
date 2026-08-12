"""Standardized API error contract (plan §2.14).

Every error response carries the envelope ``{"error": {code, message, details}}``.
The ``code`` is a stable, namespaced, machine-readable string — it, never the
message text, is what the console maps to a localized message. Keep this catalog
in sync with the frontend table (``frontend/src/services/errors.ts``).
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

logger = logging.getLogger(__name__)


class ErrorCode(enum.StrEnum):
    """Stable API error codes, mirrored by the frontend."""

    # Authentication / authorization
    AUTH_CREDENTIALS_INVALID = "auth.credentials.invalid"
    AUTH_REQUIRED = "auth.required"
    AUTH_PERMISSION_DENIED = "auth.permission.denied"
    AUTH_TOKEN_MISSING = "auth.token.missing"
    AUTH_TOKEN_INVALID = "auth.token.invalid"
    AUTH_TOKEN_REVOKED = "auth.token.revoked"
    AUTH_ENROLLMENT_SECRET_INVALID = "auth.enrollment_secret.invalid"
    # Passwords
    PASSWORD_CURRENT_INVALID = "password.current.invalid"
    PASSWORD_RESET_TOKEN_INVALID = "password.reset_token.invalid"
    # Resources
    MACHINE_NOT_FOUND = "machine.not_found"
    MACHINE_MERGE_SELF = "machine.merge.self"
    USER_NOT_FOUND = "user.not_found"
    USER_EMAIL_TAKEN = "user.email.taken"
    USER_SELF_FORBIDDEN = "user.self.forbidden"
    # Request / generic
    REQUEST_VALIDATION_ERROR = "request.validation_error"
    HTTP_NOT_FOUND = "http.not_found"
    HTTP_ERROR = "http.error"
    INTERNAL_SERVER_ERROR = "internal.server_error"


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
    # Slim, JSON-safe view of the errors (drop unserializable ctx).
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
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
