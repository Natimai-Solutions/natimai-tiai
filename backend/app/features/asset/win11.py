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
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, func, not_, or_
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col

from app.features.machine.models import Machine

# Windows reports what it can address, a little short of the sticks' sum.
MIN_RAM_MB = 4 * 1024 - 300
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


def readiness(machine: Machine) -> Readiness:
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
    ram: Check = (
        "unknown"
        if machine.ram_total_mb is None
        else ("ok" if machine.ram_total_mb >= MIN_RAM_MB else "fail")
    )
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
        verdict = "check" if architecture != "ok" or secure_boot != "ok" else "ready"
    return Readiness(verdict, tpm, ram, disk, architecture, secure_boot, "check")


def blocked_clause() -> ColumnElement[bool]:
    """Postes the inventory says cannot take Windows 11 — the « à remplacer »
    list: not on Windows 11, inventoried, and short of a TPM 2.0, of memory
    or of disk. The same reading as ``readiness`` (« blocked »)."""
    no_tpm2 = or_(
        col(Machine.tpm_version).is_(None),
        not_(func.ltrim(col(Machine.tpm_version)).startswith("2")),
    )
    return and_(
        or_(
            col(Machine.os_version).is_(None),
            not_(col(Machine.os_version).ilike("%windows 11%")),
        ),
        col(Machine.inventory_last_seen).is_not(None),
        or_(
            no_tpm2,
            col(Machine.ram_total_mb) < MIN_RAM_MB,
            col(Machine.system_volume_total_mb) < MIN_SYSTEM_MB,
        ),
    )
