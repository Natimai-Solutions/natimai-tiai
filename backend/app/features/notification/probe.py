"""« Envoyer un e-mail de test » : one mail, sent now, with its outcome in words.

The one send in the application that does not go through the outbox, and on
purpose: the outbox exists so that a failure becomes a retry nobody waits for,
and here somebody is waiting — an administrator who has just typed a server
and a password and wants to know, before saving them, whether they work. So
the mail leaves during the request, under a bounded delay, and every failure
comes back as a sentence that says what to fix rather than as a stack trace.
"""

import asyncio
import smtplib
import socket
import ssl
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.features.notification.email import send_email
from app.features.setting.email_policy import EmailPolicy

# Each network step of the test is capped at this many seconds, whatever the
# configured timeout: the administrator is watching a spinner. The whole send
# gets a few seconds more, for an SMTP dialogue made of several steps.
PROBE_TIMEOUT_SECONDS = 15
_OVERALL_TIMEOUT_SECONDS = PROBE_TIMEOUT_SECONDS + 10
_MAX_MESSAGE = 400
# « 530 5.7.0 Authentication required »: the server wants a login before it
# accepts a sender. The same code carries « 530 5.7.0 Must issue a STARTTLS
# command first », which no account answers: told apart by its text.
SMTP_AUTH_REQUIRED = 530


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    message: str


def _server_text(exc: smtplib.SMTPResponseException) -> str:
    raw = exc.smtp_error
    text = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
    return f"{exc.smtp_code} {text}".strip()


