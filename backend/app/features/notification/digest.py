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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, true
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.alert.models import ALL_RULES, MachineAlert
from app.features.asset import crud as asset_crud
from app.features.base import utcnow
from app.features.license import crud as license_crud
from app.features.license.crud import LicenseState
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    signature_age_expr,
    status_clause,
    windows_update_clause,
)
from app.features.machine.status import WindowsUpdateFilter as WUFilter
from app.features.notification.digest_texts import TEXTS, DigestTexts
from app.features.notification.language import mail_language, texts_for
from app.features.notification.outbox import queue_email
from app.features.notification.recipients import users_for
from app.features.notification.tasks import (
    fleet_maintenance,
    mail_date,
    personal_block,
)
from app.features.setting import crud as setting_crud
from app.features.setting.crud import license_expiry_days
from app.features.setting.email_policy import email_policy
from app.features.threat.models import Threat
from app.features.user import crud as user_crud
from app.features.user.models import EmailPreference, Language, User
from app.features.user.permissions import Action, Resource, has_permission
from app.features.user.scope import Scope, machine_clause, machine_ids_clause, restrict
from app.features.windows_update.models import WindowsUpdate

logger = logging.getLogger(__name__)

# MSRC ratings that count as "à installer sans attendre". Defined here rather
# than taken as "anything not low": an unrated update (NULL severity) is the
# common case for drivers, and pulling those into an alert would make every
# digest urgent.
HIGH_SEVERITIES = ("critical", "important")


@dataclass
class MachineLine:
    """One poste as a digest mentions it: a name and why it is listed.

    ``detail`` is worded when the mail is, in its reader's language: one
    digest is built per scope and read by people who may not share one.
    """

    hostname: str
    detail: str | Callable[[DigestTexts], str]

    def worded(self, texts: DigestTexts) -> str:
        return self.detail if isinstance(self.detail, str) else self.detail(texts)


def _threats_detail(n: int) -> Callable[[DigestTexts], str]:
    return lambda t: t.threats_detail(n)


def _updates_detail(n: int) -> Callable[[DigestTexts], str]:
    return lambda t: t.updates_detail(n)


def _antivirus_detail(age: int | None) -> Callable[[DigestTexts], str]:
    if age is None:
        return lambda t: t.protection_inactive
    return lambda t: t.signature_age_detail(age)


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
    # The threshold ``inactive`` was counted with, printed beside it: the page
    # Paramètres can change it, so the mail must say which one it used.
    inactive_after_days: int = 30
    # --- named examples, capped at NOTIFICATION_MAX_ITEMS ---
    threat_lines: list[MachineLine] = field(default_factory=list)
    update_lines: list[MachineLine] = field(default_factory=list)
    outdated_lines: list[MachineLine] = field(default_factory=list)
    # Postes with an open alert, per rule (``app.features.alert``) — only the
    # rules with at least one; printed after the running state.
    alerts_by_rule: dict[str, int] = field(default_factory=dict)

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


async def _count(
    session: AsyncSession, clause: ColumnElement[bool] | None, scope: Any = None
) -> int:
    stmt = restrict(select(func.count()).select_from(Machine), scope)
    if clause is not None:
        stmt = stmt.where(clause)
    return await session.scalar(stmt) or 0


def _name(machine_hostname: str | None, machine_uuid: str) -> str:
    """A poste as an operator recognises it: its name, else its UUID."""
    return machine_hostname or machine_uuid


