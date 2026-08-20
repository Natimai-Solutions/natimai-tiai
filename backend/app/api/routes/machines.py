"""Console-facing endpoints: list and inspect managed machines.

Auth (admin session/JWT) is added in M5; left open for the MVP.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, computed_field
from sqlalchemy import case, exists, func, or_
from sqlalchemy.sql.elements import UnaryExpression
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.base import utcnow
from app.features.command.models import Command, CommandStatus, CommandType
from app.features.machine import crud as machine_crud
from app.features.machine.fingerprint import trustworthy_smbios_uuid
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    WindowsUpdateFilter,
    is_online,
    status_clause,
    windows_update_clause,
)
from app.features.threat.models import Threat
from app.features.user.permissions import Action, Resource
from app.features.windows_update.models import WindowsUpdate
from app.features.wol.sender import wake as emit_wake

router = APIRouter(
    prefix="/machines",
    tags=["machines"],
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.READ))],
)


class MachineOut(BaseModel):
    """Machine summary for the console list/detail views."""

    id: uuid.UUID
    machine_uuid: str
    hostname: str | None
    domain: str | None
    ip_address: str | None
    os_version: str | None
    agent_version: str | None
    is_up_to_date: bool | None
    needs_verification: bool
    signature_version: str | None
    # Which antivirus guards the poste. In the list and not only in the detail:
    # on a mixed parc it is the column that explains an "outdated" Defender
    # reading, and the one people filter on. "" = no antivirus registered at all,
    # None = never reported (see the model).
    av_product_name: str | None
    av_product_enabled: bool | None
    av_product_signatures_up_to_date: bool | None
    av_product_is_defender: bool | None
    session_user_present: bool | None
    session_username: str | None
    # In the list and not only in the detail: "which postes are missing patches"
    # and "which are waiting on a restart" are the two questions this phase
    # exists to answer, and both are answered by scanning a column. NULL on the
    # count = never reported (see the model).
    wu_pending_count: int | None
    wu_reboot_required: bool
    last_seen: datetime

    model_config = {"from_attributes": True}

    # Derived here rather than stored, and served rather than left to the client:
    # the cadence it is read against is a server setting, and computing it at
    # serialization time keeps the answer free of any client clock skew.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_online(self) -> bool:
        """Whether the agent has phoned home within the online window."""
        return is_online(self.last_seen, utcnow(), settings.OFFLINE_AFTER_SECONDS)


class PendingUpdateOut(BaseModel):
    """An update WUA reports as applicable and not yet installed on this machine."""

    id: int
    update_id: str
    kb: str | None
    title: str
    severity: str | None
    type: str
    categories: str | None
    is_downloaded: bool
    size_mb: float | None
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


class MachineDetailOut(MachineOut):
    """Full machine detail (Defender state, session type, fingerprint, times)."""

    rtp_enabled: bool | None
    av_enabled: bool | None
    signature_last_updated: datetime | None
    signature_age_days: int | None
    last_quick_scan: datetime | None
    last_full_scan: datetime | None
    running_mode: str | None
    session_state: str | None
    session_is_remote: bool | None
    wu_last_search: datetime | None
    wu_last_install: datetime | None
    # In the detail and not in the list: nobody scans a fleet by hardware
    # address, but on one poste it is what says whether the wake button can do
    # anything at all — and it is the first thing to check against the switch
    # when a wake did not work.
    mac_address: str | None
    # The mask the poste reported for ``ip_address``. Shown next to it — an
    # address without its mask does not say which network it is on — and it is
    # what the wake broadcasts to. NULL = never reported, and the wake then falls
    # back on the server's configured default.
    ip_prefix_length: int | None
    machine_guid: str | None
    smbios_uuid: str | None
    tpm_ek_hash: str | None
    first_seen: datetime
    created_at: datetime
    updated_at: datetime
    # Embedded rather than served from a /machines/{id}/updates of its own: the
    # list is a few dozen rows, it is only ever read next to the state above, and
    # a second round trip would only make the page load in two steps.
    pending_updates: list[PendingUpdateOut] = []


class MachineList(BaseModel):
    """Paginated machine list."""

    items: list[MachineOut]
    total: int
    page: int
    page_size: int


# The list's sortable columns, keyed by their API field names. A dict lookup
# rather than getattr on user input: anything outside it is a 422, not an
# ORDER BY built from a request.
MachineSortField = Literal[
    "hostname",
    "domain",
    "av_product_name",
    "wu_pending_count",
    "session_user_present",
    "last_seen",
]
_SORT_COLUMNS = {
    "hostname": Machine.hostname,
    "domain": Machine.domain,
    "av_product_name": Machine.av_product_name,
    "wu_pending_count": Machine.wu_pending_count,
    "session_user_present": Machine.session_user_present,
    "last_seen": Machine.last_seen,
}
# Sorted case-folded: under a C collation "ZEUS" would otherwise come before
# "alpha", which no reader of a hostname column expects.
_CASEFOLD_SORT_FIELDS = {"hostname", "domain", "av_product_name"}


def _sort_clause(field: MachineSortField, descending: bool) -> UnaryExpression[Any]:
    """ORDER BY expression for one sortable column.

    NULLs last in both directions: "never reported" is an absence, not a value,
    and it must not lead the list whichever way the reader flips the arrow.
    """
    column = col(_SORT_COLUMNS[field])
    key = func.lower(column) if field in _CASEFOLD_SORT_FIELDS else column
    ordered = key.desc() if descending else key.asc()
    return ordered.nulls_last()


@router.get("", response_model=MachineList)
async def list_machines(
    session: SessionDep,
    search: str | None = None,
    domain: str | None = None,
    antivirus: str | None = None,
    status: MachineStatus | None = None,
    wu_status: WindowsUpdateFilter | None = None,
    with_active_threats: bool | None = None,
    sort_by: MachineSortField | None = None,
    sort_desc: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> MachineList:
    """List machines with optional search/domain/antivirus/status filters, plus
    the two facets the dashboard cards link to: Windows Update state and the
    presence of an active threat. Sortable on the console list's own columns;
    the default order is freshest contact first.
    """
    stmt = select(Machine)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                col(Machine.hostname).ilike(pattern),
                col(Machine.machine_uuid).ilike(pattern),
                # Searchable too: going from an address in a firewall or DHCP
                # log back to the machine is the everyday use of this field.
                col(Machine.ip_address).ilike(pattern),
                # And from a vendor name: "which postes still run the antivirus
                # we are migrating off?" is the question a mixed parc asks.
                col(Machine.av_product_name).ilike(pattern),
            )
        )
    if domain:
        stmt = stmt.where(col(Machine.domain) == domain)
    if antivirus:
        # Substring rather than equality, unlike the domain filter: the dropdown
        # feeds it exact names from the fleet, but a hand-typed "eset" must find
        # "ESET Endpoint Security" too — vendors rename their products between
        # versions and a parc runs several at once.
        stmt = stmt.where(col(Machine.av_product_name).ilike(f"%{antivirus}%"))
    if status is not None:
        stmt = stmt.where(status_clause(status, utcnow(), settings.INACTIVE_AFTER_DAYS))
    if wu_status is not None:
        stmt = stmt.where(windows_update_clause(wu_status))
    if with_active_threats is not None:
        # Same definition as the dashboard's "avec menaces" KPI: at least one
        # threat Defender has not dealt with. False selects the complement.
        active = exists().where(
            (col(Threat.machine_id) == col(Machine.id))
            & (col(Threat.status) == "active")
        )
        stmt = stmt.where(active if with_active_threats else ~active)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # last_seen then id behind the requested column: ties must land on the same
    # page from one request to the next, or rows duplicate and vanish across
    # page boundaries.
    if sort_by is None:
        stmt = stmt.order_by(col(Machine.last_seen).desc(), col(Machine.id))
    else:
        stmt = stmt.order_by(
            _sort_clause(sort_by, sort_desc),
            col(Machine.last_seen).desc(),
            col(Machine.id),
        )
    rows = await session.exec(stmt.offset((page - 1) * page_size).limit(page_size))
    items = [MachineOut.model_validate(m) for m in rows.all()]
    return MachineList(items=items, total=total or 0, page=page, page_size=page_size)


class AntivirusProduct(BaseModel):
    """One antivirus present in the fleet, with how many machines report it."""

    name: str
    count: int


# Declared before ``/{machine_id}``: FastAPI matches in declaration order, and
# the other way round "antivirus-products" would be parsed as a machine id.
@router.get("/antivirus-products", response_model=list[AntivirusProduct])
async def list_antivirus_products(session: SessionDep) -> list[AntivirusProduct]:
    """Antivirus names reported across the fleet, most widespread first.

    Feeds the console's filter dropdown: which products are installed is fleet
    data, not something a client can hardcode — and the counts double as a
    one-glance inventory of a mixed parc.

    Machines that reported no product (empty name) or nothing at all (NULL) are
    left out: they are not products to filter on, and the "Non à jour" status
    filter already gathers them.
    """
    name = col(Machine.av_product_name)
    rows = await session.exec(
        select(name, func.count().label("count"))
        .where(name.is_not(None))
        .where(name != "")
        .group_by(name)
        .order_by(func.count().desc(), name)
    )
    return [
        AntivirusProduct(name=product, count=count)
        # `if product` narrows away the NULL the SQL already excluded.
        for product, count in rows.all()
        if product
    ]


class WakeRequest(BaseModel):
    """Machines to wake: one id from a machine's page, a selection from the list."""

    # Bounded rather than open: a wake is a handful of datagrams per poste, but
    # the request holds the event loop for the whole list, and nobody wakes a
    # parc of five hundred by accident.
    machine_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class WakeOut(BaseModel):
    """What the server did about one machine, in the words the console shows."""

    machine_id: uuid.UUID
    hostname: str | None
    ok: bool
    detail: str


