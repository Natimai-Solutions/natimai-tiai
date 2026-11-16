"""Control characters in request bodies — the NUL above all.

PostgreSQL refuses a NUL in a text value outright, so a single ``\\u0000``
anywhere in a request used to end as a 500: for a poste, the whole heartbeat
lost (Defender state, threats, command pickup) for one bad character in a
software name; for the console, an error page instead of an answer.

Two answers, by who is asking, in one middleware placed before routing:

* **agent routes** — a poste's strings are reported, not typed, and refusing
  them would cost everything riding in the same request. The C0 controls
  (but tab, newline and carriage return, which command output is made of)
  are stripped from every string of the JSON body, keys included, before the
  route sees it: one place for every field of every block.
* **every other route** — a NUL in a JSON body, a query string, the path or a
  urlencoded form is refused as 422 ``request.validation_error``. Multipart
  bodies are let through unread: a package upload can weigh 2 GiB, and its
  text fields are the upload route's own business.
"""

import json
import re
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.errors import ErrorCode

# C0 controls minus \t \n \r.
_STRIPPED = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# How such a character can be spelled in JSON text: a \u escape of the C0
# range, the two short escapes of the set (\b, \f), or the raw byte, which
# makes the JSON invalid anyway. A cheap scan before any parse: most bodies
# carry none, and are passed on untouched. A false positive (an escaped
# backslash followed by "b") only costs the parse.
_JSON_CONTROL = re.compile(rb"\\u00[01][0-9a-fA-F]|\\[bf]|[\x00-\x08\x0b\x0c\x0e-\x1f]")
_JSON_NUL = re.compile(rb"\\u0000|\x00")
_URL_NUL = re.compile(rb"%00|\x00")

NUL_REFUSED = "Caractère nul refusé"


def strip_controls(value: Any) -> Any:
    """``value`` with the C0 controls (but \\t \\n \\r) removed from every string."""
    if isinstance(value, str):
        return _STRIPPED.sub("", value)
    if isinstance(value, list):
        return [strip_controls(v) for v in value]
    if isinstance(value, dict):
        return {strip_controls(k): strip_controls(v) for k, v in value.items()}
    return value


def _contains_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, list):
        return any(_contains_nul(v) for v in value)
    if isinstance(value, dict):
        return any(_contains_nul(k) or _contains_nul(v) for k, v in value.items())
    return False


def _header(scope: Scope, name: bytes) -> bytes:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value)
    return b""


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


async def _refuse(send: Send) -> None:
    body = json.dumps(
        {
            "error": {
                "code": ErrorCode.REQUEST_VALIDATION_ERROR.value,
                "message": NUL_REFUSED,
                "details": {
                    "errors": [{"loc": [], "msg": NUL_REFUSED, "type": "value_error"}]
                },
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 422,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class ControlCharMiddleware:
    """See the module docstring."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.agent_prefix = f"{settings.API_V1_STR}/agent/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        agent = str(scope.get("path", "")).startswith(self.agent_prefix)
        if not agent and (
            _URL_NUL.search(scope.get("query_string", b""))
            or _URL_NUL.search(scope.get("raw_path") or b"")
        ):
            await _refuse(send)
            return

        content_type = _header(scope, b"content-type").split(b";")[0].strip().lower()
        is_json = content_type == b"application/json" or content_type.endswith(b"+json")
        is_form = content_type == b"application/x-www-form-urlencoded"
        if not (is_json or (is_form and not agent)):
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        if agent:
            if _JSON_CONTROL.search(body):
                body = self._cleaned(body)
                scope = dict(scope)
                scope["headers"] = [
                    (k, v)
                    for k, v in scope["headers"]
                    if k.lower() != b"content-length"
                ] + [(b"content-length", str(len(body)).encode())]
        elif (is_form and _URL_NUL.search(body)) or (
            is_json and _JSON_NUL.search(body) and self._json_has_nul(body)
        ):
            await _refuse(send)
            return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    def _cleaned(body: bytes) -> bytes:
        try:
            data = json.loads(body)
        except ValueError:
            # Not JSON: the route's own validation answers it.
            return body
        return json.dumps(strip_controls(data), ensure_ascii=False).encode()

    @staticmethod
    def _json_has_nul(body: bytes) -> bool:
        try:
            return _contains_nul(json.loads(body))
        except ValueError:
            # A raw NUL makes the JSON invalid: refused here rather than left
            # to a parser whose error would name no field anyway.
            return b"\x00" in body
