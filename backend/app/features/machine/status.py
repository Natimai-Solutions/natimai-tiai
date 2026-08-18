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
