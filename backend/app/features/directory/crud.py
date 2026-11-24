"""Reading the directory through designated postes (plan-lecture-annuaire.md,
mode ``relay``): who may read, what each reader is asked, what it answers,
and how a reading is matched to the postes and files them into rooms.

The agents' own word — the ``directory`` block of their inventory — stays
stored and shown; with ``DIRECTORY_VERIFY=relay`` it is checked against what
a reader read (``directory_status``), and the rooms follow the reading.

What bounds a reader (it is trusted for its own domain, and for nothing
else): its designation is tied to the domain it declared when designated and
to the SID it first read; a NetBIOS name names one domain; a reading answers
one command, once; its records leave with its designation.
"""

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
# Two enrolled postes claim the same computer object: neither gets it until
# an administrator merges or deletes one (plan §3.3).
CONTESTED = "contested"
STATUSES = (VERIFIED, MISMATCH, UNKNOWN, STALE, CONTESTED)
# The verdicts under which a poste has a reading the rooms may follow.
READ = (VERIFIED, MISMATCH)

# The actor the audit entries of a reading name, beside the reader.
ACTOR = "directory"

# A NetBIOS computer name as a reader may be asked for it: what an LDAP
# filter can carry without escaping, and nothing longer than a DNS label.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
# Names asked of one reader at most: what one reading carries back in a
# request the proxy accepts. A larger domain is cut, and says so in the log.
MAX_NAMES = 10_000
# Moves named in an audit entry or kept pending at most, by name.
MAX_LISTED = 200
# How long a reader has to answer a reading before it is asked again.
READ_TTL = timedelta(minutes=30)


def enabled() -> bool:
    return env.DIRECTORY_VERIFY == "relay"


def source_of(reader_id: uuid.UUID) -> str:
    return f"relay:{reader_id}"


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


# --- Readers -----------------------------------------------------------------


def reader_ok(machine: Machine) -> bool:
    """A designation holds while the poste is the one that was designated:
    not re-enrolled, its token not revoked, its identity not in doubt — and
    still declaring the domain it was designated in. A reader that starts
    declaring another domain does not become that domain's reader."""
    return (
        machine.directory_reader
        and not machine.token_revoked
        and not machine.needs_verification
        and machine.reenroll_requested_at is None
        and machine.token_hash is not None
        and bool(machine.domain)
        and _same(machine.domain, machine.directory_reader_domain)
    )


def designate(machine: Machine, now: datetime) -> None:
    machine.directory_reader = True
    machine.directory_reader_since = now
    machine.directory_reader_domain = machine.domain
    machine.directory_reader_sid = None


async def undesignate(session: AsyncSession, machine: Machine) -> None:
    """End a designation, and drop what the reader read: a reader removed
    because its word is in doubt must not keep verifying postes, nor keep a
    disagreement alive. Does not commit."""
    machine.directory_reader = False
    machine.directory_reader_since = None
    machine.directory_reader_domain = None
    machine.directory_reader_sid = None
    session.add(machine)
    await session.exec(
        delete(DirectoryRecord).where(
            col(DirectoryRecord.source) == source_of(machine.id)
        )
    )


