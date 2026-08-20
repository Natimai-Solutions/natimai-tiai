"""Agent-facing endpoints: enroll, heartbeat (+ command pickup), command result."""

import uuid
from datetime import datetime
from ipaddress import ip_address

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlmodel import select

from app.api.deps import CurrentMachine, SessionDep, verify_enrollment_secret
from app.core import security
from app.core.config import settings
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command.models import (
    AGENT_REPORTABLE_STATUSES,
    TERMINAL_STATUSES,
    Command,
    CommandStatus,
)
from app.features.machine import fingerprint
from app.features.machine.models import Machine
from app.features.machine.status import compute_is_up_to_date
from app.features.threat.crud import upsert_threats
from app.features.threat.schemas import ThreatReport
from app.features.windows_update.crud import replace_pending
from app.features.windows_update.schemas import WUStateReport
from app.features.wol.packet import normalize_mac

router = APIRouter(prefix="/agent", tags=["agent"])


# --- Schemas ---------------------------------------------------------------


class Fingerprint(BaseModel):
    """Identity fingerprint components reported by the agent."""

    machine_guid: str | None = None
    smbios_uuid: str | None = None
    tpm_ek_hash: str | None = None


class EnrollRequest(BaseModel):
    """First-contact payload (authenticated by X-Enrollment-Secret header)."""

    machine_uuid: str
    hostname: str | None = None
    domain: str | None = None
    os_version: str | None = None
    agent_version: str | None = None
    fingerprint: Fingerprint | None = None


class EnrollResponse(BaseModel):
    """Returned once: the per-machine bearer token."""

    machine_id: uuid.UUID
    token: str


# Bounds the third-party product name that reaches the column and the console.
# Real names run to ~40 characters ("Bitdefender Endpoint Security Tools"); this
# leaves ample room while keeping a vendor string we do not control from growing
# without limit.
AV_PRODUCT_NAME_MAX = 120


class DefenderState(BaseModel):
    """Defender status reported on each heartbeat."""

    rtp_enabled: bool | None = None
    av_enabled: bool | None = None
    signature_version: str | None = None
    signature_last_updated: datetime | None = None
    signature_age_days: int | None = None
    last_quick_scan: datetime | None = None
    last_full_scan: datetime | None = None
    # Normal / Passive / SxS Passive Mode / EDR Block Mode (AMRunningMode).
    running_mode: str | None = None


class AVProduct(BaseModel):
    """Antivirus registered with the Windows Security Center (client SKUs only).

    Sent whenever the agent could read the registry, empty name included: "no
    antivirus at all" is a finding worth storing. An absent block means the agent
    could not look — no Security Center on Windows Server — and the server then
    keeps what it had. Every field has a default so a malformed block degrades
    instead of 422-ing the whole heartbeat.
    """

    name: str = ""
    enabled: bool | None = None
    signatures_up_to_date: bool | None = None
    is_defender: bool = False

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        """Trim and bound the product name — never 422.

        Same trade-off as ``ip_address``: this is a third-party vendor's display
        string, so it is bounded here rather than trusted, and a value we dislike
        costs the name and not the Defender state, the threats and the command
        pickup riding along in the same request.
        """
        return value.strip()[:AV_PRODUCT_NAME_MAX]


class SessionState(BaseModel):
    """Interactive session reported on each heartbeat.

    ``username`` is absent when the agent is configured not to report it
    (report_session_username=false): presence is still known, the name never
    leaves the machine. Every field has a default so a malformed block degrades
    to "nobody" instead of 422-ing the whole heartbeat, Defender state included.
    """

    user_present: bool = False
    username: str | None = None
    state: str | None = None  # active / disconnected
    is_remote: bool = False


