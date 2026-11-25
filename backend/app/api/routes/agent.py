"""Agent-facing endpoints: enroll, heartbeat (+ command pickup), command result."""

import base64
import logging
import re
import uuid
from datetime import datetime, timedelta
from ipaddress import ip_address
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import col, select
from starlette.types import Receive, Send
from starlette.types import Scope as ASGIScope

from app.api.deps import CurrentMachine, SessionDep, verify_enrollment_secret
from app.core import ratelimit, security
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.command import crud as command_crud
from app.features.command import texts as command_texts
from app.features.command.models import (
    AGENT_REPORTABLE_STATUSES,
    PACKAGE_COMMAND_TYPES,
    TERMINAL_STATUSES,
    Command,
    CommandStatus,
    CommandType,
)
from app.features.directory import crud as directory_crud
from app.features.inventory import budget as software_budget
from app.features.inventory.crud import apply_inventory
from app.features.inventory.schemas import InventoryReport
from app.features.machine import fingerprint, token_rotation
from app.features.machine.models import Machine
from app.features.machine.status import compute_is_up_to_date
from app.features.notification import threat_alert
from app.features.package import crud as package_crud
from app.features.package import storage as package_storage
from app.features.package.models import Package, PackageFile
from app.features.room import crud as room_crud
from app.features.setting import crud as setting_crud
from app.features.threat.crud import NewDetection, upsert_threats
from app.features.threat.schemas import ThreatReport
from app.features.usage import crud as usage_crud
from app.features.usage.accounting import credit_for_gap
from app.features.webhook import emit as webhook_emit
from app.features.windows_update.crud import replace_pending
from app.features.windows_update.schemas import WUStateReport
from app.features.wol import relay as wol_relay
from app.features.wol.packet import normalize_mac

security_log = logging.getLogger("app.security")
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# --- Schemas ---------------------------------------------------------------


# Bounds on the strings every heartbeat and enrollment carries. These columns
# are unbounded TEXT, so nothing below the API stops a broken or hostile agent
# from writing megabytes into the machine row — and from there into the list,
# the export and the digest. Each limit leaves an order of magnitude over what
# Windows reports. Truncated, never 422: the same trade-off as the location
# and the antivirus name — one oversized field must not cost the Defender
# state and the command pickup riding in the same request.
NAME_MAX = 255  # hostname, domain: a DNS name stops at 253
TEXT_MAX = 200  # versions, fingerprint components, Defender and session strings
# The one string that is *rejected* rather than truncated: it is the machine's
# identity, and two long identifiers cut to the same prefix would merge two
# postes into one row. Real ones are a 36-character UUID.
MACHINE_UUID_MAX = 200
# Defender keeps its detection history for weeks; a poste reporting more than
# this is not describing an infection, it is flooding. The cap also keeps the
# upsert's single INSERT well under PostgreSQL's 65 535 bind parameters (nine
# per row), past which the whole heartbeat would fail.
MAX_THREATS = 1000


def bound_text(value: str | None, limit: int = TEXT_MAX) -> str | None:
    """Cap a reported string at ``limit`` characters — never 422.

    Deliberately no strip: these values are compared as reported (hostname
    against the stored one, fingerprint components against each other), and a
    cut must not change a value that already fits.
    """
    if value is None:
        return None
    return value[:limit]


