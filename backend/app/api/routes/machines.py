"""Console-facing endpoints: list and inspect managed machines."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, computed_field
from sqlalchemy import case, exists, func, or_
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression
from sqlmodel import col, select

from app.api import machine_export
from app.api.csv_export import csv_response
from app.api.deps import CurrentUser, SessionDep, require_permission
from app.api.xlsx_export import xlsx_response
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.check import crud as check_crud
from app.features.check.models import MachineCheck
from app.features.command.models import Command, CommandStatus, CommandType
from app.features.inventory.models import (
    Disk,
    Gpu,
    MachineSoftware,
    MemoryModule,
    Nic,
    Software,
    Volume,
)
from app.features.machine import crud as machine_crud
from app.features.machine.agent_version import FleetVersions, fleet_versions
from app.features.machine.fingerprint import trustworthy_smbios_uuid
from app.features.machine.models import Machine
from app.features.machine.status import (
    MachineStatus,
    ScanFilter,
    WindowsUpdateFilter,
    agent_outdated_clause,
    disk_free_percent,
    is_online,
    low_disk_clause,
    online_clause,
    ram_clause,
    scan_clause,
    status_clause,
    windows_update_clause,
)
from app.features.maintenance import policy as maintenance_policy
from app.features.maintenance.policy import MaintenanceState
from app.features.room import crud as room_crud
from app.features.room.models import Building, Room
from app.features.setting import crud as setting_crud
from app.features.setting.crud import MaintenancePolicy
from app.features.threat.models import Threat
from app.features.user.models import User
from app.features.user.permissions import Action, Resource
from app.features.windows_update.models import WindowsUpdate
from app.features.wol import relay as wol_relay
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
    # The site, as the agent's configuration names it. In the list because it
    # is what the list is scanned by on a multi-site parc — "which postes are
    # at Taravao" — and null for every poste whose deployment set none.
    location: str | None
    # Where the console placed the poste (``features/room``): its room, the
    # room's building, and the site those two resolve to. Defaults rather than
    # required, because a ``MachineOut`` is also built off a bare ``Machine``
    # (duplicate candidates); the list and the fiche fill them in.
    room_id: uuid.UUID | None = None
    room_name: str | None = None
    building_id: uuid.UUID | None = None
    building_name: str | None = None
    # The site the room says — its building's, or its own.
    room_location: str | None = None
    # The agent and the room disagree on the site. A finding, not a refusal:
    # it is what reveals a GPO aimed at the wrong OU or a poste moved without
    # its room. False when either side has no opinion.
    location_mismatch: bool = False
    # A verification somebody asked for is open on this poste. In the list
    # because it is what the list is filtered by to see what is waiting.
    check_open: bool = False
    check_assigned_to: str | None = None
    # Maintenance, as it resolves for this poste (``maintenance/policy.py``):
    # when it is due, where it stands, who owns it. Null due = excluded.
    last_maintenance_at: datetime | None = None
    maintenance_due_at: datetime | None = None
    maintenance_state: str | None = None
    maintenance_owner: str | None = None
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
    # Three inventory fields in the list and not the twenty-five the fiche
    # shows: this payload serves a thousand rows, and the questions a list
    # answers are "quel modèle" and "lesquels n'ont plus de place". The rest is
    # one machine's business and lives in the detail.
    hw_model: str | None
    ram_total_mb: int | None
    system_volume_total_mb: int | None
    system_volume_free_mb: int | None
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


def _place(out: MachineOut, machine: Machine, placement: room_crud.Placement) -> None:
    """Fill a payload's room fields from a resolved placement."""
    room, building = placement.room, placement.building
    out.room_id = room.id if room else None
    out.room_name = room.name if room else None
    out.building_id = building.id if building else None
    out.building_name = building.name if building else None
    out.room_location = placement.location
    out.location_mismatch = room_crud.location_mismatch(
        machine.location, placement.location
    )


def _machine_out(
    machine: Machine,
    room: Room | None,
    building: Building | None,
    check: MachineCheck | None = None,
    names: dict[uuid.UUID, str] | None = None,
    policy: MaintenancePolicy | None = None,
    now: datetime | None = None,
) -> MachineOut:
    """A list row, with its placement, open request and maintenance standing
    as the joined query and the policy give them."""
    out = MachineOut.model_validate(machine)
    _place(out, machine, room_crud.Placement(room=room, building=building))
    if check is not None:
        out.check_open = True
        if check.assigned_to_id and names:
            out.check_assigned_to = names.get(check.assigned_to_id)
    if policy is not None:
        res = maintenance_policy.resolve(machine, room, policy, now or utcnow())
        out.last_maintenance_at = machine.last_maintenance_at
        out.maintenance_due_at = res.due_at
        out.maintenance_state = res.state.value
        out.maintenance_owner = (
            names.get(res.owner_id) if names and res.owner_id else None
        )
    return out


def _owner_ids(rows: list[Any], policy: MaintenancePolicy) -> set[uuid.UUID]:
    """Every account a page's rows may name: assignees, owners at each level."""
    ids: set[uuid.UUID] = set()
    if policy.owner_id:
        ids.add(policy.owner_id)
    for m, room, _b, check in rows:
        if m.maintenance_owner_id:
            ids.add(m.maintenance_owner_id)
        if room is not None and room.maintenance_owner_id:
            ids.add(room.maintenance_owner_id)
        if check is not None and check.assigned_to_id:
            ids.add(check.assigned_to_id)
    return ids


async def _assignee_names(
    session: SessionDep, checks: list[MachineCheck | None]
) -> dict[uuid.UUID, str]:
    """Display names of the accounts the page's open requests are assigned to."""
    ids = {c.assigned_to_id for c in checks if c is not None and c.assigned_to_id}
    return await setting_crud.user_names(session, ids)


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


