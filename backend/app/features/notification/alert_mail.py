"""Immediate mail for the alerts that cannot wait for the digest.

One rule today: a physical drive reported unhealthy (``AlertRule.
DISK_UNHEALTHY``) — a day of delay can cost a poste's data, where a nearly
full disk or a pending restart keeps until the morning. Sent like the threat
alert: to the active accounts on the immediate cadence that see the poste,
each in their own language, queued in the outbox inside the transaction that
opened the alert.
"""

from dataclasses import dataclass

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.alert.crud import OpenedAlert
from app.features.alert.models import AlertRule
from app.features.machine.models import Machine
from app.features.notification.language import mail_language, texts_for
from app.features.notification.outbox import queue_email
from app.features.notification.recipients import users_for
from app.features.setting.email_policy import email_policy
from app.features.user import crud as user_crud
from app.features.user.models import EmailPreference, Language
from app.features.user.scope import machine_visible

# The rules mailed at once. The others reach people through the digest.
IMMEDIATE_RULES = frozenset({AlertRule.DISK_UNHEALTHY.value})


@dataclass(frozen=True)
class DiskAlertTexts:
    subject: str
    intro: str
    disk: str
    machine: str
    open_page: str
    footer: str


FR = DiskAlertTexts(
    subject="{project} — disque en mauvaise santé sur {name}",
    intro=(
        "Windows signale un disque en mauvaise santé sur le poste {name}. "
        "Sauvegardez ses données avant de le remplacer."
    ),
    disk="  • {model} — état : {health}",
    machine="Poste : {name}",
    open_page="Ouvrir la fiche du poste : {url}",
    footer=(
        "Vous recevez ce message parce que votre compte est réglé sur les alertes "
        "immédiates. Changez-le dans la console, page « Mon compte »."
    ),
)

EN = DiskAlertTexts(
    subject="{project} — unhealthy disk on {name}",
    intro=(
        "Windows reports an unhealthy disk on the computer {name}. "
        "Back up its data before replacing it."
    ),
    disk="  • {model} — health: {health}",
    machine="Computer: {name}",
    open_page="Open the computer's page: {url}",
    footer=(
        "You receive this message because your account is set to immediate "
        "alerts. Change it in the console, under My account."
    ),
)

TEXTS: dict[Language, DiskAlertTexts] = {Language.FR: FR, Language.EN: EN}


def render_disk_alert(
    machine: Machine, alert: OpenedAlert, language: Language | None = None
) -> tuple[str, str]:
    """(subject, plain-text body) of the mail for one unhealthy-disk alert."""
    t = texts_for(TEXTS, language)
    name = machine.hostname or machine.machine_uuid
    lines = [t.intro.format(name=name), ""]
    for disk in alert.detail.get("disks", []):
        lines.append(
            t.disk.format(model=disk.get("model") or "?", health=disk.get("health"))
        )
    lines += ["", t.machine.format(name=name), ""]
    if settings.console_base_url:
        url = f"{settings.console_base_url}/machines/{machine.id}"
        lines += [t.open_page.format(url=url), ""]
    lines.append(t.footer)
    return t.subject.format(project=settings.PROJECT_NAME, name=name), "\n".join(lines)


async def queue_alert_mails(session: AsyncSession, opened: list[OpenedAlert]) -> int:
    """Queue the immediate mails of newly opened alerts. Does not commit;
    returns how many mails were queued."""
    urgent = [a for a in opened if a.rule in IMMEDIATE_RULES]
    if not urgent:
        return 0
    users = await users_for(session, [EmailPreference.IMMEDIATE])
    if not users:
        return 0
    if not (await email_policy(session)).enabled:
        return 0
    machines = {
        m.id: m
        for m in (
            await session.exec(
                select(Machine).where(
                    col(Machine.id).in_({a.machine_id for a in urgent})
                )
            )
        ).all()
    }
    scopes = {user.id: await user_crud.user_scope(session, user.id) for user in users}
    queued = 0
    for alert in urgent:
        machine = machines.get(alert.machine_id)
        if machine is None:
            continue
        for user in users:
            if not await machine_visible(session, machine.id, scopes[user.id]):
                continue
            subject, text = render_disk_alert(
                machine, alert, mail_language(user.language)
            )
            if queue_email(session, to=user.email, subject=subject, text=text):
                queued += 1
    return queued