class Fingerprint(BaseModel):
    """Identity fingerprint components reported by the agent."""

    machine_guid: str | None = None
    smbios_uuid: str | None = None
    tpm_ek_hash: str | None = None

    @field_validator("machine_guid", "smbios_uuid", "tpm_ek_hash")
    @classmethod
    def _bound(cls, value: str | None) -> str | None:
        return bound_text(value)


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

    machine_uuid: str = Field(min_length=1, max_length=MACHINE_UUID_MAX)
    hostname: str | None = None
    domain: str | None = None
    # Absent from an agent older than the field; "" from one whose
    # configuration names no site. Only the first leaves the stored value
    # alone — see ``clean_location`` and the heartbeat.
    location: str | None = None
    os_version: str | None = None
    agent_version: str | None = None
    fingerprint: Fingerprint | None = None

    @field_validator("machine_uuid", mode="before")
    @classmethod
    def _strip_uuid(cls, value: object) -> object:
        """Trim the identity before its bounds are checked: " X " and "X" are
        one poste, and a blank one is no identity at all (422)."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("location")
    @classmethod
    def _clean_location(cls, value: str | None) -> str | None:
        return clean_location(value)

    @field_validator("hostname", "domain")
    @classmethod
    def _bound_name(cls, value: str | None) -> str | None:
        return bound_text(value, NAME_MAX)

    @field_validator("os_version", "agent_version")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return bound_text(value)


class EnrollResponse(BaseModel):
    """Returned once: the per-machine bearer token."""

    machine_id: uuid.UUID
    token: str


# Bounds the third-party product name that reaches the column and the console.
# Real names run to ~40 characters ("Bitdefender Endpoint Security Tools"); this
# leaves ample room while keeping a vendor string we do not control from growing
# without limit.
AV_PRODUCT_NAME_MAX = 120
# A signature age is a number of days since a date Defender holds: a century
# covers every clock a poste can have, and anything beyond — or negative — is
# a broken or forged report. The column is a 32-bit integer the console adds
# days to on every read (``status.signature_age_expr``).
SIGNATURE_AGE_MAX_DAYS = 36500


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

    @field_validator("signature_version", "running_mode")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return bound_text(value)

    @field_validator("signature_age_days")
    @classmethod
    def _bound_age(cls, value: int | None) -> int | None:
        """Keep an age that can be one, store anything else as unknown.

        Never 422, like the fields around it: the flags of this block, the
        threats and the command pickup ride the same heartbeat. Unknown is
        also the honest reading — and « not up to date », which is what an
        age nobody can believe should count as.
        """
        if value is None or not 0 <= value <= SIGNATURE_AGE_MAX_DAYS:
            return None
        return value


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

    @field_validator("username", "state")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return bound_text(value, NAME_MAX)


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
    # Sent by an agent able to store a token handed back on a heartbeat. False
    # — the default, and what every older agent says by saying nothing — means
    # never offering one: it would be ignored, and the agent kept on the old
    # token anyway (``features/machine/token_rotation.py``).
    supports_token_rotation: bool = False

    @field_validator("location")
    @classmethod
    def _clean_location(cls, value: str | None) -> str | None:
        return clean_location(value)

    @field_validator("hostname", "domain")
    @classmethod
    def _bound_name(cls, value: str | None) -> str | None:
        return bound_text(value, NAME_MAX)

    @field_validator("os_version", "agent_version")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return bound_text(value)

    @field_validator("threats", mode="before")
    @classmethod
    def _cap_threats(cls, value: object) -> object:
        """Drop the excess *before* validating it.

        Before rather than after, unlike the inventory caps: a flood is cut
        without paying to parse each of its entries first. Anything that is
        not a list is left to the normal validation to reject.
        """
        if isinstance(value, list) and len(value) > MAX_THREATS:
            security_log.warning(
                "heartbeat: %d threats reported, keeping the first %d",
                len(value),
                MAX_THREATS,
            )
            return value[:MAX_THREATS]
        return value

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
    # The second argument the protocol carries, on the two deployment types
    # only: the package, whole. What the agent may do with it is decided on
    # the poste, from trust anchors its GPO set (plan-deploiement-logiciel §4).
    package: "PackageDelivery | None" = None
    # The third, on ``directory_read`` only: the computer names to read
    # (plan-lecture-annuaire §3.2).
    directory: "DirectoryRequest | None" = None


class DirectoryRequest(BaseModel):
    names: list[str]


class PackageFileDelivery(BaseModel):
    name: str
    sha256: str
    size: int


class PackageDelivery(BaseModel):
    """A package as the agent receives it. ``manifest``, ``signature`` and
    ``certificate`` are base64: the signature covers the manifest's exact
    bytes, which a JSON string could not carry through unchanged."""

    id: uuid.UUID
    kind: str
    name: str
    winget_id: str | None = None
    winget_version: str | None = None
    manifest: str | None = None
    signature: str | None = None
    signature_algorithm: str | None = None
    certificate: str | None = None
    files: list[PackageFileDelivery] = []


CommandOut.model_rebuild()


async def _package_deliveries(
    session: SessionDep, package_ids: set[uuid.UUID]
) -> tuple[dict[uuid.UUID, PackageDelivery], dict[uuid.UUID, str], set[uuid.UUID]]:
    """The packages as handed to the agent, the fingerprint of each as it
    stands (``package_crud.fingerprint``), and those retired meanwhile."""
    if not package_ids:
        return {}, {}, set()
    packages = (
        await session.exec(select(Package).where(col(Package.id).in_(package_ids)))
    ).all()
    files = await package_crud.files_of_many(session, [p.id for p in packages])

    def b64(value: bytes | None) -> str | None:
        return base64.b64encode(value).decode("ascii") if value is not None else None

    digests = {p.id: package_crud.fingerprint(p, files[p.id]) for p in packages}
    retired = {p.id for p in packages if p.retired_at is not None}
    deliveries = {
        p.id: PackageDelivery(
            id=p.id,
            kind=p.kind,
            name=p.name,
            winget_id=p.winget_id,
            winget_version=p.winget_version,
            manifest=b64(p.manifest),
            signature=b64(p.signature),
            signature_algorithm=p.signature_algorithm,
            certificate=b64(p.signer_certificate),
            files=[
                PackageFileDelivery(name=f.name, sha256=f.sha256, size=f.size)
                for f in files[p.id]
            ],
        )
        for p in packages
    }
    return deliveries, digests, retired


# How long after a software list was cut short the server asks the agent to
# send it again, at the earliest.
RESEND_INVENTORY_AFTER = timedelta(hours=1)


class HeartbeatResponse(BaseModel):
    """Heartbeat ack carrying the machine's pending commands.

    ``new_token`` is set when the token this heartbeat used is due for
    renewal: the agent stores it and authenticates with it from the next
    request on, which retires the old one. Null on every other heartbeat.

    ``resend_inventory`` asks the agent to send its software inventory again
    on its next heartbeat: the list the server holds was cut short by the
    catalogue budget, and the agent would otherwise only send it again at a
    restart or a change. An agent that predates the field ignores it.
    """

    commands: list[CommandOut]
    new_token: str | None = None
    resend_inventory: bool = False


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
    # What the console words the agent's own message from (plan console
    # bilingue, I5): the ``error`` of a failed result, the ``output`` of a
    # succeeded one. Optional — an older agent sends neither, and its text
    # reads as before — and dropped if malformed (``texts.clean_message``),
    # the text staying. Typed loosely on purpose: a value of the wrong shape
    # is dropped, never a reason to refuse the verdict.
    message_code: Any = None
    message_params: Any = None

    @model_validator(mode="after")
    def _clean_message(self) -> "CommandResult":
        code, params = command_texts.clean_message(
            self.message_code, self.message_params
        )
        if code is None and self.message_code is not None:
            logger.info("agent result: message code dropped (malformed)")
        self.message_code, self.message_params = code, params
        return self

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
        return value[:RESULT_TEXT_MAX] + command_texts.TRUNCATED_NOTE


# --- Routes ----------------------------------------------------------------

# How long after an enrollment its token may be replaced without approval,
# provided it was never used: the window in which an agent whose 200 answer
# was lost retries (it backs off for minutes, not hours). The one case where
# the fleet secret replaces a live token, documented as such in DEPLOYMENT.md
# (« Enrôlement : approbation et rotation du secret »).
UNUSED_TOKEN_RETRY_WINDOW = timedelta(hours=1)


async def _locked_machine(session: SessionDep, machine_uuid: str) -> Machine | None:
    """The machine of this identity, row-locked until the enrollment commits:
    two enrollments of one poste are served one after the other."""
    result = await session.exec(
        select(Machine)
        .where(col(Machine.machine_uuid) == machine_uuid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.one_or_none()


def _same_fingerprint(machine: Machine, fp: Fingerprint) -> bool:
    """Whether the enrollment reports exactly the fingerprint stored — every
    component, a missing one included: omitting a component is the cheapest
    way around a comparison."""
    return (
        fp.machine_guid == machine.machine_guid
        and fp.smbios_uuid == machine.smbios_uuid
        and fp.tpm_ek_hash == machine.tpm_ek_hash
    )


def _unused_enrollment_retry(machine: Machine, fp: Fingerprint) -> bool:
    """Whether this enrollment is the same agent asking again because the
    answer to its previous one never reached it.

    The token that enrollment minted has then never authenticated a request
    of any kind: ``enrollment_token_unused``, set below when the token is
    minted and cleared by the authentication dependency
    (``token_rotation.machine_for_token``). A stored fact, not a comparison
    of ``last_seen`` with ``token_issued_at``: a rotated token first used on
    a command verdict restarts the second without moving the first, and an
    established poste then read as never seen. No rotation offered either —
    an offer exists only because a heartbeat was accepted. Only within
    ``UNUSED_TOKEN_RETRY_WINDOW`` of the enrollment, and only with the very
    fingerprint it stored — anything else is the reinstall-or-impostor case
    the approval exists for.
    """
    if machine.token_hash is None or machine.pending_token_hash is not None:
        return False
    if not machine.enrollment_token_unused:
        return False
    if utcnow() - machine.token_issued_at > UNUSED_TOKEN_RETRY_WINDOW:
        return False
    return _same_fingerprint(machine, fp)


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

    A known machine_uuid gets a new token only when it holds none — first
    contact, or after an administrator's allow-reenroll. One that still holds a
    live token is held for approval (``ENROLLMENT_REENROLL_REQUIRES_APPROVAL``),
    and a *revoked* one is refused outright: both are lifted from the console,
    never by the fleet-wide secret — otherwise anyone holding that secret could
    take over a poste's identity, or undo the kill-switch.
    """
    machine = await _locked_machine(session, payload.machine_uuid)
    fp = payload.fingerprint or Fingerprint()

    token = security.generate_token()
    suspicious = False
    is_new = machine is None
    if machine is None:
        candidate = Machine(machine_uuid=payload.machine_uuid)
        try:
            # In a savepoint: the same new poste enrolling twice at once (an
            # agent retrying while its first attempt is still being served)
            # meets the unique identity here, and must not cost a 500.
            async with session.begin_nested():
                session.add(candidate)
        except IntegrityError:
            # The other enrollment committed first: this one is now a
            # re-enrollment of that poste, under the same rules.
            machine = await _locked_machine(session, payload.machine_uuid)
            if machine is None:
                raise AppError(
                    code=ErrorCode.HTTP_ERROR,
                    status_code=409,
                    message="Concurrent enrollment of this machine; retry",
                ) from None
            is_new = False
        else:
            machine = candidate
    retry = False
    if not is_new:
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
        retry = _unused_enrollment_retry(machine, fp)
        if (
            machine.token_hash is not None
            and settings.ENROLLMENT_REENROLL_REQUIRES_APPROVAL
            and not retry
        ):
            # A live token already exists for this identity. Its own agent never
            # asks for another while it holds one (it re-enrolls only after
            # losing it), so this is either a reinstalled poste or someone
            # presenting the fleet secret under a stolen machine_uuid — the
            # secret is readable on every poste. Minting here would hand the
            # identity over and lock the real poste out; the request waits for
            # an administrator instead, and the live token keeps working.
            ip = client_ip(request)
            # One audit line per request, not per retry: an agent waiting
            # for approval asks again every few minutes (audit B33). A new
            # line when the asking address changes, or after a day.
            already = (
                machine.reenroll_requested_at is not None
                and machine.reenroll_requested_ip == ip
                and utcnow() - machine.reenroll_requested_at < timedelta(hours=24)
            )
            if not already:
                machine.reenroll_requested_at = utcnow()
                machine.reenroll_requested_ip = ip
                audit.record(
                    session,
                    actor="agent",
                    action="machine.reenroll_requested",
                    resource_type="machine",
                    resource_id=str(machine.id),
                    details={
                        "hostname": payload.hostname,
                        "machine_uuid": payload.machine_uuid,
                    },
                )
                await session.commit()
            security_log.warning(
                "re-enrollment of %s from %s held for approval (live token exists)",
                payload.machine_uuid,
                ip,
            )
            raise AppError(
                code=ErrorCode.MACHINE_ENROLLMENT_APPROVAL_REQUIRED,
                status_code=403,
                message="This machine is already enrolled; an administrator must "
                "approve the re-enrollment from the console",
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
    machine.token_issued_at = utcnow()
    # A re-enrolled poste is no longer the one designated to read the
    # directory (plan-lecture-annuaire §3.2), nor the one an object was
    # matched to: it is matched again at the next reading.
    if machine.directory_reader:
        await directory_crud.undesignate(session, machine)
        audit.record(
            session,
            actor=directory_crud.ACTOR,
            action="directory.reader_drop",
            resource_type="machine",
            resource_id=str(machine.id),
            details={"hostname": machine.hostname, "cause": "reenrolled"},
        )
    if machine.directory_object_guid is not None:
        directory_crud.clear_match(machine)
        machine.directory_status = None
    # Until the agent's first authenticated request proves the answer below
    # reached it (``_unused_enrollment_retry``).
    machine.enrollment_token_unused = True
    machine.reenroll_requested_at = None
    machine.reenroll_requested_ip = None
    # A rotation the previous agent left half-done must not leave a second
    # token valid next to the one minted here.
    token_rotation.reset_rotation(machine)
    machine.updated_at = utcnow()

    if retry:
        # The unused token dies here, replaced above: one live token per poste.
        audit.record(
            session,
            actor="agent",
            action="machine.enrollment_retried",
            resource_type="machine",
            resource_id=str(machine.id),
            details={
                "hostname": payload.hostname,
                "machine_uuid": payload.machine_uuid,
                "ip": client_ip(request),
            },
        )
    # Every enrollment is a security event: a token was minted. The log line is
    # what ties a rogue enrollment to its source address after the fact.
    security_log.log(
        logging.WARNING if suspicious else logging.INFO,
        "%s of machine %s from %s%s",
        "enrollment"
        if is_new
        else "enrollment retry (unused token replaced)"
        if retry
        else "re-enrollment",
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
    ratelimit.check_account(
        ratelimit.heartbeat_limiter, str(machine.id), "agent.heartbeat"
    )
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
        # What the age above is measured from: it is aged on read
        # (``status.effective_signature_age``).
        machine.signature_reported_at = utcnow()
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
            max_age_days=await setting_crud.signature_max_age_days(session),
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
        if wu.reboot_required and machine.wu_reboot_required_since is None:
            machine.wu_reboot_required_since = utcnow()
        elif not wu.reboot_required:
            machine.wu_reboot_required_since = None
        machine.wu_reboot_required = wu.reboot_required
        machine.wu_last_search = wu.last_search_time
        machine.wu_last_install = wu.last_install_time
        # Counted from the reported list rather than trusted from a field of its
        # own: the badge in the machine list and the table on the detail page
        # then cannot disagree about the same machine.
        machine.wu_pending_count = await replace_pending(
            session, machine.id, wu.pending
        )
        behind = any(
            (u.type or "software") == "software"
            and (u.severity or "").lower() in ("critical", "important")
            for u in wu.pending
        )
        if not behind:
            machine.wu_critical_pending_since = None
        elif machine.wu_critical_pending_since is None:
            machine.wu_critical_pending_since = utcnow()

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
        # The directory block rides the inventory but is not hardware: stored
        # on its own columns, and — in a directory mode — what files the
        # poste into a room. Applied even on an unchanged hash: it is cheap,
        # and a ROOM_SOURCE switched since the last inventory must not wait
        # a day for the poste to move.
        if inv.directory is not None:
            directory = inv.directory
            machine.ad_distinguished_name = directory.distinguished_name
            machine.ad_ou = directory.ou
            machine.ad_ou_dn = directory.ou_dn
            machine.ad_location = directory.ad_location
            if directory_crud.enabled():
                # With the directory read by the server, the agent's word
                # files nothing: it is checked against the reading, and the
                # rooms move when a reading is taken (``directory.reconcile``)
                # — never here, where a move held for an administrator's
                # confirmation would be applied behind their back.
                await directory_crud.refresh_heartbeat_verdict(session, machine)
            else:
                # In a savepoint: whatever the directory says, a placement
                # that fails must not fail the heartbeat — the Defender
                # state, the threats and the commands ride the same request
                # (audit S07).
                try:
                    async with session.begin_nested():
                        await room_crud.place_from_directory(
                            session, machine, settings.ROOM_SOURCE, from_agent=True
                        )
                except SQLAlchemyError:
                    logger.exception(
                        "directory placement failed for machine %s", machine.id
                    )
                    # The rollback of the savepoint may have expired the row:
                    # read it again now, not lazily later (no implicit I/O in
                    # async).
                    await session.refresh(machine)

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

    # Usage: the time since the previous heartbeat, if it was short enough to
    # say the poste stayed on. Read off the *previous* last_seen, so before it
    # is overwritten, and with the same instant that overwrites it — two
    # utcnow() calls would credit a span that is not the one stored.
    seen_at = utcnow()
    await usage_crud.record(
        session,
        machine.id,
        credit_for_gap(machine.last_seen, seen_at, settings.OFFLINE_AFTER_SECONDS),
    )
    machine.last_seen = seen_at
    machine.updated_at = seen_at

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
        # In the order they were queued: the agent runs them in the order
        # received, and « installer les MAJ » then « redémarrer » must not
        # arrive the other way round (audit B28).
        .order_by(col(Command.created_at), col(Command.id))
    )
    pending = rows.all()
    for cmd in pending:
        cmd.status = CommandStatus.DELIVERED
        cmd.delivered_at = now

    # Build the payload before commit: expire_on_commit would otherwise trigger
    # a sync refresh on attribute access — MissingGreenlet under asyncio.
    deliveries, digests, retired = await _package_deliveries(
        session, {c.package_id for c in pending if c.package_id is not None}
    )

    def refusal(c: Command) -> command_texts.Verdict | None:
        """Why a deployment cannot go out: its package was deleted, or it
        changed since the deployment was queued — what was approved is not
        what would run (audit S08) — or, for an installation, it was retired
        meanwhile: retiring says "install this nowhere any more". An
        uninstall of a retired package still goes, as it may be queued."""
        if c.type == CommandType.DIRECTORY_READ:
            return (
                None
                if directory_crud.enabled() and directory_crud.reader_ok(machine)
                else command_texts.directory_not_reader()
            )
        if c.type not in PACKAGE_COMMAND_TYPES:
            return None
        if c.package_id not in deliveries:
            return command_texts.package_deleted()
        if c.type == CommandType.PACKAGE_INSTALL and c.package_id in retired:
            return command_texts.package_retired_after_queue()
        if c.package_digest is not None and c.package_digest != digests[c.package_id]:
            return command_texts.package_changed_after_queue()
        return None

    commands: list[CommandOut] = []
    # A refused deployment held files: they may be the last hold on a file
    # replaced in the package since (audit S09), swept once committed.
    refused_held_files = False
    for c in pending:
        reason = refusal(c)
        if reason is not None:
            c.status = CommandStatus.FAILED
            c.error = reason.text
            c.result_code = reason.code
            c.result_params = reason.params
            c.finished_at = now
            refused_held_files = refused_held_files or bool(c.package_files)
            continue
        commands.append(
            CommandOut(
                id=c.id,
                type=c.type,
                package=deliveries.get(c.package_id) if c.package_id else None,
                directory=(
                    DirectoryRequest(
                        names=await directory_crud.names_for(session, machine)
                    )
                    if c.type == CommandType.DIRECTORY_READ
                    else None
                ),
            )
        )

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
        # And to the webhooks that asked for it (C8), in the same transaction —
        # the same detections as the mail: a first inventory's years of
        # Defender history is not news for a chat channel either.
        fresh = threat_alert.recent_detections(new_detections)
        if fresh:
            await webhook_emit.threats_detected(session, machine, fresh)

    # Last, so that a heartbeat failing on anything above never mints a token
    # it would not return. Committed with the rest: the pending hash exists
    # exactly when the response carrying its token was produced.
    new_token: str | None = None
    if payload.supports_token_rotation and token_rotation.rotation_due(
        machine, seen_at, settings.AGENT_TOKEN_ROTATE_DAYS
    ):
        reoffer = machine.pending_token_hash is not None
        new_token = token_rotation.offer_new_token(machine)
        security_log.info(
            "token rotation %s to machine %s",
            "re-offered" if reoffer else "offered",
            machine.machine_uuid,
        )
    # A list cut short is asked for again only while both budgets have room:
    # a resend that could create nothing would be cut again, for nothing. And
    # not within RESEND_INVENTORY_AFTER of the cut: while the fleet's budget
    # is being drained, every truncated poste would otherwise upload its whole
    # inventory each time a few units come back.
    resend_inventory = (
        machine.software_truncated_at is not None
        and now - machine.software_truncated_at >= RESEND_INVENTORY_AFTER
        and await software_budget.budget_left(session, str(machine.id)) > 0
    )
    await session.commit()
    if refused_held_files:
        await package_crud.sweep_store(session)
    return HeartbeatResponse(
        commands=commands, new_token=new_token, resend_inventory=resend_inventory
    )


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
    # Locked: two deliveries of one verdict (the agent's queue replaying a
    # POST whose answer it missed) are judged one after the other.
    cmd = await session.get(Command, command_id, with_for_update=True)
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
    if cmd.agent_verdict_at is not None:
        # Already closed by its poste's own verdict: a replay must not move
        # « Terminée le », and a second, different verdict must not overwrite
        # the first (a success turned failure, its output erased). A closure
        # the *server* made — expiry, no answer, package refused, merge — is
        # not one of these: the poste's late verdict replaces it below.
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
    # The agent's code, or none: a late verdict replacing a closure the
    # server made replaces its code too.
    cmd.result_code = payload.message_code
    cmd.result_params = payload.message_params
    if relayed:
        # Signed by the relay: the row sits on the target's history, where a
        # verdict that does not say which poste emitted would read as if the
        # sleeping machine had written it.
        who = wol_relay.relay_label(machine)
        if cmd.result_output:
            cmd.result_output = command_texts.relayed(who, cmd.result_output)
        if cmd.error:
            cmd.error = command_texts.relayed(who, cmd.error)
        if cmd.result_code is not None:
            # The console signs the worded verdict the same way.
            cmd.result_params = {**(cmd.result_params or {}), "relay": who}
    cmd.finished_at = utcnow()
    cmd.agent_verdict_at = cmd.finished_at
    held_files = bool(cmd.package_files)
    if cmd.status == CommandStatus.FAILED:
        # The poste the command was for — not the relay that reported it.
        target = machine if not relayed else await session.get(Machine, cmd.machine_id)
        if target is not None:
            await webhook_emit.command_failed(session, target, cmd)
    await session.commit()
    if held_files:
        # The files it held may have been replaced in the package meanwhile:
        # once the last deployment using them is over, they go (audit S09).
        await package_crud.sweep_store(session)
    return {"status": "ok"}


# --- Directory readings (plan-lecture-annuaire.md, mode relay) ---------------

_SID = re.compile(r"^S-1-5-21(-\d{1,10}){3}$")
_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SAM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}\$$")


class DirectoryDomainIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    netbios_name: str = Field(min_length=1, max_length=64)
    sid: str = Field(max_length=100)

    @field_validator("sid")
    @classmethod
    def _sid(cls, value: str) -> str:
        if not _SID.fullmatch(value):
            raise ValueError("not a domain SID")
        return value


class DirectoryObjectIn(BaseModel):
    object_guid: str
    sam_account_name: str
    dns_host_name: str | None = None
    distinguished_name: str | None = None
    location: str | None = None
    disabled: bool = False

    @field_validator("dns_host_name", "location")
    @classmethod
    def _short(cls, value: str | None) -> str | None:
        return bound_text(value)

    @field_validator("distinguished_name")
    @classmethod
    def _dn(cls, value: str | None) -> str | None:
        return bound_text(value, 500)


class DirectorySubnetIn(BaseModel):
    subnet: str = Field(max_length=64)
    site: str = Field(max_length=255)


class DirectoryReadingIn(BaseModel):
    """What a designated reader read of its own domain."""

    domain: DirectoryDomainIn
    objects: list[DirectoryObjectIn] = Field(default_factory=list, max_length=20_000)
    subnets: list[DirectorySubnetIn] = Field(default_factory=list, max_length=5_000)


@router.post("/directory/{command_id}")
async def directory_reading(
    command_id: uuid.UUID,
    payload: DirectoryReadingIn,
    machine: CurrentMachine,
    session: SessionDep,
) -> dict[str, Any]:
    """Take a reader's reading of its domain. The reader then posts its
    command's result as for any command. Refused (409) from a poste that is
    not a reader, for another domain, or for a command not its own."""
    cmd = await session.get(Command, command_id, with_for_update=True)
    if cmd is None:
        raise AppError(code=ErrorCode.DIRECTORY_READING_REFUSED, status_code=409)
    # Objects of a shape no directory hands out are dropped, not a refusal.
    objects = [
        directory_crud.ReadObject(
            object_guid=o.object_guid.lower(),
            sam_account_name=o.sam_account_name.upper(),
            dns_host_name=o.dns_host_name,
            distinguished_name=o.distinguished_name,
            location=o.location,
            disabled=o.disabled,
        )
        for o in payload.objects
        if _GUID.fullmatch(o.object_guid) and _SAM.fullmatch(o.sam_account_name)
    ]
    reading = directory_crud.Reading(
        domain_name=payload.domain.name.strip(),
        netbios_name=payload.domain.netbios_name.strip(),
        domain_sid=payload.domain.sid,
        objects=objects,
        subnets=[s.model_dump() for s in payload.subnets],
    )
    try:
        result = await directory_crud.ingest(session, machine, cmd, reading, utcnow())
    except directory_crud.ReadingRefused as refused:
        security_log.warning(
            "directory reading refused from machine %s: %s",
            machine.machine_uuid,
            refused.code,
        )
        raise AppError(
            code=ErrorCode.DIRECTORY_READING_REFUSED,
            status_code=409,
            details={"reason": refused.code},
        ) from refused
    await session.commit()
    return {
        "status": "ok",
        "verified": result.verified,
        "mismatch": result.mismatch,
        "unknown": result.unknown,
        "stale": result.stale,
        "contested": result.contested,
        "undecided": result.undecided,
        "moved": result.moved,
        "held": result.held,
        "disagreement": result.disagreement,
    }


