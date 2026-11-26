"""The approval mails (C10, §2.5).

* To each account that could approve a new request — whose e-mail setting is
  not « rien » — in its language: who asks what, on how many postes, until
  when, with a link to the page « Approbations ».
* To the author at each outcome — approved, rejected, expired, failed —
  whatever their cadence, as ``schedule_mail``: it is about something they
  asked for. Numbers only, never a poste's name: one out of their scope
  since must not be named to them.

Queued in the transaction that creates or closes the request.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.notification.approval_mail_texts import TEXTS, ApprovalMailTexts
from app.features.notification.language import mail_language
from app.features.notification.outbox import queue_email
from app.features.user.models import EmailPreference, Language, User


@dataclass(frozen=True)
class RequestView:
    """What the mails say of a request, copied out of the ORM row."""

    kind: str
    command_type: str
    package_name: str | None
    target_kind: str
    # The domain, site, status, room or building name the target names.
    target_value: str | None
    count: int
    threshold: int
    expires_at: datetime
    requested_by: str
    schedule_name: str | None = None
    status: str = "pending"
    decided_by: str | None = None
    note: str | None = None
    result_code: str | None = None
    result_params: dict[str, Any] | None = None
    created: int | None = None
    skipped: int | None = None
    left_out: int | None = None


async def target_value(session: AsyncSession, target: dict[str, Any]) -> str | None:
    """The words of a target's value: a room's or building's name rather
    than its id."""
    from app.features.room.models import Building, Room

    kind, value = target.get("kind"), target.get("value")
    if kind in ("room", "building") and isinstance(value, str):
        try:
            place_id = uuid.UUID(value)
        except ValueError:
            return value
        place: Room | Building | None = (
            await session.get(Room, place_id)
            if kind == "room"
            else await session.get(Building, place_id)
        )
        return place.name if place is not None else value
    return value if isinstance(value, str) else None


async def view_of(session: AsyncSession, request: Any) -> RequestView:
    return RequestView(
        kind=request.kind,
        command_type=request.command_type,
        package_name=request.package_name,
        target_kind=str(request.target.get("kind")),
        target_value=await target_value(session, request.target),
        count=request.machine_count,
        threshold=request.threshold,
        expires_at=request.expires_at,
        requested_by=request.requested_by,
        schedule_name=request.schedule_name,
        status=request.status,
        decided_by=request.decided_by,
        note=request.note,
        result_code=request.result_code,
        result_params=request.result_params,
        created=request.created,
        skipped=request.skipped,
        left_out=request.left_out,
    )


def _link() -> str | None:
    if not settings.console_base_url:
        return None
    return f"{settings.console_base_url}/#/approvals"


def _action(t: ApprovalMailTexts, view: RequestView) -> str:
    template = t.actions.get(view.command_type, view.command_type)
    return template.format(package=view.package_name or "?")


def _target(t: ApprovalMailTexts, view: RequestView) -> str:
    template = t.targets.get(view.target_kind, view.target_kind)
    return template.format(value=view.target_value or "?")


def render_request(view: RequestView, language: Language) -> tuple[str, str]:
    """``(subject, body)`` of the mail to a possible approver."""
    t = TEXTS[language]
    action = _action(t, view)
    subject = t.subject_request.format(
        project=settings.PROJECT_NAME, action=action, count=view.count
    )
    intro = (
        t.intro_schedule.format(
            requested_by=view.requested_by,
            name=view.schedule_name or "?",
            action=action,
            count=view.count,
            target=_target(t, view),
        )
        if view.kind == "schedule"
        else t.intro_command.format(
            requested_by=view.requested_by,
            action=action,
            count=view.count,
            target=_target(t, view),
        )
    )
    lines = [
        intro,
        t.threshold.format(threshold=view.threshold),
        t.expires.format(expires=view.expires_at.strftime("%d/%m/%Y %H:%M")),
        "",
    ]
    link = _link()
    if link:
        lines += [t.decide.format(url=link), ""]
    lines.append(t.footer_request)
    return subject, "\n".join(lines)


def render_outcome(view: RequestView, language: Language) -> tuple[str, str] | None:
    """``(subject, body)`` of the mail to the author, or None for a status
    that is not told (pending, cancelled)."""
    t = TEXTS[language]
    action = _action(t, view)
    request = (
        t.request_schedule.format(
            name=view.schedule_name or "?", action=action, count=view.count
        )
        if view.kind == "schedule"
        else t.request_command.format(action=action, count=view.count)
    )
    project = settings.PROJECT_NAME
    if view.status == "approved":
        subject = t.subject_approved.format(project=project)
        lines = [t.approved.format(request=request, decided_by=view.decided_by or "?")]
        if view.kind == "schedule":
            lines.append(t.approved_schedule)
        else:
            lines.append(
                t.approved_counts.format(
                    created=view.created or 0,
                    skipped=view.skipped or 0,
                    left_out=view.left_out or 0,
                )
            )
    elif view.status == "rejected":
        subject = t.subject_rejected.format(project=project)
        lines = [t.rejected.format(request=request, decided_by=view.decided_by or "?")]
        if view.note:
            lines.append(t.note.format(note=view.note))
    elif view.status == "expired":
        subject = t.subject_expired.format(project=project)
        lines = [t.expired.format(request=request)]
    elif view.status == "failed":
        subject = t.subject_failed.format(project=project)
        code = view.result_code or ""
        cause = t.causes.get(code, code).format(**(view.result_params or {}))
        lines = [t.failed.format(request=request, cause=cause)]
    else:
        return None
    link = _link()
    body = [*lines, ""]
    if link:
        body += [t.open_page.format(url=link), ""]
    body.append(t.footer_outcome)
    return subject, "\n".join(body)


async def queue_request_mails(
    session: AsyncSession, request: Any, approvers: list[User]
) -> int:
    """Mail each possible approver that takes mail. The caller commits."""
    view = await view_of(session, request)
    sent = 0
    for user in approvers:
        if not user.is_active or user.email_preference == EmailPreference.NONE:
            continue
        subject, text = render_request(view, mail_language(user.language))
        if queue_email(session, to=user.email, subject=subject, text=text):
            sent += 1
    return sent


async def queue_outcome_mail(
    session: AsyncSession, request: Any, author: User | None
) -> bool:
    """Mail the author the outcome of their request, if there is one to
    write to. The caller commits."""
    if author is None or not author.is_active:
        return False
    rendered = render_outcome(
        await view_of(session, request), mail_language(author.language)
    )
    if rendered is None:
        return False
    subject, text = rendered
    return queue_email(session, to=author.email, subject=subject, text=text)