def describe_error(exc: BaseException, policy: EmailPolicy) -> str:
    """A failure as the page shows it: what went wrong, in French, and the
    server's own words where it gave any."""
    smtp_where = f"{policy.smtp_host}:{policy.smtp_port}"
    if (
        isinstance(exc, smtplib.SMTPResponseException)
        and exc.smtp_code == SMTP_AUTH_REQUIRED
        and "starttls" in _server_text(exc).lower()
    ):
        # Security « Aucune » on a server that only talks encrypted (587):
        # the field to change is the security mode, not the account.
        return (
            f"Le serveur {smtp_where} exige une connexion chiffrée avant tout "
            "envoi — choisissez la sécurité « STARTTLS » "
            f"(réponse : {_server_text(exc)})"
        )
    if (
        isinstance(exc, smtplib.SMTPResponseException)
        and exc.smtp_code == SMTP_AUTH_REQUIRED
    ):
        # Answered to MAIL FROM by a server that wants a login first: the
        # sender is not what it refuses, and saying so sent administrators
        # chasing the wrong field.
        account = (
            "le compte configuré n'a pas suffi : vérifiez l'utilisateur"
            if policy.smtp_user
            else "renseignez l'utilisateur et le mot de passe SMTP"
        )
        return (
            f"Le serveur {smtp_where} exige une authentification — {account} "
            f"(réponse : {_server_text(exc)})"
        )
    if isinstance(exc, smtplib.SMTPServerDisconnected) and _timed_out(exc):
        # smtplib turns a read that timed out into « connection unexpectedly
        # closed »: the server accepted the connection and said nothing.
        return (
            f"Le serveur {smtp_where} a accepté la connexion mais n'a pas répondu "
            f"dans les {policy.smtp_timeout_seconds} s. Est-ce bien un serveur "
            "SMTP, et le mode de sécurité correspond-il au port (TLS sur 465) ?"
        )
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Identifiants refusés par le serveur SMTP — vérifiez l'utilisateur et "
            f"le mot de passe (réponse : {_server_text(exc)})"
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return (
            f"Adresse d'expéditeur {policy.from_email} refusée par le serveur — avec "
            "un compte authentifié, elle doit en général être celle du compte "
            f"(réponse : {_server_text(exc)})"
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        details = "; ".join(
            f"{address} : {code} "
            + (text.decode(errors="replace") if isinstance(text, bytes) else str(text))
            for address, (code, text) in exc.recipients.items()
        )
        return f"Destinataire refusé par le serveur SMTP ({details})"
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return (
            "Le serveur SMTP ne propose pas ce que la configuration lui demande "
            f"(STARTTLS ou authentification) : {exc}. Essayez une autre sécurité."
        )
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return (
            f"Le serveur {smtp_where} a fermé la connexion. Le mode de sécurité "
            "correspond-il au port (STARTTLS sur 587, TLS sur 465) ?"
        )
    if isinstance(exc, smtplib.SMTPResponseException):
        return f"Le serveur SMTP a répondu par une erreur : {_server_text(exc)}"
    if isinstance(exc, smtplib.SMTPException):
        return f"Erreur SMTP : {exc}"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return (
            f"Certificat du serveur {smtp_where} refusé ({exc.verify_message}). "
            "Pour un relais interne à certificat privé, désactivez la vérification."
        )
    if isinstance(exc, ssl.SSLError):
        return (
            f"Échec de la négociation TLS avec {smtp_where} ({getattr(exc, 'reason', None) or exc}). "
            "Le mode de sécurité correspond-il au port (STARTTLS sur 587, TLS sur 465) ?"
        )
    if isinstance(exc, socket.gaierror):
        return f"Serveur SMTP introuvable : {policy.smtp_host} ne se résout pas"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 401:
            return "Clé API Mailgun refusée (401)"
        if status in (403, 404):
            return (
                f"Mailgun ne connaît pas le domaine {policy.mailgun_domain} ({status}) "
                "— vérifiez le domaine et la région de l'API (EU ou US)"
            )
        # Only Mailgun's own message field: the URL may point anywhere, and
        # a page body is not the console's to repeat (audit S10).
        try:
            data = exc.response.json()
        except ValueError:
            data = None
        body = data.get("message") if isinstance(data, dict) else None
        body = body.strip()[:200] if isinstance(body, str) else ""
        return f"Mailgun a répondu {status}" + (f" : {body}" if body else "")
    if isinstance(exc, httpx.TimeoutException):
        return "Mailgun n'a pas répondu dans le délai imparti"
    if isinstance(exc, httpx.RequestError):
        return f"Impossible de joindre Mailgun : {exc}"
    if isinstance(exc, TimeoutError) and _step_timed_out(exc, policy):
        if "handshake" in str(exc):
            # Implicit TLS: the connection was accepted and the handshake
            # never answered — the silent server of the branch above, met
            # before smtplib has anything to turn it into.
            return (
                f"Le serveur {smtp_where} a accepté la connexion mais n'a pas "
                f"répondu dans les {policy.smtp_timeout_seconds} s. Est-ce bien un "
                "serveur SMTP, et le mode de sécurité correspond-il au port "
                "(STARTTLS sur 587, TLS sur 465) ?"
            )
        return (
            f"Le serveur {smtp_where} n'a pas répondu dans le délai imparti "
            f"({policy.smtp_timeout_seconds} s)"
        )
    if isinstance(exc, TimeoutError):
        return (
            f"Le serveur {_where(policy)} n'a pas répondu dans le délai imparti "
            f"({_OVERALL_TIMEOUT_SECONDS} s)"
        )
    if isinstance(exc, ConnectionRefusedError):
        return f"Connexion refusée par {smtp_where} — le port est-il le bon ?"
    if isinstance(exc, OSError):
        return f"Impossible de joindre {_where(policy)} : {exc.strerror or exc}"
    return f"Erreur inattendue : {type(exc).__name__}: {exc}"


def _timed_out(exc: BaseException) -> bool:
    """Whether an SMTP disconnection was a read that timed out — smtplib
    raises it from the timeout, which stays attached as its context."""
    cause = exc.__cause__ or exc.__context__
    return isinstance(cause, TimeoutError) or "timed out" in str(exc)


def _step_timed_out(exc: TimeoutError, policy: EmailPolicy) -> bool:
    """Whether a timeout is one SMTP network step running out of the socket's
    delay (``smtp_timeout_seconds``, bounded for the test) rather than the
    whole test running out of its own: ``asyncio.wait_for`` raises its
    timeout from the cancellation it caused."""
    return policy.provider == "smtp" and not isinstance(
        exc.__cause__, asyncio.CancelledError
    )


def _where(policy: EmailPolicy) -> str:
    if policy.provider == "smtp":
        return f"{policy.smtp_host}:{policy.smtp_port}"
    return "Mailgun"


def _scrub(message: str, policy: EmailPolicy) -> str:
    """Never hand a secret back, even quoted by a server in its error."""
    for secret in (policy.smtp_password, policy.mailgun_api_key):
        if secret and len(secret) >= 4:
            message = message.replace(secret, "••••")
    return message[:_MAX_MESSAGE]


async def send_test(policy: EmailPolicy, to: str) -> ProbeResult:
    """Send the test mail to ``to`` with ``policy``, now; never raises."""
    if not policy.enabled:
        missing = ", ".join(policy.missing())
        return ProbeResult(
            ok=False, message=f"Configuration incomplète : il manque {missing}."
        )
    bounded = policy.bounded(PROBE_TIMEOUT_SECONDS)
    via = (
        f"le serveur SMTP {bounded.smtp_host}:{bounded.smtp_port}"
        if bounded.provider == "smtp"
        else f"Mailgun (domaine {bounded.mailgun_domain})"
    )
    text = (
        f"Ceci est un e-mail de test envoyé depuis la console {settings.PROJECT_NAME}, "
        f"page Paramètres, par {via}.\n\n"
        "S'il vous parvient, les alertes et les résumés partiront par le même chemin."
    )
    try:
        sent = await asyncio.wait_for(
            send_email(
                f"{settings.PROJECT_NAME} — e-mail de test",
                text,
                [to],
                policy=bounded,
            ),
            timeout=_OVERALL_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return ProbeResult(
            ok=False, message=_scrub(describe_error(exc, bounded), policy)
        )
    if not sent:  # pragma: no cover - enabled and a recipient: the senders send
        return ProbeResult(ok=False, message="Aucun e-mail n'est parti.")
    return ProbeResult(ok=True, message=f"E-mail de test envoyé à {to} par {via}.")