async def build_digest(session: AsyncSession, scope: Scope | None = None) -> Digest:
    """Read the current state of the fleet — of the part of it ``scope``
    covers, for an account confined to some sites (``user/scope.py``).
    A retired poste is out of the parc: out of every figure and every list,
    as on the dashboard."""
    scope_clause = machine_clause(scope)
    in_parc = asset_crud.in_parc_clause()
    in_scope = in_parc if scope_clause is None else and_(scope_clause, in_parc)
    now = utcnow()
    fleet = await setting_crud.fleet_policy(session)
    days = fleet.inactive_after_days
    # Judged on the signature age as it stands now, as the console does: a
    # poste silent for a month is not « à jour » in the mail either.
    max_age = fleet.signature_max_age_days
    cap = settings.NOTIFICATION_MAX_ITEMS

    total = await _count(session, None, in_scope)
    # Same window the console's green dot uses, so the two never disagree.
    online_since = now - timedelta(seconds=settings.OFFLINE_AFTER_SECONDS)
    online = await _count(session, col(Machine.last_seen) > online_since, in_scope)

    outdated = await _count(
        session, status_clause(MachineStatus.OUTDATED, now, days, max_age), in_scope
    )
    needs_verification = await _count(
        session, status_clause(MachineStatus.NEEDS_VERIFICATION, now, days), in_scope
    )
    inactive = await _count(
        session, status_clause(MachineStatus.INACTIVE, now, days), in_scope
    )
    wu_pending = await _count(
        session, windows_update_clause(WUFilter.PENDING), in_scope
    )
    reboot_required = await _count(
        session, windows_update_clause(WUFilter.REBOOT_REQUIRED), in_scope
    )

    # --- machines carrying an active threat, named ---
    active_threats = (
        select(Machine.hostname, Machine.machine_uuid, func.count().label("n"))
        .join(Threat, col(Threat.machine_id) == col(Machine.id))
        .where(col(Threat.status) == "active")
        .where(in_scope if in_scope is not None else true())
        .group_by(col(Machine.id), col(Machine.hostname), col(Machine.machine_uuid))
        .order_by(func.count().desc())
    )
    threat_rows = await session.exec(active_threats)
    threat_machines = threat_rows.all()
    threat_lines = [
        MachineLine(hostname=_name(hostname, machine_uuid), detail=_threats_detail(n))
        for hostname, machine_uuid, n in threat_machines[:cap]
    ]

    # --- machines with a critical or important update waiting ---
    high_updates = (
        select(Machine.hostname, Machine.machine_uuid, func.count().label("n"))
        .join(WindowsUpdate, col(WindowsUpdate.machine_id) == col(Machine.id))
        .where(func.lower(col(WindowsUpdate.severity)).in_(HIGH_SEVERITIES))
        .where(in_scope if in_scope is not None else true())
        .group_by(col(Machine.id), col(Machine.hostname), col(Machine.machine_uuid))
        .order_by(func.count().desc())
    )
    update_rows = await session.exec(high_updates)
    update_machines = update_rows.all()
    update_lines = [
        MachineLine(hostname=_name(hostname, machine_uuid), detail=_updates_detail(n))
        for hostname, machine_uuid, n in update_machines[:cap]
    ]

    # --- machines whose antivirus is not doing its job, named ---
    outdated_rows = await session.exec(
        select(Machine.hostname, Machine.machine_uuid, signature_age_expr(now))
        .where(status_clause(MachineStatus.OUTDATED, now, days, max_age))
        .where(in_scope if in_scope is not None else true())
        .order_by(signature_age_expr(now).desc().nulls_last())
        .limit(cap)
    )
    outdated_lines = [
        MachineLine(
            hostname=_name(hostname, machine_uuid), detail=_antivirus_detail(age)
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
            restrict(
                select(func.count()).select_from(Threat),
                machine_ids_clause(scope, col(Threat.machine_id)),
            ).where(
                col(Threat.detected_at) >= since,
                asset_crud.in_parc_ids_clause(col(Threat.machine_id)),
            )
        )
        or 0
    )

    # --- open alerts, postes per rule, in the catalogue's order ---
    alert_rows = await session.exec(
        restrict(
            select(col(MachineAlert.rule), func.count()),
            machine_ids_clause(scope, col(MachineAlert.machine_id)),
        )
        .where(
            col(MachineAlert.resolved_at).is_(None),
            asset_crud.in_parc_ids_clause(col(MachineAlert.machine_id)),
        )
        .group_by(col(MachineAlert.rule))
    )
    open_alerts = dict(alert_rows.all())
    alerts_by_rule = {
        r.value: open_alerts[r.value] for r in ALL_RULES if open_alerts.get(r.value)
    }

    return Digest(
        alerts_by_rule=alerts_by_rule,
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
        inactive_after_days=days,
        threat_lines=threat_lines,
        update_lines=update_lines,
        outdated_lines=outdated_lines,
    )


def _bullet_block(
    t: DigestTexts, title: str, lines: list[MachineLine], total: int
) -> list[str]:
    """A titled block of named postes, with the overflow stated rather than cut."""
    if not lines:
        return []
    out = [f"{title}", *(f"  • {line.hostname} — {line.worded(t)}" for line in lines)]
    hidden = total - len(lines)
    if hidden > 0:
        out.append(t.more_machines(hidden))
    out.append("")
    return out


