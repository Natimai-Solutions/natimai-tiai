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
  route sees it: one place for every field of every block. So is a lone
  surrogate — half of a UTF-16 pair, which JSON can spell (``\\ud800``) and
  UTF-8 cannot carry to the database: the same 500 by another character.
* **every other route** — a NUL in a JSON body, a query string, the path or a
  urlencoded form is refused as 422 ``request.validation_error``. Multipart
  bodies are let through unread: a package upload can weigh 2 GiB, and its
  text fields are the upload route's own business — ``refuse_nul_in_form``
  is that business for a route whose form reaches the database (the login).

A body nested deeper than the JSON parser goes is not JSON as far as this
middleware is concerned: it is handed on untouched, and the route answers it
as it answers the same body without a control character.
"""

import json
import re
from typing import Any

from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.validation import PREFIX

# C0 controls minus \t \n \r, and the surrogates left once the parser has
# joined every well-formed pair into its character: the lone ones.
_STRIPPED = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]")
# How such a character can be spelled in JSON text: a \u escape of the C0
# range or of a surrogate, the two short escapes of the set (\b, \f), the
# raw byte, which makes the JSON invalid anyway, or a surrogate's own three
# bytes (ED A0..BF xx) — not UTF-8, but read by Python's JSON parser all the
# same, into the very character the escape gives. A cheap scan before any
# parse: most bodies carry none, and are passed on untouched. A false
# positive (an escaped backslash followed by "b", an escaped pair that is
# well formed) only costs the parse.
_JSON_CONTROL = re.compile(
    rb"\\u00[01][0-9a-fA-F]|\\u[dD][89a-fA-F]|\\[bf]|[\x00-\x08\x0b\x0c\x0e-\x1f]"
    rb"|\xed[\xa0-\xbf]"
)
_JSON_NUL = re.compile(rb"\\u0000|\x00")
_URL_NUL = re.compile(rb"%00|\x00")

NUL_REFUSED = "Caractère nul refusé"
TOO_NESTED = "Corps JSON trop imbriqué"


def _strip(text: str) -> str:
    return _STRIPPED.sub("", text)


def strip_controls(value: Any) -> Any:
    """``value`` with the C0 controls (but \\t \\n \\r) and the lone surrogates
    removed from every string.

    Walked with a stack of its own rather than by recursion: the JSON parser
    reads tens of thousands of levels, Python's call stack holds a thousand,
    and a body nested between the two must not end as a ``RecursionError``.
    """
    holder: list[Any] = [None]
    # (container, key or index, raw value to clean into that place)
    todo: list[tuple[Any, Any, Any]] = [(holder, 0, value)]
    while todo:
        target, key, raw = todo.pop()
        if isinstance(raw, str):
            target[key] = _strip(raw)
        elif isinstance(raw, list):
            items: list[Any] = [None] * len(raw)
            target[key] = items
            todo.extend((items, i, v) for i, v in enumerate(raw))
        elif isinstance(raw, dict):
            keys = [_strip(k) if isinstance(k, str) else k for k in raw]
            # Filled in first, so the keys keep their order; pushed in
            # reverse, so that of two keys the stripping makes one, the last
            # is the one written last — what a JSON parser does with a
            # repeated key.
            cleaned: dict[Any, Any] = dict.fromkeys(keys)
            target[key] = cleaned
            todo.extend(
                (cleaned, k, v)
                for k, v in reversed(list(zip(keys, raw.values(), strict=True)))
            )
        else:
            target[key] = raw
    return holder[0]


def _contains_nul(value: Any) -> bool:
    """Whether any string of ``value`` holds a NUL — iterative, like
    ``strip_controls`` and for the same reason."""
    todo = [value]
    while todo:
        item = todo.pop()
        if isinstance(item, str):
            if "\x00" in item:
                return True
        elif isinstance(item, list):
            todo.extend(item)
        elif isinstance(item, dict):
            todo.extend(item.keys())
            todo.extend(item.values())
    return False


# The console words these by code (plan console bilingue); the message
# stays as it was, without « Value error, »: it never had it.
_CODES = {NUL_REFUSED: "nul_refused", TOO_NESTED: "too_nested"}


def _raw_refusal(code: str, message: str) -> dict[str, Any]:
    return {"loc": [], "msg": message, "type": PREFIX + code, "params": {}}


def _nul_refusal() -> AppError:
    return AppError(
        code=ErrorCode.REQUEST_VALIDATION_ERROR,
        status_code=422,
        message=NUL_REFUSED,
        details={"errors": [_raw_refusal("nul_refused", NUL_REFUSED)]},
    )


async def refuse_nul_in_form(request: Request) -> None:
    """Dependency: refuse a NUL in any text field of the request's form,
    whatever its encoding — the same 422 the middleware answers.

    For a route whose form fields reach the database. The middleware covers a
    urlencoded form before routing; a multipart one it does not read, and
    FastAPI's form parameters accept both. The form is parsed once: this
    reads the parse the route's own parameters use.
    """
    form = await request.form()
    for key, value in form.multi_items():
        if "\x00" in key or (not isinstance(value, UploadFile) and "\x00" in value):
            raise _nul_refusal()


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


async def _refuse(send: Send, message: str = NUL_REFUSED) -> None:
    body = json.dumps(
        {
            "error": {
                "code": ErrorCode.REQUEST_VALIDATION_ERROR.value,
                "message": message,
                "details": {"errors": [_raw_refusal(_CODES[message], message)]},
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


class _TooNested(Exception):
    """A body the parser read but the encoder cannot write back."""


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
                try:
                    body = self._cleaned(body)
                except _TooNested:
                    await _refuse(send, TOO_NESTED)
                    return
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
        except (ValueError, RecursionError):
            # Not JSON — or nested deeper than the parser goes, which raises
            # RecursionError and not ValueError: the route's own parsing
            # answers it, as it does without a control character.
            return body
        try:
            return json.dumps(strip_controls(data), ensure_ascii=False).encode()
        except RecursionError:
            # Read, but too deep to write back (the encoder gives up a little
            # before the parser does). Handing the body on as it came would
            # let its control characters through: refused instead.
            raise _TooNested from None

    @staticmethod
    def _json_has_nul(body: bytes) -> bool:
        try:
            return _contains_nul(json.loads(body))
        except (ValueError, RecursionError):
            # A raw NUL makes the JSON invalid: refused here rather than left
            # to a parser whose error would name no field anyway. Any other
            # body that does not parse — nested too deep included — is the
            # route's to answer.
            return b"\x00" in body
