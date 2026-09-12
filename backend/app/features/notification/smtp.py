"""Minimal SMTP client — the other channel this console can send mail through.

The standard library's ``smtplib`` is blocking, so each send runs in a worker
thread (``asyncio.to_thread``): the outbox drain sends one mail at a time and
the worker loop has nothing else to do meanwhile, so a thread per send costs
nothing worth a dependency.
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.core.config import settings


def _build_message(subject: str, text: str, to: list[str]) -> EmailMessage:
    sender = settings.email_from_email or ""
    msg = EmailMessage()
    msg["From"] = formataddr((settings.email_from_name, sender))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else None
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(text)
    return msg


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not settings.SMTP_VERIFY_TLS:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _send_sync(msg: EmailMessage) -> None:
    """Open one SMTP session, deliver one message, close it.

    Raises on anything short of every recipient being accepted: smtplib
    itself raises when the server refuses them all, and a partial refusal —
    which cannot happen with the outbox's one-recipient rows, but could with a
    direct caller — is turned into the same exception rather than reported as
    success.
    """
    host = settings.SMTP_HOST or ""
    port = settings.SMTP_PORT
    timeout = settings.SMTP_TIMEOUT_SECONDS

    client: smtplib.SMTP
    if settings.SMTP_SECURITY == "tls":
        client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=_tls_context())
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)

    with client:
        if settings.SMTP_SECURITY == "starttls":
            client.starttls(context=_tls_context())
        if settings.SMTP_USER:
            client.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        refused = client.send_message(msg)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


async def send_email(subject: str, text: str, to: list[str]) -> bool:
    """Send a plain-text e-mail through the configured SMTP server.

    Returns False (no-op) when SMTP is not configured, or when handed no
    recipient — the same contract as the Mailgun client, and for the same
    reason: there is no address in the environment to fall back on.
    """
    if not settings.smtp_configured or not to:
        return False
    await asyncio.to_thread(_send_sync, _build_message(subject, text, to))
    return True
