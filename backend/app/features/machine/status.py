"""Machine freshness and status filtering — shared by the console list, stats,
and command targeting so the definitions stay in one place.

``is_up_to_date`` is a derived attribute (plan §4): a machine is up to date when
its antivirus is running and its signatures are fresh — either Defender's, with
real dates, or a third-party product's as the Windows Security Center reports it.
It is computed on each heartbeat and stored, so reads (list, stats) are plain
aggregates.
"""

import enum
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, false, func, or_
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col

from app.features.machine.models import Machine


def compute_is_up_to_date(
    *,
    av_enabled: bool | None,
    rtp_enabled: bool | None,
    signature_age_days: int | None,
    max_age_days: int,
    av_product_enabled: bool | None = None,
    av_product_signatures_up_to_date: bool | None = None,
    av_product_is_defender: bool | None = None,
) -> bool:
    """Whether a machine is adequately protected (plan §4).

    Two ways to qualify, because two products can be doing the protecting:

    * Defender itself — antivirus + real-time protection enabled and signatures
      no older than ``max_age_days``. Missing data is not up to date.
    * a third-party antivirus registered with the Windows Security Center —
      running, and not reporting its signatures as out of date.

    The second path is not a courtesy. Installing ESET or Bitdefender pushes
    Defender into passive mode, which zeroes ``av_enabled``/``rtp_enabled``, so
    without it every third-party-protected machine would count as unprotected
    forever and the dashboard KPIs would be wrong by construction.

    It is deliberately weaker than the Defender path: the Security Center exposes
    no signature version and no date, only a freshness bit that vendors fill in
    unevenly. An *unknown* freshness therefore still qualifies, while an explicit
    "out of date" does not — requiring a positive bit would reinstate the very
    bug this path fixes. Defender's own entry in that registry is ignored here:
    the Defender columns say the same thing with real dates behind them.
    """
    if _defender_protects(av_enabled, rtp_enabled, signature_age_days, max_age_days):
        return True
    return _third_party_protects(
        enabled=av_product_enabled,
        signatures_up_to_date=av_product_signatures_up_to_date,
        is_defender=av_product_is_defender,
    )


def _defender_protects(
    av_enabled: bool | None,
    rtp_enabled: bool | None,
    signature_age_days: int | None,
    max_age_days: int,
) -> bool:
    """Defender is on and its signatures are within the threshold."""
    if not av_enabled or not rtp_enabled:
        return False
    if signature_age_days is None:
        return False
    return signature_age_days <= max_age_days


def _third_party_protects(
    *,
    enabled: bool | None,
    signatures_up_to_date: bool | None,
    is_defender: bool | None,
) -> bool:
    """A registered third-party antivirus is running and not stale.

    ``is_defender`` must be an explicit ``False``: unknown means the agent could
    not tell the product apart, and crediting protection on that would let a
    misread Defender entry mask a genuinely unprotected machine.
    """
    if is_defender is not False:
        return False
    if enabled is not True:
        return False
    return signatures_up_to_date is not False


def is_online(last_seen: datetime, now: datetime, offline_after_seconds: int) -> bool:
    """Whether the machine is powered on with its agent reaching the server.

    Read from ``last_seen`` alone: the agent polls on a fixed interval, so a
    heartbeat younger than a few of those intervals is the only evidence the
    server has that a poste is up. Deliberately *not* the same question as the
    ``INACTIVE`` status, which spans thirty days and means "this record looks
    abandoned" — this one spans minutes and means "it is on right now".

    Computed on read and never stored: unlike ``is_up_to_date``, it decays with
    the clock, so no write would ever mark a poste as gone.
    """
    return (now - last_seen).total_seconds() < offline_after_seconds


def online_clause(
    online: bool, now: datetime, offline_after_seconds: int
) -> ColumnElement[bool]:
    """SQL predicate for ``is_online``, asked of the whole fleet at once.

    The same window as the per-row property above — one definition of "on",
    whether the console reads a dot or filters a list. ``False`` selects the
    complement: the postes to wake, not merely the ones not to bother.
    """
    cutoff = now - timedelta(seconds=offline_after_seconds)
    if online:
        return col(Machine.last_seen) >= cutoff
    return col(Machine.last_seen) < cutoff


class MachineStatus(enum.StrEnum):
    """Console status filters (also usable as command broadcast targets)."""

    UP_TO_DATE = "up_to_date"
    OUTDATED = (
        "outdated"  # not up to date (stale signatures / protection off / unknown)
    )
    NEEDS_VERIFICATION = "needs_verification"
    INACTIVE = "inactive"  # no heartbeat for longer than the inactivity window


def status_clause(
    status: MachineStatus, now: datetime, inactive_after_days: int
) -> ColumnElement[bool]:
    """Build the SQL predicate selecting machines in the given status."""
    match status:
        case MachineStatus.UP_TO_DATE:
            return col(Machine.is_up_to_date).is_(True)
        case MachineStatus.OUTDATED:
            # Includes explicit False and unknown (NULL): the machines to act on.
            return col(Machine.is_up_to_date).is_not(True)
        case MachineStatus.NEEDS_VERIFICATION:
            return col(Machine.needs_verification).is_(True)
        case MachineStatus.INACTIVE:
            cutoff = now - timedelta(days=inactive_after_days)
            return col(Machine.last_seen) < cutoff


class WindowsUpdateFilter(enum.StrEnum):
    """Console Windows Update filters for the machine list.

    Not folded into ``MachineStatus``: that enum is an antivirus axis (and a
    command broadcast target), and a poste sits on both axes at once — filtering
    "antivirus périmé" must stay combinable with "MAJ Windows requises".
    """

    PENDING = "pending"
    REBOOT_REQUIRED = "reboot_required"


