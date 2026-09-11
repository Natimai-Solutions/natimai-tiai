"""Mail about *somebody's* tasks: a verification handed to them, the
maintenances they own that are due.

Three messages, all behind the account's e-mail cadence and none of them a
fleet-wide broadcast:

* an assignment — "on vous demande d'aller voir ce poste" — the moment a
  verification is given to somebody, unless they asked for no mail at all;
* a personal block at the end of the daily digest, for whoever receives one:
  the verifications assigned to them, the rooms and postes they own that are
  overdue or due soon;
* a weekly reminder to every owner with something due, on a morning of the
  deployment's choice (``MAINTENANCE_REMINDER_WEEKDAY``).

Queued through the outbox like everything else; nothing here sends.
"""

import logging
import uuid
from datetime import datetime

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.base import utcnow
from app.features.check.models import MachineCheck
from app.features.machine.models import Machine
from app.features.maintenance import crud as maintenance_crud
from app.features.maintenance.policy import MaintenanceState
from app.features.notification.outbox import queue_email
from app.features.setting import crud as setting_crud
from app.features.user.models import EmailPreference, User

logger = logging.getLogger(__name__)


def _console_link(path: str) -> str | None:
    if not settings.CONSOLE_BASE_URL:
        return None
    return f"{settings.CONSOLE_BASE_URL.rstrip('/')}/#{path}"


def _wants_mail(user: User) -> bool:
    """Whether an account hears about its own tasks at all. Only « aucun
    e-mail » silences these: they are addressed to the person, not a digest
    of the parc, so the two digest cadences receive them too."""
    return user.is_active and user.email_preference != EmailPreference.NONE.value


# --- A verification handed to somebody ------------------------------------------


def send_checks_assigned(
    session: AsyncSession,
    *,
    assignee: User,
    machines: list[Machine],
    requested_by: str,
    instructions: str | None,
) -> bool:
    """Tell ``assignee`` that ``requested_by`` asks them to look at these
    postes. One mail for the lot: a request on a whole room is one request.
    Queued in the caller's transaction, so no mail goes out for a request
    that was rolled back."""
    if not machines or not _wants_mail(assignee):
        return False
    names = sorted((m.hostname or m.machine_uuid) for m in machines)
    if len(machines) == 1:
        subject = f"{settings.PROJECT_NAME} — vérification demandée : {names[0]}"
        intro = f"{requested_by} vous demande de vérifier le poste {names[0]}."
    else:
        subject = f"{settings.PROJECT_NAME} — vérification demandée sur {len(machines)} postes"
        intro = f"{requested_by} vous demande de vérifier {len(machines)} postes."
    body = [intro, ""]
    if instructions:
        body += ["Consignes :", instructions, ""]
    if len(machines) > 1:
        cap = settings.NOTIFICATION_MAX_ITEMS
        body += [f"  • {n}" for n in names[:cap]]
        if len(names) > cap:
            body.append(f"  … et {len(names) - cap} autre(s)")
        body.append("")
    link = _console_link("/tasks")
    if link:
        body += [f"Vos tâches : {link}", ""]
    body.append(
        "Vous recevez ce message parce qu'une vérification vous a été affectée. "
        "Réglez vos e-mails dans la console, page « Mon compte »."
    )
    return queue_email(
        session, to=assignee.email, subject=subject, text="\n".join(body)
    )


# --- What one person has on their plate -------------------------------------------