async def drop_ineligible_readers(session: AsyncSession) -> list[Machine]:
    """Undesignate the readers whose designation fell (``reader_ok``), with an
    audit entry each, and drop the records no designated reader stands
    behind (a reader merged away or deleted). Does not commit."""
    rows = await session.exec(
        select(Machine).where(col(Machine.directory_reader).is_(True))
    )
    dropped = []
    kept: list[str] = []
    for machine in rows.all():
        if reader_ok(machine):
            kept.append(source_of(machine.id))
            continue
        await undesignate(session, machine)
        audit.record(
            session,
            actor=ACTOR,
            action="directory.reader_drop",
            resource_type="machine",
            resource_id=str(machine.id),
            details={"hostname": machine.hostname},
        )
        dropped.append(machine)
    orphans = delete(DirectoryRecord)
    if kept:
        orphans = orphans.where(col(DirectoryRecord.source).not_in(kept))
    await session.exec(orphans)
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
    if len(names) > MAX_NAMES:
        logger.warning(
            "directory: %d names in the domain of reader %s, %d asked",
            len(names),
            reader.id,
            MAX_NAMES,
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
    contested: int = 0
    moved: int = 0
    held: int = 0
    # Postes whose reading names a room the server cannot settle (a name
    # borne by rooms made by hand): left where they are.
    undecided: int = 0
    disagreement: bool = False


async def lock_domain(session: AsyncSession, sid: str) -> DirectoryDomain | None:
    """The domain's row, locked: a reading and a confirmation of the same
    domain queue here, before either touches the postes."""
    return (
        await session.exec(
            select(DirectoryDomain)
            .where(col(DirectoryDomain.sid) == sid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


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
    # One command, answered once, while it is fresh: DELIVERED, never
    # RUNNING — the state this function leaves it in.
    if (
        command.machine_id != reader.id
        or command.type != CommandType.DIRECTORY_READ
        or command.status != CommandStatus.DELIVERED
        or (command.delivered_at or command.created_at) <= now - READ_TTL
    ):
        raise ReadingRefused("directory.command")
    # Its own domain only: a reader answers for nobody else's (plan §3.2).
    if not _same(reading.netbios_name, reader.domain):
        raise ReadingRefused("directory.other_domain")
    # And always the same one: the SID it first read.
    if reader.directory_reader_sid not in (None, reading.domain_sid):
        raise ReadingRefused("directory.other_sid")

    # The domain row first, locked, whoever writes it (``lock_domain``).
    await session.exec(
        pg_insert(DirectoryDomain)
        .values(
            sid=reading.domain_sid,
            name=reading.domain_name,
            netbios_name=reading.netbios_name,
            objects_read=0,
            pending_count=0,
            created_at=now,
        )
        .on_conflict_do_nothing()
    )
    domain = await lock_domain(session, reading.domain_sid)
    if domain is None:
        # Another SID already bears this NetBIOS name: one name, one domain.
        # A second domain of the name is not read (an administrator removes
        # the first from Paramètres if the domain was rebuilt).
        raise ReadingRefused("directory.name_taken")
    if not _same(domain.netbios_name, reading.netbios_name):
        # A known SID reported under another name: not this reader's.
        raise ReadingRefused("directory.other_domain")
    command.status = CommandStatus.RUNNING
    command.started_at = now
    session.add(command)
    reader.directory_reader_sid = reading.domain_sid
    session.add(reader)
    domain.name = reading.domain_name
    domain.subnets = reading.subnets or None
    domain.last_read_at = now
    domain.last_reader_id = reader.id

    # Only the names it was asked for: a reader does not volunteer objects.
    asked = {f"{n}$" for n in await names_for(session, reader)}
    source = source_of(reader.id)
    await session.exec(
        delete(DirectoryRecord).where(col(DirectoryRecord.source) == source)
    )
    seen: set[str] = set()
    names: set[str] = set()
    for obj in reading.objects:
        sam = obj.sam_account_name.upper()
        # One object per name, one name per object: a directory holds no
        # two computers of the same sAMAccountName.
        if sam not in asked or obj.object_guid in seen or sam in names:
            continue
        seen.add(obj.object_guid)
        names.add(sam)
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
    domain.objects_read = len(seen)
    session.add(domain)
    await session.flush()
    return await reconcile(session, domain, now, reader=reader)


def verdict(machine: Machine) -> str:
    """``verified`` when what the agent declares agrees with what was read,
    ``mismatch`` otherwise. Signalled, never blocking (plan §9.5): a poste
    moved in AD and not yet restarted has a local DN behind. An agent that
    declares nothing on a point (it could not read its location) has no
    opinion to disagree with."""
    if machine.ad_distinguished_name is not None and not _same(
        machine.ad_distinguished_name, machine.dir_distinguished_name
    ):
        return MISMATCH
    if machine.ad_location is not None and not _same(
        machine.ad_location, machine.dir_location
    ):
        return MISMATCH
    return VERIFIED


def _set_status(session: AsyncSession, machine: Machine, status: str) -> None:
    if machine.directory_status == status:
        return
    if status in (MISMATCH, CONTESTED):
        audit.record(
            session,
            actor=ACTOR,
            action=f"directory.{status}",
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


def clear_match(m: Machine) -> None:
    """Forget what was read for a poste (it was re-enrolled, or its object
    is contested): it is matched again from scratch."""
    m.directory_object_guid = None
    m.dir_distinguished_name = None
    m.dir_ou = None
    m.dir_ou_dn = None
    m.dir_location = None
    m.directory_domain_sid = None


def _record_key(r: DirectoryRecord) -> tuple[Any, ...]:
    return (
        r.object_guid,
        (r.distinguished_name or "").lower(),
        (r.location or "").strip(),
        r.disabled,
    )


async def _current_records(
    session: AsyncSession, domain: DirectoryDomain, now: datetime
) -> dict[str, list[DirectoryRecord]]:
    """The fresh records of the domain, by reader — of the readers
    designated now. When several read recently (within two intervals), only
    those are compared: a reader off for the weekend must not freeze the
    domain on what it read on Friday."""
    readers = (
        await session.exec(
            select(Machine).where(col(Machine.directory_reader).is_(True))
        )
    ).all()
    sources = {source_of(r.id) for r in readers if reader_ok(r)}
    if not sources:
        return {}
    fresh_after = now - timedelta(hours=env.DIRECTORY_STALE_HOURS)
    rows = (
        await session.exec(
            select(DirectoryRecord).where(
                col(DirectoryRecord.domain_sid) == domain.sid,
                col(DirectoryRecord.read_at) > fresh_after,
                col(DirectoryRecord.source).in_(sources),
            )
        )
    ).all()
    by_source: dict[str, list[DirectoryRecord]] = {}
    for r in rows:
        by_source.setdefault(r.source, []).append(r)
    recent_after = now - 2 * timedelta(minutes=env.DIRECTORY_SYNC_MINUTES) - READ_TTL
    recent = {
        s: rs
        for s, rs in by_source.items()
        if max(r.read_at for r in rs) > recent_after
    }
    return recent or by_source


def _disagreements(
    by_source: dict[str, list[DirectoryRecord]],
) -> list[dict[str, str]]:
    """Names on which the readers do not say the same thing: another object,
    another place, or an object one of them did not find."""
    if len(by_source) < 2:
        return []
    per_name: dict[str, dict[str, tuple[Any, ...]]] = {}
    for source, records in by_source.items():
        for r in records:
            per_name.setdefault(r.sam_account_name.upper(), {})[source] = _record_key(r)
    out = []
    for sam, seen in sorted(per_name.items()):
        if len(seen) < len(by_source) or len(set(seen.values())) > 1:
            out.append({"sam": sam})
    return out


async def reconcile(
    session: AsyncSession,
    domain: DirectoryDomain,
    now: datetime,
    *,
    reader: Machine | None = None,
    confirmed: bool = False,
) -> ReconcileResult:
    """Match the domain's fresh records to its postes, give each its verdict,
    and file them into rooms. The domain's row is locked by the caller.
    Does not commit."""
    from app.features.room import crud as room_crud

    result = ReconcileResult()
    by_source = await _current_records(session, domain, now)

    # Readers that disagree: nothing moves (plan §3.2).
    disagreeing = _disagreements(by_source)
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

    by_sam: dict[str, DirectoryRecord] = {}
    by_guid: dict[str, DirectoryRecord] = {}
    for records in by_source.values():
        for r in records:
            by_sam.setdefault(r.sam_account_name.upper(), r)
            by_guid.setdefault(r.object_guid, r)

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
    # Who claims each name: the postes in good standing only — a revoked
    # record (a PC replaced that kept its name) claims nothing.
    claimants: dict[str, list[Machine]] = {}
    for m in machines:
        if m.hostname and _same(m.domain, domain.netbios_name) and not m.token_revoked:
            claimants.setdefault(f"{m.hostname.upper()}$", []).append(m)

    for m in machines:
        in_domain = _same(m.domain, domain.netbios_name)
        sam = f"{m.hostname.upper()}$" if m.hostname else ""
        if in_domain and len(claimants.get(sam, [])) > 1 and sam in by_sam:
            # Claimed by two postes: neither gets the object, whichever
            # came first — and neither is knocked out of anything else. An
            # administrator decides (merge, delete, revoke).
            clear_match(m)
            _set_status(session, m, CONTESTED)
            result.contested += 1
            continue
        record: DirectoryRecord | None = None
        if in_domain and not m.token_revoked:
            # By name first: the object of the name the poste bears now.
            # By GUID only for a poste whose name has no object any more
            # (renamed in AD, the agent not restarted yet).
            record = by_sam.get(sam)
            if record is None and m.directory_object_guid:
                kept = by_guid.get(m.directory_object_guid)
                if kept is not None and not claimants.get(kept.sam_account_name):
                    record = kept
        if record is None:
            if m.directory_domain_sid == domain.sid and m.directory_object_guid:
                # Read before, gone now: deleted from the directory.
                _set_status(session, m, STALE)
                result.stale += 1
            elif in_domain:
                _set_status(session, m, UNKNOWN)
                result.unknown += 1
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

    # The rooms, by the reading (plan §4.1).
    source = env.ROOM_SOURCE
    if source == "manual":
        domain.pending_moves = None
        domain.pending_since = None
        domain.pending_count = 0
        session.add(domain)
        return result
    moves: list[tuple[Machine, Room | None, tuple[str, str] | None]] = []
    for m in machines:
        if m.directory_status not in READ:
            continue
        key = room_crud.directory_key(m, source)
        current = await session.get(Room, m.room_id) if m.room_id else None
        if key is None:
            if current is not None:
                moves.append((m, current, None))
            continue
        if current is not None and current.ad_key == key[0]:
            continue
        if not await room_crud.settles(session, *key, sid=domain.sid):
            # A room made by hand bears the name: a reading does not take
            # it over. Left for « Resynchroniser depuis l'annuaire », which
            # asks first.
            result.undecided += 1
            continue
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
        if domain.pending_count != len(moves) or domain.pending_since is None:
            domain.pending_since = now
        domain.pending_count = len(moves)
        result.held = len(moves)
    else:
        moved: list[str | None] = []
        for m, _cur, _key in moves:
            before = m.room_id
            # Never adopting a room made by hand: ``settles`` kept those out.
            await room_crud.place_from_directory(session, m, source, adopt=False)
            if m.room_id != before:
                moved.append(m.hostname)
        result.moved = len(moved)
        domain.pending_moves = None
        domain.pending_since = None
        domain.pending_count = 0
        if moved:
            last_reader = reader or (
                await session.get(Machine, domain.last_reader_id)
                if domain.last_reader_id
                else None
            )
            audit.record(
                session,
                actor=ACTOR,
                action="directory.moves",
                resource_type="directory_domain",
                resource_id=domain.sid,
                details={
                    "domain": domain.name,
                    "reader": last_reader.hostname if last_reader else None,
                    "count": len(moved),
                    "hostnames": moved[:MAX_LISTED],
                },
            )
    session.add(domain)
    return result


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
            col(Machine.directory_status).in_(READ),
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
    if machine.directory_status in READ:
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


def key_sid(key: str) -> str | None:
    sid, sep, _ = key.partition("|")
    return sid if sep else None


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
    """An administrator confirms the moves a reading held. The domain's row
    is locked by the caller. Does not commit."""
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


async def forget_domain(session: AsyncSession, domain: DirectoryDomain) -> None:
    """Remove a domain the server read (rebuilt under another SID, or read
    by mistake): its records go with it, its postes are matched again from
    scratch, its readers are tied to no SID. Does not commit."""
    rows = await session.exec(
        select(Machine).where(
            or_(
                col(Machine.directory_domain_sid) == domain.sid,
                col(Machine.directory_reader_sid) == domain.sid,
            )
        )
    )
    for m in rows.all():
        if m.directory_domain_sid == domain.sid:
            clear_match(m)
            m.directory_status = None
        if m.directory_reader_sid == domain.sid:
            m.directory_reader_sid = None
        session.add(m)
    await session.delete(domain)