class HeartbeatRequest(BaseModel):
    """State report; threats reported separately as a list of raw dicts."""

    hostname: str | None = None
    domain: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    ip_prefix_length: int | None = None
    os_version: str | None = None
    agent_version: str | None = None
    defender: DefenderState | None = None
    av_product: AVProduct | None = None
    session: SessionState | None = None
    # Sent only on the heartbeats that follow a Windows Update collection — the
    # agent runs that on its own slow cycle (hours), because a WU search takes
    # minutes. Absent on every other heartbeat, which leaves the stored state
    # alone exactly like an absent Defender block.
    windows_update: WUStateReport | None = None
    fingerprint: Fingerprint | None = None
    threats: list[ThreatReport] = []

    @field_validator("ip_address")
    @classmethod
    def _normalize_ip(cls, value: str | None) -> str | None:
        """Keep a parseable address, drop anything else — never 422.

        Same trade-off as SessionState's defaults: one malformed field must not
        cost us the Defender state, the threats and the command pickup riding
        along in the same request. Dropping it to None means the heartbeat
        simply doesn't touch the stored address.

        Parsing also bounds what reaches the column and the console: only an
        IPv4/IPv6 literal gets through, in its canonical form.
        """
        if value is None:
            return None
        try:
            return str(ip_address(value))
        except ValueError:
            return None

    @field_validator("mac_address")
    @classmethod
    def _normalize_mac(cls, value: str | None) -> str | None:
        """Canonicalise the wake target, drop anything else — never 422.

        Same trade-off as the address above, and the same reason to parse rather
        than store: the column feeds a magic packet, so what reaches it has to be
        six bytes of hardware address and not a string an agent happened to send.
        Canonical form (upper case, colons) means the console shows one shape and
        the value can be compared as text.
        """
        return normalize_mac(value)

    @field_validator("ip_prefix_length")
    @classmethod
    def _bound_prefix(cls, value: int | None) -> int | None:
        """Keep a mask that can describe a network, drop anything else.

        1 to 128 — the widest an IPv6 prefix goes; the derivation refuses a value
        that does not fit the address it is applied to anyway. Zero is excluded
        on both readings: it is what Windows leaves when it did not fill the
        field in, and a /0 whose broadcast address is 255.255.255.255, which
        reaches the whole world or nothing at all and never the poste.

        Degrades to None like its neighbours rather than 422-ing the heartbeat:
        the wake then falls back on the configured default, which is what it did
        before agents reported this at all.
        """
        if value is None or not 1 <= value <= 128:
            return None
        return value


class CommandOut(BaseModel):
    """A pending command handed to the agent."""

    id: uuid.UUID
    type: str


class HeartbeatResponse(BaseModel):
    """Heartbeat ack carrying the machine's pending commands."""

    commands: list[CommandOut]


# Bounds what one command result can write to the database and pour into the
# console's result dialog. The agent truncates to the same budget before
# posting; this is the server not taking its word for it.
RESULT_TEXT_MAX = 64 * 1024


class CommandResult(BaseModel):
    """Execution result posted back by the agent.

    ``status`` is also the progress ping: a long command (sfc, dism, chkdsk)
    posts ``running`` when it starts, then its final verdict.
    """

    status: CommandStatus
    output: str | None = None
    error: str | None = None

    @field_validator("status")
    @classmethod
    def _reportable(cls, value: CommandStatus) -> CommandStatus:
        """Reject the statuses that are the server's to write, not the agent's.

        Unlike the degrade-don't-422 fields above, this one *is* worth
        rejecting: there is no partial value to salvage, and silently accepting
        "pending" or "expired" would let an agent rewrite the queue it is only
        meant to drain.
        """
        if value not in AGENT_REPORTABLE_STATUSES:
            allowed = ", ".join(sorted(AGENT_REPORTABLE_STATUSES))
            raise ValueError(f"status must be one of: {allowed}")
        return value

    @field_validator("output", "error")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        """Cap the reported text rather than 422 it — a truncated verdict beats none."""
        if value is None or len(value) <= RESULT_TEXT_MAX:
            return value
        return value[:RESULT_TEXT_MAX] + "\n[…] sortie tronquée par le serveur"


# --- Routes ----------------------------------------------------------------