class WakeResponse(BaseModel):
    """Per-machine outcomes, and the two counts a notification needs.

    Per machine and not one status for the batch: waking thirty postes of which
    two have never reported a MAC is a *partial* success, and a single "OK"
    would hide exactly the two an administrator has to go and look at.
    """

    results: list[WakeOut]
    woken: int
    failed: int


# Declared before ``/{machine_id}``, like the antivirus listing above: FastAPI
# matches in declaration order, and this path would otherwise be read as an id.
@router.post(
    "/wake",
    response_model=WakeResponse,
    dependencies=[Depends(require_permission(Resource.COMMAND, Action.EXECUTE))],
)
async def wake_machines(
    payload: WakeRequest, session: SessionDep, user: CurrentUser
) -> WakeResponse:
    """Broadcast a Wake-on-LAN magic packet for each machine (admin only).

    The one action in this console the *server* performs on a poste rather than
    its agent, for the only reason that could justify it: the machine is off, so
    there is no agent to ask. What travels is a frame the network adapter
    recognises while the rest of the hardware sleeps — see ``features/wol``.

    Each attempt is recorded as a ``wake_on_lan`` row in the command history,
    created already closed: it is never handed out on a heartbeat and no agent
    can pick it up. That keeps "who woke this poste, and when" in the same table
    as "who restarted it", which is where an administrator looks.

    Never fails as a whole. A poste without a known MAC, or without an address
    to derive a broadcast from, comes back as one failed entry among the
    others — the batch is not the unit of success here, the poste is.
    """
    rows = await session.exec(
        select(Machine).where(col(Machine.id).in_(payload.machine_ids))
    )
    machines = {m.id: m for m in rows.all()}

    results: list[WakeOut] = []
    for machine_id in payload.machine_ids:
        machine = machines.get(machine_id)
        if machine is None:
            # Reported rather than 404'd: one stale id in a selection of thirty
            # must not cost the other twenty-nine their wake. Nothing is
            # recorded — there is no machine left to record it against.
            results.append(
                WakeOut(
                    machine_id=machine_id,
                    hostname=None,
                    ok=False,
                    detail="Poste introuvable : il a été supprimé ou fusionné.",
                )
            )
            continue

        outcome = await emit_wake(
            mac=machine.mac_address,
            ip=machine.ip_address,
            prefix_length=machine.ip_prefix_length,
        )
        now = utcnow()
        session.add(
            Command(
                machine_id=machine.id,
                type=CommandType.WAKE_ON_LAN.value,
                status=(
                    CommandStatus.SUCCEEDED.value
                    if outcome.ok
                    else CommandStatus.FAILED.value
                ),
                created_by=user.email,
                created_at=now,
                # Already terminal, so it never had a life to expire — the sweep
                # only ever touches PENDING rows. Set to the creation instant so
                # the column reads as "was never offered to anyone" rather than
                # dangling an hour into the future.
                expires_at=now,
                started_at=now,
                finished_at=now,
                result_output=outcome.detail if outcome.ok else None,
                error=None if outcome.ok else outcome.detail,
            )
        )
        results.append(
            WakeOut(
                machine_id=machine.id,
                hostname=machine.hostname,
                ok=outcome.ok,
                detail=outcome.detail,
            )
        )

    await session.commit()
    woken = sum(1 for r in results if r.ok)
    return WakeResponse(results=results, woken=woken, failed=len(results) - woken)