def _ending(t: DigestTexts, personal: list[str]) -> list[str]:
    """What every digest ends with: the recipient's own tasks, the console's
    address, then — last — why they receive it."""
    out = list(personal)
    if settings.console_base_url:
        out.append(t.open_console(settings.console_base_url))
        out.append("")
    out.append(t.footer)
    return out


def render_digest(
    digest: Digest,
    personal: list[str] | None = None,
    language: Language | None = None,
    licenses: list[LicenseState] | None = None,
) -> tuple[str, str]:
    """The digest as (subject, plain-text body), ``personal`` — the
    recipient's « VOS TÂCHES » block (``tasks.personal_block``) — after the
    parc and before the footer. In ``language``, else ``DEFAULT_LANGUAGE``.

    The subject carries the headline so the mail can be triaged without being
    opened — a list of "Tia'i — résumé quotidien" in an inbox says nothing about
    which morning had a threat on it.
    """
    t = texts_for(TEXTS, language)
    date = mail_date(digest.generated_at)
    if digest.with_active_threats:
        headline = t.headline_threats(digest.with_active_threats)
    elif digest.with_high_severity_updates:
        headline = t.headline_updates(digest.with_high_severity_updates)
    elif digest.needs_verification:
        headline = t.headline_verify(digest.needs_verification)
    else:
        headline = t.headline_quiet
    subject = t.subject(settings.PROJECT_NAME, date, headline)

    body: list[str] = [
        t.state_at(date),
        "",
        t.totals(digest.total, digest.online),
        "",
    ]

    if digest.has_events:
        body.append(t.to_handle)
        if digest.with_active_threats:
            body.append(t.threats_line(digest.with_active_threats))
        if digest.new_threats_24h:
            body.append(
                t.new_threats_line(
                    digest.new_threats_24h, settings.THREAT_ALERT_MAX_AGE_HOURS
                )
            )
        if digest.with_high_severity_updates:
            body.append(t.updates_line(digest.with_high_severity_updates))
        if digest.needs_verification:
            body.append(t.verify_line(digest.needs_verification))
        body.append("")
    else:
        body += [t.nothing_urgent, ""]

    body += [
        t.current_state,
        t.outdated_antivirus(digest.outdated_antivirus),
        t.wu_pending(digest.wu_pending),
        t.reboot_required(digest.reboot_required),
        t.inactive(digest.inactive_after_days, digest.inactive),
        "",
    ]

    if digest.alerts_by_rule:
        body.append(t.title_alerts)
        body += [t.alert_line(rule, n) for rule, n in digest.alerts_by_rule.items()]
        body.append("")

    if licenses:
        body.append(t.title_licenses)
        body += _license_lines(t, licenses)
        body.append("")

    body += _bullet_block(
        t, t.title_threats, digest.threat_lines, digest.with_active_threats
    )
    body += _bullet_block(
        t, t.title_updates, digest.update_lines, digest.with_high_severity_updates
    )
    body += _bullet_block(
        t, t.title_antivirus, digest.outdated_lines, digest.outdated_antivirus
    )

    body += _ending(t, personal or [])
    return subject, "\n".join(body)


def _license_lines(t: DigestTexts, licenses: list[LicenseState]) -> list[str]:
    """A line per finding: a licence both over its count and ending has two.
    The dates are the contract's own days, printed as such (no zone)."""
    lines = []
    for state in licenses:
        lic = state.license
        if state.over and lic.seats is not None:
            lines.append(t.license_over(lic.name, state.installed, lic.seats))
        if lic.expires_on is not None and state.expiry == "soon":
            lines.append(t.license_soon(lic.name, f"{lic.expires_on:%d/%m/%Y}"))
        elif lic.expires_on is not None and state.expiry == "expired":
            lines.append(t.license_expired(lic.name, f"{lic.expires_on:%d/%m/%Y}"))
    return lines


def render_tasks_digest(
    personal: list[str], now: datetime, language: Language | None = None
) -> tuple[str, str]:
    """The digest of an account that reads no poste (no ``machine:read``):
    nothing of the parc, only its own tasks."""
    t = texts_for(TEXTS, language)
    date = mail_date(now)
    subject = t.tasks_subject(settings.PROJECT_NAME, date)
    return subject, "\n".join([t.tasks_intro(date), "", *_ending(t, personal)])