class MemoryModuleOut(BaseModel):
    """One physical memory stick."""

    id: int
    slot: str
    capacity_mb: int | None
    type: str | None
    speed_mhz: int | None
    manufacturer: str | None
    serial: str | None
    form_factor: str | None

    model_config = {"from_attributes": True}


class DiskOut(BaseModel):
    """One physical drive."""

    id: int
    device_id: str
    model: str | None
    serial: str | None
    firmware: str | None
    media_type: str | None
    bus_type: str | None
    size_mb: int | None
    health_status: str | None
    is_removable: bool

    model_config = {"from_attributes": True}


class VolumeOut(BaseModel):
    """One fixed logical volume.

    ``used_mb`` is not here either: the console subtracts. Two figures that can
    contradict each other about one number is what deriving avoids.
    """

    id: int
    letter: str
    label: str | None
    filesystem: str | None
    total_mb: int | None
    free_mb: int | None
    is_system: bool
    encryption_status: str | None

    model_config = {"from_attributes": True}


class NicOut(BaseModel):
    """One network adapter.

    The elected address is on the machine itself (``ip_address``,
    ``mac_address``) and is *not* one of these rows: it is re-read every
    heartbeat because it is the wake target, while this list is a day old.
    """

    id: int
    name: str | None
    mac: str | None
    type: str | None
    speed_mbps: int | None
    is_up: bool
    is_virtual: bool
    ip_address: str | None
    ip_prefix_length: int | None
    is_dhcp: bool | None
    gateway: str | None
    driver_version: str | None

    model_config = {"from_attributes": True}


class GpuOut(BaseModel):
    """One display adapter."""

    id: int
    name: str
    chipset: str | None
    memory_mb: int | None
    driver_version: str | None
    driver_date: date | None
    resolution: str | None

    model_config = {"from_attributes": True}


class InstalledSoftwareOut(BaseModel):
    """One program installed on this machine, catalogue identity included.

    ``software_id`` rides along because it is the parc-wide handle: it is what
    "qui d'autre a ce logiciel" is asked with, and what a deployed package will
    hang on.
    """

    software_id: int
    name: str
    version: str
    publisher: str
    install_date: date | None
    arch: str | None
    source: str | None
    install_location: str | None
    first_seen: datetime


class OpenCheckOut(BaseModel):
    id: uuid.UUID
    requested_by: str
    assigned_to_id: uuid.UUID | None
    assigned_to_name: str | None
    instructions: str | None
    created_at: datetime


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
    # What the domain says about the poste, as its agent last read it. On the
    # fiche whatever ROOM_SOURCE says: it is what a directory-driven placement
    # reads, and what explains one.
    ad_distinguished_name: str | None
    ad_ou: str | None
    ad_ou_dn: str | None
    ad_location: str | None
    # The verification request open on this poste, if any: who asked, who is
    # asked, what to look at. The banner of the fiche.
    open_check: OpenCheckOut | None = None
    # Lets the console show that a poste is cut off and offer the only way
    # back: « autoriser le ré-enrôlement » (the fleet secret no longer clears
    # a revocation on its own).
    token_revoked: bool
    first_seen: datetime
    created_at: datetime
    updated_at: datetime
    # Embedded rather than served from a /machines/{id}/updates of its own: the
    # list is a few dozen rows, it is only ever read next to the state above, and
    # a second round trip would only make the page load in two steps.
    pending_updates: list[PendingUpdateOut] = []

    # --- Inventory. Cardinality-one facts as columns, the rest as lists.
    hw_manufacturer: str | None
    hw_serial: str | None
    hw_chassis_type: str | None
    hw_is_virtual: bool
    hw_hypervisor: str | None
    mb_manufacturer: str | None
    mb_model: str | None
    mb_serial: str | None
    bios_vendor: str | None
    bios_version: str | None
    bios_date: date | None
    secure_boot: bool | None
    tpm_version: str | None
    cpu_model: str | None
    cpu_manufacturer: str | None
    cpu_cores: int | None
    cpu_threads: int | None
    cpu_speed_mhz: int | None
    cpu_count: int | None
    ram_slots_total: int | None
    ram_slots_used: int | None
    os_architecture: str | None
    os_install_date: datetime | None
    last_boot_time: datetime | None
    # Deliberately not last_seen: a poste seen a minute ago whose inventory is
    # three weeks old is an anomaly the console has to be able to show.
    inventory_last_seen: datetime | None
    memory_modules: list[MemoryModuleOut] = []
    disks: list[DiskOut] = []
    volumes: list[VolumeOut] = []
    nics: list[NicOut] = []
    gpus: list[GpuOut] = []
    # The software list rides along with the rest for the same reason as the
    # pending updates: it is read on this page and nowhere else, and a few
    # hundred rows do not deserve a round trip of their own.
    software: list[InstalledSoftwareOut] = []
    # The version this poste's agent is measured against — the highest one on
    # the parc, or the configured one (see ``agent_version``). Served with the
    # fiche so "0.4.1" can be read as "behind 0.5.0" rather than as a string.
    agent_latest_version: str | None = None


class MachineList(BaseModel):
    """Paginated machine list."""

    items: list[MachineOut]
    total: int
    page: int
    page_size: int
    # Same reference as on the fiche, once per page rather than per row: the
    # list flags the postes below it, and a thousand rows carrying the same
    # string would be a thousand copies of one fact.
    agent_latest_version: str | None = None


