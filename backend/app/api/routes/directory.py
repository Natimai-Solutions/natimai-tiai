"""The directory as the readers read it (plan-lecture-annuaire.md, mode
``relay``): its state for the Paramètres page, the designation of readers,
and the confirmation of a reading that would move many postes."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.api.routes.machines import _require_machine
from app.core.config import settings as env
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.directory import crud as directory_crud
from app.features.directory.models import DirectoryDomain
from app.features.machine.models import Machine
from app.features.user.permissions import Action, Resource

router = APIRouter(
    prefix="/directory",
    tags=["directory"],
    dependencies=[Depends(require_permission(Resource.SETTINGS, Action.READ))],
)
_WRITE = Depends(require_permission(Resource.SETTINGS, Action.WRITE))


class ReaderOut(BaseModel):
    id: uuid.UUID
    hostname: str | None
    domain: str | None
    since: datetime | None
    last_seen: datetime


class PendingMoveOut(BaseModel):
    machine_id: str
    hostname: str | None = None
    from_room: str | None = None
    to_room: str | None = None


class DomainOut(BaseModel):
    sid: str
    name: str
    netbios_name: str
    last_read_at: datetime | None
    last_reader: str | None
    objects_read: int
    disagreement_at: datetime | None
    disagreement: list[dict[str, str]] = []
    pending_count: int = 0
    pending_since: datetime | None = None
    pending_moves: list[PendingMoveOut] = []
    readers: list[ReaderOut] = []


class DirectoryOut(BaseModel):
    mode: str
    sync_minutes: int
    stale_hours: int
    confirm_moves: int
    room_source: str
    domains: list[DomainOut]
    # Readers of a domain not read yet (its first reading is on its way).
    readers_waiting: list[ReaderOut]
    # Domains the postes declare and no reader reads: they keep the agents'
    # word (plan §3.2), and the page says so.
    domains_without_reader: list[str]
    # Postes by verdict.
    status_counts: dict[str, int]


def _reader(m: Machine) -> ReaderOut:
    return ReaderOut(
        id=m.id,
        hostname=m.hostname,
        domain=m.domain,
        since=m.directory_reader_since,
        last_seen=m.last_seen,
    )


@router.get("", response_model=DirectoryOut)
async def directory_state(session: SessionDep) -> DirectoryOut:
    domains = await directory_crud.domains_overview(session)
    readers = (
        await session.exec(
            select(Machine)
            .where(col(Machine.directory_reader).is_(True))
            .order_by(col(Machine.hostname))
        )
    ).all()
    names = {
        m.id: m.hostname
        for m in (
            await session.exec(
                select(Machine).where(
                    col(Machine.id).in_(
                        [d.last_reader_id for d in domains if d.last_reader_id]
                    )
                )
            )
        ).all()
    }
    by_netbios: dict[str, list[Machine]] = {}
    for r in readers:
        by_netbios.setdefault((r.domain or "").lower(), []).append(r)
    read_netbios = {d.netbios_name.lower() for d in domains}
    declared = (
        await session.exec(
            select(func.lower(col(Machine.domain)))
            .where(col(Machine.domain).is_not(None), col(Machine.domain) != "")
            .distinct()
        )
    ).all()
    counts = dict(
        (
            await session.exec(
                select(col(Machine.directory_status), func.count())
                .where(col(Machine.directory_status).is_not(None))
                .group_by(col(Machine.directory_status))
            )
        ).all()
    )
    return DirectoryOut(
        mode=env.DIRECTORY_VERIFY,
        sync_minutes=env.DIRECTORY_SYNC_MINUTES,
        stale_hours=env.DIRECTORY_STALE_HOURS,
        confirm_moves=env.DIRECTORY_CONFIRM_MOVES,
        room_source=env.ROOM_SOURCE,
        domains=[
            DomainOut(
                sid=d.sid,
                name=d.name,
                netbios_name=d.netbios_name,
                last_read_at=d.last_read_at,
                last_reader=names.get(d.last_reader_id) if d.last_reader_id else None,
                objects_read=d.objects_read,
                disagreement_at=d.disagreement_at,
                disagreement=d.disagreement or [],
                pending_count=d.pending_count,
                pending_since=d.pending_since,
                pending_moves=[
                    PendingMoveOut(
                        machine_id=str(p.get("machine_id")),
                        hostname=p.get("hostname"),
                        from_room=p.get("from"),
                        to_room=p.get("to"),
                    )
                    for p in (d.pending_moves or [])
                ],
                readers=[
                    _reader(r) for r in by_netbios.get(d.netbios_name.lower(), [])
                ],
            )
            for d in domains
        ],
        readers_waiting=[
            _reader(r)
            for key, rs in by_netbios.items()
            if key not in read_netbios
            for r in rs
        ],
        domains_without_reader=sorted(d for d in declared if d and d not in by_netbios),
        status_counts={str(k): int(v) for k, v in counts.items()},
    )


@router.post("/readers/{machine_id}", response_model=ReaderOut, dependencies=[_WRITE])
async def designate_reader(
    machine_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> ReaderOut:
    """Designate a poste to read its domain for the others: a member server
    or an administration poste always on, never a pupil's poste."""
    if not directory_crud.enabled():
        raise AppError(code=ErrorCode.DIRECTORY_OFF, status_code=409)
    machine = await _require_machine(session, machine_id, scope)
    directory_crud.designate(machine, utcnow())
    if not directory_crud.reader_ok(machine):
        raise AppError(code=ErrorCode.DIRECTORY_NOT_ELIGIBLE, status_code=409)
    session.add(machine)
    audit.record(
        session,
        actor=current.email,
        action="directory.reader_designate",
        resource_type="machine",
        resource_id=str(machine.id),
        details={"hostname": machine.hostname, "domain": machine.domain},
    )
    await session.commit()
    await session.refresh(machine)
    return _reader(machine)