@router.post(
    "/enroll",
    response_model=EnrollResponse,
    dependencies=[Depends(verify_enrollment_secret)],
)
async def enroll(payload: EnrollRequest, session: SessionDep) -> EnrollResponse:
    """Register a machine (trust on first use) and emit its token once.

    Idempotent on machine_uuid: re-enrollment rotates the token. A known
    machine_uuid re-enrolling is a guard-rail signal (reinstall vs token theft).
    """
    result = await session.exec(
        select(Machine).where(Machine.machine_uuid == payload.machine_uuid)
    )
    machine = result.one_or_none()
    fp = payload.fingerprint or Fingerprint()

    token = security.generate_token()
    suspicious = False
    if machine is None:
        machine = Machine(machine_uuid=payload.machine_uuid)
        session.add(machine)
    else:
        # Re-enrollment of a known identity: a changed hardware anchor is a
        # guard-rail signal (reinstall vs token theft / clone).
        suspicious = fingerprint.is_suspicious_change(
            machine, smbios_uuid=fp.smbios_uuid, tpm_ek_hash=fp.tpm_ek_hash
        )

    # Another active identity sharing the same SMBIOS anchor → re-image of the
    # same physical box or a clone → flag for manual reconciliation (merge).
    if fp.smbios_uuid:
        other = await session.exec(
            select(Machine.id)
            .where(Machine.smbios_uuid == fp.smbios_uuid)
            .where(Machine.machine_uuid != payload.machine_uuid)
        )
        if other.first() is not None:
            suspicious = True

    machine.hostname = payload.hostname
    machine.domain = payload.domain
    machine.os_version = payload.os_version
    machine.agent_version = payload.agent_version
    fingerprint.store_fingerprint(
        machine,
        machine_guid=fp.machine_guid,
        smbios_uuid=fp.smbios_uuid,
        tpm_ek_hash=fp.tpm_ek_hash,
    )
    if suspicious:
        machine.needs_verification = True
    machine.token_hash = security.hash_token(token)
    machine.token_revoked = False
    machine.updated_at = utcnow()

    await session.commit()
    await session.refresh(machine)
    return EnrollResponse(machine_id=machine.id, token=token)


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    payload: HeartbeatRequest, machine: CurrentMachine, session: SessionDep
) -> HeartbeatResponse:
    """Upsert Defender state, then return this machine's pending commands."""
    if payload.hostname is not None:
        machine.hostname = payload.hostname
    if payload.domain is not None:
        machine.domain = payload.domain
    if payload.ip_address is not None:
        # Conditional like the other attributes: an agent that could not read an
        # address omits the field, and the last known one is better than none —
        # it is dated by last_seen anyway.
        machine.ip_address = payload.ip_address
    if payload.mac_address is not None:
        # Conditional for the same reason, and it matters more here: this is the
        # only way to wake the poste once it is off, so a heartbeat that could
        # not read the adapter must never erase the address that still can.
        machine.mac_address = payload.mac_address
    if payload.ip_prefix_length is not None:
        # The mask that goes with the address above. Conditional again: an agent
        # too old to report it, or one whose adapter did not expose it, leaves
        # the last known mask in place rather than sending the wake back to the
        # server's configured default.
        machine.ip_prefix_length = payload.ip_prefix_length
    if payload.os_version is not None:
        machine.os_version = payload.os_version
    if payload.agent_version is not None:
        machine.agent_version = payload.agent_version

    if payload.defender is not None:
        d = payload.defender
        machine.rtp_enabled = d.rtp_enabled
        machine.av_enabled = d.av_enabled
        machine.signature_version = d.signature_version
        machine.signature_last_updated = d.signature_last_updated
        machine.signature_age_days = d.signature_age_days
        machine.last_quick_scan = d.last_quick_scan
        machine.last_full_scan = d.last_full_scan
        machine.running_mode = d.running_mode

    if payload.av_product is not None:
        # Straight assignment, like the session block below: an antivirus being
        # uninstalled must *clear* the name stored earlier, or the console would
        # keep crediting a product that is no longer there. The empty name the
        # agent then sends is what carries that.
        av = payload.av_product
        machine.av_product_name = av.name
        machine.av_product_enabled = av.enabled
        machine.av_product_signatures_up_to_date = av.signatures_up_to_date
        machine.av_product_is_defender = av.is_defender

    if payload.defender is not None or payload.av_product is not None:
        # Recomputed whenever *either* source moved: a machine whose third-party
        # antivirus was just uninstalled changes state without its Defender block
        # changing at all, and the reverse holds too.
        machine.is_up_to_date = compute_is_up_to_date(
            av_enabled=machine.av_enabled,
            rtp_enabled=machine.rtp_enabled,
            signature_age_days=machine.signature_age_days,
            max_age_days=settings.SIGNATURE_MAX_AGE_DAYS,
            av_product_enabled=machine.av_product_enabled,
            av_product_signatures_up_to_date=machine.av_product_signatures_up_to_date,
            av_product_is_defender=machine.av_product_is_defender,
        )

    if payload.session is not None:
        # `s`, not `session`: `session` is the database session in this scope.
        s = payload.session
        machine.session_user_present = s.user_present
        # Straight assignment, like the defender block above: a logoff, or the
        # privacy toggle being turned off, must *clear* a name stored earlier or
        # the console would keep displaying it forever.
        machine.session_username = s.username
        machine.session_state = s.state
        machine.session_is_remote = s.is_remote

    if payload.windows_update is not None:
        wu = payload.windows_update
        machine.wu_reboot_required = wu.reboot_required
        machine.wu_last_search = wu.last_search_time
        machine.wu_last_install = wu.last_install_time
        # Counted from the reported list rather than trusted from a field of its
        # own: the badge in the machine list and the table on the detail page
        # then cannot disagree about the same machine.
        machine.wu_pending_count = await replace_pending(
            session, machine.id, wu.pending
        )

    if payload.fingerprint is not None:
        fp = payload.fingerprint
        if fingerprint.is_suspicious_change(
            machine, smbios_uuid=fp.smbios_uuid, tpm_ek_hash=fp.tpm_ek_hash
        ):
            machine.needs_verification = True
        fingerprint.store_fingerprint(
            machine,
            machine_guid=fp.machine_guid,
            smbios_uuid=fp.smbios_uuid,
            tpm_ek_hash=fp.tpm_ek_hash,
        )

    machine.last_seen = utcnow()
    machine.updated_at = utcnow()

    if payload.threats:
        await upsert_threats(session, machine.id, payload.threats)

    # Persist the EXPIRED status for this machine's stale pending commands so a
    # long-offline host doesn't run a scan requested weeks ago (plan §2.8).
    await command_crud.mark_expired(session, machine_id=machine.id)

    rows = await session.exec(
        select(Command)
        .where(Command.machine_id == machine.id)
        .where(Command.status == CommandStatus.PENDING)
        .where(Command.expires_at > utcnow())
    )
    pending = rows.all()
    for cmd in pending:
        cmd.status = CommandStatus.DELIVERED
        cmd.delivered_at = utcnow()

    # Build the payload before commit: expire_on_commit would otherwise trigger
    # a sync refresh on attribute access — MissingGreenlet under asyncio.
    commands = [CommandOut(id=c.id, type=c.type) for c in pending]
    await session.commit()
    return HeartbeatResponse(commands=commands)


@router.post("/commands/{command_id}/result")
async def command_result(
    command_id: uuid.UUID,
    payload: CommandResult,
    machine: CurrentMachine,
    session: SessionDep,
) -> dict[str, str]:
    """Record the result — or the start — of a command executed by the agent."""
    cmd = await session.get(Command, command_id)
    if cmd is None or cmd.machine_id != machine.id:
        return {"status": "ignored"}

    if payload.status == CommandStatus.RUNNING:
        # Progress ping from a long command (sfc, dism, chkdsk): it says "I have
        # started", not "I am done", so the command is *not* closed — no
        # finished_at, and the output/error columns are left alone for the final
        # verdict to fill. Guarded against arriving late: a duplicate delivery
        # must never reopen a command that already has one.
        if cmd.status in TERMINAL_STATUSES:
            return {"status": "ignored"}
        cmd.status = CommandStatus.RUNNING
        cmd.started_at = utcnow()
        await session.commit()
        return {"status": "ok"}

    cmd.status = payload.status
    cmd.result_output = payload.output
    cmd.error = payload.error
    cmd.finished_at = utcnow()
    await session.commit()
    return {"status": "ok"}