# The list's sortable columns, keyed by their API field names. A dict lookup
# rather than getattr on user input: anything outside it is a 422, not an
# ORDER BY built from a request.
MachineSortField = Literal[
    "hostname",
    "domain",
    "location",
    # The console's placement, off the joined tables: grouping a parc by room
    # is what the column is for.
    "building",
    "room",
    # When the poste is next due: the "what do I do this week" sort. Needs
    # the policy, so ``_sort_key`` takes it.
    "maintenance_due_at",
    "av_product_name",
    "wu_pending_count",
    "session_user_present",
    "last_seen",
    # Inventory. "quel modèle" and "lequel n'a plus de place" are the two the
    # list is sorted by; the free space is a *percentage*, because 40 Go left on
    # a 4 To disk and on a 128 Go SSD are not the same news.
    "hw_model",
    "ram_total_mb",
    "disk_free_percent",
    # The agent's version, ordered the way a human reads one ("0.10.0" after
    # "0.9.0"): the sort the morning after a deployment, stragglers first.
    "agent_version",
]

# Sorted case-folded: under a C collation "ZEUS" would otherwise come before
# "alpha", which no reader of a hostname column expects.
_CASEFOLD_SORT_FIELDS = {
    "hostname",
    "domain",
    "location",
    "av_product_name",
    "hw_model",
}


def _agent_version_rank(versions: FleetVersions | None) -> Any:
    """The agent version as a sortable rank.

    A version compare has no honest translation into an ORDER BY — a string
    sort puts "0.10.0" before "0.9.0" — but a parc only ever carries a handful
    of distinct versions, so they are ranked in Python and handed to SQL as a
    CASE: the lowest version gets 0, the reference the highest rank. A poste
    with no version reported falls through to NULL, which the clause puts
    last in both directions like every other absence.
    """
    names = [name for name, _ in versions.counts] if versions else []
    if not names:
        return col(Machine.agent_version)
    # ``counts`` is newest first; the rank must grow with the version.
    ranks = {name: rank for rank, name in enumerate(reversed(names))}
    return case(ranks, value=col(Machine.agent_version), else_=None)


def _sort_key(
    field: MachineSortField,
    policy: MaintenancePolicy | None = None,
    versions: FleetVersions | None = None,
) -> Any:
    """The expression a sort orders by.

    Expressions and not columns, since this one was extended: the free-space
    percentage is derived from two columns and has none of its own, and it has
    to be sortable like any other.
    """
    if field == "disk_free_percent":
        return disk_free_percent()
    if field == "agent_version":
        return _agent_version_rank(versions)
    if field == "maintenance_due_at" and policy is not None:
        return maintenance_policy.due_expr(policy)
    if field == "building":
        return func.lower(col(Building.name))
    if field == "room":
        return func.lower(col(Room.name))
    column = col(getattr(Machine, field))
    return func.lower(column) if field in _CASEFOLD_SORT_FIELDS else column


def _sort_clause(
    field: MachineSortField,
    descending: bool,
    policy: MaintenancePolicy | None = None,
    versions: FleetVersions | None = None,
) -> UnaryExpression[Any]:
    """ORDER BY expression for one sortable column.

    NULLs last in both directions: "never reported" is an absence, not a value,
    and it must not lead the list whichever way the reader flips the arrow.
    """
    key: Any = _sort_key(field, policy, versions)
    ordered: UnaryExpression[Any] = key.desc() if descending else key.asc()
    return ordered.nulls_last()


# Characters a hand-typed MAC may carry between its bytes (Windows hyphenates,
# Cisco dots) — stripped before matching against the stored colon form.
_MAC_SEARCH_STRIP = str.maketrans("", "", ":-. ")


def _search_clause(search: str) -> ColumnElement[bool]:
    """The free-search predicate: hostname, UUID, IP, antivirus — and MAC.

    The MAC leg compares hex-only forms on both sides, so "AA-BB-CC" and
    "aabb.cc" find the stored "AA:BB:CC:…" — the value on screen is whatever
    tool the administrator read it from (a switch, ipconfig), never this
    console's own notation. Only added when the term reads as hex at all: a
    hostname search must not pay for a REPLACE() over the whole fleet.
    """
    pattern = f"%{search}%"
    clauses = [
        col(Machine.hostname).ilike(pattern),
        col(Machine.machine_uuid).ilike(pattern),
        # Searchable too: going from an address in a firewall or DHCP
        # log back to the machine is the everyday use of this field.
        col(Machine.ip_address).ilike(pattern),
        # And from a vendor name: "which postes still run the antivirus
        # we are migrating off?" is the question a mixed parc asks.
        col(Machine.av_product_name).ilike(pattern),
    ]
    compact = search.translate(_MAC_SEARCH_STRIP)
    try:
        int(compact, 16)
    except ValueError:
        pass
    else:
        clauses.append(
            func.replace(col(Machine.mac_address), ":", "").ilike(f"%{compact}%")
        )
    return or_(*clauses)


