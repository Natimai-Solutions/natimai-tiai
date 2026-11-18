"""Transactional e-mail for console accounts (password reset).

Queued through the same outbox as the supervision notifications, and the only
mail here that ignores the recipient's cadence: it answers a request the
account holder has just made, so « aucun e-mail » does not suppress it.

Written in the account's language, else ``DEFAULT_LANGUAGE``
(``notification.language``). The French is the mail as it has always read —
pinned by ``tests/test_mail_languages.py``.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.notification.language import mail_language
from app.features.notification.outbox import queue_email
from app.features.user.models import Language

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResetTexts:
    subject: Callable[[str], str]
    # (project, link, minutes)
    body: Callable[[str, str, int], str]


RESET_TEXTS: dict[Language, ResetTexts] = {
    Language.FR: ResetTexts(
        subject=lambda project: f"{project} — réinitialisation du mot de passe",
        body=lambda project, link, minutes: (
            "Vous avez demandé la réinitialisation de votre mot de passe "
            f"{project}.\n\n"
            f"Ouvrez ce lien pour choisir un nouveau mot de passe :\n{link}\n\n"
            f"Ce lien expire dans {minutes} minutes et ne peut servir qu'une fois.\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : "
            "votre mot de passe reste inchangé."
        ),
    ),
    Language.EN: ResetTexts(
        subject=lambda project: f"{project} — password reset",
        body=lambda project, link, minutes: (
            f"You asked to reset your {project} password.\n\n"
            f"Open this link to choose a new password:\n{link}\n\n"
            f"This link expires in {minutes} minutes and can be used only once.\n"
            "If you did not make this request, ignore this message: "
            "your password stays as it is."
        ),
    ),
}


def reset_link(token: str) -> str | None:
    """Build the console reset URL, or None when the console URL is unknown."""
    if not settings.console_base_url:
        return None
    return f"{settings.console_base_url}/reset-password?token={token}"


def send_password_reset(
    session: AsyncSession, email: str, token: str, *, language: str | None = None
) -> bool:
    """Queue a reset link, in the caller's open transaction. False if it could not be.

    ``language`` is the account's stored choice (``User.language``): the mail
    is written in it, else in ``DEFAULT_LANGUAGE``.

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

    texts = RESET_TEXTS[mail_language(language)]
    queued = queue_email(
        session,
        to=email,
        subject=texts.subject(settings.PROJECT_NAME),
        text=texts.body(
            settings.PROJECT_NAME, link, settings.PASSWORD_RESET_EXPIRE_MINUTES
        ),
    )
    if not queued:
        logger.error("Password reset mail not queued: no e-mail provider is configured")
    return queued
