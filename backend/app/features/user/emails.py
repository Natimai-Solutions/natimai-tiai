"""Transactional e-mail for console accounts (password reset).

Sent through the same Mailgun client as supervision alerts; only the recipient
differs (the account holder rather than ``ALERT_RECIPIENTS``).
"""

import logging

from app.core.config import settings
from app.features.notification.mailgun import send_email

logger = logging.getLogger(__name__)


def reset_link(token: str) -> str | None:
    """Build the console reset URL, or None when CONSOLE_BASE_URL is unset."""
    if not settings.CONSOLE_BASE_URL:
        return None
    return f"{settings.CONSOLE_BASE_URL.rstrip('/')}/reset-password?token={token}"


async def send_password_reset(email: str, token: str) -> bool:
    """Mail a reset link. Returns False when it could not be sent.

    A missing CONSOLE_BASE_URL or Mailgun configuration is logged loudly: the
    endpoint answers 204 either way so as not to reveal whether the account
    exists, which would otherwise make this failure silent.
    """
    link = reset_link(token)
    if link is None:
        logger.error(
            "Password reset requested but CONSOLE_BASE_URL is not set; no mail sent"
        )
        return False

    minutes = settings.PASSWORD_RESET_EXPIRE_MINUTES
    text = (
        "Vous avez demandé la réinitialisation de votre mot de passe "
        f"{settings.PROJECT_NAME}.\n\n"
        f"Ouvrez ce lien pour choisir un nouveau mot de passe :\n{link}\n\n"
        f"Ce lien expire dans {minutes} minutes et ne peut servir qu'une fois.\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : "
        "votre mot de passe reste inchangé."
    )
    sent = await send_email(
        subject=f"{settings.PROJECT_NAME} — réinitialisation du mot de passe",
        text=text,
        to=[email],
    )
    if not sent:
        logger.error("Password reset mail not sent: Mailgun is not configured")
    return sent