@dataclass(frozen=True)
class MachineFilters:
    """Every facet the machine list understands.

    A dataclass rather than a dozen parameters threaded twice: the CSV export is
    the same query without the pagination, and an export that silently ignored
    half the filters the reader had set would be worse than no export at all.
    """

    search: str | None = None
    domain: str | None = None
    # Exact, like the domain: the dropdown feeds it values the fleet reported,
    # and "Lycée" as a substring would gather every lycée of the académie.
    location: str | None = None
    # The console's placement. ``room_id`` and ``building_id`` are exact;
    # ``without_room`` selects the postes nobody placed — the ones a manual
    # classification still has to file. ``location_mismatch`` is the finding
    # the rooms page counts: agent and room disagreeing on the site.
    room_id: uuid.UUID | None = None
    building_id: uuid.UUID | None = None
    without_room: bool | None = None
    location_mismatch: bool | None = None
    # A verification request is open (true) or not (false).
    check_open: bool | None = None
    # Where the poste stands on its maintenance cycle.
    maintenance_state: MaintenanceState | None = None
    antivirus: str | None = None
    os_version: str | None = None
    status: MachineStatus | None = None
    online: bool | None = None
    wu_status: WindowsUpdateFilter | None = None
    scan_type: ScanFilter | None = None
    scan_older_than_days: int = 7
    with_active_threats: bool | None = None
    hw_model: str | None = None
    hw_manufacturer: str | None = None
    # Inventory facets a renewal plan is drawn with: which processor, how much
    # memory, which kind of poste. The memory bounds are in whole GiB — the
    # unit anyone thinks in — and inclusive on both ends.
    cpu_model: str | None = None
    hw_chassis_type: str | None = None
    ram_min_gb: int | None = None
    ram_max_gb: int | None = None
    disk_free_below: int | None = None
    software_id: int | None = None
    # The agent itself. An exact version (the dropdown feeds fleet values), or
    # "behind the reference" — the question asked the morning after a
    # deployment, and the one that names the postes it has not reached.
    agent_version: str | None = None
    agent_outdated: bool | None = None


def machine_filters(
    search: str | None = None,
    domain: str | None = None,
    location: str | None = None,
    room_id: uuid.UUID | None = None,
    building_id: uuid.UUID | None = None,
    without_room: bool | None = None,
    location_mismatch: bool | None = None,
    check_open: bool | None = None,
    maintenance_state: MaintenanceState | None = None,
    antivirus: str | None = None,
    os_version: str | None = None,
    status: MachineStatus | None = None,
    online: bool | None = None,
    wu_status: WindowsUpdateFilter | None = None,
    scan_type: ScanFilter | None = None,
    scan_older_than_days: int = Query(7, ge=1),
    with_active_threats: bool | None = None,
    hw_model: str | None = None,
    hw_manufacturer: str | None = None,
    cpu_model: str | None = None,
    hw_chassis_type: str | None = None,
    ram_min_gb: int | None = Query(None, ge=1),
    ram_max_gb: int | None = Query(None, ge=1),
    disk_free_below: int | None = Query(None, ge=1, le=100),
    software_id: int | None = None,
    agent_version: str | None = None,
    agent_outdated: bool | None = None,
) -> MachineFilters:
    """The list's facets as query parameters, shared by the list and the exports.

    One dependency rather than the same twenty parameters declared three times:
    a facet added to the list and forgotten by an export would make the export
    silently broader than the screen the reader was looking at.
    """
    return MachineFilters(
        search=search,
        domain=domain,
        location=location,
        room_id=room_id,
        building_id=building_id,
        without_room=without_room,
        location_mismatch=location_mismatch,
        check_open=check_open,
        maintenance_state=maintenance_state,
        antivirus=antivirus,
        os_version=os_version,
        status=status,
        online=online,
        wu_status=wu_status,
        scan_type=scan_type,
        scan_older_than_days=scan_older_than_days,
        with_active_threats=with_active_threats,
        hw_model=hw_model,
        hw_manufacturer=hw_manufacturer,
        cpu_model=cpu_model,
        hw_chassis_type=hw_chassis_type,
        ram_min_gb=ram_min_gb,
        ram_max_gb=ram_max_gb,
        disk_free_below=disk_free_below,
        software_id=software_id,
        agent_version=agent_version,
        agent_outdated=agent_outdated,
    )


FiltersDep = Annotated[MachineFilters, Depends(machine_filters)]


def _room_location() -> Any:
    """The site a poste's room says, as SQL: its building's, else its own."""
    return func.coalesce(col(Building.location), col(Room.location))


def _mismatch_clause() -> Any:
    """Agent and room both name a site, and not the same one."""
    site = _room_location()
    return (
        col(Machine.location).is_not(None)
        & site.is_not(None)
        & (col(Machine.location) != site)
    )


