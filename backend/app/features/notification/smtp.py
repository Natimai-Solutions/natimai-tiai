"""Minimal SMTP client — the other channel this console can send mail through.

The standard library's ``smtplib`` is blocking, so each send runs in a thread
of its own (``_in_thread``): the outbox drain sends one mail at a time and
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
import threading
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
    """The client side of the TLS session: the chain must end at a CA the
    container trusts and the certificate must name the server — unless the
    administrator turned the verification off."""
    ctx = ssl.create_default_context()
    # Python 3.13 added VERIFY_X509_STRICT to the default context: RFC 5280
    # to the letter, which refuses a CA without a key-usage extension or a
    # certificate without an authority key identifier — what `openssl req
    # -x509` and many home-made CAs produce. The relays this console talks to
    # are often behind such a CA, and v1.2.0 (Python 3.12) accepted them: a
    # patch release that moved the interpreter must not stop a site's mail.
    # So the verification stays what it was — chain and host name. The flag
    # can come back with a release whose notes tell those sites to reissue
    # their CA first, or behind a setting of its own.
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
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


async def _in_thread(policy: EmailPolicy, msg: EmailMessage) -> None:
    """Run ``_send_sync`` in a thread and wait for it.

    A daemon thread, not ``asyncio.to_thread``: the loop's default executor
    is joined when the loop closes, so a send the worker had cancelled at the
    end of its stop grace — a server gone silent — still held the process
    for the rest of its SMTP timeout, past the ten seconds ``docker stop``
    gives. A daemon thread is abandoned with the process; the mail's row is
    still pending, and the next start sends it.
    """
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()

    def settle(error: BaseException | None) -> None:
        if done.cancelled():
            return  # nobody waits for this send any more
        if error is None:
            done.set_result(None)
        else:
            done.set_exception(error)

    def run() -> None:
        error: BaseException | None = None
        try:
            _send_sync(policy, msg)
        except BaseException as exc:
            error = exc
        try:
            loop.call_soon_threadsafe(settle, error)
        except RuntimeError:
            pass  # the loop is closed: the process is going down

    threading.Thread(target=run, name="smtp-send", daemon=True).start()
    await done


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
    await _in_thread(policy, msg)
    return True
