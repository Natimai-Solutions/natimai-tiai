"""Reading the directory through designated postes (plan-lecture-annuaire.md,
mode ``relay``): who may read, what each reader is asked, what it answers,
and how a reading is matched to the postes and files them into rooms.

The agents' own word — the ``directory`` block of their inventory — stays
stored and shown; with ``DIRECTORY_VERIFY=relay`` it is checked against what
a reader read (``directory_status``), and the rooms follow the reading.
"""

import hashlib
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as env
from app.features.audit import crud as audit
from app.features.command.models import Command, CommandStatus, CommandType
from app.features.directory.models import DirectoryDomain, DirectoryRecord
from app.features.machine.models import Machine
from app.features.room.models import Room

logger = logging.getLogger(__name__)

# The verdicts on a poste (``machines.directory_status``).
VERIFIED = "verified"
MISMATCH = "mismatch"
UNKNOWN = "unknown"
STALE = "stale"
STATUSES = (VERIFIED, MISMATCH, UNKNOWN, STALE)

# The actor the audit entries of a reading name, beside the reader.
ACTOR = "directory"

# A NetBIOS computer name as a reader may be asked for it: what an LDAP
# filter can carry without escaping, and nothing longer than a DNS label.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
# Names asked of one reader at most: a parc is a few thousand postes.
MAX_NAMES = 20_000
# Moves named in an audit entry or kept pending at most, by name.
MAX_LISTED = 200
# How long a reader has to answer a reading before it is asked again.
READ_TTL = timedelta(minutes=30)


def enabled() -> bool:
    return env.DIRECTORY_VERIFY == "relay"


def source_of(reader_id: uuid.UUID) -> str:
    return f"relay:{reader_id}"


# --- Readers -----------------------------------------------------------------


def reader_ok(machine: Machine) -> bool:
    """A designation holds while the poste is the one that was designated:
    not re-enrolled, its token not revoked, its identity not in doubt."""
    return (
        machine.directory_reader
        and not machine.token_revoked
        and not machine.needs_verification
        and machine.reenroll_requested_at is None
        and machine.token_hash is not None
        and bool(machine.domain)
    )


def designate(machine: Machine, now: datetime) -> None:
    machine.directory_reader = True
    machine.directory_reader_since = now


def undesignate(machine: Machine) -> None:
    machine.directory_reader = False
    machine.directory_reader_since = None


async def drop_ineligible_readers(session: AsyncSession) -> list[Machine]:
    """Undesignate the readers whose designation fell (``reader_ok``), with an
    audit entry each. Does not commit."""
    rows = await session.exec(
        select(Machine).where(col(Machine.directory_reader).is_(True))
    )
    dropped = []
    for machine in rows.all():
        if reader_ok(machine):
            continue
        undesignate(machine)
        session.add(machine)
        audit.record(
            session,
            actor=ACTOR,
            action="directory.reader_drop",
            resource_type="machine",
            resource_id=str(machine.id),
            details={"hostname": machine.hostname},
        )
        dropped.append(machine)
    return dropped


async def names_for(session: AsyncSession, reader: Machine) -> list[str]:
    """The computer names a reader is asked to read: the postes enrolled
    that declare its domain, itself included."""
    rows = await session.exec(
        select(col(Machine.hostname)).where(
            func.lower(col(Machine.domain)) == (reader.domain or "").lower(),
            col(Machine.hostname).is_not(None),
        )
    )
    names = sorted(
        {h.upper() for h in rows.all() if h and _NAME.fullmatch(h)},
    )
    return names[:MAX_NAMES]


