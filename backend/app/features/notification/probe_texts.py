"""The test e-mail's own texts (``probe.py``), in French and in English.

Only the mail that goes out: the sentence the page Paramètres shows about
how the send went is the probe's result, not part of the mail. The test mail
is written in the language of the administrator who asked for it, else
``DEFAULT_LANGUAGE``; its French is the mail as it has always read — pinned
by ``tests/test_mail_languages.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import settings
from app.features.notification.language import texts_for
from app.features.setting.email_policy import EmailPolicy
from app.features.user.models import Language


@dataclass(frozen=True)
class ProbeMailTexts:
    via_smtp: Callable[[str], str]
    via_mailgun: Callable[[str], str]
    subject: Callable[[str], str]
    # (project, via)
    body: Callable[[str, str], str]


TEXTS: dict[Language, ProbeMailTexts] = {
    Language.FR: ProbeMailTexts(
        via_smtp=lambda where: f"le serveur SMTP {where}",
        via_mailgun=lambda domain: f"Mailgun (domaine {domain})",
        subject=lambda project: f"{project} — e-mail de test",
        body=lambda project, via: (
            f"Ceci est un e-mail de test envoyé depuis la console {project}, "
            f"page Paramètres, par {via}.\n\n"
            "S'il vous parvient, les alertes et les résumés partiront par le même chemin."
        ),
    ),
    Language.EN: ProbeMailTexts(
        via_smtp=lambda where: f"the SMTP server {where}",
        via_mailgun=lambda domain: f"Mailgun (domain {domain})",
        subject=lambda project: f"{project} — test e-mail",
        body=lambda project, via: (
            f"This is a test e-mail sent from the {project} console, "
            f"Settings page, through {via}.\n\n"
            "If it reaches you, alerts and digests will go out the same way."
        ),
    ),
}


def probe_mail(policy: EmailPolicy, language: Language | None) -> tuple[str, str]:
    """The test mail as (subject, plain-text body) for ``policy``."""
    t = texts_for(TEXTS, language)
    via = (
        t.via_smtp(f"{policy.smtp_host}:{policy.smtp_port}")
        if policy.provider == "smtp"
        else t.via_mailgun(f"{policy.mailgun_domain}")
    )
    project = settings.PROJECT_NAME
    return t.subject(project), t.body(project, via)
