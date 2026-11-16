"""Whose X-Forwarded-For is believed (audit S28), and the OpenAPI pages
outside local development (audit S36)."""

from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from app.core import net


def _request(peer: str, *forwarded: str):
    """A request from ``peer`` carrying one X-Forwarded-For line per value."""
    headers = Headers(raw=[(b"x-forwarded-for", f.encode()) for f in forwarded])
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_a_header_from_anyone_is_ignored(monkeypatch):
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", [])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    # A poste on the LAN hitting the dev port, claiming to be someone else.
    assert net.client_ip(_request("192.168.1.20", "10.9.9.9")) == "192.168.1.20"


def test_our_proxy_is_believed(monkeypatch):
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", ["172.18.0.0/16"])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    assert net.client_ip(_request("172.18.0.5", "1.2.3.4, 192.168.1.20")) == (
        "192.168.1.20"
    )
    assert net.client_ip(_request("127.0.0.1", "192.168.1.30")) == "192.168.1.30"


def test_the_proxy_is_found_by_name(monkeypatch):
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", [])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", ["caddy"])
    monkeypatch.setattr(net, "_proxy_addresses", lambda host: frozenset({"172.18.0.9"}))
    assert net.client_ip(_request("172.18.0.9", "192.168.1.40")) == "192.168.1.40"
    assert net.client_ip(_request("172.18.0.10", "192.168.1.40")) == "172.18.0.10"


def test_every_forwarded_line_counts_in_order(monkeypatch):
    """T40: two header lines — the client's own first, the proxy's last —
    read as one list; the first line used to win."""
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", ["172.18.0.0/16"])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    request = _request("172.18.0.5", "6.6.6.6", "1.2.3.4, 192.168.1.20")
    assert net.client_ip(request) == "192.168.1.20"


def test_empty_forwarded_entries_are_skipped(monkeypatch):
    """T40: a trusted header ending in a comma named the client ''."""
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", ["172.18.0.0/16"])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    assert net.client_ip(_request("172.18.0.5", "192.168.1.20,")) == "192.168.1.20"
    assert net.client_ip(_request("172.18.0.5", " , ,")) == "172.18.0.5"
    assert net.client_ip(_request("172.18.0.5", "")) == "172.18.0.5"


def test_our_own_proxies_in_the_chain_are_passed_over(monkeypatch):
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", ["172.18.0.0/16"])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    request = _request("172.18.0.5", "6.6.6.6, 192.168.1.20, 172.18.0.7")
    assert net.client_ip(request) == "192.168.1.20"


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("192.168.1.20", "192.168.1.20"),
        # A load balancer that appends the client's port.
        ("192.168.1.20:51234", "192.168.1.20"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("[2001:db8::1]", "2001:db8::1"),
        ('"[2001:db8::1]:443"', "2001:db8::1"),
        # One spelling per address.
        ("2001:0DB8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
        ("::ffff:192.168.1.20", "192.168.1.20"),
        ("[::ffff:192.168.1.20]:8080", "192.168.1.20"),
        ("  10.0.0.7  ", "10.0.0.7"),
        ("not-an-address", None),
        ("192.168.1.20:", "192.168.1.20"),
        ("192.168.1.999", None),
        ("192.168.1.20:80:80", None),
        ("[2001:db8::1", None),
        ("[2001:db8::1]443", None),
        ("unknown", None),
        ("_hidden", None),
        ("", None),
    ],
)
def test_a_forwarded_entry_is_read_as_an_address(entry, expected):
    assert net.forwarded_address(entry) == expected


@pytest.mark.parametrize(
    "forwarded,client",
    [
        ("192.168.1.20:51234", "192.168.1.20"),
        ("192.168.1.20:51235", "192.168.1.20"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("6.6.6.6, [2001:DB8:0::1]:51000", "2001:db8::1"),
    ],
)
def test_a_port_does_not_make_a_new_client(monkeypatch, forwarded, client):
    """A proxy appending ports gave one rate-limit key per connection."""
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", ["172.18.0.0/16"])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    assert net.client_ip(_request("172.18.0.5", forwarded)) == client


def test_an_entry_that_is_no_address_falls_back_on_the_socket_peer(monkeypatch):
    """What our proxy wrote is not an address: nothing in the header says who
    the client is, and what lies left of it is the client's own word."""
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", ["172.18.0.0/16"])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    assert net.client_ip(_request("172.18.0.5", "not-an-address")) == "172.18.0.5"
    assert net.client_ip(_request("172.18.0.5", "6.6.6.6, unknown")) == "172.18.0.5"
    # Past our own proxies too.
    request = _request("172.18.0.5", "6.6.6.6, garbage, 172.18.0.7")
    assert net.client_ip(request) == "172.18.0.5"


def test_a_proxy_of_ours_written_with_its_port_is_still_passed_over(monkeypatch):
    monkeypatch.setattr(net.settings, "TRUSTED_PROXIES", ["172.18.0.0/16", "fd00::/8"])
    monkeypatch.setattr(net.settings, "TRUSTED_PROXY_HOSTS", [])
    request = _request("172.18.0.5", "6.6.6.6, 192.168.1.20:4000, 172.18.0.7:8443")
    assert net.client_ip(request) == "192.168.1.20"
    request = _request("172.18.0.5", "192.168.1.21, [fd00::7]:8443")
    assert net.client_ip(request) == "192.168.1.21"


def test_openapi_is_off_outside_local(monkeypatch):
    from app import main

    monkeypatch.setattr(main.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(main.settings, "EXPOSE_OPENAPI", False)
    assert main.openapi_enabled() is False
    monkeypatch.setattr(main.settings, "EXPOSE_OPENAPI", True)
    assert main.openapi_enabled() is True
    monkeypatch.setattr(main.settings, "EXPOSE_OPENAPI", False)
    monkeypatch.setattr(main.settings, "ENVIRONMENT", "local")
    assert main.openapi_enabled() is True
