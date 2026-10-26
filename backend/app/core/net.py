"""Request-level network helpers."""

from contextvars import ContextVar

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

# The client address of the request being served, set once per request by a
# middleware (app.main). Read where a request object is not at hand — the
# audit log above all, written from thirty-odd call sites.
current_client_ip: ContextVar[str | None] = ContextVar(
    "current_client_ip", default=None
)


def client_ip(request: Request) -> str:
    """Best client address available for this request.

    In production the backend has no published port: everything arrives
    through Caddy, which appends the real peer to ``X-Forwarded-For`` — the
    rightmost entry is therefore the one written by *our* proxy and the one to
    trust (anything left of it is client-supplied). Without the header (dev
    override's direct port, tests) the socket peer is the client itself.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"


class ClientIPMiddleware:
    """Record each HTTP request's client address in ``current_client_ip``.

    Pure ASGI rather than ``BaseHTTPMiddleware``: no response buffering, and the
    variable is set in the very context the endpoint runs in.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = current_client_ip.set(client_ip(Request(scope)))
        try:
            await self.app(scope, receive, send)
        finally:
            current_client_ip.reset(token)