async def personal_block(
    session: AsyncSession, user: User, now: datetime | None = None
) -> list[str]:
    """The lines a digest ends with for this recipient: their open
    verifications, and the rooms and postes they own that are due. Empty when
    they have nothing — a digest must not grow a section that says so."""
    now = now or utcnow()
    cap = settings.NOTIFICATION_MAX_ITEMS
    lines: list[str] = []

    checks = await session.exec(
        select(MachineCheck, Machine)
        .join(Machine, col(Machine.id) == col(MachineCheck.machine_id))
        .where(
            col(MachineCheck.assigned_to_id) == user.id,
            col(MachineCheck.closed_at).is_(None),
        )
        .order_by(col(MachineCheck.created_at))
    )
    check_rows = checks.all()
    if check_rows:
        lines.append(f"  Vérifications qui vous sont affectées : {len(check_rows)}")
        for check, machine in check_rows[:cap]:
            what = f" — {check.instructions}" if check.instructions else ""
            lines.append(f"    • {machine.hostname or machine.machine_uuid}{what}")
        if len(check_rows) > cap:
            lines.append(f"    … et {len(check_rows) - cap} autre(s)")

    policy = await setting_crud.maintenance_policy(session)
    resolved = await maintenance_crud.fleet_resolved(session, policy, now)
    rooms, loose = maintenance_crud.group_due(
        resolved, policy, owner_filter=user.id, unowned=False
    )
    due_rooms = [r for r in rooms if r.overdue or r.due_soon]
    due_loose = [
        (m, res)
        for m, res in loose
        if res.state in (MaintenanceState.OVERDUE, MaintenanceState.DUE_SOON)
    ]
    overdue = sum(r.overdue for r in due_rooms) + sum(
        1 for _, res in due_loose if res.state == MaintenanceState.OVERDUE
    )
    due_soon = sum(r.due_soon for r in due_rooms) + sum(
        1 for _, res in due_loose if res.state == MaintenanceState.DUE_SOON
    )
    if overdue or due_soon:
        lines.append(
            f"  Maintenances dont vous êtes responsable : {overdue} poste(s) en retard, "
            f"{due_soon} à échéance"
        )
        shown = 0
        for r in due_rooms:
            if shown >= cap:
                break
            place = f"{r.building.name} › {r.room.name}" if r.building else r.room.name
            lines.append(
                f"    • {place} — {r.overdue} en retard, {r.due_soon} à échéance"
            )
            shown += 1
        for m, res in due_loose:
            if shown >= cap:
                break
            state = (
                "en retard" if res.state == MaintenanceState.OVERDUE else "à échéance"
            )
            lines.append(f"    • {m.hostname or m.machine_uuid} (sans salle) — {state}")
            shown += 1
        hidden = len(due_rooms) + len(due_loose) - shown
        if hidden > 0:
            lines.append(f"    … et {hidden} autre(s)")

    if not lines:
        return []
    out = ["VOS TÂCHES", *lines]
    link = _console_link("/tasks")
    if link:
        out.append(f"  Voir : {link}")
    out.append("")
    return out


# --- The weekly reminder --------------------------------------------------------


async def send_maintenance_reminders(session: AsyncSession) -> int:
    """One mail per owner with a maintenance overdue or due soon, on the
    parc's reminder morning. Returns how many were queued. Owners with
    nothing due, and accounts on « aucun e-mail », get nothing."""
    users = await session.exec(select(User).where(col(User.is_active).is_(True)))
    now = utcnow()
    queued = 0
    for user in users.all():
        if not _wants_mail(user):
            continue
        block = await personal_block(session, user, now)
        if not any("Maintenances dont vous êtes responsable" in line for line in block):
            continue
        date = now.strftime("%d/%m/%Y")
        subject = f"{settings.PROJECT_NAME} — vos maintenances au {date}"
        body = [
            "Rappel hebdomadaire de ce qui vous attend.",
            "",
            *block,
            "Vous recevez ce message parce que vous êtes responsable de la maintenance "
            "de salles ou de postes. Réglez vos e-mails dans la console, page « Mon compte ».",
        ]
        if queue_email(session, to=user.email, subject=subject, text="\n".join(body)):
            queued += 1
    await session.commit()
    logger.info("Maintenance reminders: %d queued", queued)
    return queued


async def user_by_id(session: AsyncSession, user_id: uuid.UUID | None) -> User | None:
    if user_id is None:
        return None
    return await session.get(User, user_id)
