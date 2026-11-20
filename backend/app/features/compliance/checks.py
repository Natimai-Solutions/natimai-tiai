"""The compliance checks of a poste (dev/plan-evolutions-itil.md, C5).

A closed list, read as « 7 sur 9 » rather than as a weighted score: a score
does not say what to fix, the failed checks do. Each check is pass, fail,
unknown — not read, not counted — or, for the encryption of a desktop when
only laptops are required to be, not applicable. Pure: the facts that are not
columns of ``machines`` are loaded by ``crud`` and handed in.
"""

import enum
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.features.alert.os_support import support_of
from app.features.machine.models import Machine
from app.features.machine.status import effective_up_to_date
from app.features.setting.crud import CompliancePolicy


class Check(enum.StrEnum):
    ENCRYPTION = "encryption"
    SECURE_BOOT = "secure_boot"
    TPM = "tpm"
    ANTIVIRUS = "antivirus"
    PATCHES = "patches"
    REBOOT = "reboot"
    OS_SUPPORTED = "os_supported"
    AGENT_CURRENT = "agent_current"
    FIREWALL = "firewall"
    LOCAL_ADMINS = "local_admins"


ALL_CHECKS: tuple[Check, ...] = tuple(Check)


class State(enum.StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Result:
    check: Check
    state: State
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Facts:
    """What a check needs beyond the poste's own columns."""

    # The system volume's BitLocker status; None when not read.
    system_encryption: str | None = None
    # Critical or important updates pending past the grace period; None when
    # the poste never reported its Windows Update state.
    overdue_patches: list[str] | None = None
    # Agent versions behind the parc's reference.
    outdated_agents: frozenset[str] = frozenset()


FULLY_ENCRYPTED = "FullyEncrypted"
MOBILE_CHASSIS = ("laptop", "tablet")
# Members of Administrators that are the system's own, whatever their name:
# the built-in Administrator (RID 500), Domain Admins (512), Enterprise
# Admins (519). Identified by SID, since their names are translated.
BUILTIN_ADMIN_RIDS = ("500", "512", "519")
_RID = re.compile(r"-(\d+)$")
# Names shown in a failed check's detail at most.
MAX_NAMES = 10


def _state(value: bool | None) -> State:
    if value is None:
        return State.UNKNOWN
    return State.PASS if value else State.FAIL


def _builtin(sid: str | None) -> bool:
    if not sid:
        return False
    m = _RID.search(sid)
    return bool(m and m.group(1) in BUILTIN_ADMIN_RIDS and sid.startswith("S-1-5-21-"))


def extra_admins(members: list[dict[str, Any]], allowed: tuple[str, ...]) -> list[str]:
    """The members of Administrators that are neither the system's own nor
    on the console's list."""
    accepted = {a.lower() for a in allowed}
    extra = []
    for m in members:
        name = str(m.get("name") or "")
        bare = name.rsplit("\\", 1)[-1]
        if _builtin(m.get("sid")):
            continue
        if name.lower() in accepted or bare.lower() in accepted:
            continue
        extra.append(name)
    return extra


def evaluate(
    machine: Machine, facts: Facts, policy: CompliancePolicy, now: datetime
) -> list[Result]:
    results: list[Result] = []

    # Volume système chiffré — the alerts' scope: only laptops and tablets
    # are required to be, unless the setting says every poste.
    if (
        policy.unencrypted_scope == "laptops"
        and machine.hw_chassis_type not in MOBILE_CHASSIS
    ):
        results.append(Result(Check.ENCRYPTION, State.NOT_APPLICABLE))
    elif facts.system_encryption is None:
        results.append(Result(Check.ENCRYPTION, State.UNKNOWN))
    else:
        results.append(
            Result(
                Check.ENCRYPTION,
                _state(facts.system_encryption == FULLY_ENCRYPTED),
                {"status": facts.system_encryption},
            )
        )

    results.append(Result(Check.SECURE_BOOT, _state(machine.secure_boot)))

    tpm = machine.tpm_version
    results.append(
        Result(
            Check.TPM,
            _state(tpm.startswith("2") if tpm else None),
            {"version": tpm} if tpm else {},
        )
    )

    results.append(
        Result(
            Check.ANTIVIRUS,
            _state(effective_up_to_date(machine, now, policy.signature_max_age_days)),
        )
    )

    if facts.overdue_patches is None:
        results.append(Result(Check.PATCHES, State.UNKNOWN))
    else:
        results.append(
            Result(
                Check.PATCHES,
                _state(not facts.overdue_patches),
                {
                    "count": len(facts.overdue_patches),
                    "updates": facts.overdue_patches[:MAX_NAMES],
                    "grace_days": policy.patch_grace_days,
                }
                if facts.overdue_patches
                else {},
            )
        )

    if machine.wu_pending_count is None and not machine.wu_reboot_required:
        results.append(Result(Check.REBOOT, State.UNKNOWN))
    else:
        since = machine.wu_reboot_required_since
        overdue = bool(
            machine.wu_reboot_required
            and since is not None
            and since <= now - timedelta(days=policy.reboot_pending_days)
        )
        results.append(
            Result(
                Check.REBOOT,
                _state(not overdue),
                {
                    "since": since.isoformat(),
                    "threshold_days": policy.reboot_pending_days,
                }
                if overdue and since
                else {},
            )
        )

    support = support_of(machine.os_version) if machine.os_version else None
    if support is None:
        results.append(Result(Check.OS_SUPPORTED, State.UNKNOWN))
    else:
        ended = support.ended(now.date())
        results.append(
            Result(
                Check.OS_SUPPORTED,
                _state(not ended),
                {"end_of_support": support.end.isoformat()} if support.end else {},
            )
        )

    version = machine.agent_version or None
    results.append(
        Result(
            Check.AGENT_CURRENT,
            _state(None if version is None else version not in facts.outdated_agents),
            {"version": version} if version else {},
        )
    )

    profiles = {
        "domain": machine.firewall_domain,
        "private": machine.firewall_private,
        "public": machine.firewall_public,
    }
    off = [name for name, on in profiles.items() if on is False]
    if off:
        results.append(Result(Check.FIREWALL, State.FAIL, {"profiles": off}))
    elif all(on is True for on in profiles.values()):
        results.append(Result(Check.FIREWALL, State.PASS))
    else:
        results.append(Result(Check.FIREWALL, State.UNKNOWN))

    if machine.local_admins is None:
        results.append(Result(Check.LOCAL_ADMINS, State.UNKNOWN))
    else:
        extra = extra_admins(machine.local_admins, policy.admins_allowed)
        results.append(
            Result(
                Check.LOCAL_ADMINS,
                _state(not extra),
                {"count": len(extra), "names": extra[:MAX_NAMES]} if extra else {},
            )
        )
    return results


@dataclass(frozen=True)
class Summary:
    passed: int
    total: int
    failed: list[str]


def summarize(results: list[Result]) -> Summary:
    """« N sur M »: the checks known, and those passed among them."""
    known = [r for r in results if r.state in (State.PASS, State.FAIL)]
    return Summary(
        passed=sum(1 for r in known if r.state == State.PASS),
        total=len(known),
        failed=[r.check.value for r in known if r.state == State.FAIL],
    )
