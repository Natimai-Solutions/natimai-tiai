"""Put an event in the queue of every webhook that asked for it (C8).

Called inside the transaction of the change being reported: the delivery
lives or dies with it. One query for the webhooks — none subscribed, nothing
written — and one row each. The payload is the same for every format; the
chat formats word it when they send it (``texts.py``).
"""

import uuid
from typing import Any

from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.webhook.models import Webhook, WebhookDelivery, WebhookEvent

# Items named in one event at most: the first evaluation of the alerts on a
# large parc opens hundreds; the payload says how many, and names these.
MAX_ITEMS = 100


def envelope(event: WebhookEvent, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "event": event.value,
        "occurred_at": utcnow().isoformat(),
        "data": data,
    }


async def emit(session: AsyncSession, event: WebhookEvent, data: dict[str, Any]) -> int:
    """Queue ``event`` for every enabled webhook subscribed to it. Does not
    commit. Returns the deliveries queued."""
    rows = await session.exec(
        select(col(Webhook.id)).where(
            col(Webhook.enabled).is_(True),
            col(Webhook.events).op("@>")(cast([event.value], JSONB)),
        )
    )
    ids = list(rows.all())
    if not ids:
        return 0
    payload = envelope(event, data)
    for webhook_id in ids:
        session.add(
            WebhookDelivery(webhook_id=webhook_id, event=event.value, payload=payload)
        )
    return len(ids)


def items(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A list of items, bounded, with how many there were."""
    return {"total": len(rows), "items": rows[:MAX_ITEMS]}


def machine_ref(machine: Any) -> dict[str, Any]:
    """A poste as an event names it."""
    return {
        "id": str(machine.id),
        "hostname": getattr(machine, "hostname", None),
    }


# --- The events, as the call sites raise them ---------------------------------


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def threats_detected(
    session: AsyncSession, machine: Any, detections: list[Any]
) -> int:
    rows = [
        {
            "detection_id": d.detection_id,
            "name": d.threat_name,
            "severity": d.severity,
            "status": d.status,
            "detected_at": _iso(d.detected_at),
        }
        for d in detections
    ]
    return await emit(
        session,
        WebhookEvent.THREAT_DETECTED,
        {"machine": machine_ref(machine), **items(rows)},
    )


async def checks_created(
    session: AsyncSession,
    created: list[tuple[Any, Any]],
    *,
    requested_by: str,
    instructions: str | None,
    priority: str | None = None,
    category: str | None = None,
    instructions_of: dict[Any, str | None] | None = None,
) -> int:
    """One event for the verifications a request opened: ``created`` as
    (machine, check id). Each item carries its check id, which
    ``check.closed`` names too; ``instructions_of`` gives per-poste
    instructions where they differ (the checks the alerts open)."""
    if not created:
        return 0
    rows = []
    for machine, check_id in created:
        row = {**machine_ref(machine), "check_id": str(check_id)}
        if instructions_of is not None:
            row["instructions"] = instructions_of.get(machine.id)
        rows.append(row)
    first_machine, first_check = created[0]
    return await emit(
        session,
        WebhookEvent.CHECK_CREATED,
        {
            **items(rows),
            "machine": machine_ref(first_machine),
            "check_id": str(first_check),
            "requested_by": requested_by,
            "instructions": instructions,
            "priority": priority,
            "category": category,
        },
    )


async def check_closed(
    session: AsyncSession,
    machine: Any,
    *,
    check_id: Any,
    closed_by: str,
    note: str | None,
) -> int:
    return await emit(
        session,
        WebhookEvent.CHECK_CLOSED,
        {
            "machine": machine_ref(machine),
            "check_id": str(check_id),
            "closed_by": closed_by,
            "note": note,
        },
    )


async def command_failed(session: AsyncSession, machine: Any, command: Any) -> int:
    return await emit(
        session,
        WebhookEvent.COMMAND_FAILED,
        {
            "machine": machine_ref(machine),
            "command_id": str(command.id),
            "type": str(command.type),
            "result_code": command.result_code,
            "error": (command.error or "")[:500] or None,
        },
    )


async def commands_failed(session: AsyncSession, command_ids: list[Any]) -> int:
    """``command.failed`` for commands the server closed as failed (no
    answer from the poste): one event each, as for an agent's verdict."""
    from app.features.command.models import Command
    from app.features.machine.models import Machine

    if not command_ids:
        return 0
    rows = (
        await session.exec(
            select(Command, Machine)
            .join(Machine, col(Machine.id) == col(Command.machine_id))
            .where(col(Command.id).in_(command_ids))
        )
    ).all()
    queued = 0
    for command, machine in rows:
        queued += await command_failed(session, machine, command)
    return queued


async def alerts_changed(
    session: AsyncSession,
    opened: list[tuple[Any, str, Any]],
    resolved: list[tuple[Any, str]],
) -> int:
    """One event for the alerts an evaluation opened, one for those it
    resolved: ``opened`` as (machine id, rule, detail), ``resolved`` as
    (machine id, rule)."""
    from app.features.machine.models import Machine

    if not opened and not resolved:
        return 0
    ids = {m for m, *_ in opened} | {m for m, _ in resolved}
    names = dict(
        (
            await session.exec(
                select(col(Machine.id), col(Machine.hostname)).where(
                    col(Machine.id).in_(ids)
                )
            )
        ).all()
    )
    queued = 0
    if opened:
        queued += await emit(
            session,
            WebhookEvent.ALERT_OPENED,
            items(
                [
                    {
                        "machine_id": str(m),
                        "hostname": names.get(m),
                        "rule": rule,
                        "detail": detail,
                    }
                    for m, rule, detail in opened
                ]
            ),
        )
    if resolved:
        queued += await emit(
            session,
            WebhookEvent.ALERT_RESOLVED,
            items(
                [
                    {"machine_id": str(m), "hostname": names.get(m), "rule": rule}
                    for m, rule in resolved
                ]
            ),
        )
    return queued


async def approval_requested(session: AsyncSession, request: Any) -> int:
    """A request waits for its approval (C10): what is asked, on how many
    postes, by whom, until when — never the list of postes. The readers of
    the webhooks are unrestricted accounts: the target may be described."""
    target = dict(request.target or {})
    kind = target.get("kind")
    if request.kind == "schedule":
        described: dict[str, Any] = {"target": kind}
        if target.get("value") is not None:
            described[str(kind)] = target.get("value")
    elif kind == "machines":
        described = {"target": "machines", "requested": request.machine_count}
    elif kind == "all":
        described = {"target": "all"}
    else:
        described = {"target": kind, str(kind): target.get("value")}
    return await emit(
        session,
        WebhookEvent.APPROVAL_REQUESTED,
        {
            "id": str(request.id),
            "kind": request.kind,
            "command_type": request.command_type,
            "package": request.package_name,
            "schedule": request.schedule_name,
            "target": described,
            "count": request.machine_count,
            "threshold": request.threshold,
            "requested_by": request.requested_by,
            "expires_at": _iso(request.expires_at),
        },
    )
