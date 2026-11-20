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
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.alert.texts import worded_instructions
from app.features.base import utcnow
from app.features.check import crud as check_crud
from app.features.check.models import MachineCheck
from app.features.machine.models import Machine
from app.features.maintenance import crud as maintenance_crud
from app.features.maintenance.crud import DueRoom
from app.features.maintenance.policy import MaintenanceState, Resolved
from app.features.notification.language import mail_language
from app.features.notification.outbox import queue_email
from app.features.notification.tasks_texts import TEXTS, TasksTexts
from app.features.room.models import Building, Room
from app.features.setting import crud as setting_crud
from app.features.setting.email_policy import email_policy
from app.features.user.models import EmailPreference, User

logger = logging.getLogger(__name__)


def _console_link(path: str) -> str | None:
    if not settings.console_base_url:
        return None
    return f"{settings.console_base_url}/#{path}"


def mail_date(at: datetime) -> str:
    """The date a mail is about, as its subject prints it. The server knows
    no time zone of its readers — the page Paramètres shows the schedule in
    each browser's own — so the date is the UTC one, and says so: a reader
    east of Greenwich would otherwise read « hier » as « aujourd'hui »."""
    return f"{at:%d/%m/%Y} (UTC)"


def bullet(text: str, *, indent: int) -> str:
    """``•`` and ``text`` at ``indent`` spaces, its continuation lines (typed
    instructions span several) aligned under the text rather than at the
    margin, where they read as lines of the mail itself."""
    first, *rest = text.splitlines() or [""]
    pad = " " * (indent + 2)
    return "\n".join([f"{' ' * indent}• {first}", *(pad + line for line in rest)])


def _wants_mail(user: User) -> bool:
    """Whether an account hears about its own tasks at all. Only « aucun
    e-mail » silences these: they are addressed to the person, not a digest
    of the parc, so the two digest cadences receive them too."""
    return user.is_active and user.email_preference != EmailPreference.NONE.value


def _texts(user: User) -> TasksTexts:
    """These mails in their reader's language (``language.mail_language``)."""
    return TEXTS[mail_language(user.language)]


# --- A verification handed to somebody ------------------------------------------


def send_checks_assigned(
    session: AsyncSession,
    *,
    assignee: User,
    machines: list[Machine],
    requested_by: str,
    instructions: str | None,
    instructions_code: str | None = None,
    instructions_params: dict[str, Any] | None = None,
) -> bool:
    """Tell ``assignee`` that ``requested_by`` asks them to look at these
    postes. One mail for the lot: a request on a whole room is one request.
    Queued in the caller's transaction, so no mail goes out for a request
    that was rolled back."""
    if not machines or not _wants_mail(assignee):
        return False
    t = _texts(assignee)
    project = settings.PROJECT_NAME
    names = sorted((m.hostname or m.machine_uuid) for m in machines)
    if len(machines) == 1:
        subject = t.check_subject_one(project, names[0])
        intro = t.check_intro_one(requested_by, names[0])
    else:
        subject = t.check_subject_many(project, len(machines))
        intro = t.check_intro_many(requested_by, len(machines))
    body = [intro, ""]
    # Opened by the server for an alert: worded in the assignee's language.
    worded = worded_instructions(
        instructions,
        instructions_code,
        instructions_params,
        mail_language(assignee.language),
    )
    if worded:
        body += [t.instructions, worded, ""]
    if len(machines) > 1:
        cap = settings.NOTIFICATION_MAX_ITEMS
        body += [f"  • {n}" for n in names[:cap]]
        if len(names) > cap:
            body.append(f"  {t.more(len(names) - cap)}")
        body.append("")
    link = _console_link("/tasks")
    if link:
        body += [t.tasks_link(link), ""]
    body.append(t.check_footer)
    return queue_email(
        session, to=assignee.email, subject=subject, text="\n".join(body)
    )


# --- What one person has on their plate -------------------------------------------


@dataclass(frozen=True)
class FleetMaintenance:
    """The parc's maintenance, resolved once for a run that writes to many
    people: the policy — with which owners still reach what they are named
    on — and every poste's standing and owner."""

    policy: setting_crud.MaintenancePolicy
    resolved: list[tuple[Machine, Room | None, Building | None, Resolved]]


async def fleet_maintenance(session: AsyncSession, now: datetime) -> FleetMaintenance:
    policy = await setting_crud.maintenance_policy(session)
    return FleetMaintenance(
        policy=policy,
        resolved=await maintenance_crud.fleet_resolved(session, policy, now),
    )


async def personal_block(
    session: AsyncSession,
    user: User,
    now: datetime | None = None,
    *,
    fleet: FleetMaintenance | None = None,
) -> list[str]:
    """The lines a digest ends with for this recipient: their open
    verifications, and the rooms and postes they own that are due. Empty when
    they have nothing — a digest must not grow a section that says so.

    ``fleet`` is the parc's maintenance already resolved: a run that writes
    to every recipient reads it once, not once per recipient. What a person
    owns is what the resolution names them on — never a poste or a room they
    no longer reach (``maintenance.reach``), whatever is stored on it.

    Written in the recipient's language (``language.mail_language``)."""
    lines, _ = await _personal_block(session, user, now, fleet=fleet)
    return lines


