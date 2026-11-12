"""Whose X-Forwarded-For is believed (audit S28), and the OpenAPI pages
outside local development (audit S36)."""

from types import SimpleNamespace

from app.core import net


def _request(peer: str, forwarded: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
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