async def _require_machine(session: SessionDep, machine_id: uuid.UUID) -> Machine:
    """Fetch a machine or raise the stable not-found error."""
    machine = await session.get(Machine, machine_id)
    if machine is None:
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    return machine


async def _machine_detail(session: SessionDep, machine: Machine) -> MachineDetailOut:
    """Build a detail payload, pending Windows updates included.

    Ordered by severity then title rather than by insertion: the reason to open
    this table is to find the critical patch, and the ``severity`` values are
    MSRC's own vocabulary, which sorts alphabetically as critical < important <
    low < moderate — no use at all. Hence the explicit CASE.
    """
    severity_rank = case(
        {
            "critical": 0,
            "important": 1,
            "moderate": 2,
            "low": 3,
        },
        value=col(WindowsUpdate.severity),
        else_=4,
    )
    rows = await session.exec(
        select(WindowsUpdate)
        .where(col(WindowsUpdate.machine_id) == machine.id)
        .order_by(severity_rank, col(WindowsUpdate.title))
    )
    detail = MachineDetailOut.model_validate(machine)
    detail.pending_updates = [PendingUpdateOut.model_validate(u) for u in rows.all()]
    return detail


@router.get("/{machine_id}", response_model=MachineDetailOut)
async def get_machine(machine_id: uuid.UUID, session: SessionDep) -> MachineDetailOut:
    """Fetch a single machine by id (full Defender state + fingerprint)."""
    machine = await _require_machine(session, machine_id)
    return await _machine_detail(session, machine)


