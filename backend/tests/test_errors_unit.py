"""Unit tests for the error handlers (no app/DB needed)."""

import json
from typing import cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import errors
from app.core.config import settings

_REQ = cast(Request, None)  # handlers ignore the request argument


def _body(resp) -> dict:
    return json.loads(resp.body)


async def test_app_error_handler_builds_envelope():
    exc = errors.AppError(
        code=errors.ErrorCode.MACHINE_NOT_FOUND,
        status_code=404,
        message="nope",
        details={"x": 1},
        headers={"X-Test": "1"},
    )
    resp = await errors.app_error_handler(_REQ, exc)
    assert resp.status_code == 404
    assert _body(resp) == {
        "error": {"code": "machine.not_found", "message": "nope", "details": {"x": 1}}
    }
    assert resp.headers.get("X-Test") == "1"


async def test_app_error_defaults_message_to_code():
    exc = errors.AppError(code=errors.ErrorCode.HTTP_ERROR)
    assert exc.message == "http.error"
    assert exc.status_code == 400


async def test_validation_handler_envelope():
    exc = RequestValidationError(
        [{"loc": ("body", "x"), "msg": "field required", "type": "missing"}]
    )
    resp = await errors.validation_error_handler(_REQ, exc)
    assert resp.status_code == 422
    body = _body(resp)
    assert body["error"]["code"] == "request.validation_error"
    assert body["error"]["details"]["errors"][0]["loc"] == ["body", "x"]


async def test_http_exception_handler_maps_known_status():
    resp = await errors.http_exception_handler(
        _REQ, StarletteHTTPException(status_code=404, detail="missing")
    )
    assert resp.status_code == 404
    assert _body(resp)["error"]["code"] == "http.not_found"


async def test_http_exception_handler_fallback_code():
    resp = await errors.http_exception_handler(
        _REQ, StarletteHTTPException(status_code=418, detail="teapot")
    )
    assert _body(resp)["error"]["code"] == "http.error"


async def test_unexpected_handler_local_includes_details(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    resp = await errors.unexpected_exception_handler(_REQ, ValueError("kaboom"))
    assert resp.status_code == 500
    body = _body(resp)
    assert body["error"]["code"] == "internal.server_error"
    assert body["error"]["message"] == "kaboom"
    assert body["error"]["details"]["exception_type"] == "ValueError"


async def test_unexpected_handler_prod_masks_details(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    resp = await errors.unexpected_exception_handler(_REQ, ValueError("secret-detail"))
    assert resp.status_code == 500
    body = _body(resp)
    assert body["error"]["message"] == "Internal server error"
    assert "secret-detail" not in json.dumps(body)


def test_every_code_has_a_message_in_the_console():
    """The catalog is mirrored by the console (``services/errors.ts``): a code
    added here without its French message reaches the operator as the
    backend's English text. Skipped where the frontend is not checked out."""
    import pathlib

    import pytest

    table = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "services"
        / "errors.ts"
    )
    if not table.exists():
        pytest.skip("frontend sources not available")
    source = table.read_text(encoding="utf-8")
    missing = [c.value for c in errors.ErrorCode if f"'{c.value}'" not in source]
    assert missing == []
