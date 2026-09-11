"""Agent-facing endpoints: enroll, heartbeat (+ command pickup), command result."""

import logging
import uuid
from datetime import datetime
from ipaddress import ip_address

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import CurrentMachine, SessionDep, verify_enrollment_secret
from app.core import ratelimit, security
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command.models import (
    AGENT_REPORTABLE_STATUSES,
    TERMINAL_STATUSES,
    Command,
    CommandStatus,
    CommandType,
)
from app.features.inventory.crud import apply_inventory
from app.features.inventory.schemas import InventoryReport
from app.features.machine import fingerprint
from app.features.machine.models import Machine
from app.features.machine.status import compute_is_up_to_date
from app.features.notification import threat_alert
from app.features.threat.crud import NewDetection, upsert_threats
from app.features.threat.schemas import ThreatReport
from app.features.windows_update.crud import replace_pending
from app.features.windows_update.schemas import WUStateReport
from app.features.wol import relay as wol_relay
from app.features.wol.packet import normalize_mac

security_log = logging.getLogger("app.security")

router = APIRouter(prefix="/agent", tags=["agent"])


# --- Schemas ---------------------------------------------------------------


class Fingerprint(BaseModel):
    """Identity fingerprint components reported by the agent."""

    machine_guid: str | None = None
    smbios_uuid: str | None = None
    tpm_ek_hash: str | None = None


# Bounds the site name that reaches the column, the filter dropdown and the
# relay's equality test. A site is a few words; this leaves room for a long
# one while keeping a value a configuration file controls from growing without
# limit.
LOCATION_MAX = 120


def clean_location(value: str | None) -> str | None:
    """Trim and bound the site name; "" becomes None — never 422.

    Same trade-off as the other reported strings: this rides in the same
    request as the Defender state and the command pickup, and a value we
    dislike costs the location alone. The empty string maps to None on
    purpose: it is what an agent sends when its configuration names no site,
    and "no site" is NULL, not a blank the filter would list as a site.
    """
    if value is None:
        return None
    cleaned = value.strip()[:LOCATION_MAX]
    return cleaned or None


