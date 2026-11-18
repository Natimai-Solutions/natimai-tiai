"""Unit tests for the error handlers (no app/DB needed)."""

import json
import re
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
    """The catalog is mirrored by the console (``i18n/messages/errorCodes.ts``,
    one table per language): a code added here without its message reaches
    the operator as the backend's fallback text. Each code must be there
    twice, in French and in English — the English table's type also makes a
    missing line fail the console's typecheck. Skipped where the frontend is
    not checked out."""
    import pathlib

    import pytest

    table = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "i18n"
        / "messages"
        / "errorCodes.ts"
    )
    if not table.exists():
        pytest.skip("frontend sources not available")
    source = table.read_text(encoding="utf-8")
    missing = [c.value for c in errors.ErrorCode if source.count(f"'{c.value}'") < 2]
    assert missing == []


_TS_TOKEN = re.compile(
    r"""\s+|//[^\n]*|/\*.*?\*/"""
    r"""|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`"""
    r"""|[A-Za-z_$][\w$]*|[{}:,]|.""",
    re.S,
)


def _catalogue_texts(source: str, declaration: str) -> set[str]:
    """The texts of one language of a console catalogue
    (``frontend/src/i18n/messages/<domain>.ts``), as dotted paths:
    ``const fr = { actions: { machine: { merge: '…' } } }`` gives
    ``actions.machine.merge``. Enough of TypeScript for an object literal of
    strings: keys bare or quoted, comments, trailing commas."""
    start = source.index("{", source.index(declaration))
    tokens = [
        t
        for t in _TS_TOKEN.findall(source, start)
        if t.strip() and not t.startswith(("//", "/*"))
    ]
    texts: set[str] = set()
    stack: list[str] = []
    key = ""
    expect_value = False
    for tok in tokens:
        if tok == "{":
            stack.append(key if expect_value else "")
            key, expect_value = "", False
        elif tok == "}":
            stack.pop()
            if not stack:
                break
        elif tok == ":":
            expect_value = True
        elif tok == ",":
            key, expect_value = "", False
        elif expect_value:
            if tok[0] in "'\"`":
                texts.add(".".join([*filter(None, stack), key]))
            expect_value = False
        else:
            key = tok.strip("'\"")
    return texts


def test_catalogue_texts_reads_nested_keys_in_each_language():
    source = """
    const fr = {
      // a comment { with braces }
      actions: { machine: { merge: 'Fusion', 'quoted_key': "a {x} b" } },
      /** doc */
      resourceTypes: { machine: 'Poste', },
    };
    const en: Translation<typeof fr> = {
      actions: { machine: { merge: 'Merged' } },
      resourceTypes: {},
    };
    """
    assert _catalogue_texts(source, "const fr =") == {
        "actions.machine.merge",
        "actions.machine.quoted_key",
        "resourceTypes.machine",
    }
    assert _catalogue_texts(source, "const en:") == {"actions.machine.merge"}


def test_every_audit_action_has_a_label_in_the_console():
    """Audit B25: an action recorded server-side is named, and filterable,
    in the journal's page — in French and in English: the console's audit
    catalogue (``i18n/messages/audit.ts``) holds a label per action and per
    resource type in each language. Skipped where the frontend is not
    checked out."""
    from pathlib import Path

    import pytest

    root = Path(__file__).resolve().parents[1]
    catalogue = root.parent / "frontend/src/i18n/messages/audit.ts"
    if not catalogue.exists():
        pytest.skip("frontend sources not available")
    source = catalogue.read_text(encoding="utf-8")
    actions: set[str] = set()
    resource_types: set[str] = set()
    for path in (root / "app").rglob("*.py"):
        text = path.read_text()
        actions |= set(re.findall(r'action="([a-z_]+\.[a-z_.]+)"', text))
        resource_types |= set(re.findall(r'resource_type="([a-z_]+)"', text))
    assert actions and resource_types
    for declaration in ("const fr =", "const en:"):
        texts = _catalogue_texts(source, declaration)
        missing = sorted(a for a in actions if f"actions.{a}" not in texts)
        assert missing == [], declaration
        missing = sorted(t for t in resource_types if f"resourceTypes.{t}" not in texts)
        assert missing == [], declaration
