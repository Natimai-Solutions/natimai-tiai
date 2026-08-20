"""The daily digest: what the fleet looks like this morning, in one mail.

Two cadences share this module, and they differ only in when they stay quiet:

* ``DIGEST_EVENTS`` — sent only on a day that has something to act on.
* ``DIGEST_DAILY`` — sent every day, so that a mail that says "rien à signaler"
  is itself the signal. A console nobody opens is the case this product exists
  for, and silence from a digest that only speaks up on bad days is
  indistinguishable from silence from a digest that has stopped working.

The content is the dashboard's own reading of the fleet, in words: same
definitions, same thresholds, one source of truth for "périmé" and "inactif".
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    status_clause,
    windows_update_clause,
)
from app.features.machine.status import WindowsUpdateFilter as WUFilter
from app.features.notification.mailgun import send_email
from app.features.notification.recipients import recipients_for
from app.features.threat.models import Threat
from app.features.user.models import EmailPreference
from app.features.windows_update.models import WindowsUpdate

logger = logging.getLogger(__name__)

# MSRC ratings that count as "à installer sans attendre". Defined here rather
# than taken as "anything not low": an unrated update (NULL severity) is the
# common case for drivers, and pulling those into an alert would make every
# digest urgent.
HIGH_SEVERITIES = ("critical", "important")


@dataclass
class MachineLine:
    """One poste as a digest mentions it: a name and why it is listed."""

    hostname: str
    detail: str


@dataclass
class Digest:
    """The fleet as of one instant, in the shape the mail prints it."""

    generated_at: datetime
    total: int
    online: int
    # --- the four counts that make a day worth reporting ---
    with_active_threats: int
    with_high_severity_updates: int
    needs_verification: int
    new_threats_24h: int
    # --- the running state, reported whether or not anything happened ---
    outdated_antivirus: int
    wu_pending: int
    reboot_required: int
    inactive: int
    # --- named examples, capped at NOTIFICATION_MAX_ITEMS ---
    threat_lines: list[MachineLine] = field(default_factory=list)
    update_lines: list[MachineLine] = field(default_factory=list)
    outdated_lines: list[MachineLine] = field(default_factory=list)

    @property
    def has_events(self) -> bool:
        """Whether this day has something an operator must act on.

        The threshold for the "seulement s'il y a du nouveau" cadence, and it is
        deliberately narrow: an active threat, a high-severity patch waiting, or
        a poste whose identity no longer adds up. A périmé antivirus and a
        pending restart are *running state* — real, worth a line in the daily
        digest, but present on most parcs most days. Letting them trigger the
        event digest would make it fire every morning, which is the other
        cadence, and the distinction between the two would be lost.
        """
        return bool(
            self.with_active_threats
            or self.with_high_severity_updates
            or self.needs_verification
            or self.new_threats_24h
        )


async def _count(session: AsyncSession, clause: ColumnElement[bool] | None) -> int:
    stmt = select(func.count()).select_from(Machine)
    if clause is not None:
        stmt = stmt.where(clause)
    return await session.scalar(stmt) or 0


def _name(machine_hostname: str | None, machine_uuid: str) -> str:
    """A poste as an operator recognises it: its name, else its UUID."""
    return machine_hostname or machine_uuid


async def build_digest(session: AsyncSession) -> Digest:
    """Read the current state of the fleet."""
    now = utcnow()
    days = settings.INACTIVE_AFTER_DAYS
    cap = settings.NOTIFICATION_MAX_ITEMS

    total = await _count(session, None)
    # Same window the console's green dot uses, so the two never disagree.
    online_since = now - timedelta(seconds=settings.OFFLINE_AFTER_SECONDS)
    online = await _count(session, col(Machine.last_seen) > online_since)

    outdated = await _count(session, status_clause(MachineStatus.OUTDATED, now, days))
    needs_verification = await _count(
        session, status_clause(MachineStatus.NEEDS_VERIFICATION, now, days)
    )
    inactive = await _count(session, status_clause(MachineStatus.INACTIVE, now, days))
    wu_pending = await _count(session, windows_update_clause(WUFilter.PENDING))
    reboot_required = await _count(
        session, windows_update_clause(WUFilter.REBOOT_REQUIRED)
    )

    # --- machines carrying an active threat, named ---
    active_threats = (
        select(Machine.hostname, Machine.machine_uuid, func.count().label("n"))
        .join(Threat, col(Threat.machine_id) == col(Machine.id))
        .where(col(Threat.status) == "active")
        .group_by(col(Machine.id), col(Machine.hostname), col(Machine.machine_uuid))
        .order_by(func.count().desc())
    )
    threat_rows = await session.exec(active_threats)
    threat_machines = threat_rows.all()
    threat_lines = [
        MachineLine(
            hostname=_name(hostname, machine_uuid), detail=f"{n} menace(s) active(s)"
        )
        for hostname, machine_uuid, n in threat_machines[:cap]
    ]

    # --- machines with a critical or important update waiting ---
    high_updates = (
        select(Machine.hostname, Machine.machine_uuid, func.count().label("n"))
        .join(WindowsUpdate, col(WindowsUpdate.machine_id) == col(Machine.id))
        .where(func.lower(col(WindowsUpdate.severity)).in_(HIGH_SEVERITIES))
        .group_by(col(Machine.id), col(Machine.hostname), col(Machine.machine_uuid))
        .order_by(func.count().desc())
    )
    update_rows = await session.exec(high_updates)
    update_machines = update_rows.all()
    update_lines = [
        MachineLine(
            hostname=_name(hostname, machine_uuid),
            detail=f"{n} MAJ critique(s)/importante(s)",
        )
        for hostname, machine_uuid, n in update_machines[:cap]
    ]

    # --- machines whose antivirus is not doing its job, named ---
    outdated_rows = await session.exec(
        select(Machine.hostname, Machine.machine_uuid, Machine.signature_age_days)
        .where(status_clause(MachineStatus.OUTDATED, now, days))
        .order_by(col(Machine.signature_age_days).desc().nulls_last())
        .limit(cap)
    )
    outdated_lines = [
        MachineLine(
            hostname=_name(hostname, machine_uuid),
            detail=(
                f"signatures vieilles de {age} j"
                if age is not None
                else "protection inactive ou jamais relevée"
            ),
        )
        for hostname, machine_uuid, age in outdated_rows.all()
    ]

    # --- detections Defender dates within the last day ---
    # Read off ``detected_at``, which is Defender's own clock and not when the
    # row was written: a poste coming back online after a week reports what
    # happened while it was away, and those detections belong to the day they
    # occurred. Undated detections are therefore not counted here — the alert
    # path is what covers them.
    since = now - timedelta(hours=settings.THREAT_ALERT_MAX_AGE_HOURS)
    new_threats = (
        await session.scalar(
            select(func.count())
            .select_from(Threat)
            .where(col(Threat.detected_at) >= since)
        )
        or 0
    )

    return Digest(
        generated_at=now,
        total=total,
        online=online,
        with_active_threats=len(threat_machines),
        with_high_severity_updates=len(update_machines),
        needs_verification=needs_verification,
        new_threats_24h=new_threats,
        outdated_antivirus=outdated,
        wu_pending=wu_pending,
        reboot_required=reboot_required,
        inactive=inactive,
        threat_lines=threat_lines,
        update_lines=update_lines,
        outdated_lines=outdated_lines,
    )


def _bullet_block(title: str, lines: list[MachineLine], total: int) -> list[str]:
    """A titled block of named postes, with the overflow stated rather than cut."""
    if not lines:
        return []
    out = [f"{title}", *(f"  • {line.hostname} — {line.detail}" for line in lines)]
    hidden = total - len(lines)
    if hidden > 0:
        out.append(f"  … et {hidden} autre(s) poste(s)")
    out.append("")
    return out


def render_digest(digest: Digest) -> tuple[str, str]:
    """The digest as (subject, plain-text body).

    The subject carries the headline so the mail can be triaged without being
    opened — a list of "Tia'i — résumé quotidien" in an inbox says nothing about
    which morning had a threat on it.
    """
    date = digest.generated_at.strftime("%d/%m/%Y")
    if digest.with_active_threats:
        headline = f"{digest.with_active_threats} poste(s) avec menace active"
    elif digest.with_high_severity_updates:
        headline = f"{digest.with_high_severity_updates} poste(s) à mettre à jour"
    elif digest.needs_verification:
        headline = f"{digest.needs_verification} poste(s) à vérifier"
    else:
        headline = "rien à signaler"
    subject = f"{settings.PROJECT_NAME} — parc du {date} : {headline}"

    body: list[str] = [
        f"État du parc au {date}.",
        "",
        f"{digest.total} poste(s) enregistré(s), {digest.online} en ligne à l'instant du relevé.",
        "",
    ]

    if digest.has_events:
        body.append("À TRAITER")
        if digest.with_active_threats:
            body.append(
                f"  {digest.with_active_threats} poste(s) avec au moins une menace active"
            )
        if digest.new_threats_24h:
            body.append(
                f"  {digest.new_threats_24h} détection(s) enregistrée(s) dans les dernières "
                f"{settings.THREAT_ALERT_MAX_AGE_HOURS} h"
            )
        if digest.with_high_severity_updates:
            body.append(
                f"  {digest.with_high_severity_updates} poste(s) avec une mise à jour "
                "critique ou importante en attente"
            )
        if digest.needs_verification:
            body.append(
                f"  {digest.needs_verification} poste(s) à vérifier (empreinte matérielle "
                "divergente ou doublon)"
            )
        body.append("")
    else:
        body += ["Aucune menace active, aucun correctif urgent en attente.", ""]

    body += [
        "ÉTAT COURANT",
        f"  Antivirus périmé ou inactif : {digest.outdated_antivirus} poste(s)",
        f"  Mises à jour Windows en attente : {digest.wu_pending} poste(s)",
        f"  Redémarrage requis : {digest.reboot_required} poste(s)",
        f"  Sans contact depuis plus de {settings.INACTIVE_AFTER_DAYS} j : "
        f"{digest.inactive} poste(s)",
        "",
    ]

    body += _bullet_block(
        "MENACES ACTIVES", digest.threat_lines, digest.with_active_threats
    )
    body += _bullet_block(
        "MISES À JOUR CRITIQUES OU IMPORTANTES",
        digest.update_lines,
        digest.with_high_severity_updates,
    )
    body += _bullet_block(
        "ANTIVIRUS À REPRENDRE", digest.outdated_lines, digest.outdated_antivirus
    )

    if settings.CONSOLE_BASE_URL:
        body.append(f"Ouvrir la console : {settings.CONSOLE_BASE_URL.rstrip('/')}")
    body.append("")
    body.append(
        "Vous recevez ce message parce que votre compte est réglé sur un résumé "
        "quotidien. Changez-le dans la console, page « Mon compte »."
    )
    return subject, "\n".join(body)


async def send_daily_digest(session: AsyncSession) -> int:
    """Mail the digest to the accounts that asked for one. Returns how many went out.

    One message per recipient rather than one message to all of them: the two
    cadences do not receive the same days, and putting every operator's address
    in a shared ``To:`` would hand each of them the console's user list.
    """
    digest = await build_digest(session)

    wants_daily = await recipients_for(session, [EmailPreference.DIGEST_DAILY])
    wants_events = (
        await recipients_for(session, [EmailPreference.DIGEST_EVENTS])
        if digest.has_events
        else []
    )
    recipients = list(dict.fromkeys([*wants_daily, *wants_events]))
    if not recipients:
        # Not a misconfiguration to work around: either nobody asked for a
        # digest, or nobody had anything to hear about today. Both are answers.
        logger.info("Daily digest: no recipient today, nothing sent")
        return 0

    subject, text = render_digest(digest)
    sent = 0
    for address in recipients:
        try:
            if await send_email(subject=subject, text=text, to=[address]):
                sent += 1
        except Exception:
            # One address failing must not cost the others their digest: a
            # bounced or malformed recipient is a per-address problem.
            logger.exception("Daily digest could not be sent to %s", address)
    logger.info("Daily digest sent to %d/%d recipient(s)", sent, len(recipients))
    return sent
