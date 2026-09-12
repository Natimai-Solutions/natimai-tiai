"""Unit tests for the SMTP provider and the provider switch (no network: smtplib is mocked)."""

import smtplib

import pytest

from app.core.config import settings
from app.features.notification import email, mailgun, smtp


class _FakeSMTP:
    """Records every step of the session so tests can assert its shape."""

    instances: list["_FakeSMTP"] = []
    refused: dict = {}
    fail_with: Exception | None = None

    def __init__(self, host: str, port: int, timeout: float, context=None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.starttls_context = None
        self.login_args: tuple[str, str] | None = None
        self.sent = None
        self.closed = False
        type(self).instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *args) -> bool:
        self.closed = True
        return False

    def starttls(self, context=None) -> None:
        self.starttls_context = context

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, msg) -> dict:
        if type(self).fail_with is not None:
            raise type(self).fail_with
        self.sent = msg
        return dict(type(self).refused)


class _FakeSMTPSSL(_FakeSMTP):
    pass


@pytest.fixture
def smtp_configured(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USER", None)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
    monkeypatch.setattr(settings, "SMTP_SECURITY", "starttls")
    monkeypatch.setattr(settings, "SMTP_VERIFY_TLS", True)
    monkeypatch.setattr(settings, "EMAIL_FROM_EMAIL", "tiai@example.com")
    monkeypatch.setattr(settings, "EMAIL_FROM_NAME", "Tia'i test")


@pytest.fixture
def fake_smtplib(monkeypatch):
    _FakeSMTP.instances = []
    _FakeSMTP.refused = {}
    _FakeSMTP.fail_with = None
    _FakeSMTPSSL.instances = _FakeSMTP.instances
    monkeypatch.setattr(smtp.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtp.smtplib, "SMTP_SSL", _FakeSMTPSSL)
    return _FakeSMTP


# --- Provider switch -------------------------------------------------------


def test_alerts_follow_the_selected_provider(monkeypatch):
    """Configuring the *other* provider does not enable mail."""
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-123")
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "EMAIL_FROM_EMAIL", "tiai@example.com")

    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "mailgun")
    assert settings.alerts_enabled is True
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    assert settings.alerts_enabled is False

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    assert settings.alerts_enabled is True


def test_smtp_needs_a_sender_address(monkeypatch):
    """A host alone is not enough: an SMTP mail with no From is refused by most relays."""
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "EMAIL_FROM_EMAIL", None)
    monkeypatch.setattr(settings, "MAILGUN_FROM_EMAIL", None)
    assert settings.smtp_configured is False
    # The historical Mailgun name still counts as the sender for SMTP.
    monkeypatch.setattr(settings, "MAILGUN_FROM_EMAIL", "tiai@example.com")
    assert settings.smtp_configured is True
    assert settings.email_from_email == "tiai@example.com"


async def test_dispatcher_routes_to_smtp(smtp_configured, fake_smtplib, monkeypatch):
    async def _mailgun_must_not_be_called(*args, **kwargs):
        raise AssertionError("Mailgun called with EMAIL_PROVIDER=smtp")

    monkeypatch.setattr(mailgun, "send_email", _mailgun_must_not_be_called)
    assert await email.send_email("Subject", "Body", to=["a@example.com"]) is True
    assert len(fake_smtplib.instances) == 1


async def test_dispatcher_routes_to_mailgun(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "mailgun")
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-123")
    calls: list[dict] = []

    async def _fake_mailgun(subject, text, to):
        calls.append({"subject": subject, "to": to})
        return True

    async def _smtp_must_not_be_called(*args, **kwargs):
        raise AssertionError("SMTP called with EMAIL_PROVIDER=mailgun")

    monkeypatch.setattr(mailgun, "send_email", _fake_mailgun)
    monkeypatch.setattr(smtp, "send_email", _smtp_must_not_be_called)
    assert await email.send_email("Subject", "Body", to=["a@example.com"]) is True
    assert calls == [{"subject": "Subject", "to": ["a@example.com"]}]


async def test_dispatcher_noop_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert await email.send_email("s", "t", to=["a@example.com"]) is False


# --- SMTP client -----------------------------------------------------------


async def test_send_email_noop_when_disabled(monkeypatch, fake_smtplib):
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert await smtp.send_email("s", "t", to=["a@example.com"]) is False
    assert fake_smtplib.instances == []


async def test_send_email_noop_without_recipients(smtp_configured, fake_smtplib):
    """Same rule as Mailgun: no recipient, no mail — never a fallback address."""
    assert await smtp.send_email("s", "t", to=[]) is False
    assert fake_smtplib.instances == []


async def test_send_email_starttls_session(smtp_configured, fake_smtplib, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "s3cret")

    ok = await smtp.send_email("Subject", "Body text", to=["a@example.com"])

    assert ok is True
    (session,) = fake_smtplib.instances
    assert type(session) is _FakeSMTP  # plain connection, upgraded in-band
    assert (session.host, session.port) == ("smtp.example.com", 587)
    assert session.timeout == settings.SMTP_TIMEOUT_SECONDS
    assert session.starttls_context is not None
    assert session.starttls_context.check_hostname is True
    assert session.login_args == ("user@example.com", "s3cret")
    assert session.closed is True

    msg = session.sent
    assert msg is not None
    assert msg["Subject"] == "Subject"
    assert msg["To"] == "a@example.com"
    assert msg["From"] == "Tia'i test <tiai@example.com>"
    assert msg["Message-ID"].endswith("@example.com>")
    assert msg["Date"]
    assert msg.get_content().strip() == "Body text"


async def test_send_email_implicit_tls_session(
    smtp_configured, fake_smtplib, monkeypatch
):
    monkeypatch.setattr(settings, "SMTP_SECURITY", "tls")
    monkeypatch.setattr(settings, "SMTP_PORT", 465)

    assert await smtp.send_email("s", "t", to=["a@example.com"]) is True
    (session,) = fake_smtplib.instances
    assert type(session) is _FakeSMTPSSL
    assert session.port == 465
    assert session.context is not None
    assert session.starttls_context is None  # already encrypted, no upgrade
    assert session.login_args is None  # no credentials configured → no LOGIN


async def test_send_email_plain_session(smtp_configured, fake_smtplib, monkeypatch):
    """A relay on the LAN: port 25, no TLS, no credentials."""
    monkeypatch.setattr(settings, "SMTP_SECURITY", "none")
    monkeypatch.setattr(settings, "SMTP_PORT", 25)

    assert await smtp.send_email("s", "t", to=["a@example.com"]) is True
    (session,) = fake_smtplib.instances
    assert type(session) is _FakeSMTP
    assert session.starttls_context is None
    assert session.login_args is None


async def test_send_email_can_skip_certificate_verification(
    smtp_configured, fake_smtplib, monkeypatch
):
    monkeypatch.setattr(settings, "SMTP_VERIFY_TLS", False)
    assert await smtp.send_email("s", "t", to=["a@example.com"]) is True
    (session,) = fake_smtplib.instances
    assert session.starttls_context.check_hostname is False


async def test_send_email_propagates_smtp_error(smtp_configured, fake_smtplib):
    """The outbox turns the exception into a retry; swallowing it here would lose mail."""
    fake_smtplib.fail_with = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    with pytest.raises(smtplib.SMTPAuthenticationError):
        await smtp.send_email("s", "t", to=["a@example.com"])


async def test_send_email_treats_refused_recipient_as_failure(
    smtp_configured, fake_smtplib
):
    fake_smtplib.refused = {"a@example.com": (550, b"no such user")}
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        await smtp.send_email("s", "t", to=["a@example.com"])
