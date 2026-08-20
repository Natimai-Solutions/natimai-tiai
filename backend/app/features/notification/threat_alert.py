"""Immediate alert on a newly detected threat.

The one notification that cannot wait for the morning: a mail per poste and per
heartbeat that brought a detection nobody had seen before.

Three filters stand between a Defender line and someone's inbox, and each of
them is a mail that would otherwise be sent for nothing:

* only *new* detections (``crud.NewDetection``) — the agent re-reads the whole
  detection history on every poll, and a status moving to "quarantined" is not a
  new threat;
* only *recent* ones — a poste enrolling for the first time hands over years of
  Defender history in one call, and none of it happened today;
* only accounts on the ``IMMEDIATE`` cadence — everyone else hears about it in
  the digest, which is what they asked for.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import engine
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.notification.mailgun import send_email
from app.features.notification.recipients import recipients_for
from app.features.threat.crud import NewDetection
from app.features.user.models import EmailPreference

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MachineContext:
    """The poste as the alert names it, copied out of the ORM instance.

    A snapshot and not the ``Machine`` row itself, because the mail is sent
    *after* the heartbeat's transaction has committed: reading an attribute off
    a committed instance would lazy-load it synchronously inside the event loop
    (MissingGreenlet), and the heartbeat path is the last place to risk that.
    """

    id: uuid.UUID
    machine_uuid: str
    hostname: str | None
    domain: str | None
    ip_address: str | None
    session_username: str | None

    @classmethod
    def of(cls, machine: Machine) -> "MachineContext":
        """Snapshot a machine before its session commits."""
        return cls(
            id=machine.id,
            machine_uuid=machine.machine_uuid,
            hostname=machine.hostname,
            domain=machine.domain,
            ip_address=machine.ip_address,
            session_username=machine.session_username,
        )


def recent_detections(detections: list[NewDetection]) -> list[NewDetection]:
    """The detections worth alerting on: new *and* not backfilled history.

    A detection with no timestamp at all is kept: Defender did not say when, the
    agent has just reported it, and treating "unknown" as "old" would silence
    the very case where the console knows least.
    """
    cutoff = utcnow() - timedelta(hours=settings.THREAT_ALERT_MAX_AGE_HOURS)
    return [d for d in detections if d.detected_at is None or d.detected_at >= cutoff]


def render_alert(
    machine: MachineContext, detections: list[NewDetection]
) -> tuple[str, str]:
    """The alert as (subject, plain-text body)."""
    name = machine.hostname or machine.machine_uuid
    count = len(detections)
    subject = (
        f"{settings.PROJECT_NAME} — menace détectée sur {name}"
        if count == 1
        else f"{settings.PROJECT_NAME} — {count} menaces détectées sur {name}"
    )

    lines = [
        f"Microsoft Defender a signalé {count} détection(s) sur le poste {name}.",
        "",
    ]
    # Capped like the digest's own lists: a poste whose whole undated history
    # arrives at once — nothing dates it, so nothing filters it out by age —
    # would otherwise produce a mail of several hundred bullet lines. The
    # remainder is stated rather than dropped, and the fiche has them all.
    cap = settings.NOTIFICATION_MAX_ITEMS
    for d in detections[:cap]:
        parts = [d.threat_name or "menace non nommée"]
        if d.severity:
            parts.append(f"sévérité {d.severity}")
        if d.status:
            parts.append(f"statut {d.status}")
        if d.detected_at:
            parts.append(
                f"détectée le {d.detected_at.strftime('%d/%m/%Y à %H:%M UTC')}"
            )
        lines.append(f"  • {' — '.join(parts)}")
    if count > cap:
        lines.append(f"  … et {count - cap} autre(s) détection(s)")

    lines += [
        "",
        f"Poste : {name}",
        f"UUID : {machine.machine_uuid}",
        f"Domaine : {machine.domain or '—'}",
        f"Adresse IP : {machine.ip_address or '—'}",
        f"Session ouverte : {machine.session_username or '—'}",
        "",
    ]
    if settings.CONSOLE_BASE_URL:
        base = settings.CONSOLE_BASE_URL.rstrip("/")
        lines.append(f"Ouvrir la fiche du poste : {base}/machines/{machine.id}")
        lines.append("")
    lines.append(
        "Vous recevez ce message parce que votre compte est réglé sur les alertes "
        "immédiates. Changez-le dans la console, page « Mon compte »."
    )
    return subject, "\n".join(lines)


async def send_threat_alert(
    session: AsyncSession, machine: MachineContext, detections: list[NewDetection]
) -> int:
    """Mail the accounts on the immediate cadence. Returns how many went out."""
    fresh = recent_detections(detections)
    if not fresh:
        return 0
    recipients = await recipients_for(session, [EmailPreference.IMMEDIATE])
    if not recipients:
        return 0

    subject, text = render_alert(machine, fresh)
    sent = 0
    for address in recipients:
        try:
            if await send_email(subject=subject, text=text, to=[address]):
                sent += 1
        except Exception:
            logger.exception("Threat alert could not be sent to %s", address)
    return sent


async def alert_new_threats(
    machine: MachineContext, detections: list[NewDetection]
) -> None:
    """Background entry point: open a session of our own and send the alert.

    Runs after the heartbeat's response has gone out, on a session that is not
    the request's — that one is closed by then, and holding a database
    transaction open across an HTTP call to Mailgun would be worse anyway.

    Never raises. The caller is a background task with nobody to report to, and
    a Mailgun outage must not surface as a failed heartbeat: the poste would
    retry, and each retry would re-attempt a mail on a service already known to
    be down.
    """
    try:
        async with AsyncSession(engine) as session:
            await send_threat_alert(session, machine, detections)
    except Exception:
        logger.exception(
            "Threat alert failed for machine %s",
            machine.hostname or machine.machine_uuid,
        )