def _filtered_machines(
    filters: MachineFilters,
    outdated: list[str] | None = None,
    policy: MaintenancePolicy | None = None,
) -> Any:
    """The machine SELECT with every requested facet applied.

    Returns ``(Machine, Room | None, Building | None, MachineCheck | None)``
    rows: the placement and the open verification request are joined in
    rather than fetched per row, because they are also what facets filter
    on and columns sort by. At most one open request per poste (partial
    unique index), so the join never multiplies rows.

    ``outdated`` is the list of agent versions ranking below the reference,
    from ``fleet_versions`` — read by the caller, because this builds a
    statement and does not touch the database.
    """
    stmt = (
        select(Machine, Room, Building, MachineCheck)
        .outerjoin(Room, col(Room.id) == col(Machine.room_id))
        .outerjoin(Building, col(Building.id) == col(Room.building_id))
        .outerjoin(
            MachineCheck,
            (col(MachineCheck.machine_id) == col(Machine.id))
            & (col(MachineCheck.closed_at).is_(None)),
        )
    )
    if filters.check_open is not None:
        stmt = stmt.where(
            col(MachineCheck.id).is_not(None)
            if filters.check_open
            else col(MachineCheck.id).is_(None)
        )
    if filters.maintenance_state is not None and policy is not None:
        stmt = stmt.where(
            maintenance_policy.state_clause(filters.maintenance_state, policy, utcnow())
        )
    if filters.room_id is not None:
        stmt = stmt.where(col(Machine.room_id) == filters.room_id)
    if filters.building_id is not None:
        stmt = stmt.where(col(Room.building_id) == filters.building_id)
    if filters.without_room:
        stmt = stmt.where(col(Machine.room_id).is_(None))
    if filters.location_mismatch is not None:
        stmt = stmt.where(
            _mismatch_clause() if filters.location_mismatch else ~_mismatch_clause()
        )
    if filters.agent_version:
        # Equality, like the chassis kind: a version is a closed string the
        # dropdown feeds exactly, and "0.5" as a substring of "0.5.0" and
        # "10.5.0" alike would answer a question nobody asked.
        stmt = stmt.where(col(Machine.agent_version) == filters.agent_version)
    if filters.agent_outdated is not None:
        stmt = stmt.where(agent_outdated_clause(outdated or [], filters.agent_outdated))
    if filters.search:
        stmt = stmt.where(_search_clause(filters.search))
    if filters.domain:
        stmt = stmt.where(col(Machine.domain) == filters.domain)
    if filters.location:
        stmt = stmt.where(col(Machine.location) == filters.location)
    if filters.antivirus:
        # Substring rather than equality, unlike the domain filter: the dropdown
        # feeds it exact names from the fleet, but a hand-typed "eset" must find
        # "ESET Endpoint Security" too — vendors rename their products between
        # versions and a parc runs several at once.
        stmt = stmt.where(col(Machine.av_product_name).ilike(f"%{filters.antivirus}%"))
    if filters.os_version:
        # Substring like the antivirus filter, and for the same reason: the
        # dropdown feeds exact values, but "Windows 10" typed by hand must
        # gather every build of it.
        stmt = stmt.where(col(Machine.os_version).ilike(f"%{filters.os_version}%"))
    if filters.hw_model:
        # Substring again: "OptiPlex" has to gather the 7010 and the 7020, which
        # is how a parc is actually reasoned about.
        stmt = stmt.where(col(Machine.hw_model).ilike(f"%{filters.hw_model}%"))
    if filters.hw_manufacturer:
        stmt = stmt.where(
            col(Machine.hw_manufacturer).ilike(f"%{filters.hw_manufacturer}%")
        )
    if filters.cpu_model:
        # Substring like the model: "i5-8" gathers a whole generation, which is
        # the granularity a renewal plan reasons at.
        stmt = stmt.where(col(Machine.cpu_model).ilike(f"%{filters.cpu_model}%"))
    if filters.hw_chassis_type:
        # Equality: the agent normalises the kind to a short closed vocabulary
        # (desktop, laptop…), and "desktop" as a substring of nothing else.
        stmt = stmt.where(col(Machine.hw_chassis_type) == filters.hw_chassis_type)
    if filters.ram_min_gb is not None or filters.ram_max_gb is not None:
        stmt = stmt.where(ram_clause(filters.ram_min_gb, filters.ram_max_gb))
    if filters.disk_free_below is not None:
        stmt = stmt.where(low_disk_clause(filters.disk_free_below))
    if filters.software_id is not None:
        # The drill-down behind every row of the software catalogue. An EXISTS
        # and not a join: a machine carries one row per program, and joining
        # would return it once per match — here there is at most one, but the
        # shape is what keeps the pagination count honest.
        stmt = stmt.where(
            exists().where(
                (col(MachineSoftware.machine_id) == col(Machine.id))
                & (col(MachineSoftware.software_id) == filters.software_id)
            )
        )
    if filters.status is not None:
        stmt = stmt.where(
            status_clause(filters.status, utcnow(), settings.INACTIVE_AFTER_DAYS)
        )
    if filters.online is not None:
        # Its own axis, not a MachineStatus value: "allumé maintenant" must stay
        # combinable with the antivirus statuses — the everyday question is
        # "which postes are outdated *and* on, so a scan sent now will land".
        stmt = stmt.where(
            online_clause(filters.online, utcnow(), settings.OFFLINE_AFTER_SECONDS)
        )
    if filters.wu_status is not None:
        stmt = stmt.where(windows_update_clause(filters.wu_status))
    if filters.scan_type is not None:
        cutoff = utcnow() - timedelta(days=filters.scan_older_than_days)
        stmt = stmt.where(scan_clause(filters.scan_type, cutoff))
    if filters.with_active_threats is not None:
        # Same definition as the dashboard's "avec menaces" KPI: at least one
        # threat Defender has not dealt with. False selects the complement.
        active = exists().where(
            (col(Threat.machine_id) == col(Machine.id))
            & (col(Threat.status) == "active")
        )
        stmt = stmt.where(active if filters.with_active_threats else ~active)
    return stmt