MatchReason = Literal["smbios_uuid", "tpm_ek_hash", "hostname"]


class DuplicateCandidateOut(MachineOut):
    """A machine that may be another record of the same physical poste.

    Carries *why* it is a candidate: the two anchors are hardware evidence, a
    matching hostname is a hint and nothing more. The console shows the reason
    rather than a flat list, because merging is irreversible and the decision
    is not the same one in the two cases.

    ``first_seen`` rides along, which the list payload does not carry: two
    records of one poste share its hostname, so what tells them apart is when
    each was first enrolled — the older one is usually the record being retired.
    """

    first_seen: datetime
    match_reason: MatchReason


def _hardware_contradicts(
    anchor: str | None, tpm: str, other_anchor: str | None, other_tpm: str
) -> bool:
    """Whether two records provably describe *different* physical machines.

    Only a pair of values that both exist and differ proves anything: a missing
    anchor is a missing reading, not evidence of difference, and the firmware
    constants are already filtered out by ``trustworthy_smbios_uuid``.
    """
    if anchor and other_anchor and anchor != other_anchor:
        return True
    return bool(tpm and other_tpm and tpm != other_tpm)


def _duplicate_candidate(
    machine: Machine, reason: MatchReason
) -> DuplicateCandidateOut:
    """A machine as a merge candidate, tagged with what makes it one."""
    # ``is_online`` is derived from ``last_seen`` at serialization time, so it is
    # dropped here rather than fed back in as an input.
    base = MachineOut.model_validate(machine).model_dump(exclude={"is_online"})
    return DuplicateCandidateOut(
        **base, first_seen=machine.first_seen, match_reason=reason
    )


