"""Machine reconciliation (merging a duplicate record into the one to keep), and
the fleet-wide recomputation of the stored up-to-date flag."""

from sqlalchemy import delete, exists, update
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.check import crud as check_crud
from app.features.command.models import Command
from app.features.intervention import crud as intervention_crud
from app.features.machine.models import Machine
from app.features.machine.status import compute_is_up_to_date
from app.features.threat.models import Threat
from app.features.usage import crud as usage_crud


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

    Its *usage counters* are reattached, hour by hour, and added to the
    target's where both have the same hour (``usage.crud.move_to``).
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

    # The journal follows: what was done to the duplicate was done to the poste.
    await intervention_crud.move_to(session, source_id=source.id, target_id=target.id)
    await check_crud.move_to(session, source_id=source.id, target_id=target.id)
    # So do the hours it was on: usage is history, and the statistics must not
    # lose a week because an administrator reconciled two records.
    await usage_crud.move_to(session, source_id=source.id, target_id=target.id)

    # Keep the freshest last-seen; the merge resolves the verification. The
    # room follows too, when the kept record has none: a duplicate was often
    # the one somebody filed.
    if source.last_seen > target.last_seen:
        target.last_seen = source.last_seen
    if target.room_id is None:
        target.room_id = source.room_id
    # The maintenance record follows the journal: the latest visit counts.
    if source.last_maintenance_at is not None and (
        target.last_maintenance_at is None
        or source.last_maintenance_at > target.last_maintenance_at
    ):
        target.last_maintenance_at = source.last_maintenance_at
    target.needs_verification = False
    target.updated_at = utcnow()

    await session.delete(source)


async def recompute_up_to_date(session: AsyncSession, *, max_age_days: int) -> int:
    """Re-derive ``is_up_to_date`` on every machine against a new threshold.

    The flag is stored, computed on each heartbeat, so a change of the
    signature age threshold would otherwise reach a poste only at its next
    heartbeat — never, for one that is off — and the list, the dashboard and
    the digest would disagree for as long. Recomputed here from what each
    machine last reported, by the heartbeat's own function, so the two can
    never differ. Only the machines whose verdict moved are written. Returns
    how many; the caller commits.
    """
    machines = (await session.exec(select(Machine))).all()
    changed = 0
    for machine in machines:
        verdict = compute_is_up_to_date(
            av_enabled=machine.av_enabled,
            rtp_enabled=machine.rtp_enabled,
            signature_age_days=machine.signature_age_days,
            max_age_days=max_age_days,
            av_product_enabled=machine.av_product_enabled,
            av_product_signatures_up_to_date=machine.av_product_signatures_up_to_date,
            av_product_is_defender=machine.av_product_is_defender,
        )
        if verdict is not machine.is_up_to_date:
            machine.is_up_to_date = verdict
            session.add(machine)
            changed += 1
    return changed
