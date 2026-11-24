"""Hardware and software inventory tables.

Current state, not history — the same semantics as ``windows_updates`` and the
opposite of ``threats``: a disk that was pulled, a volume that was deleted, a
program that was uninstalled must *disappear* here, or the console would keep
describing a machine that no longer exists. ``crud`` replaces each set on every
reported inventory; ``first_seen`` is the one historical fact that survives.

What has cardinality one — the chassis, the motherboard, the BIOS, the CPU —
lives in columns on ``machines`` instead. See ``dev/plan-inventaire.md`` §3.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Column, ForeignKey, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow

# The four columns every per-machine inventory table carries, as factories.
#
# Factories and not a shared base class: a ``sa_column`` instance belongs to one
# table and cannot be handed to a second, so a base declaring them would have
# the first table claim the Column objects and the next four fail to build. It
# is the same rule ``utc_field`` exists for, one level up.


def _child_id() -> Any:
    """The BigInteger surrogate key. These tables are wide and churn daily."""
    return Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )


def _machine_fk() -> Any:
    """The owning machine. ON DELETE CASCADE: an inventory outlives nothing."""
    return Field(
        sa_column=Column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    )


class MemoryModule(SQLModel, table=True):
    """One physical memory stick, as ``Win32_PhysicalMemory`` describes it.

    A table and not a "16 Go de RAM" column because the question it answers is
    "puis-je ajouter de la barrette sans rien jeter", which needs the slots. The
    totals live on ``machines`` (``ram_total_mb``, ``ram_slots_total``,
    ``ram_slots_used``) for the list view, which must not join to show a number.
    """

    __tablename__ = "inventory_memory_modules"
    __table_args__ = (
        UniqueConstraint("machine_id", "slot", name="uq_inv_memory_machine_slot"),
        Index("ix_inv_memory_machine_id", "machine_id"),
    )

    id: int | None = _child_id()
    machine_id: uuid.UUID = _machine_fk()
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)

    # The bank/slot label Windows reports ("DIMM A1"). The key: it is the only
    # thing that stays put across reboots — a serial can be blank on cheap
    # modules, and the enumeration order is not stable.
    slot: str
    capacity_mb: int | None = None
    type: str | None = None  # DDR4, DDR5, LPDDR5…
    speed_mhz: int | None = None
    manufacturer: str | None = None
    serial: str | None = None
    form_factor: str | None = None  # DIMM, SODIMM…


class Disk(SQLModel, table=True):
    """One physical drive: model, media type, size and health."""

    __tablename__ = "inventory_disks"
    __table_args__ = (
        UniqueConstraint("machine_id", "device_id", name="uq_inv_disks_machine_device"),
        Index("ix_inv_disks_machine_id", "machine_id"),
    )

    id: int | None = _child_id()
    machine_id: uuid.UUID = _machine_fk()
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)

    # Windows' own device identifier (``\\.\PHYSICALDRIVE0``) and not the serial:
    # a serial is the better key right up to the machines that report none, and
    # a blank key is not a key. The serial is stored beside it for the humans.
    device_id: str
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    # SSD / HDD / NVMe / unknown. "unknown" is a real answer here and not a
    # missing one: ``Win32_DiskDrive`` cannot tell the two apart, and a host
    # without the Storage WMI namespace falls back to it (plan §4.2).
    media_type: str | None = None
    bus_type: str | None = None  # SATA, NVMe, USB, RAID…
    size_mb: int | None = None
    health_status: str | None = None  # Healthy / Warning / Unhealthy
    is_removable: bool = False


class Volume(SQLModel, table=True):
    """One fixed logical volume: what is on the disk and what is left of it.

    The row an administrator actually looks at. ``used_mb`` is deliberately not
    stored — it is ``total_mb - free_mb``, and two columns that can contradict
    each other about one number is the mistake ``wu_pending_count`` already
    avoided by being derived server-side.
    """

    __tablename__ = "inventory_volumes"
    __table_args__ = (
        UniqueConstraint("machine_id", "letter", name="uq_inv_volumes_machine_letter"),
        Index("ix_inv_volumes_machine_id", "machine_id"),
    )

    id: int | None = _child_id()
    machine_id: uuid.UUID = _machine_fk()
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)

    letter: str  # "C:"
    label: str | None = None
    filesystem: str | None = None  # NTFS, ReFS…
    total_mb: int | None = None
    free_mb: int | None = None
    is_system: bool = False
    # BitLocker, read best-effort: the namespace is absent on some SKUs and the
    # class needs elevation. NULL = not read, which is not "not encrypted".
    encryption_status: str | None = None


class Nic(SQLModel, table=True):
    """One network adapter, from the same ``GetAdaptersAddresses`` walk that
    elects ``machines.ip_address``.

    The elected address stays on ``machines`` and is *not* derived from this
    table: it is re-read every 60 s because it is the wake target, while this
    table is refreshed once a day. Deriving either from the other would cost
    freshness on one side or completeness on the other.
    """

    __tablename__ = "inventory_nics"
    __table_args__ = (
        UniqueConstraint("machine_id", "key", name="uq_inv_nics_machine_key"),
        Index("ix_inv_nics_machine_id", "machine_id"),
    )

    id: int | None = _child_id()
    machine_id: uuid.UUID = _machine_fk()
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)

    # The MAC when the adapter has one, else its name. A tunnel or PPP
    # pseudo-adapter has no hardware address, and it still has to be keyed on
    # something stable.
    key: str
    name: str | None = None  # Windows' description = the adapter's model
    mac: str | None = None
    type: str | None = None  # ethernet / wifi / other
    speed_mbps: int | None = None
    is_up: bool = False
    # Set on the adapters Windows reports as virtual (Hyper-V switches, VPN,
    # WSL). What lets the console show a real card without hiding the rest.
    is_virtual: bool = False
    ip_address: str | None = None
    ip_prefix_length: int | None = None
    is_dhcp: bool | None = None
    gateway: str | None = None
    driver_version: str | None = None


class Gpu(SQLModel, table=True):
    """One display adapter. Two is the common case: an iGPU and a card."""

    __tablename__ = "inventory_gpus"
    __table_args__ = (
        UniqueConstraint("machine_id", "name", name="uq_inv_gpus_machine_name"),
        Index("ix_inv_gpus_machine_id", "machine_id"),
    )

    id: int | None = _child_id()
    machine_id: uuid.UUID = _machine_fk()
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)

    name: str
    chipset: str | None = None
    memory_mb: int | None = None
    driver_version: str | None = None
    driver_date: date | None = None
    resolution: str | None = None  # "1920x1080"


class WingetPackage(SQLModel, table=True):
    """One program winget knows on a poste, with the version it would
    upgrade to (C5). Reported only by agents with ``ReportWingetPackages``."""

    __tablename__ = "inventory_winget_packages"
    __table_args__ = (
        UniqueConstraint("machine_id", "winget_id", name="uq_inv_winget_machine_id"),
        Index("ix_inv_winget_winget_id", "winget_id"),
    )

    id: int | None = _child_id()
    machine_id: uuid.UUID = _machine_fk()
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)

    winget_id: str
    name: str | None = None
    version: str | None = None
    # Empty when winget offers nothing newer.
    available: str | None = None


class Software(SQLModel, table=True):
    """One (name, version, publisher) known anywhere in the parc.

    A catalogue rather than a column repeated on every machine, for two reasons
    that are not storage size — a denormalised table would be perfectly
    affordable (plan §3.3):

    1. The question this module exists to answer is "qui a encore Java 8", which
       here is a GROUP BY over a few thousand rows instead of a few hundred
       thousand repeated strings;
    2. software deployment, next in the same phase, needs a stable id to hang a
       package on. Adding it now costs a table; adding it later costs a data
       migration over the whole history.

    ``version`` and ``publisher`` are NOT NULL and empty-when-absent on purpose:
    Postgres considers NULLs distinct in a UNIQUE constraint, so a nullable
    publisher would let one unpublished program accumulate a row per machine —
    exactly the duplication the catalogue exists to avoid.

    No name normalisation, deliberately: GLPI and OCS both grew dictionaries to
    fold "Mozilla Firefox" into "Firefox (x64 fr)", and that is a product of its
    own. What the poste declares is what is stored; a dictionary can sit above
    this table later without touching collection.
    """

    __tablename__ = "software"
    __table_args__ = (
        UniqueConstraint("name", "version", "publisher", name="uq_software_identity"),
        Index("ix_software_name", "name"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    name: str
    version: str = ""
    publisher: str = ""
    first_seen: datetime = utc_field(default_factory=utcnow)


class MachineSoftware(SQLModel, table=True):
    """One program installed on one machine — the link to the catalogue."""

    __tablename__ = "machine_software"
    __table_args__ = (
        UniqueConstraint(
            "machine_id", "software_id", name="uq_machine_software_identity"
        ),
        Index("ix_machine_software_machine_id", "machine_id"),
        Index("ix_machine_software_software_id", "software_id"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    machine_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    )
    software_id: int = Field(
        sa_column=Column(
            BigInteger, ForeignKey("software.id", ondelete="CASCADE"), nullable=False
        )
    )
    install_date: date | None = None
    arch: str | None = None  # x86 / x64
    # Which registry view it was read from — the two Uninstall hives. Kept
    # because "why does this 32-bit program show up twice" is answered by it.
    source: str | None = None
    install_location: str | None = None
    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)