@router.get("/{machine_id}/duplicates", response_model=list[DuplicateCandidateOut])
async def list_duplicates(
    machine_id: uuid.UUID, session: SessionDep
) -> list[DuplicateCandidateOut]:
    """Candidate duplicates of this machine — the records an admin may merge.

    Three signals, strongest first:

    - **SMBIOS UUID** (plan §2.3), the motherboard's own identifier. Only when
      it identifies a single machine: the firmware constants a whitebox ships on
      every unit are excluded, or a batch of forty would each list the other
      thirty-nine as duplicates.
    - **TPM EK hash**, which survives a re-image just as well and is there when
      the SMBIOS anchor is not.
    - **Hostname**, deliberately included although it proves nothing on its own:
      the case that most needs merging — a poste whose anchor drifted, which is
      exactly what the "empreinte divergente" banner reports — leaves no *shared*
      anchor between the two records, so an anchors-only search would answer
      "aucun doublon" on the one page that offers the button. Reported as the
      weak signal it is, never for a poste that reported no hostname at all, and
      **only when the hardware does not contradict it**: two records that each
      carry a real, different SMBIOS UUID or TPM key are two machines, and no
      shared name makes them one.

      That last rule costs one real case to buy a much worse one. It keeps a
      batch of freshly imaged, not-yet-renamed postes — all still answering to
      the image's computer name — from listing each other as candidates for a
      merge that *deletes* a row; and the drift it turns away is the variant
      where both records hold a real anchor, which is indistinguishable from two
      distinct machines by any query. That variant is resolved from the merge
      dialog's manual search instead, deliberately and with both UUIDs on
      screen. The everyday drift — an old record that predates fingerprinting
      and carries no anchor at all — is not contradicted, and is still offered.

    ``machine_guid`` is not a signal here: this fleet's postes are re-imaged
    without Sysprep, which is precisely the case where clones share it — it
    would group a whole image, not the copies of one machine.
    """
    machine = await _require_machine(session, machine_id)

    anchor = trustworthy_smbios_uuid(machine.smbios_uuid)
    tpm = (machine.tpm_ek_hash or "").strip()
    hostname = (machine.hostname or "").strip()

    clauses = []
    if anchor:
        clauses.append(func.lower(func.trim(col(Machine.smbios_uuid))) == anchor)
    if tpm:
        clauses.append(func.trim(col(Machine.tpm_ek_hash)) == tpm)
    if hostname:
        clauses.append(func.lower(func.trim(col(Machine.hostname))) == hostname.lower())
    if not clauses:
        return []

    rows = await session.exec(
        select(Machine)
        .where(or_(*clauses))
        .where(col(Machine.id) != machine_id)
        .order_by(col(Machine.last_seen).desc())
    )

    candidates: list[DuplicateCandidateOut] = []
    for other in rows.all():
        reason: MatchReason
        other_anchor = trustworthy_smbios_uuid(other.smbios_uuid)
        other_tpm = (other.tpm_ek_hash or "").strip()
        if anchor and other_anchor == anchor:
            reason = "smbios_uuid"
        elif tpm and other_tpm == tpm:
            reason = "tpm_ek_hash"
        elif _hardware_contradicts(anchor, tpm, other_anchor, other_tpm):
            # Same name, demonstrably different hardware: not a duplicate, and
            # offering it would be offering to delete a live poste.
            continue
        else:
            reason = "hostname"
        candidates.append(_duplicate_candidate(other, reason))

    # Hardware evidence first, whatever their last contact: a hostname match is
    # a lead an administrator checks, an anchor match is a duplicate.
    order = {"smbios_uuid": 0, "tpm_ek_hash": 1, "hostname": 2}
    candidates.sort(key=lambda c: order[c.match_reason])
    return candidates


@router.post(
    "/{machine_id}/revoke-token",
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.WRITE))],
)
async def revoke_token(machine_id: uuid.UUID, session: SessionDep) -> dict[str, str]:
    """Revoke a machine's token (kill-switch): its next call is rejected and it
    must re-enroll, which issues a fresh token and clears the flag (plan §2.4).
    """
    machine = await _require_machine(session, machine_id)
    machine.token_revoked = True
    machine.updated_at = utcnow()
    await session.commit()
    return {"status": "revoked"}


class MergeRequest(BaseModel):
    """Merge the ``source`` machine into the path's target (kept) machine."""

    source_id: uuid.UUID


@router.post(
    "/{machine_id}/merge",
    response_model=MachineDetailOut,
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.WRITE))],
)
async def merge_machine(
    machine_id: uuid.UUID, payload: MergeRequest, session: SessionDep
) -> MachineDetailOut:
    """Merge a duplicate record into this one (plan §8): the source's threats
    and commands are reattached here, the verification flag is cleared, and the
    source is deleted. This machine (the path id) is the one kept.
    """
    if machine_id == payload.source_id:
        raise AppError(
            code=ErrorCode.MACHINE_MERGE_SELF,
            status_code=400,
            message="Cannot merge a machine into itself",
        )
    target = await _require_machine(session, machine_id)
    source = await _require_machine(session, payload.source_id)
    await machine_crud.merge_into(session, target=target, source=source)
    await session.commit()
    await session.refresh(target)
    return await _machine_detail(session, target)