class EnrollRequest(BaseModel):
    """First-contact payload (authenticated by X-Enrollment-Secret header)."""

    machine_uuid: str
    hostname: str | None = None
    domain: str | None = None
    # Absent from an agent older than the field; "" from one whose
    # configuration names no site. Only the first leaves the stored value
    # alone — see ``clean_location`` and the heartbeat.
    location: str | None = None
    os_version: str | None = None
    agent_version: str | None = None
    fingerprint: Fingerprint | None = None

    @field_validator("location")
    @classmethod
    def _clean_location(cls, value: str | None) -> str | None:
        return clean_location(value)


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
    # ``location_reported`` below tells "absent" from "sent empty": the
    # validator folds "" into None, and an agent that *cleared* its site must
    # still clear the stored one where an older agent must not.
    location: str | None = None
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
    # Rarer still than the block above: the agent collects this once a day and
    # attaches it only when its own hash of the result changed, so a stable
    # poste sends it once and then never again. Absent leaves everything stored
    # alone, exactly like an absent Defender block.
    inventory: InventoryReport | None = None
    fingerprint: Fingerprint | None = None
    threats: list[ThreatReport] = []

    @field_validator("location")
    @classmethod
    def _clean_location(cls, value: str | None) -> str | None:
        return clean_location(value)

    @property
    def location_reported(self) -> bool:
        """Whether the agent said anything about its site at all."""
        return "location" in self.model_fields_set

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
    """A pending command handed to the agent.

    ``target_mac`` is the one argument the protocol carries, and it travels on
    one type only: a ``wake_on_lan`` handed to this agent as a *relay* names
    the poste to wake. Absent on everything else, where a bare type name is
    the whole security model (``CommandType``).
    """

    id: uuid.UUID
    type: str
    target_mac: str | None = None


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
    # The limiter runs first: a brute force of the secret must hit the 429
    # wall, not a free constant-time comparison oracle.
    dependencies=[
        Depends(ratelimit.rate_limit(ratelimit.enroll_limiter, "agent.enroll")),
        Depends(verify_enrollment_secret),
    ],
)
async def enroll(
    request: Request, payload: EnrollRequest, session: SessionDep
) -> EnrollResponse:
    """Register a machine (trust on first use) and emit its token once.

    Idempotent on machine_uuid: re-enrollment rotates the token. A known
    machine_uuid re-enrolling is a guard-rail signal (reinstall vs token theft),
    and a *revoked* machine is refused outright: the revocation is lifted from
    the console (allow-reenroll), never by the fleet-wide secret — otherwise
    anyone holding that secret could undo the kill-switch.
    """
    result = await session.exec(
        select(Machine).where(Machine.machine_uuid == payload.machine_uuid)
    )
    machine = result.one_or_none()
    fp = payload.fingerprint or Fingerprint()

    token = security.generate_token()
    suspicious = False
    is_new = machine is None
    if machine is None:
        machine = Machine(machine_uuid=payload.machine_uuid)
        session.add(machine)
    else:
        if machine.token_revoked:
            security_log.warning(
                "enroll refused for revoked machine %s from %s",
                payload.machine_uuid,
                client_ip(request),
            )
            raise AppError(
                code=ErrorCode.MACHINE_ENROLLMENT_REVOKED,
                status_code=403,
                message="Machine token was revoked; an administrator must "
                "allow re-enrollment from the console",
            )
        # Re-enrollment of a known identity: a changed hardware anchor is a
        # guard-rail signal (reinstall vs token theft / clone).
        suspicious = fingerprint.is_suspicious_change(
            machine, smbios_uuid=fp.smbios_uuid, tpm_ek_hash=fp.tpm_ek_hash
        )
        # A missing anchor is as suspicious as a changed one — omitting the
        # field is the cheapest way around the comparison above, and an agent
        # that could read the anchor once can read it still.
        if fingerprint.trustworthy_smbios_uuid(
            machine.smbios_uuid
        ) and not fingerprint.trustworthy_smbios_uuid(fp.smbios_uuid):
            suspicious = True

    # Another active identity sharing the same SMBIOS anchor → re-image of the
    # same physical box or a clone → flag for manual reconciliation (merge).
    # Only for an anchor that identifies one machine: a firmware constant shared
    # by every unit of a batch would otherwise flag the whole batch, and the flag
    # is what puts the "à vérifier" banner on a poste that is perfectly fine.
    anchor = fingerprint.trustworthy_smbios_uuid(fp.smbios_uuid)
    if anchor:
        other = await session.exec(
            select(Machine.id)
            .where(func.lower(Machine.smbios_uuid) == anchor)
            .where(Machine.machine_uuid != payload.machine_uuid)
        )
        if other.first() is not None:
            suspicious = True

    machine.hostname = payload.hostname
    machine.domain = payload.domain
    if "location" in payload.model_fields_set:
        # Straight assignment when the agent spoke: an enrollment is a fresh
        # start, and "" (now None) means "no site". An agent too old to send
        # the field leaves whatever an administrator may rely on.
        machine.location = payload.location
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
    machine.updated_at = utcnow()

    # Every enrollment is a security event: a token was minted. The log line is
    # what ties a rogue enrollment to its source address after the fact.
    security_log.log(
        logging.WARNING if suspicious else logging.INFO,
        "%s of machine %s from %s%s",
        "enrollment" if is_new else "re-enrollment",
        payload.machine_uuid,
        client_ip(request),
        " (suspicious fingerprint, flagged for verification)" if suspicious else "",
    )

    await session.commit()
    await session.refresh(machine)
    return EnrollResponse(machine_id=machine.id, token=token)


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    payload: HeartbeatRequest,
    machine: CurrentMachine,
    session: SessionDep,
) -> HeartbeatResponse:
    """Upsert Defender state, then return this machine's pending commands."""
    if payload.hostname is not None:
        machine.hostname = payload.hostname
    if payload.domain is not None:
        machine.domain = payload.domain
    if payload.location_reported:
        # On presence, not on value: the agent sends the field on every
        # heartbeat, empty when its configuration names no site, and empty has
        # to *clear* — a poste moved to another building, or whose GPO dropped
        # the setting, must not stay filed under the old one. Only an agent
        # that predates the field says nothing, and leaves it alone.
        machine.location = payload.location
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

    if payload.inventory is not None:
        inv = payload.inventory
        # Short-circuit on an unchanged hash: an agent that restarted has
        # forgotten sending this and re-sends it, and there is nothing to do but
        # note that the picture is still current. Skipping saves seven set
        # replacements — a few hundred upserts on a well-stocked poste — for a
        # machine already described correctly.
        #
        # Guarded on a non-empty hash: an agent that reports none has no claim
        # to make, and "" == "" would silently skip every inventory it sends.
        if inv.hash and inv.hash == machine.inventory_hash:
            machine.inventory_last_seen = utcnow()
        else:
            await apply_inventory(session, machine, inv)

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

    # Detections nobody had seen before, for the immediate-alert cadence. Taken
    # here and mailed after the response: the agent is waiting on this request,
    # and Mailgun is not on its critical path.
    new_detections: list[NewDetection] = []
    if payload.threats:
        result = await upsert_threats(session, machine.id, payload.threats)
        new_detections = result.new_detections

    # Persist the EXPIRED status for this machine's stale pending commands so a
    # long-offline host doesn't run a scan requested weeks ago (plan §2.8).
    await command_crud.mark_expired(session, machine_id=machine.id)

    now = utcnow()
    rows = await session.exec(
        select(Command)
        .where(Command.machine_id == machine.id)
        .where(Command.status == CommandStatus.PENDING)
        .where(Command.expires_at > now)
        # Never a wake: the machine it targets is the one this agent runs on,
        # and an agent cannot wake itself. A pending wake on *this* machine is
        # one waiting for a relay — or, since this poste is evidently on, one
        # that has just succeeded (below).
        .where(col(Command.type) != CommandType.WAKE_ON_LAN.value)
    )
    pending = rows.all()
    for cmd in pending:
        cmd.status = CommandStatus.DELIVERED
        cmd.delivered_at = now

    # Build the payload before commit: expire_on_commit would otherwise trigger
    # a sync refresh on attribute access — MissingGreenlet under asyncio.
    commands = [CommandOut(id=c.id, type=c.type) for c in pending]

    if settings.WOL_RELAY_ENABLED:
        # This poste is awake, whatever woke it: the wakes queued for it are
        # done. Only in relay mode do such rows exist — the server-side path
        # writes its rows closed — so the default path pays no extra query.
        await wol_relay.close_wakes_for_awake_machine(session, machine, now)
        # And it may be the poste another one has been waiting for: the first
        # eligible agent to contact the server takes the wake, MAC included.
        for claimed in await wol_relay.claim_wakes(session, machine, now):
            commands.append(
                CommandOut(
                    id=claimed.command.id,
                    type=claimed.command.type,
                    target_mac=claimed.target_mac,
                )
            )
    if new_detections:
        # Queued in the outbox inside this same transaction: the alert commits
        # with the detections it names, or not at all. The worker sends it with
        # retries — Mailgun down never fails a heartbeat, and never loses the
        # mail either.
        await threat_alert.queue_threat_alert(
            session, threat_alert.MachineContext.of(machine), new_detections
        )
    await session.commit()
    return HeartbeatResponse(commands=commands)