@router.get("", response_model=MachineList)
async def list_machines(
    session: SessionDep,
    filters: FiltersDep,
    sort_by: MachineSortField | None = None,
    sort_desc: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> MachineList:
    """List machines with optional search/domain/location/antivirus/OS/status
    filters, plus the two facets the dashboard cards link to (Windows Update state and
    the presence of an active threat), a scan-freshness facet — which postes no
    quick/full scan has visited within ``scan_older_than_days`` — and the
    inventory facets: model, manufacturer, processor, chassis kind, memory
    bounds in GiB, system volume below a percentage of free space, and
    "carries this program". Sortable on the console list's own columns; the
    default order is freshest contact first.
    """
    versions = await fleet_versions(session)
    policy = await setting_crud.maintenance_policy(session)
    stmt = _filtered_machines(filters, versions.outdated, policy)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # last_seen then id behind the requested column: ties must land on the same
    # page from one request to the next, or rows duplicate and vanish across
    # page boundaries.
    if sort_by is None:
        stmt = stmt.order_by(col(Machine.last_seen).desc(), col(Machine.id))
    else:
        stmt = stmt.order_by(
            _sort_clause(sort_by, sort_desc, policy, versions),
            col(Machine.last_seen).desc(),
            col(Machine.id),
        )
    rows = await session.exec(stmt.offset((page - 1) * page_size).limit(page_size))
    page_rows = rows.all()
    names = await setting_crud.user_names(session, _owner_ids(page_rows, policy))
    now = utcnow()
    items = [
        _machine_out(m, room, building, check, names, policy, now)
        for m, room, building, check in page_rows
    ]
    return MachineList(
        items=items,
        total=total or 0,
        page=page,
        page_size=page_size,
        agent_latest_version=versions.latest,
    )


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


class AgentVersionOut(BaseModel):
    """One agent version present in the fleet, with how many machines run it."""

    name: str
    count: int
    # Below the reference — what makes the dropdown a deployment progress bar
    # rather than a list of strings.
    outdated: bool


class AgentVersions(BaseModel):
    """The agent versions on the parc, and the one they are measured against."""

    # The configured reference, or the highest version reported; None on an
    # empty parc.
    latest: str | None
    # Configured (``AGENT_EXPECTED_VERSION``) rather than derived from the
    # fleet: the console says which, because "latest" means two different
    # things in the two cases.
    pinned: bool
    versions: list[AgentVersionOut]


# Declared before ``/{machine_id}`` like the listings around it.
@router.get("/agent-versions", response_model=AgentVersions)
async def list_agent_versions(session: SessionDep) -> AgentVersions:
    """Agent versions reported across the fleet, newest first, each flagged
    against the reference. Feeds the console's agent filter, and the counts
    are the deployment's progress bar ("combien restent sur 0.4.1")."""
    fleet = await fleet_versions(session)
    behind = set(fleet.outdated)
    return AgentVersions(
        latest=fleet.latest,
        pinned=fleet.pinned,
        versions=[
            AgentVersionOut(name=name, count=count, outdated=name in behind)
            for name, count in fleet.counts
        ],
    )


class OsVersion(BaseModel):
    """One OS version present in the fleet, with how many machines report it."""

    name: str
    count: int


# Declared before ``/{machine_id}`` like the antivirus listing: FastAPI matches
# in declaration order, and "os-versions" would otherwise be read as an id.
@router.get("/os-versions", response_model=list[OsVersion])
async def list_os_versions(session: SessionDep) -> list[OsVersion]:
    """OS versions reported across the fleet, most widespread first.

    Feeds the console's OS filter dropdown, on the same reasoning as the
    antivirus one: which versions run on the parc is fleet data, not a list a
    client can hardcode — and the counts double as a migration progress bar
    ("how many postes are still on Windows 10").

    Machines that never reported an OS (NULL or empty) are left out: an absence
    is not a version to filter on.
    """
    name = col(Machine.os_version)
    rows = await session.exec(
        select(name, func.count().label("count"))
        .where(name.is_not(None))
        .where(name != "")
        .group_by(name)
        .order_by(func.count().desc(), name)
    )
    return [
        OsVersion(name=version, count=count)
        # `if version` narrows away the NULL the SQL already excluded.
        for version, count in rows.all()
        if version
    ]


class FleetValue(BaseModel):
    """One distinct inventory value present in the fleet, with its count."""

    name: str
    count: int


async def _distinct_values(session: SessionDep, column: Any) -> list[FleetValue]:
    """Distinct non-empty values of one machine column, most widespread first.

    The shape ``/antivirus-products`` and ``/os-versions`` already established:
    what a parc contains is fleet data, not a list a client can hardcode, and
    the counts double as an inventory in their own right.
    """
    name = col(column)
    rows = await session.exec(
        select(name, func.count().label("count"))
        .where(name.is_not(None))
        .where(name != "")
        .group_by(name)
        .order_by(func.count().desc(), name)
    )
    # `if value` narrows away the NULL the SQL already excluded.
    return [FleetValue(name=value, count=count) for value, count in rows.all() if value]


# Declared before ``/{machine_id}`` like the two listings above: FastAPI matches
# in declaration order, and "models" would otherwise be read as an id.
@router.get("/models", response_model=list[FleetValue])
async def list_models(session: SessionDep) -> list[FleetValue]:
    """Hardware models present in the fleet, most widespread first.

    The renewal plan reads this list top-down, and the console's model filter
    is fed from it.
    """
    return await _distinct_values(session, Machine.hw_model)


@router.get("/manufacturers", response_model=list[FleetValue])
async def list_manufacturers(session: SessionDep) -> list[FleetValue]:
    """Hardware manufacturers present in the fleet, most widespread first."""
    return await _distinct_values(session, Machine.hw_manufacturer)


@router.get("/processors", response_model=list[FleetValue])
async def list_processors(session: SessionDep) -> list[FleetValue]:
    """Processor models present in the fleet, most widespread first.

    Feeds the console's processor filter. The list is read the way the model
    list is: the top is what the parc is made of, the bottom is the odd poste.
    """
    return await _distinct_values(session, Machine.cpu_model)


@router.get("/chassis-types", response_model=list[FleetValue])
async def list_chassis_types(session: SessionDep) -> list[FleetValue]:
    """Chassis kinds present in the fleet (desktop, laptop…), most common first."""
    return await _distinct_values(session, Machine.hw_chassis_type)


@router.get("/locations", response_model=list[FleetValue])
async def list_locations(session: SessionDep) -> list[FleetValue]:
    """Sites the agents report, most populated first.

    Feeds the console's location filter, and the counts double as a head
    count per site. Postes whose agent names no site are not a site: they are
    left out here, and reached by clearing the filter.
    """
    return await _distinct_values(session, Machine.location)


class ExportColumnOut(BaseModel):
    """One column the fleet export can produce, as the console's picker lists it."""

    key: str
    label: str
    group: str
    group_label: str
    kind: str
    default: bool


@router.get("/export-columns", response_model=list[ExportColumnOut])
async def list_export_columns() -> list[ExportColumnOut]:
    """The export's column catalogue, in the order the picker shows it.

    Served rather than duplicated in the console: the catalogue is what the
    export reads, and a picker offering a column the server does not know
    would produce a 422 at the moment the reader clicks « Exporter ».
    """
    return [
        ExportColumnOut(
            key=c.key,
            label=c.label,
            group=c.group,
            group_label=machine_export.GROUP_LABELS[c.group],
            kind=c.kind,
            default=c.default,
        )
        for c in machine_export.COLUMNS
    ]


async def _export_rows(
    session: SessionDep, filters: MachineFilters
) -> list[machine_export.ExportRow]:
    """The filtered fleet, every row, hostname order.

    Unpaginated on purpose: an export of the first fifty rows is not an export.
    The filters are the same ones as the list, and they are what bounds it — a
    parc is thousands of rows, not millions.
    """
    versions = await fleet_versions(session)
    policy = await setting_crud.maintenance_policy(session)
    stmt = _filtered_machines(filters, versions.outdated, policy).order_by(
        func.lower(col(Machine.hostname)).nulls_last(), col(Machine.id)
    )
    rows = await session.exec(stmt)
    all_rows = rows.all()
    names = await setting_crud.user_names(session, _owner_ids(all_rows, policy))
    now = utcnow()
    return [
        machine_export.ExportRow(
            machine=m,
            room=room,
            building=building,
            check=check,
            check_assigned_to=(
                names.get(check.assigned_to_id)
                if check and check.assigned_to_id
                else None
            ),
            maintenance=maintenance_policy.resolve(m, room, policy, now),
            maintenance_owner=(
                names.get(res.owner_id)
                if (res := maintenance_policy.resolve(m, room, policy, now)).owner_id
                else None
            ),
        )
        for m, room, building, check in all_rows
    ]


# The fleet export, and deliberately not a per-machine one. A fiche is read on
# screen; and one machine's inventory is heterogeneous — sticks, disks, volumes,
# adapters, programs — so a spreadsheet of it is a shape nobody can pivot. What
# gets asked for is the parc: one row per poste, opened in Excel, sorted on
# whatever column the meeting is about — and with the columns the meeting is
# about, which is what ``columns`` chooses (see ``machine_export``).
@router.get("/export.csv")
async def export_machines_csv(
    session: SessionDep,
    filters: FiltersDep,
    columns: str | None = None,
    tz: str | None = None,
) -> Response:
    """The filtered fleet as CSV — every facet of the list, no pages.

    ``columns`` is a comma-separated list of catalogue keys (default set when
    absent); ``tz`` the IANA zone timestamps are written in (UTC when absent).
    """
    chosen = machine_export.resolve_columns(columns)
    zone = machine_export.resolve_timezone(tz)
    machines = await _export_rows(session, filters)
    return csv_response(
        "parc.csv",
        [c.label for c in chosen],
        [
            [machine_export.csv_value(c, c.read(m), zone) for c in chosen]
            for m in machines
        ],
    )


@router.get("/export.xlsx")
async def export_machines_xlsx(
    session: SessionDep,
    filters: FiltersDep,
    columns: str | None = None,
    tz: str | None = None,
) -> Response:
    """The filtered fleet as an Excel workbook, with real dates and numbers.

    Same facets, same column catalogue and the same ``tz`` as the CSV; the
    difference is what lands in the cells — values Excel can sort, filter and
    sum without a conversion step.
    """
    chosen = machine_export.resolve_columns(columns)
    zone = machine_export.resolve_timezone(tz)
    machines = await _export_rows(session, filters)
    return xlsx_response(
        "parc.xlsx",
        [c.label for c in chosen],
        [
            [machine_export.xlsx_value(c, c.read(m), zone) for c in chosen]
            for m in machines
        ],
        sheet_title="Parc",
    )


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

    ``relayed`` says which mode the server is in: emitted from here, or handed
    to a poste of the site to emit. The console words its notification on it —
    "paquet émis" is a promise the relay mode cannot make yet.
    """

    results: list[WakeOut]
    woken: int
    failed: int
    relayed: bool = False


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

    With ``WOL_RELAY_ENABLED`` the server emits nothing itself — it is not on
    the postes' network — and the row is queued instead, for the first poste of
    the target's site to claim on its heartbeat and emit from there
    (``features/wol/relay``). Same endpoint, same history, same per-poste
    outcomes; only the sentence the console shows changes.

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

        if settings.WOL_RELAY_ENABLED:
            # Queued for a poste of the site, or refused on the spot; either
            # way the relay module writes the history row itself.
            outcome = await wol_relay.queue_relayed_wake(
                session, machine, created_by=user.email
            )
            results.append(
                WakeOut(
                    machine_id=machine.id,
                    hostname=machine.hostname,
                    ok=outcome.ok,
                    detail=outcome.detail,
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
    return WakeResponse(
        results=results,
        woken=woken,
        failed=len(results) - woken,
        relayed=settings.WOL_RELAY_ENABLED,
    )


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
    _place(detail, machine, await room_crud.placement(session, machine.room_id))
    policy = await setting_crud.maintenance_policy(session)
    placement = await room_crud.placement(session, machine.room_id)
    res = maintenance_policy.resolve(machine, placement.room, policy, utcnow())
    detail.last_maintenance_at = machine.last_maintenance_at
    detail.maintenance_due_at = res.due_at
    detail.maintenance_state = res.state.value
    if res.owner_id:
        detail.maintenance_owner = (
            await setting_crud.user_names(session, {res.owner_id})
        ).get(res.owner_id)
    open_check = await check_crud.open_for_machine(session, machine.id)
    if open_check is not None:
        detail.check_open = True
        assignee = (
            await session.get(User, open_check.assigned_to_id)
            if open_check.assigned_to_id
            else None
        )
        detail.check_assigned_to = (
            (assignee.full_name or assignee.email) if assignee else None
        )
        detail.open_check = OpenCheckOut(
            id=open_check.id,
            requested_by=open_check.requested_by,
            assigned_to_id=open_check.assigned_to_id,
            assigned_to_name=detail.check_assigned_to,
            instructions=open_check.instructions,
            created_at=open_check.created_at,
        )
    detail.pending_updates = [PendingUpdateOut.model_validate(u) for u in rows.all()]
    await _attach_inventory(session, machine, detail)
    detail.agent_latest_version = (await fleet_versions(session)).latest
    return detail


async def _attach_inventory(
    session: SessionDep, machine: Machine, detail: MachineDetailOut
) -> None:
    """Load the six inventory sets onto a detail payload.

    Six small queries rather than one join: they land in six independent lists
    with nothing in common but the machine, and a join would multiply the rows
    of each by the count of the others. Each is a handful of rows behind the
    index on ``machine_id`` — except the software list, which is the reason the
    fiche is worth a page rather than a card.

    Every set is ordered explicitly. Insertion order is WMI's enumeration order,
    which is not stable between two collections, and a fiche whose disks swap
    places on refresh reads as a change that did not happen.
    """
    memory = await session.exec(
        select(MemoryModule)
        .where(col(MemoryModule.machine_id) == machine.id)
        .order_by(col(MemoryModule.slot))
    )
    detail.memory_modules = [MemoryModuleOut.model_validate(m) for m in memory.all()]

    disks = await session.exec(
        select(Disk)
        .where(col(Disk.machine_id) == machine.id)
        .order_by(col(Disk.device_id))
    )
    detail.disks = [DiskOut.model_validate(d) for d in disks.all()]

    volumes = await session.exec(
        select(Volume)
        .where(col(Volume.machine_id) == machine.id)
        .order_by(col(Volume.letter))
    )
    detail.volumes = [VolumeOut.model_validate(v) for v in volumes.all()]

    # Connected adapters first: a laptop reports a dozen, of which one is
    # carrying the traffic, and that is the one being looked for.
    nics = await session.exec(
        select(Nic)
        .where(col(Nic.machine_id) == machine.id)
        .order_by(col(Nic.is_up).desc(), col(Nic.is_virtual), col(Nic.key))
    )
    detail.nics = [NicOut.model_validate(n) for n in nics.all()]

    gpus = await session.exec(
        select(Gpu).where(col(Gpu.machine_id) == machine.id).order_by(col(Gpu.name))
    )
    detail.gpus = [GpuOut.model_validate(g) for g in gpus.all()]

    # The one join of the six: the link table holds the install facts, the
    # catalogue holds the identity, and the console needs both on one line.
    # Ordered case-folded — under a C collation "Zoom" would come before
    # "abcde", which no reader of an alphabetical list expects.
    installed = await session.exec(
        select(MachineSoftware, Software)
        .join(Software, col(MachineSoftware.software_id) == col(Software.id))
        .where(col(MachineSoftware.machine_id) == machine.id)
        .order_by(func.lower(col(Software.name)), col(Software.version))
    )
    detail.software = [
        InstalledSoftwareOut(
            software_id=soft.id if soft.id is not None else 0,
            name=soft.name,
            version=soft.version,
            publisher=soft.publisher,
            install_date=link.install_date,
            arch=link.arch,
            source=link.source,
            install_location=link.install_location,
            first_seen=link.first_seen,
        )
        for link, soft in installed.all()
    ]


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
async def revoke_token(
    machine_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> dict[str, str]:
    """Revoke a machine's token (kill-switch): its next call is rejected, and
    so is any re-enrollment attempt — the fleet-wide secret must not be enough
    to undo a revocation (plan §2.4). The way back is ``allow-reenroll``.
    """
    machine = await _require_machine(session, machine_id)
    machine.token_revoked = True
    machine.updated_at = utcnow()
    audit.record(
        session,
        actor=user.email,
        action="machine.revoke_token",
        resource_type="machine",
        resource_id=str(machine.id),
        details={"hostname": machine.hostname, "machine_uuid": machine.machine_uuid},
    )
    await session.commit()
    return {"status": "revoked"}


@router.post(
    "/{machine_id}/allow-reenroll",
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.WRITE))],
)
async def allow_reenroll(
    machine_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> dict[str, str]:
    """Lift a revocation: the machine may enroll again with the shared secret.

    The old token stays dead — ``token_hash`` is cleared rather than left in
    place, so a token stolen before the revocation never comes back to life.
    The poste returns on its next enrollment attempt with a fresh token (its
    agent drops the stale token on the first 401 and re-enrolls by itself).
    """
    machine = await _require_machine(session, machine_id)
    machine.token_revoked = False
    machine.token_hash = None
    machine.updated_at = utcnow()
    audit.record(
        session,
        actor=user.email,
        action="machine.allow_reenroll",
        resource_type="machine",
        resource_id=str(machine.id),
        details={"hostname": machine.hostname, "machine_uuid": machine.machine_uuid},
    )
    await session.commit()
    return {"status": "reenroll-allowed"}


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