# --- Package files ----------------------------------------------------------

# Downloads in progress, in this process. A room switched on at 8 o'clock
# asks for the same installer forty times in a minute: beyond the bound the
# agent is told to come back later (429 + Retry-After) — which it does without
# failing the command — instead of the server serving them all at once.
_downloads_in_flight = 0


def _release_download() -> None:
    global _downloads_in_flight
    _downloads_in_flight = max(0, _downloads_in_flight - 1)


class _CountedFileResponse(FileResponse):
    """A download holding one of the slots above until it is over, however
    it ends.

    Not a ``BackgroundTask``: FileResponse answers a ``Range`` it cannot
    serve (416, or 400 for a malformed one) without running its background,
    and a client gone mid-transfer raises past it — each one a slot never
    given back, until every poste was told 429 until a restart.
    """

    async def __call__(self, scope: ASGIScope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            _release_download()


@router.get("/packages/{package_id}/files/{sha256}")
async def download_package_file(
    package_id: uuid.UUID,
    sha256: str,
    machine: CurrentMachine,
    session: SessionDep,
) -> FileResponse:
    """A file of a package, for a poste that has a deployment of it open.

    The token says which poste asks; the open command says it was asked to.
    Without one: 404, as for a file that does not exist — a poste has no
    business browsing the store. ``Range`` is honoured (FileResponse), so a
    download cut halfway resumes where it stopped.
    """
    global _downloads_in_flight
    not_found = AppError(
        code=ErrorCode.PACKAGE_NOT_FOUND, status_code=404, message="Not found"
    )
    # Before any query: what is not a SHA-256 names no file, and a NUL in it
    # is a value PostgreSQL refuses outright — a 500 where a 404 is due.
    try:
        path = package_storage.path_for(sha256)
    except ValueError:
        raise not_found from None
    open_commands = (
        await session.exec(
            select(Command.package_files)
            .where(col(Command.machine_id) == machine.id)
            .where(col(Command.package_id) == package_id)
            .where(
                col(Command.status).in_(
                    [CommandStatus.DELIVERED.value, CommandStatus.RUNNING.value]
                )
            )
        )
    ).all()
    if not open_commands:
        raise not_found
    # What the deployment was queued with is what it downloads, even if the
    # package has changed since (audit B13). A command queued before the
    # snapshot existed falls back on the package as it stands.
    name = sha256
    if not any(shas is not None and sha256 in shas for shas in open_commands):
        row = (
            await session.exec(
                select(PackageFile)
                .where(col(PackageFile.package_id) == package_id)
                .where(col(PackageFile.sha256) == sha256)
                .limit(1)
            )
        ).first()
        if row is None or not any(shas is None for shas in open_commands):
            raise not_found
        name = row.name
    if not path.exists():
        raise not_found
    if _downloads_in_flight >= settings.PACKAGE_MAX_CONCURRENT_DOWNLOADS:
        raise AppError(
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            message="Too many downloads in progress",
            headers={"Retry-After": "60"},
        )
    _downloads_in_flight += 1
    return _CountedFileResponse(
        path, media_type="application/octet-stream", filename=name
    )
