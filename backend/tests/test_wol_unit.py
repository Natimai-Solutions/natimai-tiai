"""Wake-on-LAN: the packet and its destinations (no database, no socket).

The addressing rules are where this feature is right or wrong — a magic packet
is trivial to build and useless if broadcast on the wrong segment — so they are
pure functions, tested here without a network.
"""

import pytest

from app.features.wol.packet import (
    broadcast_for,
    destinations_for,
    magic_packet,
    normalize_mac,
    parse_mac,
)


@pytest.mark.parametrize(
    "value",
    [
        "AA:BB:CC:DD:EE:FF",  # what the agent sends
        "aa:bb:cc:dd:ee:ff",  # …in the case a hand-written config uses
        "AA-BB-CC-DD-EE-FF",  # Windows' own ipconfig /all
        "AABB.CCDD.EEFF",  # Cisco, three groups of four
        "AABBCCDDEEFF",  # no separator at all
        "  AA:BB:CC:DD:EE:FF  ",
    ],
)
def test_every_common_notation_parses_to_the_same_address(value):
    """One stored shape, whatever an agent or an operator wrote.

    A mixed column would have the same adapter look like two, and the console
    show a MAC that matches nothing an administrator can search for.
    """
    assert normalize_mac(value) == "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "not a mac",
        "AA:BB:CC:DD:EE",  # five bytes
        "AA:BB:CC:DD:EE:FF:00",  # seven
        "GG:BB:CC:DD:EE:FF",  # not hex
        # Reported by some virtual adapters in place of nothing, and a valid
        # six-byte string: a packet naming it would be sent and wake nothing.
        "00:00:00:00:00:00",
        # The Ethernet broadcast address is not a wake target either.
        "FF:FF:FF:FF:FF:FF",
    ],
)
def test_what_is_not_a_wake_target_is_refused(value):
    """None rather than an exception: the heartbeat degrades, it never 422s."""
    assert parse_mac(value) is None
    assert normalize_mac(value) is None


def test_magic_packet_is_the_sync_stream_then_the_mac_sixteen_times():
    """The frame the sleeping NIC watches for — 102 bytes, and nothing else."""
    packet = magic_packet("AA:BB:CC:DD:EE:FF")

    assert len(packet) == 6 + 6 * 16
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("AABBCCDDEEFF") * 16


def test_magic_packet_refuses_what_it_cannot_address():
    with pytest.raises(ValueError):
        magic_packet("00:00:00:00:00:00")


@pytest.mark.parametrize(
    ("ip", "prefixlen", "expected"),
    [
        ("192.168.1.42", 24, "192.168.1.255"),
        ("10.4.7.9", 16, "10.4.255.255"),
        # A /22 parc: the derived address is wrong at /24 and right here, which
        # is the whole reason the prefix is a setting and not a constant.
        ("172.20.5.30", 22, "172.20.7.255"),
        # No broadcast to compute: ipaddress hands back the host, and the packet
        # goes out as a unicast. Deliberate — see broadcast_for.
        ("192.168.1.42", 32, "192.168.1.42"),
        # IPv6 has no broadcast at all.
        ("2001:db8::20", 64, None),
        # A poste that never reported an address, and a value that is not one.
        (None, 24, None),
        ("", 24, None),
        ("not-an-address", 24, None),
    ],
)
def test_broadcast_derivation(ip, prefixlen, expected):
    assert broadcast_for(ip, prefixlen) == expected


def test_configured_addresses_replace_the_derived_one():
    """An operator who listed the segments knows better than the derivation.

    Replacing and not adding: a destination nobody configured, quietly appended,
    is a packet on a segment nobody asked to shout on.
    """
    assert destinations_for(
        "192.168.1.42", configured=["10.0.0.255", "10.0.1.255"], prefixlen=24
    ) == ["10.0.0.255", "10.0.1.255"]


def test_the_derivation_carries_a_deployment_that_configured_nothing():
    assert destinations_for("192.168.1.42", configured=[], prefixlen=24) == [
        "192.168.1.255"
    ]


def test_the_mask_the_poste_reported_beats_the_configured_default():
    """The case this exists for: a /16 parc against a server defaulting to /24.

    Without the reported mask the packet goes to 10.4.7.255 — a subnet the poste
    is not on, on a network where the whole 10.4.0.0/16 is one broadcast domain.
    """
    assert destinations_for(
        "10.4.7.9", configured=[], prefixlen=24, reported_prefixlen=16
    ) == ["10.4.255.255"]


def test_the_default_carries_a_poste_that_reported_no_mask():
    """An agent older than the reporting, or an adapter that exposed none."""
    assert destinations_for(
        "10.4.7.9", configured=[], prefixlen=16, reported_prefixlen=None
    ) == ["10.4.255.255"]


def test_a_stored_mask_that_does_not_fit_the_address_falls_back():
    """Degrades to the default instead of costing the poste its wake.

    An IPv6-sized prefix against an IPv4 address is not a value the heartbeat
    accepts today, but the column is older than any future agent and the wake
    has no business failing on it.
    """
    assert destinations_for(
        "10.4.7.9", configured=[], prefixlen=24, reported_prefixlen=64
    ) == ["10.4.7.255"]


def test_configured_addresses_still_beat_a_reported_mask():
    """An operator who listed the segments has said the last word on the matter."""
    assert destinations_for(
        "10.4.7.9", configured=["10.0.0.255"], prefixlen=24, reported_prefixlen=16
    ) == ["10.0.0.255"]


def test_nowhere_to_send_it_is_an_empty_list_not_a_guess():
    """No address, nothing configured → the caller refuses and says so.

    255.255.255.255 is *not* substituted: from a container it reaches the Docker
    bridge and nothing else, so a wake that claimed success would be a wake that
    silently did nothing.
    """
    assert destinations_for(None, configured=[], prefixlen=24) == []
    assert destinations_for("2001:db8::20", configured=[], prefixlen=64) == []