async def queue_reads(session: AsyncSession, now: datetime) -> int:
    """Ask each reader for a reading every ``DIRECTORY_SYNC_MINUTES``, one at
    a time. Does not commit. Returns how many were queued."""
    if not enabled():
        return 0
    await drop_ineligible_readers(session)
    readers = (
        await session.exec(
            select(Machine).where(col(Machine.directory_reader).is_(True))
        )
    ).all()
    queued = 0
    for reader in readers:
        last = (
            await session.exec(
                select(Command)
                .where(
                    col(Command.machine_id) == reader.id,
                    col(Command.type) == CommandType.DIRECTORY_READ,
                )
                .order_by(col(Command.created_at).desc())
                .limit(1)
            )
        ).first()
        if last is not None:
            # Open: waiting for the reader, or handed to it less than
            # READ_TTL ago. One delivered and never answered (the agent was
            # stopped mid-reading) is closed by the server a day later; it
            # must not keep the domain unread until then.
            open_ = last.status == CommandStatus.PENDING or (
                last.status in (CommandStatus.DELIVERED, CommandStatus.RUNNING)
                and (last.delivered_at or last.created_at) > now - READ_TTL
            )
            if open_ or last.created_at > now - timedelta(
                minutes=env.DIRECTORY_SYNC_MINUTES
            ):
                continue
        session.add(
            Command(
                machine_id=reader.id,
                type=CommandType.DIRECTORY_READ,
                created_by=ACTOR,
                created_at=now,
                expires_at=now + READ_TTL,
            )
        )
        queued += 1
    return queued


# --- A reading -----------------------------------------------------------------


