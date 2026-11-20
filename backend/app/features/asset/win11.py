"""Whether a poste's hardware can take Windows 11, from its inventory.

Microsoft's floor, as far as the inventory can read it: a TPM 2.0, 4 GB of
memory, a 64 GB system disk, a 64-bit system. Two parts of it the inventory
cannot settle, and they are said so rather than guessed:

* Secure Boot: the inventory reads whether it is *on*, not whether the
  firmware *can* — a poste with it off is « à vérifier », not « incompatible »;
* the processor: Microsoft's list of supported processors is not in the
  product. It is always « à vérifier » unless the poste already runs
  Windows 11.

So a verdict is « prêt » only short of the processor, « incompatible » only
on a part the inventory reads for sure, and « à vérifier » otherwise.

The memory is the sticks' sum when the inventory lists them all
(``Win32_PhysicalMemory``), as Microsoft's own check reads it. Without them,
only what Windows can address is known (``ram_total_mb``), short of what
the firmware keeps for an integrated graphics chip: a little under 4 GB is
« à vérifier », not « incompatible ».

A Windows Server is not a poste that moves to Windows 11: no verdict at all.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, case, func, not_, or_
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select

from app.features.inventory.models import MemoryModule
from app.features.machine.models import Machine

# The sticks' sum Microsoft asks for.
MIN_INSTALLED_RAM_MB = 4 * 1024
# Windows reports what it can address, a little short of the sticks' sum.
MIN_RAM_MB = 4 * 1024 - 300
# Below this, no graphics chip explains the gap: short of 4 GB for sure.
MIN_RAM_CHECK_MB = 3 * 1024
# A « 64 GB » disk shows as about 59.6 GiB of volume.
MIN_SYSTEM_MB = 58 * 1024

Verdict = Literal["already", "ready", "check", "blocked", "unknown"]
Check = Literal["ok", "fail", "check", "unknown"]


@dataclass(frozen=True)
class Readiness:
    verdict: Verdict
    tpm: Check
    ram: Check
    disk: Check
    architecture: Check
    secure_boot: Check
    processor: Check


def _is_windows_11(os_version: str | None) -> bool:
    return bool(os_version) and "windows 11" in (os_version or "").lower()


def _is_server(os_version: str | None) -> bool:
    return "server" in (os_version or "").lower()


def installed_ram_mb(capacities: list[int | None]) -> int | None:
    """The sticks' sum, when the inventory lists sticks and reads each."""
    if not capacities or any(c is None for c in capacities):
        return None
    return sum(c for c in capacities if c is not None)


def _ram(machine: Machine, installed_mb: int | None) -> Check:
    if installed_mb is not None:
        return "ok" if installed_mb >= MIN_INSTALLED_RAM_MB else "fail"
    if machine.ram_total_mb is None:
        return "unknown"
    if machine.ram_total_mb >= MIN_RAM_MB:
        return "ok"
    return "check" if machine.ram_total_mb >= MIN_RAM_CHECK_MB else "fail"


def readiness(machine: Machine, installed_mb: int | None = None) -> Readiness | None:
    """The verdict for ``machine``; ``installed_mb`` is the sticks' sum
    (``installed_ram_mb``). None for a Windows Server."""
    if _is_server(machine.os_version):
        return None
    if _is_windows_11(machine.os_version):
        return Readiness("already", "ok", "ok", "ok", "ok", "ok", "ok")
    if machine.inventory_last_seen is None:
        return Readiness(
            "unknown", "unknown", "unknown", "unknown", "unknown", "unknown", "unknown"
        )

    tpm: Check
    if not machine.tpm_version:
        tpm = "fail"
    else:
        tpm = "ok" if machine.tpm_version.strip().startswith("2") else "fail"
    ram = _ram(machine, installed_mb)
    disk: Check = (
        "unknown"
        if machine.system_volume_total_mb is None
        else ("ok" if machine.system_volume_total_mb >= MIN_SYSTEM_MB else "fail")
    )
    arch_value = (machine.os_architecture or "").lower()
    architecture: Check
    if not arch_value:
        architecture = "unknown"
    elif "64" in arch_value:
        architecture = "ok"
    else:
        # A 32-bit Windows may sit on a 64-bit processor: a reinstall, not a
        # replacement — to check, not refused.
        architecture = "check"
    secure_boot: Check = (
        "ok" if machine.secure_boot else "check"
    )  # off, or not read: the firmware may still support it

    parts = (tpm, ram, disk)
    if "fail" in parts:
        verdict: Verdict = "blocked"
    elif "unknown" in parts:
        verdict = "unknown"
    else:
        # The processor always leaves it to check, short of Windows 11 itself.
        verdict = (
            "check"
            if "check" in parts or architecture != "ok" or secure_boot != "ok"
            else "ready"
        )
    return Readiness(verdict, tpm, ram, disk, architecture, secure_boot, "check")


def installed_ram_expr() -> ColumnElement[int | None]:
    """``installed_ram_mb`` in SQL, per poste: the sum of its sticks when
    every one of them reads, else NULL."""
    return (
        select(
            case(
                (
                    func.count() == func.count(col(MemoryModule.capacity_mb)),
                    func.sum(col(MemoryModule.capacity_mb)),
                ),
                else_=None,
            )
        )
        .where(col(MemoryModule.machine_id) == col(Machine.id))
        .scalar_subquery()
    )


def blocked_clause() -> ColumnElement[bool]:
    """Postes the inventory says cannot take Windows 11 — the « à remplacer »
    list: not on Windows 11 nor a server, inventoried, and short of a TPM
    2.0, of memory or of disk. The same reading as ``readiness``
    (« blocked »)."""
    no_tpm2 = or_(
        col(Machine.tpm_version).is_(None),
        not_(func.ltrim(col(Machine.tpm_version)).startswith("2")),
    )
    installed = installed_ram_expr()
    short_of_memory = or_(
        and_(installed.is_not(None), installed < MIN_INSTALLED_RAM_MB),
        and_(installed.is_(None), col(Machine.ram_total_mb) < MIN_RAM_CHECK_MB),
    )
    return and_(
        or_(
            col(Machine.os_version).is_(None),
            and_(
                not_(col(Machine.os_version).ilike("%windows 11%")),
                not_(col(Machine.os_version).ilike("%server%")),
            ),
        ),
        col(Machine.inventory_last_seen).is_not(None),
        or_(
            no_tpm2,
            short_of_memory,
            col(Machine.system_volume_total_mb) < MIN_SYSTEM_MB,
        ),
    )
