"""Transactional e-mail for console accounts (password reset).

Queued through the same outbox as the supervision notifications, and the only
mail here that ignores the recipient's cadence: it answers a request the
account holder has just made, so « aucun e-mail » does not suppress it.
"""

import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.notification.outbox import queue_email

logger = logging.getLogger(__name__)


def reset_link(token: str) -> str | None:
    """Build the console reset URL, or None when the console URL is unknown."""
    if not settings.console_base_url:
        return None
    return f"{settings.console_base_url}/reset-password?token={token}"


def send_password_reset(session: AsyncSession, email: str, token: str) -> bool:
    """Queue a reset link, in the caller's open transaction. False if it could not be.

    The row commits with the reset token itself, so a link only ever goes out
    for a token that exists. An unknown console URL (neither CONSOLE_BASE_URL nor
    TIAI_SERVER_NAME) or a missing e-mail provider configuration is logged loudly: the endpoint answers 204 either way so as not to reveal
    whether the account exists, which would otherwise make this failure silent.
    """
    link = reset_link(token)
    if link is None:
        logger.error(
            "Password reset requested but the console URL is unknown "
            "(set TIAI_SERVER_NAME or CONSOLE_BASE_URL); no mail sent"
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
    queued = queue_email(
        session,
        to=email,
        subject=f"{settings.PROJECT_NAME} — réinitialisation du mot de passe",
        text=text,
    )
    if not queued:
        logger.error("Password reset mail not queued: no e-mail provider is configured")
    return queued