def _split_dn(dn: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in dn:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            current.append(ch)
            escaped = True
        elif ch == ",":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current or parts:
        parts.append("".join(current).strip())
    return parts


def _rdn_value(rdn: str) -> str:
    _, _, value = rdn.partition("=")
    out: list[str] = []
    escaped = False
    for ch in value:
        if escaped or ch != "\\":
            out.append(ch)
            escaped = False
        else:
            escaped = True
    return "".join(out).strip()


def parent_ou(dn: str | None) -> tuple[str | None, str | None]:
    """The OU directly holding the object — its name and DN — as the agent
    computes it (``collector.parentOU``). None outside any OU."""
    parts = _split_dn(dn or "")
    if len(parts) < 2:
        return None, None
    if parts[1].split("=", 1)[0].strip().upper() != "OU":
        return None, None
    return _rdn_value(parts[1]) or None, ",".join(parts[1:])


@dataclass(frozen=True)
class ReadObject:
    object_guid: str
    sam_account_name: str
    dns_host_name: str | None = None
    distinguished_name: str | None = None
    location: str | None = None
    disabled: bool = False


@dataclass(frozen=True)
class Reading:
    domain_name: str
    netbios_name: str
    domain_sid: str
    objects: list[ReadObject]
    subnets: list[dict[str, Any]] = field(default_factory=list)


class ReadingRefused(Exception):
    """A reading the server does not take: its code names why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class ReconcileResult:
    verified: int = 0
    mismatch: int = 0
    unknown: int = 0
    stale: int = 0
    moved: int = 0
    held: int = 0
    disagreement: bool = False


async def ingest(
    session: AsyncSession,
    reader: Machine,
    command: Command,
    reading: Reading,
    now: datetime,
) -> ReconcileResult:
    """Take a reader's answer: store what it read of its own domain, then
    match it to the postes. Does not commit. Raises ``ReadingRefused``."""
    if not enabled():
        raise ReadingRefused("directory.off")
    if not reader_ok(reader):
        raise ReadingRefused("directory.not_reader")
    if (
        command.machine_id != reader.id
        or command.type != CommandType.DIRECTORY_READ
        or command.status not in (CommandStatus.DELIVERED, CommandStatus.RUNNING)
    ):
        raise ReadingRefused("directory.command")
    # Its own domain only: a reader answers for nobody else's (plan §3.2).
    if reading.netbios_name.lower() != (reader.domain or "").lower():
        raise ReadingRefused("directory.other_domain")

    domain = await session.get(DirectoryDomain, reading.domain_sid)
    if domain is None:
        domain = DirectoryDomain(
            sid=reading.domain_sid,
            name=reading.domain_name,
            netbios_name=reading.netbios_name,
        )
    domain.name = reading.domain_name
    domain.netbios_name = reading.netbios_name
    domain.subnets = reading.subnets or None
    domain.last_read_at = now
    domain.last_reader_id = reader.id
    session.add(domain)
    await session.flush()

    # Only the names it was asked for: a reader does not volunteer objects.
    asked = {f"{n}$" for n in await names_for(session, reader)}
    source = source_of(reader.id)
    await session.exec(
        delete(DirectoryRecord).where(col(DirectoryRecord.source) == source)
    )
    seen: set[str] = set()
    kept = 0
    for obj in reading.objects:
        sam = obj.sam_account_name.upper()
        if sam not in asked or obj.object_guid in seen:
            continue
        seen.add(obj.object_guid)
        ou, ou_dn = parent_ou(obj.distinguished_name)
        session.add(
            DirectoryRecord(
                object_guid=obj.object_guid,
                domain_sid=reading.domain_sid,
                sam_account_name=sam,
                dns_host_name=obj.dns_host_name,
                distinguished_name=obj.distinguished_name,
                ou=ou,
                ou_dn=ou_dn,
                location=obj.location,
                disabled=obj.disabled,
                source=source,
                read_at=now,
            )
        )
        kept += 1
    domain.objects_read = kept
    await session.flush()
    return await reconcile(session, domain, now, reader=reader)


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def verdict(machine: Machine) -> str:
    """``verified`` when what the agent declares agrees with what was read,
    ``mismatch`` otherwise. Signalled, never blocking (plan §9.5): a poste
    moved in AD and not yet restarted has a local DN behind."""
    declared = (machine.ad_distinguished_name, machine.ad_location)
    if declared == (None, None):
        return VERIFIED
    if machine.ad_distinguished_name is not None and not _same(
        machine.ad_distinguished_name, machine.dir_distinguished_name
    ):
        return MISMATCH
    if not _same(machine.ad_location, machine.dir_location):
        return MISMATCH
    return VERIFIED


def _set_status(session: AsyncSession, machine: Machine, status: str) -> None:
    if machine.directory_status == status:
        return
    if status == MISMATCH:
        audit.record(
            session,
            actor=ACTOR,
            action="directory.mismatch",
            resource_type="machine",
            resource_id=str(machine.id),
            details={
                "hostname": machine.hostname,
                "declared": machine.ad_distinguished_name,
                "read": machine.dir_distinguished_name,
            },
        )
    machine.directory_status = status
    session.add(machine)


def _record_key(r: DirectoryRecord) -> tuple[Any, ...]:
    return (
        r.sam_account_name,
        (r.distinguished_name or "").lower(),
        (r.location or "").strip(),
        r.disabled,
    )


async def reconcile(
    session: AsyncSession,
    domain: DirectoryDomain,
    now: datetime,
    *,
    reader: Machine | None = None,
    confirmed: bool = False,
) -> ReconcileResult:
    """Match the domain's fresh records to its postes, give each its verdict,
    and file them into rooms. Does not commit."""
    from app.features.room import crud as room_crud

    result = ReconcileResult()
    fresh_after = now - timedelta(hours=env.DIRECTORY_STALE_HOURS)
    records = (
        await session.exec(
            select(DirectoryRecord).where(
                col(DirectoryRecord.domain_sid) == domain.sid,
                col(DirectoryRecord.read_at) > fresh_after,
            )
        )
    ).all()

    # Two readers that disagree on an object: nothing moves (plan §3.2).
    by_guid: dict[str, list[DirectoryRecord]] = {}
    for r in records:
        by_guid.setdefault(r.object_guid, []).append(r)
    disagreeing = [
        {"object_guid": guid, "sam": rs[0].sam_account_name}
        for guid, rs in by_guid.items()
        if len({_record_key(r) for r in rs}) > 1
    ]
    if disagreeing:
        if domain.disagreement_at is None:
            audit.record(
                session,
                actor=ACTOR,
                action="directory.disagreement",
                resource_type="directory_domain",
                resource_id=domain.sid,
                details={"domain": domain.name, "objects": disagreeing[:MAX_LISTED]},
            )
            domain.disagreement_at = now
        domain.disagreement = disagreeing[:MAX_LISTED]
        session.add(domain)
        result.disagreement = True
        return result
    domain.disagreement_at = None
    domain.disagreement = None

    objects = {guid: rs[0] for guid, rs in by_guid.items()}
    by_sam: dict[str, list[DirectoryRecord]] = {}
    for r in objects.values():
        by_sam.setdefault(r.sam_account_name.upper(), []).append(r)
    # Domains of the same NetBIOS name: an object of the name in another of
    # them leaves the poste undecided (plan §3.2).
    twins = (
        await session.exec(
            select(DirectoryRecord.sam_account_name, DirectoryRecord.domain_sid).where(
                col(DirectoryRecord.domain_sid) != domain.sid,
                col(DirectoryRecord.read_at) > fresh_after,
                col(DirectoryRecord.domain_sid).in_(
                    select(DirectoryDomain.sid).where(
                        func.lower(col(DirectoryDomain.netbios_name))
                        == domain.netbios_name.lower()
                    )
                ),
            )
        )
    ).all()
    twin_names = {sam.upper() for sam, _ in twins}

    machines = (
        await session.exec(
            select(Machine)
            .where(
                or_(
                    func.lower(col(Machine.domain)) == domain.netbios_name.lower(),
                    col(Machine.directory_domain_sid) == domain.sid,
                )
            )
            .order_by(col(Machine.id))
            .with_for_update()
        )
    ).all()
    claims = Counter(
        f"{(m.hostname or '').upper()}$"
        for m in machines
        if _same(m.domain, domain.netbios_name)
    )

    matched: dict[uuid.UUID, DirectoryRecord | None] = {}
    for m in machines:
        record: DirectoryRecord | None = None
        if m.directory_object_guid and m.directory_object_guid in objects:
            record = objects[m.directory_object_guid]
        elif _same(m.domain, domain.netbios_name) and m.hostname:
            sam = f"{m.hostname.upper()}$"
            candidates = by_sam.get(sam, [])
            if claims[sam] > 1 and candidates:
                # Claimed by two postes: neither gets it, both are to be
                # confirmed, as for a suspicious fingerprint.
                m.needs_verification = True
                _clear(m)
                _set_status(session, m, UNKNOWN)
                result.unknown += 1
                matched[m.id] = None
                continue
            if sam in twin_names:
                _clear(m)
                _set_status(session, m, UNKNOWN)
                result.unknown += 1
                matched[m.id] = None
                continue
            record = candidates[0] if len(candidates) == 1 else None
        if record is None:
            if m.directory_domain_sid == domain.sid and m.directory_object_guid:
                # Read before, gone now: deleted from the directory.
                _set_status(session, m, STALE)
                result.stale += 1
            elif _same(m.domain, domain.netbios_name):
                _set_status(session, m, UNKNOWN)
                result.unknown += 1
            matched[m.id] = None
            continue
        m.directory_object_guid = record.object_guid
        m.directory_domain_sid = domain.sid
        m.dir_distinguished_name = record.distinguished_name
        m.dir_ou = record.ou
        m.dir_ou_dn = record.ou_dn
        m.dir_location = record.location
        session.add(m)
        if record.disabled:
            _set_status(session, m, STALE)
            result.stale += 1
        else:
            status = verdict(m)
            _set_status(session, m, status)
            if status == VERIFIED:
                result.verified += 1
            else:
                result.mismatch += 1
        matched[m.id] = record

    # The rooms, by the reading (plan §4.1).
    source = env.ROOM_SOURCE
    if source != "manual":
        moves: list[tuple[Machine, Room | None, tuple[str, str] | None]] = []
        for m in machines:
            if m.directory_status not in (VERIFIED, MISMATCH):
                continue
            key = room_crud.directory_key(m, source)
            current = await session.get(Room, m.room_id) if m.room_id else None
            if key is None:
                if current is not None:
                    moves.append((m, current, None))
                continue
            if current is None or current.ad_key != key[0]:
                moves.append((m, current, key))
        if len(moves) > env.DIRECTORY_CONFIRM_MOVES and not confirmed:
            domain.pending_moves = [
                {
                    "machine_id": str(m.id),
                    "hostname": m.hostname,
                    "from": cur.name if cur else None,
                    "to": key[1] if key else None,
                }
                for m, cur, key in moves[:MAX_LISTED]
            ]
            domain.pending_since = now
            domain.pending_count = len(moves)
            result.held = len(moves)
        else:
            for m, _cur, _key in moves:
                await room_crud.place_from_directory(session, m, source, adopt=True)
            result.moved = len(moves)
            domain.pending_moves = None
            domain.pending_since = None
            domain.pending_count = 0
            if moves:
                audit.record(
                    session,
                    actor=ACTOR,
                    action="directory.moves",
                    resource_type="directory_domain",
                    resource_id=domain.sid,
                    details={
                        "domain": domain.name,
                        "reader": reader.hostname if reader else None,
                        "count": len(moves),
                        "hostnames": [m.hostname for m, _, _ in moves][:MAX_LISTED],
                    },
                )
    session.add(domain)
    return result


def _clear(m: Machine) -> None:
    m.directory_object_guid = None
    m.dir_distinguished_name = None
    m.dir_ou = None
    m.dir_ou_dn = None
    m.dir_location = None
    m.directory_domain_sid = None


async def mark_stale(session: AsyncSession, now: datetime) -> int:
    """Postes whose domain has not been read for ``DIRECTORY_STALE_HOURS``:
    their reading verifies nothing any more. Does not commit."""
    cutoff = now - timedelta(hours=env.DIRECTORY_STALE_HOURS)
    old = select(DirectoryDomain.sid).where(
        or_(
            col(DirectoryDomain.last_read_at).is_(None),
            col(DirectoryDomain.last_read_at) <= cutoff,
        )
    )
    rows = await session.exec(
        select(Machine).where(
            col(Machine.directory_domain_sid).in_(old),
            col(Machine.directory_status).in_((VERIFIED, MISMATCH)),
        )
    )
    count = 0
    for m in rows.all():
        _set_status(session, m, STALE)
        count += 1
    return count


async def refresh_heartbeat_verdict(session: AsyncSession, machine: Machine) -> None:
    """The agent's word changed (its directory block): judged again against
    what was read, when something was. Does not commit."""
    if not enabled() or machine.directory_object_guid is None:
        return
    if machine.directory_status in (VERIFIED, MISMATCH):
        _set_status(session, machine, verdict(machine))


def room_key(machine: Machine, source: str) -> tuple[str, str] | None:
    """The room key of a reading: the domain's SID ahead of the OU's DN or
    of the location, so that two schools' « Salle 101 » are two rooms. A key
    longer than the column is hashed after the SID."""
    sid = machine.directory_domain_sid or ""
    if source == "ad_ou":
        if not (machine.dir_ou_dn and machine.dir_ou):
            return None
        raw, name = machine.dir_ou_dn, machine.dir_ou
    elif source == "ad_location":
        if not machine.dir_location:
            return None
        raw, name = machine.dir_location, machine.dir_location
    else:
        return None
    key = f"{sid}|{raw}"
    if len(key) > 500:
        key = f"{sid}|sha256:{hashlib.sha256(raw.encode()).hexdigest()}"
    return key, name


def legacy_key(key: str) -> str | None:
    """The key a room had before its domain was read: the part after the SID."""
    _, sep, raw = key.partition("|")
    return raw if sep and not raw.startswith("sha256:") else None


async def domains_overview(session: AsyncSession) -> list[DirectoryDomain]:
    return list(
        (
            await session.exec(
                select(DirectoryDomain).order_by(col(DirectoryDomain.name))
            )
        ).all()
    )


async def apply_pending(
    session: AsyncSession, domain: DirectoryDomain, now: datetime, *, actor: str
) -> ReconcileResult:
    """An administrator confirms the moves a reading held. Does not commit."""
    result = await reconcile(session, domain, now, confirmed=True)
    audit.record(
        session,
        actor=actor,
        action="directory.confirm_moves",
        resource_type="directory_domain",
        resource_id=domain.sid,
        details={"domain": domain.name, "count": result.moved},
    )
    return result