@router.post("/commands/{command_id}/result")
async def command_result(
    command_id: uuid.UUID,
    payload: CommandResult,
    machine: CurrentMachine,
    session: SessionDep,
) -> dict[str, str]:
    """Record the result — or the start — of a command executed by the agent.

    The reporter is the command's own machine, or — for a relayed wake — the
    poste that claimed it: the target is off and cannot answer for itself.
    """
    cmd = await session.get(Command, command_id)
    if cmd is None:
        return {"status": "ignored"}
    relayed = cmd.relay_machine_id is not None and cmd.relay_machine_id == machine.id
    if cmd.machine_id != machine.id and not relayed:
        return {"status": "ignored"}
    if relayed and cmd.status in TERMINAL_STATUSES:
        # The target came back on its own before the relay reported — its
        # heartbeat closed the row with the one acknowledgement a wake can
        # have, and "packet emitted" is not news next to "poste revenu".
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
    if relayed:
        # Signed by the relay: the row sits on the target's history, where a
        # verdict that does not say which poste emitted would read as if the
        # sleeping machine had written it.
        who = wol_relay.relay_label(machine)
        if cmd.result_output:
            cmd.result_output = f"Relayé par {who} — {cmd.result_output}"
        if cmd.error:
            cmd.error = f"Relayé par {who} — {cmd.error}"
    cmd.finished_at = utcnow()
    await session.commit()
    return {"status": "ok"}
