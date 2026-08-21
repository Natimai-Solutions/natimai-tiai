"""Machine reconciliation: merging a duplicate record into the one to keep."""

from sqlalchemy import delete, exists, update
from sqlalchemy.orm import aliased
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.command.models import Command
from app.features.machine.models import Machine
from app.features.threat.models import Threat


async def merge_into(
    session: AsyncSession, *, target: Machine, source: Machine
) -> None:
    """Merge ``source`` into ``target`` (plan §8): reattach the source's threats
    and commands to the target, clear the verification flag, and delete the
    source. Threats whose ``detection_id`` already exists on the target are
    dropped (the target's row wins) to honor the (machine_id, detection_id)
    uniqueness. The caller commits.

    The source's *pending Windows updates* are deliberately not reattached: they
    are current state and not history, they would collide with the target's own
    set, and the target's ``wu_pending_count`` would then disagree with the rows.
    Deleting the source drops them by FK cascade, and the target's next Windows
    Update cycle re-establishes the truth.
    """
    # Commands carry no uniqueness constraint — reassign them wholesale.
    await session.exec(
        update(Command)
        .where(col(Command.machine_id) == source.id)
        .values(machine_id=target.id)
    )

    # Drop source threats that would collide with an existing target detection.
    target_threat = aliased(Threat)
    colliding = (
        delete(Threat)
        .where(col(Threat.machine_id) == source.id)
        .where(col(Threat.detection_id).is_not(None))
        .where(
            exists().where(
                (col(target_threat.machine_id) == target.id)
                & (col(target_threat.detection_id) == col(Threat.detection_id))
            )
        )
    )
    await session.exec(colliding)

    # Reassign the remaining source threats to the target.
    await session.exec(
        update(Threat)
        .where(col(Threat.machine_id) == source.id)
        .values(machine_id=target.id)
    )

    # Keep the freshest last-seen; the merge resolves the verification.
    if source.last_seen > target.last_seen:
        target.last_seen = source.last_seen
    target.needs_verification = False
    target.updated_at = utcnow()

    await session.delete(source)
