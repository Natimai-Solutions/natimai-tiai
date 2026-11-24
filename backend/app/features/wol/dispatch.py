"""Waking postes: what ``POST /machines/wake`` does once the caller's rights
are checked, shared with a schedule's « réveiller d'abord »
(``features.schedule``).

Emitted by the server, or queued for a poste of the site to relay
(``WOL_RELAY_ENABLED``); either way one ``wake_on_lan`` row per poste, the
caller commits.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.base import utcnow
from app.features.command.models import Command, CommandStatus, CommandType
from app.features.machine.models import Machine
from app.features.wol import relay as wol_relay
from app.features.wol.sender import wake as emit_wake


@dataclass
class WakeResult:
    machine: Machine
    ok: bool
    detail: str
    code: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


async def wake(
    session: AsyncSession,
    machines: list[Machine],
    *,
    created_by: str | None,
    schedule_run_id: uuid.UUID | None = None,
) -> list[WakeResult]:
    """Wake each poste, in order; one result per poste, never an exception."""
    batch = (
        await wol_relay.open_batch(session, machines)
        if settings.WOL_RELAY_ENABLED
        else None
    )
    results: list[WakeResult] = []
    for machine in machines:
        if settings.WOL_RELAY_ENABLED:
            # Queued for a poste of the site, or refused on the spot; either
            # way the relay module writes the history row itself.
            relayed = await wol_relay.queue_relayed_wake(
                session, machine, created_by=created_by, batch=batch
            )
            results.append(
                WakeResult(
                    machine, relayed.ok, relayed.detail, relayed.code, relayed.params
                )
            )
            continue
        outcome = await emit_wake(
            mac=machine.mac_address,
            ip=machine.ip_address,
            prefix_length=machine.ip_prefix_length,
        )
        now = utcnow()
        session.add(
            Command(
                machine_id=machine.id,
                type=CommandType.WAKE_ON_LAN.value,
                status=(
                    CommandStatus.SUCCEEDED.value
                    if outcome.ok
                    else CommandStatus.FAILED.value
                ),
                created_by=created_by,
                created_at=now,
                # Already terminal, so it never had a life to expire — the
                # sweep only ever touches PENDING rows. Set to the creation
                # instant so the column reads as "was never offered to anyone"
                # rather than dangling an hour into the future.
                expires_at=now,
                started_at=now,
                finished_at=now,
                result_output=outcome.detail if outcome.ok else None,
                error=None if outcome.ok else outcome.detail,
                result_code=outcome.code,
                result_params=outcome.params,
            )
        )
        results.append(
            WakeResult(
                machine, outcome.ok, outcome.detail, outcome.code, outcome.params
            )
        )
    if schedule_run_id is not None:
        # The rows this call wrote, whichever path wrote them: they belong to
        # the run, in its history.
        ids = {m.id for m in machines}
        for obj in session.new:
            if (
                isinstance(obj, Command)
                and obj.type == CommandType.WAKE_ON_LAN.value
                and obj.machine_id in ids
            ):
                obj.schedule_run_id = schedule_run_id
    return results
