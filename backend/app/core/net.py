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


def forwarded_address(entry: str) -> str | None:
    """The address an ``X-Forwarded-For`` entry names, in one canonical
    spelling, or None when it names none.

    A proxy may append the client's port (``192.168.1.20:51234``,
    ``[2001:db8::1]:443``): taken verbatim, every connection of one client
    was a client of its own — one rate-limit key each, one "address" each in
    the audit log. The port and the brackets go, and ``ipaddress`` settles
    the spelling (an IPv6 address has many; an IPv4 one mapped into IPv6 is
    that IPv4 address).
    """
    text = entry.strip().strip('"')
    if text.startswith("["):
        # "[v6]" or "[v6]:port".
        host, bracket, rest = text[1:].partition("]")
        if not bracket or (rest and not rest.startswith(":")):
            return None
        text = host
    elif text.count(":") == 1:
        # One colon is "v4:port"; an IPv6 address has at least two.
        text = text.partition(":")[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return str(address)


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

    Every ``X-Forwarded-For`` line counts, joined in order — a client that
    sends its own line ahead of the proxy's must not have the first one read
    — and empty entries are skipped (a header ending in a comma named the
    client ''). From the right, entries that are proxies of ours are passed
    over (a chain of them); with nothing else left, the socket peer it is.

    An entry is read as an address (``forwarded_address``), never returned as
    written. The first one that is not a proxy of ours names the client; if
    it is not an address at all, nothing in the header says who the client
    is — what lies left of it is the client's own word — and the socket peer
    stands in.
    """
    peer = request.client.host if request.client else None
    if not trusted_proxy(peer):
        return peer or "unknown"
    entries = [
        entry.strip()
        for line in request.headers.getlist("x-forwarded-for")
        for entry in line.split(",")
    ]
    entries = [e for e in entries if e]
    for entry in reversed(entries):
        address = forwarded_address(entry)
        if address is None:
            break
        if not trusted_proxy(address):
            return address
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
