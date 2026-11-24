"""The mail a schedule's author gets when the server stops it: suspended (an
account, a right, a target, a package lost since it was written) or a
deployment in rings halted on its failure threshold.

To the author alone, in their language, queued in the transaction that
stopped it. Whatever their e-mail cadence: it is about something they set
up, as the assignment of a verification is.
"""

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.features.notification.language import mail_language
from app.features.notification.outbox import queue_email
from app.features.user.models import Language, User


@dataclass(frozen=True)
class ScheduleMailTexts:
    subject_suspended: str
    subject_halted: str
    intro_suspended: str
    intro_halted: str
    causes: dict[str, str]
    halted_detail: str
    no_result_detail: str
    open_page: str
    footer: str


FR = ScheduleMailTexts(
    subject_suspended="{project} — planification « {name} » suspendue",
    subject_halted="{project} — déploiement « {name} » arrêté",
    intro_suspended="La planification « {name} » n'a pas été exécutée et est suspendue :",
    intro_halted="Le déploiement par étapes « {name} » s'est arrêté à l'étape {stage} :",
    causes={
        "author_gone": "le compte qui l'a créée n'existe plus.",
        "author_inactive": "le compte qui l'a créée est désactivé.",
        "permission_lost": "le compte qui l'a créée n'a plus le droit « {permission} ».",
        "target_gone": "la salle ou le bâtiment visé n'existe plus ou n'est plus dans sa portée.",
        "package_gone": "le paquet à déployer n'existe plus.",
    },
    halted_detail=(
        "{failed} échec(s) sur {finished} poste(s) ayant répondu ({percent} %), "
        "au-delà du seuil de {threshold} %. Les étapes suivantes ne sont pas lancées."
    ),
    no_result_detail=(
        "aucun des {created} poste(s) de l'étape n'a répondu pendant le délai "
        "d'observation. Les étapes suivantes ne sont pas lancées."
    ),
    open_page="Voir la planification : {url}",
    footer="Vous recevez ce message parce que vous êtes l'auteur de cette planification.",
)

EN = ScheduleMailTexts(
    subject_suspended="{project} — schedule “{name}” suspended",
    subject_halted="{project} — deployment “{name}” halted",
    intro_suspended="The schedule “{name}” was not run and is suspended:",
    intro_halted="The staged deployment “{name}” stopped at stage {stage}:",
    causes={
        "author_gone": "the account that created it no longer exists.",
        "author_inactive": "the account that created it is deactivated.",
        "permission_lost": "the account that created it no longer holds “{permission}”.",
        "target_gone": "the targeted room or building no longer exists or is out of its scope.",
        "package_gone": "the package to deploy no longer exists.",
    },
    halted_detail=(
        "{failed} failure(s) out of {finished} computer(s) that answered "
        "({percent} %), above the {threshold} % threshold. The next stages are "
        "not started."
    ),
    no_result_detail=(
        "none of the stage's {created} computer(s) answered during the "
        "observation delay. The next stages are not started."
    ),
    open_page="See the schedule: {url}",
    footer="You receive this message because you created this schedule.",
)

TEXTS: dict[Language, ScheduleMailTexts] = {Language.FR: FR, Language.EN: EN}


def _link() -> str | None:
    if not settings.console_base_url:
        return None
    return f"{settings.console_base_url}/#/schedules"


def render(
    *, name: str, code: str, params: dict[str, Any], language: Language
) -> tuple[str, str]:
    """``(subject, body)`` of the mail for a stop coded ``code``."""
    t = TEXTS[language]
    project = settings.PROJECT_NAME
    if code in ("ring_failed", "ring_no_result"):
        subject = t.subject_halted.format(project=project, name=name)
        detail = (
            t.halted_detail if code == "ring_failed" else t.no_result_detail
        ).format(**params)
        lines = [
            t.intro_halted.format(name=name, stage=params.get("stage", "?")),
            detail,
        ]
    else:
        subject = t.subject_suspended.format(project=project, name=name)
        cause = t.causes.get(code, code).format(**params)
        lines = [t.intro_suspended.format(name=name), cause]
    link = _link()
    body = [*lines, ""]
    if link:
        body += [t.open_page.format(url=link), ""]
    body.append(t.footer)
    return subject, "\n".join(body)


def queue_stop_mail(
    session: Any, author: User | None, *, name: str, code: str, params: dict[str, Any]
) -> bool:
    """Queue it to the author, if there is one to write to. The caller
    commits."""
    if author is None or not author.is_active:
        return False
    subject, text = render(
        name=name, code=code, params=params, language=mail_language(author.language)
    )
    return queue_email(session, to=author.email, subject=subject, text=text)