def windows_update_clause(wu: WindowsUpdateFilter) -> ColumnElement[bool]:
    """Build the SQL predicate selecting machines in the given WU state."""
    match wu:
        case WindowsUpdateFilter.PENDING:
            # Strictly positive: a NULL count means the agent never reported a
            # Windows Update search — unknown, not behind.
            return col(Machine.wu_pending_count) > 0
        case WindowsUpdateFilter.REBOOT_REQUIRED:
            return col(Machine.wu_reboot_required).is_(True)


def agent_outdated_clause(outdated: list[str], value: bool) -> ColumnElement[bool]:
    """Machines whose agent version is (or is not) among ``outdated``.

    The list comes from ``agent_version.outdated_versions``: which strings rank
    below the reference is decided in Python, on the handful of distinct
    versions a parc carries, because a version compare has no honest SQL.

    A machine that never reported a version matches neither side — unknown is
    not behind, and it is not current either.
    """
    version = col(Machine.agent_version)
    if not outdated:
        # Nothing is behind: "outdated" is empty, "current" is every poste
        # that reported anything at all.
        return false() if value else version.is_not(None)
    return version.in_(outdated) if value else version.not_in(outdated)


class ScanFilter(enum.StrEnum):
    """Console scan-freshness filters for the machine list.

    A third axis next to ``MachineStatus`` and ``WindowsUpdateFilter``: "which
    postes have not been *scanned* lately" is a different question from "whose
    signatures are stale", and the two must stay combinable. ``BOTH`` means both
    scans are overdue at once — the postes nothing has looked at in any way.
    """

    QUICK = "quick"
    FULL = "full"
    BOTH = "both"


def _scan_overdue(column: datetime | None, cutoff: datetime) -> ColumnElement[bool]:
    """One scan column being older than ``cutoff`` — NULL included.

    NULL qualifies deliberately: a poste that *never* ran the scan is further
    behind than any dated one, and the filter exists to find postes to act on.
    """
    return or_(col(column).is_(None), col(column) < cutoff)


def scan_clause(scan: ScanFilter, cutoff: datetime) -> ColumnElement[bool]:
    """Build the SQL predicate selecting machines whose scans predate ``cutoff``."""
    quick = _scan_overdue(Machine.last_quick_scan, cutoff)
    full = _scan_overdue(Machine.last_full_scan, cutoff)
    match scan:
        case ScanFilter.QUICK:
            return quick
        case ScanFilter.FULL:
            return full
        case ScanFilter.BOTH:
            return and_(quick, full)


def disk_free_percent() -> ColumnElement[Any]:
    """Free space on the system volume, as a percentage of its size.

    Derived rather than stored, unlike the two megabyte figures it divides: a
    percentage is a presentation of them, and storing it would be a third number
    that can disagree with the other two.

    ``nullif`` guards the division: a machine that never reported an inventory
    has NULL there, and one that reported a zero-sized volume would divide by
    zero. Both come out NULL, which sorts last and matches no threshold — an
    absence is not a full disk.
    """
    return (
        col(Machine.system_volume_free_mb)
        * 100.0
        / func.nullif(col(Machine.system_volume_total_mb), 0)
    )


def ram_nominal_gb() -> ColumnElement[Any]:
    """Installed memory as the whole number of GiB printed on the box.

    Windows reports what it can address, which is a few hundred MiB short of
    the sticks' sum — a 16 GiB poste says 16 289 MiB. Rounding *up* recovers the
    nominal size, so "au moins 16 Gio" finds every 16 GiB machine rather than
    none of them. NULL stays NULL: never reported is not zero memory.
    """
    return func.ceil(col(Machine.ram_total_mb) / 1024.0)


def ram_clause(min_gb: int | None, max_gb: int | None) -> ColumnElement[bool]:
    """Machines whose nominal memory sits within [min_gb, max_gb], GiB, inclusive.

    Either bound may be absent. A machine that never reported its memory
    matches neither — the filter exists to find postes to upgrade, and an
    absence is not a small memory.
    """
    nominal = ram_nominal_gb()
    clauses: list[ColumnElement[bool]] = [col(Machine.ram_total_mb).is_not(None)]
    if min_gb is not None:
        clauses.append(nominal >= min_gb)
    if max_gb is not None:
        clauses.append(nominal <= max_gb)
    return and_(*clauses)


def low_disk_clause(percent: int) -> ColumnElement[bool]:
    """Machines whose system volume is below ``percent`` free.

    Written as a multiplication rather than a division so the comparison stays
    in integers: ``free * 100 < total * percent``. Same answer, no float, and no
    special case for the zero-sized volume — which cannot be below a threshold
    because it has no space to be below it with.

    This is the filter behind the dashboard's "plus de place" card, and it is the
    most actionable figure the inventory produces: a full C: is the first cause
    of a poste that quietly stops taking Windows updates.
    """
    free = col(Machine.system_volume_free_mb)
    total = col(Machine.system_volume_total_mb)
    return and_(free.is_not(None), total > 0, free * 100 < total * percent)


def aging_hardware_clause(now: datetime, years: int) -> ColumnElement[bool]:
    """Machines whose BIOS predates ``years`` ago — the renewal plan's figure.

    The BIOS date is the closest thing to a machine's age the poste knows: a
    purchase date lives in an accounting system this product does not talk to,
    and a reimaged Windows resets its own install date. NULL is excluded: never
    reported is not old.
    """
    cutoff = (now - timedelta(days=365 * years)).date()
    return col(Machine.bios_date) < cutoff
