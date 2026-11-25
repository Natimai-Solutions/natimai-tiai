"""Where a webhook may send (C8).

A webhook makes the server send requests to an address someone typed: the
server's own network is what that must not reach. A destination is refused
unless it is ``https://``, carries no credentials, and resolves only to
public addresses — never loopback, private, link-local (the cloud metadata
service lives there), shared (CGNAT), site-local, multicast or reserved ones.
An internal chat server is declared by name in ``WEBHOOK_ALLOWED_HOSTS``, and
only those hosts may be reached over plain ``http://``.

Checked when the webhook is written and again before each send: a name that
resolved to a public address on Monday may not on Tuesday. The send then
connects to the very address that was checked (``Target.address``), not to
a second resolution of the name, so a resolver answering differently the
second time (DNS rebinding) gains nothing. The name is read once, in the
form the HTTP client would send it (IDNA 2008), so the name checked is the
name reached.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

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


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 one stands for (mapped, NAT64, 6to4), which
    is what the network reaches in the end."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip.sixtofour is not None:
        return ip.sixtofour
    return None


def _public(address: str) -> bool:
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.teredo is not None:
            return False
        v4 = _embedded_v4(ip)
        if v4 is not None:
            ip = v4
    return bool(
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_private
        and not (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    )


def _ascii_host(url: str) -> str:
    """The host as the HTTP client will send it: IDNA 2008 A-labels, lower
    case, no trailing dot. Read through httpx so the name checked is the
    name reached (``straße`` is ``xn--strae-oqa``, not ``strasse``)."""
    try:
        raw = httpx.URL(url).raw_host
    except (httpx.InvalidURL, UnicodeError, ValueError) as exc:
        raise DestinationError(HOST, "invalid host") from exc
    try:
        host = raw.decode("ascii")
    except UnicodeError as exc:
        raise DestinationError(HOST, "invalid host") from exc
    return host.lower().rstrip(".")


def parse(url: str) -> tuple[str, str, bool]:
    """The URL's scheme and host (ASCII), and whether the host is one the
    operator allowed; raises ``DestinationError`` on a form refused
    outright."""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise DestinationError(HOST, "invalid address") from exc
    scheme = parts.scheme.lower()
    if not parts.hostname:
        raise DestinationError(HOST, "no host")
    if parts.username or parts.password:
        raise DestinationError(CREDENTIALS, "credentials in the URL")
    host = _ascii_host(url)
    labels = host.strip("[]").split(".") if ":" not in host else [host]
    if len(host) > 253 or any(not 0 < len(label) <= 63 for label in labels):
        raise DestinationError(HOST, "invalid host")
    allowed = host in _allowed_hosts()
    if scheme != "https" and not (scheme == "http" and allowed):
        raise DestinationError(SCHEME, f"scheme {scheme!r}")
    try:
        _ = parts.port
    except ValueError as exc:
        raise DestinationError(HOST, "bad port") from exc
    return scheme, host, allowed


@dataclass(frozen=True)
class Target:
    """A checked destination: its ASCII host and, unless the operator
    allowed the host by name, the public address to connect to."""

    host: str
    address: str | None


async def resolve(url: str) -> Target:
    """Refuse a destination the server must not reach; otherwise the address
    to connect to. Resolves the host."""
    _, host, allowed = parse(url)
    if allowed:
        return Target(host, None)
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _public(str(literal)):
            raise DestinationError(INTERNAL, "not a public address")
        return Target(host, str(literal))
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise DestinationError(UNRESOLVED, f"{host} cannot be resolved") from exc
    addresses = [str(info[4][0]) for info in infos]
    if not addresses:
        raise DestinationError(UNRESOLVED, f"{host} cannot be resolved")
    # Every address must be public: the client could pick any of them. The
    # message does not say which internal address the name has — that
    # would map the internal DNS for whoever types names.
    if any(not _public(a) for a in addresses):
        raise DestinationError(INTERNAL, f"{host} resolves to an internal address")
    return Target(host, addresses[0])


async def check(url: str) -> None:
    """Refuse a destination the server must not reach."""
    await resolve(url)
