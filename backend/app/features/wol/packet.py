"""Wake-on-LAN: the magic packet, and where to send it.

Everything here is pure — a MAC string in, bytes and destination addresses out
— which is what makes the interesting part testable without a network. The
emission itself is one function in ``sender.py``.

Why the server sends this at all, when every other action on a poste is executed
by its agent: the machine is *off*. There is no agent to ask, and no way to
reach the poste over IP. What wakes it is a frame its network adapter recognises
while the rest of the hardware is asleep, and only a host on the same broadcast
domain can put that frame on the wire.
"""

import ipaddress

# An EUI-48 address, and the only kind a magic packet can carry.
MAC_LENGTH = 6

# The frame the NIC watches for: six 0xFF bytes, then the target MAC sixteen
# times over (AMD's Magic Packet specification). Nothing else in the datagram
# matters — not the IP header, not the UDP port — which is why this is built by
# hand rather than negotiated with anything.
_SYNC_STREAM = b"\xff" * 6
_MAC_REPEATS = 16

# Separators seen in the wild: colons (Unix, and what the agent sends), hyphens
# (Windows' own ipconfig /all), dots (Cisco's three groups of four).
_SEPARATORS = ":-. "


def parse_mac(value: str | None) -> bytes | None:
    """Parse a hardware address in any common notation, or return None.

    None rather than an exception for the same reason the heartbeat validators
    degrade instead of raising: this is applied to a value reported by an agent,
    and one unreadable field must not cost the request it rode in on. A caller
    that needs to *refuse* checks the None.

    Two six-byte strings are rejected as well, and neither is a parse failure:
    the all-zero address, which some virtual adapters report in place of nothing,
    and the all-ones broadcast address. A packet naming either would be sent and
    would wake nothing, which is the one outcome worth preventing — the console
    must be able to say "this poste has no wake target" rather than claim it
    tried.
    """
    if not value:
        return None
    cleaned = value.strip()
    for sep in _SEPARATORS:
        cleaned = cleaned.replace(sep, "")
    if len(cleaned) != MAC_LENGTH * 2:
        return None
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError:
        return None
    if raw == bytes(MAC_LENGTH) or raw == b"\xff" * MAC_LENGTH:
        return None
    return raw


def normalize_mac(value: str | None) -> str | None:
    """Canonical "AA:BB:CC:DD:EE:FF", or None when the value is not a MAC.

    One shape in the column and one shape in the console: agents send colons
    today, but a value read off a Windows tool arrives hyphenated, and a stored
    mix would have the same adapter look like two.
    """
    raw = parse_mac(value)
    if raw is None:
        return None
    return ":".join(f"{b:02X}" for b in raw)


def magic_packet(mac: str) -> bytes:
    """Build the magic packet for a MAC. Raises ValueError if it is not one."""
    raw = parse_mac(mac)
    if raw is None:
        raise ValueError(f"not a usable hardware address: {mac!r}")
    return _SYNC_STREAM + raw * _MAC_REPEATS


def broadcast_for(ip: str | None, prefixlen: int) -> str | None:
    """The broadcast address of the subnet ``ip`` sits on, or None.

    None for an IPv6 address, and that is a limitation rather than an oversight:
    IPv6 has no broadcast at all, and the IPv6 way to do this (a link-local
    all-nodes multicast) needs the server to hold an address on the poste's own
    link, which a container does not. A poste that only ever reported an IPv6
    address is woken through ``WOL_BROADCAST_ADDRESSES`` or not at all.

    At /31 and /32 there is no broadcast address to compute and ``ipaddress``
    returns the host itself; the packet then goes out as a unicast, which wakes
    a poste only while some router upstream still remembers its MAC. Deliberate:
    an operator who narrows the prefix that far has asked for exactly that.
    """
    if not ip:
        return None
    try:
        interface = ipaddress.ip_interface(f"{ip}/{prefixlen}")
    except ValueError:
        return None
    if not isinstance(interface, ipaddress.IPv4Interface):
        return None
    return str(interface.network.broadcast_address)


def destinations_for(
    ip: str | None,
    *,
    configured: list[str],
    prefixlen: int,
    reported_prefixlen: int | None = None,
) -> list[str]:
    """Where to send this poste's magic packet, most specific policy first.

    Three sources, in this order, and the order is the argument:

    1. **Configured addresses**, when there are any. An operator who has listed
       them knows the parc's segments, and mixing in a derived address would
       quietly add a destination nobody asked for.
    2. **The mask the poste itself reported** (``reported_prefixlen``), which is
       the one true answer: the adapter holds it, the agent reads it off Windows
       and sends it with the address. A parc in /16 needs no configuration at
       all for this to be right.
    3. **The configured default** (``prefixlen``), for a poste whose agent
       predates the reporting or whose adapter did not expose a mask. A guess,
       and the only one left — which is why it is a setting and not a constant.

    An empty list means "nowhere to send it" — a poste that has never reported
    an address, on a deployment that has not been told where its subnets are.
    The caller reports that as a refusal; 255.255.255.255 is *not* substituted,
    because from a container it reaches the Docker bridge and nothing else, and
    a wake that silently fails is worse than one that says why.
    """
    if configured:
        return list(configured)
    # The fallback runs when the reported mask yields nothing usable, not only
    # when none was reported: a stored value that does not fit the address
    # (an IPv6 prefix against an IPv4, say) must degrade to the default rather
    # than cost the poste its wake.
    for candidate in (reported_prefixlen, prefixlen):
        if candidate is None:
            continue
        derived = broadcast_for(ip, candidate)
        if derived:
            return [derived]
    return []
