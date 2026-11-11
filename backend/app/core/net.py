"""Request-level network helpers."""

import ipaddress
import socket
import time
from contextvars import ContextVar

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings

# The client address of the request being served, set once per request by a
# middleware (app.main). Read where a request object is not at hand — the
# audit log above all, written from thirty-odd call sites.
current_client_ip: ContextVar[str | None] = ContextVar(
    "current_client_ip", default=None
)


_RESOLVE_TTL = 60.0
_resolved: dict[str, tuple[float, frozenset[str]]] = {}


def _proxy_addresses(host: str) -> frozenset[str]:
    """The addresses of a trusted proxy named by host (Caddy's service name
    in the compose network), resolved at most once a minute — a name that
    does not resolve (outside Docker) is remembered as such as long."""
    now = time.monotonic()
    cached = _resolved.get(host)
    if cached and now - cached[0] < _RESOLVE_TTL:
        return cached[1]
    try:
        found = frozenset(str(info[4][0]) for info in socket.getaddrinfo(host, None))
    except OSError:
        found = frozenset()
    _resolved[host] = (now, found)
    return found


def trusted_proxy(peer: str | None) -> bool:
    """Whether the socket peer is a proxy of ours, whose X-Forwarded-For is to
    be believed (audit S28): loopback, ``TRUSTED_PROXIES``, or the address of
    a host in ``TRUSTED_PROXY_HOSTS`` (``caddy`` by default)."""
    if not peer:
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    for network in settings.TRUSTED_PROXIES:
        try:
            if address in ipaddress.ip_network(network, strict=False):
                return True
        except ValueError:
            continue
    return any(peer in _proxy_addresses(h) for h in settings.TRUSTED_PROXY_HOSTS)


def client_ip(request: Request) -> str:
    """Best client address available for this request.

    In production the backend has no published port: everything arrives
    through Caddy, which appends the real peer to ``X-Forwarded-For`` — the
    rightmost entry is therefore the one written by *our* proxy and the one to
    trust (anything left of it is client-supplied). The header is read only
    when the request comes *from* that proxy (``trusted_proxy``): on the dev
    override's published port anyone could write it, and dodge the rate
    limits or sign the audit log with any address (audit S28). Otherwise the
    socket peer is the client itself.
    """
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and trusted_proxy(peer):
        return forwarded.rsplit(",", 1)[-1].strip()
    return peer or "unknown"


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
