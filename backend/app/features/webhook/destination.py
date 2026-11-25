"""Where a webhook may send (C8).

A webhook makes the server send requests to an address someone typed: the
server's own network is what that must not reach. A destination is refused
unless it is ``https://``, carries no credentials, and resolves only to
public addresses — never loopback, private, link-local (the cloud metadata
service lives there), multicast or reserved ones. An internal chat server is
declared by name in ``WEBHOOK_ALLOWED_HOSTS``, and only those hosts may be
reached over plain ``http://``.

Checked when the webhook is written and again before each send: a name that
resolved to a public address on Monday may not on Tuesday. What remains is
the instant between that check and the connection (DNS rebinding), which a
short-lived resolver could exploit; documented, and bounded by the hosts an
administrator agreed to.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import settings


class DestinationError(ValueError):
    """A destination refused. ``code`` says why, for the console."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


# The reasons, as the console words them.
SCHEME = "webhook.url.scheme"
CREDENTIALS = "webhook.url.credentials"
HOST = "webhook.url.host"
UNRESOLVED = "webhook.url.unresolved"
INTERNAL = "webhook.url.internal"


def _allowed_hosts() -> set[str]:
    raw = settings.WEBHOOK_ALLOWED_HOSTS
    hosts = raw if isinstance(raw, list) else [raw]
    return {h.strip().lower().rstrip(".") for h in hosts if h and h.strip()}


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_private
    )


def parse(url: str) -> tuple[str, str, bool]:
    """The URL's scheme and host, and whether the host is one the operator
    allowed; raises ``DestinationError`` on a form refused outright."""
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise DestinationError(HOST, str(exc)) from exc
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise DestinationError(HOST, "no host")
    if parts.username or parts.password:
        raise DestinationError(CREDENTIALS, "credentials in the URL")
    allowed = host in _allowed_hosts()
    if scheme != "https" and not (scheme == "http" and allowed):
        raise DestinationError(SCHEME, f"scheme {scheme!r}")
    try:
        _ = parts.port
    except ValueError as exc:
        raise DestinationError(HOST, "bad port") from exc
    return scheme, host, allowed


async def check(url: str) -> None:
    """Refuse a destination the server must not reach. Resolves the host."""
    _, host, allowed = parse(url)
    if allowed:
        return
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _public(str(literal)):
            raise DestinationError(INTERNAL, f"{host} is not a public address")
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DestinationError(UNRESOLVED, f"{host}: {exc}") from exc
    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        raise DestinationError(UNRESOLVED, host)
    internal = [a for a in addresses if not _public(a)]
    if internal:
        raise DestinationError(
            INTERNAL, f"{host} resolves to an internal address ({internal[0]})"
        )