async def _personal_block(
    session: AsyncSession,
    user: User,
    now: datetime | None = None,
    *,
    fleet: FleetMaintenance | None = None,
) -> tuple[list[str], bool]:
    """``personal_block``, and whether it names a maintenance due — what the
    weekly reminder is about."""
    t = _texts(user)
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
    # Only what they can still take: a poste moved out of their sight, rights
    # removed — the request is nobody's now (``check_crud.assignee_reach``),
    # and its poste and instructions are not theirs to read.
    reach = await check_crud.assignee_reach(session, [user.id])
    check_rows = [
        (check, machine)
        for check, machine in checks.all()
        if reach.machine(user.id, machine.location, machine.room_id)
    ]
    if check_rows:
        lines.append(t.checks_assigned(len(check_rows)))
        for check, machine in check_rows[:cap]:
            worded = worded_instructions(
                check.instructions,
                check.instructions_code,
                check.instructions_params,
                mail_language(user.language),
            )
            what = f" — {worded}" if worded else ""
            lines.append(
                bullet(f"{machine.hostname or machine.machine_uuid}{what}", indent=4)
            )
        if len(check_rows) > cap:
            lines.append(f"    {t.more(len(check_rows) - cap)}")

    if fleet is None:
        fleet = await fleet_maintenance(session, now)
    rooms, loose = maintenance_crud.group_due(
        fleet.resolved, fleet.policy, owner_filter=user.id, unowned=False
    )
    # One line per room: « Mes tâches » splits a room whose postes resolve to
    # different cycles (each group is taken on its own), but the mail only
    # counts, and the same room twice would read as two rooms.
    merged: dict[uuid.UUID, DueRoom] = {}
    for r in rooms:
        if not (r.overdue or r.due_soon):
            continue
        if r.room.id not in merged:
            merged[r.room.id] = replace(r, machines=list(r.machines))
        else:
            merged[r.room.id].overdue += r.overdue
            merged[r.room.id].due_soon += r.due_soon
    due_rooms = list(merged.values())
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
    maintenance_due = bool(overdue or due_soon)
    if maintenance_due:
        lines.append(t.maintenance_summary(overdue, due_soon))
        shown = 0
        for r in due_rooms:
            if shown >= cap:
                break
            place = f"{r.building.name} › {r.room.name}" if r.building else r.room.name
            lines.append(t.room_line(place, r.overdue, r.due_soon))
            shown += 1
        for m, res in due_loose:
            if shown >= cap:
                break
            state = t.overdue if res.state == MaintenanceState.OVERDUE else t.due_soon
            lines.append(t.loose_line(m.hostname or m.machine_uuid, state))
            shown += 1
        hidden = len(due_rooms) + len(due_loose) - shown
        if hidden > 0:
            lines.append(f"    {t.more(hidden)}")

    if not lines:
        return [], False
    out = [t.your_tasks, *lines]
    link = _console_link("/tasks")
    if link:
        out.append(t.see(link))
    out.append("")
    return out, maintenance_due


# --- The weekly reminder --------------------------------------------------------


async def send_maintenance_reminders(session: AsyncSession) -> int:
    """One mail per owner with a maintenance overdue or due soon, on the
    parc's reminder morning. Returns how many were queued. Owners with
    nothing due, and accounts on « aucun e-mail », get nothing."""
    if not (await email_policy(session)).enabled:
        logger.info("Maintenance reminders: no e-mail provider is configured")
        return 0
    from app.features.notification.digest import plan_daily_digest

    users = await session.exec(select(User).where(col(User.is_active).is_(True)))
    now = utcnow()
    # The reminder goes out at the digest's hour: an owner whose digest of
    # this morning already carries « VOS TÂCHES » would read the same block
    # twice. They have it there; the reminder is for the others.
    #
    # Asked under a savepoint, and answered « nobody » when it fails: the
    # digest's plan reads the whole parc (every section of every scope), and
    # a failure there must not cost the owners their week's reminder — nor
    # the caller its transaction, which carries the worker's record of the
    # week. The price is an owner told twice, should the digest then go out.
    in_digest: set[uuid.UUID] = set()
    try:
        async with session.begin_nested():
            in_digest = {
                plan.user.id
                for plan in await plan_daily_digest(session)
                if plan.personal
            }
    except Exception:
        logger.warning(
            "Maintenance reminders: today's digest could not be planned, "
            "every owner is reminded",
            exc_info=True,
        )
    # Once for the run: the parc, and who reaches what.
    fleet = await fleet_maintenance(session, now)
    queued = 0
    for user in users.all():
        if not _wants_mail(user) or user.id in in_digest:
            continue
        block, maintenance_due = await _personal_block(session, user, now, fleet=fleet)
        if not maintenance_due:
            continue
        t = _texts(user)
        subject = t.reminder_subject(settings.PROJECT_NAME, mail_date(now))
        body = [t.reminder_intro, "", *block, t.reminder_footer]
        if queue_email(session, to=user.email, subject=subject, text="\n".join(body)):
            queued += 1
    await session.commit()
    logger.info("Maintenance reminders: %d queued", queued)
    return queued


async def user_by_id(session: AsyncSession, user_id: uuid.UUID | None) -> User | None:
    if user_id is None:
        return None
    return await session.get(User, user_id)
