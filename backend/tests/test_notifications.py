"""Unit tests for the Mailgun alert provider (no network: httpx is mocked)."""

import pytest

from app.core.config import settings
from app.features.notification import mailgun


class _FakeResponse:
    def __init__(self, raise_exc: Exception | None = None) -> None:
        self._raise = raise_exc

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise


class _FakeAsyncClient:
    """Records construction and the last POST so tests can assert the request shape."""

    last_call: dict | None = None
    last_init: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        type(self).last_init = kwargs
        self.raise_exc: Exception | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        type(self).last_call = {"url": url, **kwargs}
        return _FakeResponse(self.raise_exc)


def _configure_mailgun(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-123")
    monkeypatch.setattr(settings, "MAILGUN_FROM_EMAIL", "tiai@example.com")


async def test_send_email_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", None)
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", None)
    assert await mailgun.send_email("s", "t", to=["a@example.com"]) is False


async def test_send_email_noop_without_recipients(monkeypatch):
    """An empty recipient list is a no-op, never a mail to somebody else.

    There is no configured address to fall back on: who hears from the console
    is a per-account setting, and a client able to substitute an address of its
    own would be a client able to mail someone nobody chose.
    """
    _configure_mailgun(monkeypatch)
    assert await mailgun.send_email("s", "t", to=[]) is False


async def test_send_email_posts_to_mailgun(monkeypatch):
    _configure_mailgun(monkeypatch)
    _FakeAsyncClient.last_call = None
    monkeypatch.setattr(mailgun.httpx, "AsyncClient", _FakeAsyncClient)

    ok = await mailgun.send_email("Subject", "Body", to=["a@example.com"])

    assert ok is True
    call = _FakeAsyncClient.last_call
    assert call is not None
    assert call["url"].endswith("/mg.example.com/messages")
    assert call["data"]["subject"] == "Subject"
    assert call["data"]["to"] == ["a@example.com"]
    assert call["auth"] == ("api", "key-123")
    # No proxy configured → none handed to the client (httpx treats None as "direct").
    assert _FakeAsyncClient.last_init is not None
    assert _FakeAsyncClient.last_init["proxy"] is None


async def test_send_email_routes_through_dedicated_proxy(monkeypatch):
    """MAILGUN_PROXY_URL reaches the Mailgun client, and only the Mailgun client.

    School networks force outbound traffic through a proxy. The setting is a
    dedicated variable rather than HTTP_PROXY/HTTPS_PROXY because those names
    are honoured by every process handed the environment — Caddy included,
    which must keep talking to its upstreams directly.
    """
    _configure_mailgun(monkeypatch)
    monkeypatch.setattr(settings, "MAILGUN_PROXY_URL", "http://proxy.school.local:3128")
    _FakeAsyncClient.last_init = None
    monkeypatch.setattr(mailgun.httpx, "AsyncClient", _FakeAsyncClient)

    ok = await mailgun.send_email("Subject", "Body", to=["a@example.com"])

    assert ok is True
    assert _FakeAsyncClient.last_init is not None
    assert _FakeAsyncClient.last_init["proxy"] == "http://proxy.school.local:3128"


async def test_send_email_propagates_http_error(monkeypatch):
    _configure_mailgun(monkeypatch)

    class _Failing(_FakeAsyncClient):
        async def post(self, url: str, **kwargs) -> _FakeResponse:
            return _FakeResponse(RuntimeError("boom"))

    monkeypatch.setattr(mailgun.httpx, "AsyncClient", _Failing)

    with pytest.raises(RuntimeError):
        await mailgun.send_email("s", "t", to=["a@example.com"])
