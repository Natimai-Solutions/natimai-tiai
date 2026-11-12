"""Store one reported inventory.

Replacement semantics throughout, like ``windows_update.replace_pending`` and
unlike ``threat.upsert_threats``: what is reported *is* the machine's current
hardware and software, so what is no longer reported has to go. ``first_seen``
is excluded from every update set — it is the only historical fact these tables
carry, and re-reporting the same disk every day must not reset it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, exists, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.inventory.models import (
    Disk,
    Gpu,
    MachineSoftware,
    MemoryModule,
    Nic,
    Software,
    Volume,
)
from app.features.inventory.schemas import InventoryReport
from app.features.machine.models import Machine

# Columns no upsert ever overwrites: the key it conflicted on, the machine it
# belongs to, and the date it was first seen.
_NEVER_UPDATED = frozenset({"machine_id", "first_seen"})


async def _replace_set(
    session: AsyncSession,
    model: type[SQLModel],
    *,
    constraint: str,
    key: str,
    machine_id: uuid.UUID,
    rows: list[dict[str, Any]],
) -> int:
    """Make one child table match what the agent reported, and return the count.

    Upsert what is there, then delete what is not — in that order, so a row that
    is still present is never briefly absent from the console.

    Rows whose key is empty are dropped: there is nothing to conflict on, and a
    blank key would collapse every such row onto one. Duplicates within the
    report are collapsed in Python because ``ON CONFLICT DO UPDATE`` raises
    "cannot affect row a second time" when one statement carries a key twice —
    which WMI does hand out (two volumes reported under the same letter on a
    machine mid-mount, two adapters sharing a MAC on a teamed NIC).
    """
    unique: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if not row[key]:
            continue
        unique[row[key]] = row
    deduped = list(unique.values())

    if deduped:
        stmt = pg_insert(model).values(deduped)
        updatable = {
            name: stmt.excluded[name]
            for name in deduped[0]
            if name != key and name not in _NEVER_UPDATED
        }
        await session.exec(
            stmt.on_conflict_do_update(constraint=constraint, set_=updatable)
        )

    # Columns off the mapped table rather than off the class: the key is a
    # string here — this helper serves six tables that agree on nothing but
    # ``machine_id`` — and ``Table.c`` is how SQLAlchemy is asked for a column by
    # name.
    columns = model.__table__.c  # type: ignore[attr-defined]
    stale = delete(model).where(columns.machine_id == machine_id)
    if deduped:
        stale = stale.where(columns[key].not_in(list(unique)))
    await session.exec(stale)

    return len(deduped)


async def _catalogue_ids(
    session: AsyncSession, triples: list[tuple[str, str, str]]
) -> dict[tuple[str, str, str], int]:
    """Ensure a catalogue row per (name, version, publisher), and return their ids.

    Two statements rather than one: ``ON CONFLICT DO NOTHING`` returns nothing
    for the rows that already existed, and on the second machine of a parc that
    is nearly all of them — so the ids have to be read back.
    """
    if not triples:
        return {}
    now = utcnow()
    rows = [
        {"name": name, "version": version, "publisher": publisher, "first_seen": now}
        for name, version, publisher in triples
    ]
    stmt = pg_insert(Software).values(rows)
    await session.exec(stmt.on_conflict_do_nothing(constraint="uq_software_identity"))
    found = await session.exec(
        select(Software).where(
            tuple_(
                col(Software.name), col(Software.version), col(Software.publisher)
            ).in_(triples)
        )
    )
    return {
        (s.name, s.version, s.publisher): s.id for s in found.all() if s.id is not None
    }


async def replace_software(
    session: AsyncSession, machine_id: uuid.UUID, reports: list[Any]
) -> int:
    """Make this machine's software list match what was reported.

    Entries without a name are dropped — the registry carries plenty, and
    "Applications et fonctionnalités" hides them for the same reason.
    """
    named = [r for r in reports if r.name]
    triples = sorted({(r.name, r.version, r.publisher) for r in named})
    ids = await _catalogue_ids(session, triples)

    now = utcnow()
    rows: list[dict[str, Any]] = []
    for r in named:
        software_id = ids.get((r.name, r.version, r.publisher))
        if software_id is None:  # pragma: no cover - the insert above created it
            continue
        rows.append(
            {
                "machine_id": machine_id,
                "software_id": software_id,
                "install_date": r.install_date,
                "arch": r.arch,
                "source": r.source,
                "install_location": r.install_location,
                "first_seen": now,
                "last_seen": now,
            }
        )
    return await _replace_set(
        session,
        MachineSoftware,
        constraint="uq_machine_software_identity",
        key="software_id",
        machine_id=machine_id,
        rows=rows,
    )


def _stamped(row: dict[str, Any], machine_id: uuid.UUID, now: Any) -> dict[str, Any]:
    """Add the columns every child row carries, whatever its table."""
    return {**row, "machine_id": machine_id, "first_seen": now, "last_seen": now}


async def apply_inventory(
    session: AsyncSession, machine: Machine, report: InventoryReport
) -> None:
    """Write one reported inventory onto a machine and its child tables.

    Lives here rather than inline in the heartbeat route, unlike the Defender
    and session blocks: this one is twenty-five columns and seven tables, and
    the route's job is to decide *whether* a block applies, not to spell out
    what each one means.

    The caller commits.
    """
    # Cardinality-one facts. Straight assignment and not conditional per field:
    # the block as a whole is what is optional (an absent block leaves everything
    # alone), and within a block a NULL is the agent saying it could not read
    # that one value — a motherboard serial the OEM never flashed does not stay
    # at the value some earlier agent guessed.
    machine.hw_manufacturer = report.hw_manufacturer
    machine.hw_model = report.hw_model
    machine.hw_serial = report.hw_serial
    machine.hw_chassis_type = report.hw_chassis_type
    machine.hw_is_virtual = report.hw_is_virtual
    machine.hw_hypervisor = report.hw_hypervisor
    machine.mb_manufacturer = report.mb_manufacturer
    machine.mb_model = report.mb_model
    machine.mb_serial = report.mb_serial
    machine.bios_vendor = report.bios_vendor
    machine.bios_version = report.bios_version
    machine.bios_date = report.bios_date
    machine.secure_boot = report.secure_boot
    machine.tpm_version = report.tpm_version
    machine.cpu_model = report.cpu_model
    machine.cpu_manufacturer = report.cpu_manufacturer
    machine.cpu_cores = report.cpu_cores
    machine.cpu_threads = report.cpu_threads
    machine.cpu_speed_mhz = report.cpu_speed_mhz
    machine.cpu_count = report.cpu_count
    machine.ram_total_mb = report.ram_total_mb
    machine.ram_slots_total = report.ram_slots_total
    machine.ram_slots_used = report.ram_slots_used
    machine.os_architecture = report.os_architecture
    machine.os_install_date = report.os_install_date
    machine.last_boot_time = report.last_boot_time

    now = utcnow()

    if report.memory_modules is not None:
        await _replace_set(
            session,
            MemoryModule,
            constraint="uq_inv_memory_machine_slot",
            key="slot",
            machine_id=machine.id,
            rows=[
                _stamped(m.model_dump(), machine.id, now) for m in report.memory_modules
            ],
        )
    if report.disks is not None:
        await _replace_set(
            session,
            Disk,
            constraint="uq_inv_disks_machine_device",
            key="device_id",
            machine_id=machine.id,
            rows=[_stamped(d.model_dump(), machine.id, now) for d in report.disks],
        )
    if report.volumes is not None:
        await _replace_set(
            session,
            Volume,
            constraint="uq_inv_volumes_machine_letter",
            key="letter",
            machine_id=machine.id,
            rows=[_stamped(v.model_dump(), machine.id, now) for v in report.volumes],
        )
        # Derived here, from the same list that was just stored, so the column
        # and the table can never disagree about one machine. A report that
        # names no system volume clears them rather than keeping a stale figure:
        # a disk figure nobody can date is worse than none.
        system = next((v for v in report.volumes if v.is_system), None)
        machine.system_volume_total_mb = system.total_mb if system else None
        machine.system_volume_free_mb = system.free_mb if system else None

    if report.nics is not None:
        await _replace_set(
            session,
            Nic,
            constraint="uq_inv_nics_machine_key",
            key="key",
            machine_id=machine.id,
            rows=[_stamped(n.model_dump(), machine.id, now) for n in report.nics],
        )
    if report.gpus is not None:
        await _replace_set(
            session,
            Gpu,
            constraint="uq_inv_gpus_machine_name",
            key="name",
            machine_id=machine.id,
            rows=[_stamped(g.model_dump(), machine.id, now) for g in report.gpus],
        )
    if report.software is not None:
        await replace_software(session, machine.id, report.software)

    # Written last, and only once everything above landed: the pair is what says
    # "the console's picture of this machine is this inventory, taken then". A
    # hash stored ahead of a failed write would have the next cycle skip the
    # repair (see the short-circuit in the heartbeat route).
    machine.inventory_hash = report.hash or None
    machine.inventory_last_seen = now


async def purge_orphan_software(session: AsyncSession, older_than: datetime) -> int:
    """Drop the catalogue entries no poste has installed any more, first seen
    before ``older_than``. The catalogue is shared and fed by every agent's
    report: without this it only ever grows (audit S21). Commits."""
    result = await session.exec(
        delete(Software)
        .where(col(Software.first_seen) < older_than)
        .where(~exists().where(col(MachineSoftware.software_id) == col(Software.id)))
    )
    await session.commit()
    return result.rowcount or 0
