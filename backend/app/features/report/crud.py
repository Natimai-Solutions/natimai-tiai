"""The reports' life: whether the form is open, the scope they are read in,
the verification one becomes, the merge, the purge."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as env
from app.features.asset.models import Asset
from app.features.check.models import CheckPriority, MachineCheck
from app.features.report.models import Report, ReportStatus
from app.features.room.models import Room
from app.features.user.scope import Scope, machine_ids_clause, room_clause

KEY_ENABLED = "reports.enabled"


async def enabled(session: AsyncSession, values: dict[str, Any] | None = None) -> bool:
    """Whether a label's QR code opens the form: the console's setting,
    else ``REPORTS_ENABLED``."""
    from app.features.setting import crud as setting_crud

    if values is None:
        values = await setting_crud.get_all(session)
    stored = values.get(KEY_ENABLED)
    return stored if isinstance(stored, bool) else env.REPORTS_ENABLED


def scope_clause(scope: Scope | None) -> Any:
    """The reports a scope sees: about one of its postes, or about equipment
    in one of its rooms. One about neither — its poste deleted — is the
    unrestricted accounts' alone."""
    if scope is None:
        return None
    equipment_in_scope = col(Report.asset_id).in_(
        select(Asset.id).where(
            col(Asset.machine_id).is_(None),
            col(Asset.room_id).in_(select(Room.id).where(room_clause(scope))),
        )
    )
    return or_(
        and_(
            col(Report.machine_id).is_not(None),
            machine_ids_clause(scope, col(Report.machine_id)),
        ),
        and_(col(Report.machine_id).is_(None), equipment_in_scope),
    )


def open_check_from(
    report: Report,
    *,
    requested_by: str,
    assigned_to_id: uuid.UUID | None,
    priority: CheckPriority,
    due_date: Any,
) -> MachineCheck:
    """The verification a report becomes — the one function a GLPI
    connector would redirect (plan §2): the report's words as the
    instructions, its category. Not added to the session."""
    assert report.machine_id is not None
    return MachineCheck(
        machine_id=report.machine_id,
        requested_by=requested_by,
        assigned_to_id=assigned_to_id,
        instructions=report.text,
        priority=priority.value,
        category=report.category,
        due_date=due_date,
    )


def mark_handled(
    report: Report,
    status: ReportStatus,
    *,
    by: str,
    now: datetime,
    note: str | None = None,
    check_id: uuid.UUID | None = None,
) -> None:
    report.status = status
    report.handled_by = by
    report.handled_at = now
    report.handling_note = note
    report.check_id = check_id


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge: the duplicate's reports are the poste's."""
    await session.exec(
        update(Report)
        .where(col(Report.machine_id) == source_id)
        .values(machine_id=target_id)
    )


async def purge_before(session: AsyncSession, cutoff: datetime) -> int:
    """Drop the reports handled before ``cutoff`` — their contact with them.
    Commits. A report still to sort is never purged."""
    result = await session.exec(
        delete(Report).where(
            col(Report.status) != ReportStatus.NEW,
            col(Report.handled_at) < cutoff,
        )
    )
    await session.commit()
    return result.rowcount or 0