@dataclass
class PlannedDigest:
    """Who gets a digest today, and what goes in it."""

    user: User
    # The parc as this account may read it; None for an account without
    # machine:read, whose digest is its tasks alone.
    digest: Digest | None
    personal: list[str]
    # The licences to look at (C6), for an account that reads them on the
    # whole parc; empty otherwise.
    licenses: list[LicenseState] = field(default_factory=list)


async def plan_daily_digest(session: AsyncSession) -> list[PlannedDigest]:
    """Every digest the run would queue, without queueing anything — what the
    weekly reminder asks to know which owners already have their tasks in
    today's digest.

    The parc's sections go only to accounts that read postes
    (``machine:read``), confined to their scope: an account that may only
    read the settings is not mailed the names of the postes. An account that
    reads none is mailed its tasks when it has some, and nothing otherwise.
    """
    wants_daily = await users_for(session, [EmailPreference.DIGEST_DAILY])
    wants_events = await users_for(session, [EmailPreference.DIGEST_EVENTS])
    users = sorted(
        {u.id: u for u in [*wants_daily, *wants_events]}.values(),
        key=lambda u: u.email,
    )
    if not users:
        return []

    now = utcnow()
    # The parc's maintenance is resolved once for the run, not per recipient.
    fleet = await fleet_maintenance(session, now)
    # One digest per distinct scope: an account confined to a site is told
    # about that site, and "events only" is decided on what *it* would read.
    # Most installations have one scope — everybody's — hence one build.
    digests: dict[Scope | None, Digest] = {}
    # The licences to look at, read once for the run when someone reads them.
    licenses: list[LicenseState] | None = None
    planned: list[PlannedDigest] = []
    for user in users:
        authority = await user_crud.user_authority(session, user.id)
        personal = await personal_block(session, user, now, fleet=fleet)
        if not has_permission(
            authority.permissions, Resource.MACHINE.value, Action.READ.value
        ):
            if personal:
                planned.append(PlannedDigest(user, None, personal))
            continue
        scope = authority.scope
        if scope not in digests:
            digests[scope] = await build_digest(session, scope)
        digest = digests[scope]
        if user.email_preference == EmailPreference.DIGEST_EVENTS and not (
            digest.has_events
        ):
            continue
        to_review: list[LicenseState] = []
        if scope is None and has_permission(
            authority.permissions, Resource.LICENSE.value, Action.READ.value
        ):
            if licenses is None:
                licenses = await license_crud.attention(
                    session, now.date(), await license_expiry_days(session)
                )
            to_review = licenses
        planned.append(PlannedDigest(user, digest, personal, to_review))
    return planned


async def send_daily_digest(session: AsyncSession) -> int:
    """Queue the digest for the accounts that asked for one. Returns how many.

    One message per recipient rather than one message to all of them: the two
    cadences do not receive the same days, and putting every operator's address
    in a shared ``To:`` would hand each of them the console's user list.

    Queued, not sent: the rows land in the outbox and the worker's drain sends
    them — with retries, so a Mailgun or proxy incident delays the digest
    instead of losing it. The body is a dated snapshot ("État du parc au …"),
    so a retried digest stays truthful about the morning it describes.
    """
    planned = await plan_daily_digest(session)
    if not planned:
        # Not a misconfiguration to work around: either nobody asked for a
        # digest, or nobody had anything to hear about today. Both are answers.
        logger.info("Daily digest: no recipient today, nothing sent")
        return 0

    # Read the mail settings now, not as the API last saw them: the worker
    # may run for weeks, and a provider set up in the console this afternoon
    # must carry this morning's digest.
    if not (await email_policy(session)).enabled:
        logger.info("Daily digest: no e-mail provider is configured, nothing queued")
        return 0

    queued = 0
    for plan in planned:
        # The same parc for everyone who reads it, then what is *theirs*: the
        # verifications they were handed, the maintenances they own that are due.
        # In their language: the parc is read once per scope, worded per reader.
        language = mail_language(plan.user.language)
        if plan.digest is not None:
            subject, body = render_digest(
                plan.digest, plan.personal, language, plan.licenses
            )
        else:
            subject, body = render_tasks_digest(plan.personal, utcnow(), language)
        if queue_email(session, to=plan.user.email, subject=subject, text=body):
            queued += 1
    await session.commit()
    logger.info("Daily digest queued for %d/%d recipient(s)", queued, len(planned))
    return queued