@router.delete("/readers/{machine_id}", status_code=204, dependencies=[_WRITE])
async def revoke_reader(
    machine_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> None:
    machine = await _require_machine(session, machine_id, scope)
    if not machine.directory_reader:
        return
    directory_crud.undesignate(machine)
    session.add(machine)
    audit.record(
        session,
        actor=current.email,
        action="directory.reader_revoke",
        resource_type="machine",
        resource_id=str(machine.id),
        details={"hostname": machine.hostname},
    )
    await session.commit()


async def _domain_with_pending(session: SessionDep, sid: str) -> DirectoryDomain:
    domain = await session.get(DirectoryDomain, sid)
    if domain is None:
        raise AppError(code=ErrorCode.DIRECTORY_DOMAIN_NOT_FOUND, status_code=404)
    if not domain.pending_moves:
        raise AppError(code=ErrorCode.DIRECTORY_NOTHING_PENDING, status_code=409)
    return domain


@router.post("/domains/{sid}/confirm", dependencies=[_WRITE])
async def confirm_moves(
    sid: str, session: SessionDep, current: CurrentUser
) -> dict[str, int]:
    """Apply the moves a reading held back (more than DIRECTORY_CONFIRM_MOVES)."""
    domain = await _domain_with_pending(session, sid)
    result = await directory_crud.apply_pending(
        session, domain, utcnow(), actor=current.email
    )
    await session.commit()
    return {"moved": result.moved}


@router.post("/domains/{sid}/discard", status_code=204, dependencies=[_WRITE])
async def discard_moves(sid: str, session: SessionDep, current: CurrentUser) -> None:
    """Leave the postes where they are. The next reading holds the same moves
    again if the directory still says so."""
    domain = await _domain_with_pending(session, sid)
    count = domain.pending_count
    domain.pending_moves = None
    domain.pending_since = None
    domain.pending_count = 0
    session.add(domain)
    audit.record(
        session,
        actor=current.email,
        action="directory.discard_moves",
        resource_type="directory_domain",
        resource_id=domain.sid,
        details={"domain": domain.name, "count": count},
    )
    await session.commit()
