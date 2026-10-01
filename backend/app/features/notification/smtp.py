"""Minimal SMTP client — the other channel this console can send mail through.

The standard library's ``smtplib`` is blocking, so each send runs in a worker
thread (``asyncio.to_thread``): the outbox drain sends one mail at a time and
the worker loop has nothing else to do meanwhile, so a thread per send costs
nothing worth a dependency.

Every setting comes from the ``EmailPolicy`` the caller resolved — the
console's values over the environment's — never from ``settings`` directly:
a server or a password changed on the page Paramètres must apply at the next
send, not at the next restart.
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.features.setting.email_policy import EmailPolicy


def _build_message(
    policy: EmailPolicy, subject: str, text: str, to: list[str]
) -> EmailMessage:
    sender = policy.from_email or ""
    msg = EmailMessage()
    msg["From"] = formataddr((policy.from_name, sender))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else None
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(text)
    return msg


def _tls_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _send_sync(policy: EmailPolicy, msg: EmailMessage) -> None:
    """Open one SMTP session, deliver one message, close it.

    Raises on anything short of every recipient being accepted: smtplib
    itself raises when the server refuses them all, and a partial refusal —
    which cannot happen with the outbox's one-recipient rows, but could with a
    direct caller — is turned into the same exception rather than reported as
    success.
    """
    host = policy.smtp_host or ""
    port = policy.smtp_port
    timeout = policy.smtp_timeout_seconds
    context = _tls_context(policy.smtp_verify_tls)

    client: smtplib.SMTP
    if policy.smtp_security == "tls":
        client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)

    with client:
        if policy.smtp_security == "starttls":
            client.starttls(context=context)
        if policy.smtp_user:
            client.login(policy.smtp_user, policy.smtp_password or "")
        refused = client.send_message(msg)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


async def send_email(
    subject: str, text: str, to: list[str], *, policy: EmailPolicy
) -> bool:
    """Send a plain-text e-mail through the policy's SMTP server.

    Returns False (no-op) when SMTP is not configured, or when handed no
    recipient — the same contract as the Mailgun client, and for the same
    reason: there is no address in the configuration to fall back on.
    """
    if not policy.smtp_configured or not to:
        return False
    msg = _build_message(policy, subject, text, to)
    await asyncio.to_thread(_send_sync, policy, msg)
    return True
