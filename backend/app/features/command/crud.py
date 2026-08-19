"""Command queue operations: bulk creation, de-duplication and expiry sweep."""

import uuid
from datetime import datetime

from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.command.models import (
    TERMINAL_STATUSES,
    Command,
    CommandStatus,
    CommandType,
)


async def machines_with_open_command(
    session: AsyncSession,
    *,
    machine_ids: list[uuid.UUID],
    command_type: CommandType,
) -> set[uuid.UUID]:
    """Which of these machines already carry an unfinished command of this type.

    "Unfinished" is two conditions, and the second one is what keeps this from
    becoming a trap:

    * a non-terminal status — pending, delivered or running. An expired one does
      not count: that is precisely the case an administrator re-queues, the
      poste having been off the whole time.
    * **still inside its TTL.** Only PENDING commands are ever swept to EXPIRED
      (``mark_expired`` — once delivered, the agent owns the command). So a
      command handed to an agent that never came back stays DELIVERED for good,
      and without this clause it would lock its type out of that machine
      permanently. Past ``expires_at`` an administrator is entitled to assume
      the poste is not going to answer; should it answer anyway, its verdict
      still lands on the original row, which is written whatever its status.
    """
    if not machine_ids:
        return set()
    stmt = (
        select(Command.machine_id)
        .where(col(Command.machine_id).in_(machine_ids))
        .where(col(Command.type) == command_type.value)
        .where(col(Command.status).notin_([s.value for s in TERMINAL_STATUSES]))
        .where(col(Command.expires_at) > utcnow())
    )
    rows = await session.exec(stmt)
    return set(rows.all())


async def create_for_machines(
    session: AsyncSession,
    *,
    machine_ids: list[uuid.UUID],
    command_type: CommandType,
    created_by: str | None,
    expires_at: datetime,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Queue one command per machine, skipping those that already have it open.

    Returns ``(created ids, skipped machine ids)``. The caller commits.

    The de-duplication is per (machine, type) and deliberately uniform across
    the catalogue rather than reserved for the destructive entries: queueing a
    second `full_scan` behind one that is still running gains nothing (Defender
    serialises scans itself and the agent executes one command at a time), and
    a rule that applied to some types and not others would be a rule nobody
    could predict from the console.

    What this does *not* claim to be is atomic. Two admins pressing the same
    button in the same second can still both pass this check under READ
    COMMITTED, and the outcome is two identical commands — today's behaviour,
    simply made rare instead of routine. Closing that window means a partial
    unique index on (machine_id, type) over the non-terminal statuses; it costs
    a migration and a data cleanup, and buys a case the console has never seen.
    """
    already_open = await machines_with_open_command(
        session, machine_ids=machine_ids, command_type=command_type
    )
    targets = [m for m in machine_ids if m not in already_open]

    commands = [
        Command(
            machine_id=machine_id,
            type=command_type.value,
            created_by=created_by,
            expires_at=expires_at,
        )
        for machine_id in targets
    ]
    session.add_all(commands)
    await session.flush()
    # Ordered like the input rather than taken from the set, so a caller that
    # reports them gets a stable list.
    skipped = [m for m in machine_ids if m in already_open]
    return [c.id for c in commands], skipped


async def mark_expired(
    session: AsyncSession, *, machine_id: uuid.UUID | None = None
) -> int:
    """Flip still-pending commands past their expiry to EXPIRED (plan §2.8).

    Only PENDING commands are expired: once delivered, the agent owns the
    command and its reported result is authoritative. Scoped to one machine when
    ``machine_id`` is given. The caller commits.
    """
    stmt = (
        update(Command)
        .where(col(Command.status) == CommandStatus.PENDING)
        .where(col(Command.expires_at) < utcnow())
        .values(status=CommandStatus.EXPIRED)
    )
    if machine_id is not None:
        stmt = stmt.where(col(Command.machine_id) == machine_id)
    result = await session.execute(stmt)
    return result.rowcount or 0  # type: ignore[attr-defined]
