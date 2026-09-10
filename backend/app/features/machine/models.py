import uuid
from datetime import date, datetime

from sqlalchemy import Column, ForeignKey, Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class Machine(SQLModel, table=True):
    """A managed Windows endpoint, identified by its stable MachineGuid."""

    __tablename__ = "machines"
    __table_args__ = (
        Index("ix_machines_hostname", "hostname"),
        Index("ix_machines_domain", "domain"),
        Index("ix_machines_location", "location"),
        Index("ix_machines_last_seen", "last_seen"),
        Index("ix_machines_is_up_to_date", "is_up_to_date"),
        Index("ix_machines_needs_verification", "needs_verification"),
        Index("ix_machines_smbios_uuid", "smbios_uuid"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Stable identity resolved by the agent: validated SMBIOS UUID, else a
    # persisted agent-generated UUID. Never the hostname. See plan §2.3.
    machine_uuid: str = Field(unique=True, index=True)

    # Identity fingerprint — components stored separately (not hashed) so the
    # server can diff them and tell a benign rename from a suspicious hardware
    # change. A suspicious delta sets needs_verification.
    machine_guid: str | None = (
        None  # HKLM Cryptography MachineGuid (dup on non-sysprep clones)
    )
    smbios_uuid: str | None = None  # Win32_ComputerSystemProduct.UUID (anchor)
    tpm_ek_hash: str | None = None  # hash of the TPM 2.0 EK public, when present
    needs_verification: bool = Field(default=False)

    # Attributes (may change over time)
    hostname: str | None = None
    domain: str | None = None
    # Where the poste physically is — "Lycée de Taravao" — as its agent's
    # configuration names it (YAML ``location`` or registry ``Location``). Free
    # text chosen by the deployment, never derived: nothing on a machine says
    # which building it is in. NULL = the agent reports none, which is the
    # default, and an agent that clears its setting clears this too.
    #
    # Two readers. The console, which filters and groups the parc by it — the
    # question "which postes are at this site" that the domain cannot answer
    # once one domain spans several sites. And the Wake-on-LAN relay, which
    # asks the same question for a harder reason: only a poste on the same wire
    # can put a magic packet in front of the one to wake (``features/wol``).
    location: str | None = None
    # The room the console (or the directory, ``ROOM_SOURCE``) placed the poste
    # in — ``features/room``. Distinct from ``location`` above, which the agent
    # owns: a room belongs to a building, which sits on a site, and a poste
    # whose two answers disagree is flagged in the list. SET NULL: deleting a
    # room leaves its postes standing, room-less.
    room_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    # What the domain says about the poste, as its agent read it on the
    # inventory cycle: the computer object's DN, the OU holding it (name and
    # DN), and the object's "location" attribute. Stored whatever
    # ``ROOM_SOURCE`` says — shown on the fiche regardless, and the input of
    # a directory-driven placement, re-runnable from the console when the
    # setting changes. NULL = never reported: a workgroup poste, or an agent
    # older than the field.
    ad_distinguished_name: str | None = None
    ad_ou: str | None = None
    ad_ou_dn: str | None = None
    ad_location: str | None = None
    # Maintenance: the poste's own cycle and owner, overriding its room's and
    # the parc's (``maintenance/policy.py``); NULL = inherit, 0 = excluded.
    # ``last_maintenance_at`` is denormalised from the journal — it is what
    # the list sorts and filters on, and a poste is due at
    # ``COALESCE(last_maintenance_at, first_seen) + cycle``.
    maintenance_cycle_days: int | None = None
    maintenance_owner_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    last_maintenance_at: datetime | None = utc_field(default=None, nullable=True)
    os_version: str | None = None
    agent_version: str | None = None
    # Primary IP address elected by the agent among the machine's addresses
    # (loopback and 169.254.0.0/16 excluded), refreshed on each heartbeat. Only
    # as fresh as last_seen: a DHCP lease outlives neither. NULL = never
    # reported — an agent older than the feature, or a host with no usable
    # address.
    ip_address: str | None = None
    # Hardware address of the adapter holding ``ip_address``, canonicalised
    # server-side as "AA:BB:CC:DD:EE:FF". The wake target: a magic packet names
    # this MAC and is broadcast on the subnet of the address above, which is why
    # the agent elects both from the same adapter rather than reporting them
    # independently. NULL = never reported — an agent older than the feature, or
    # an adapter with no usable hardware address (a PPP or tunnel pseudo-NIC) —
    # and a machine with no MAC simply cannot be woken from the console.
    mac_address: str | None = None
    # The mask that goes with ``ip_address``, as the poste's own adapter holds
    # it: 16 for a machine in 10.4.0.0/16. Reported rather than assumed, because
    # only the poste knows — a server-side default is right by accident on a flat
    # /24 parc and wrong on every other. It is what turns the address above into
    # the broadcast address a magic packet has to be sent to.
    #
    # NULL = never reported (an agent older than the feature, or an adapter whose
    # prefix Windows did not fill in), and the wake then falls back on
    # ``WOL_SUBNET_PREFIXLEN``.
    ip_prefix_length: int | None = None

    # Defender state (derived from MSFT_MpComputerStatus)
    rtp_enabled: bool | None = None
    av_enabled: bool | None = None
    signature_version: str | None = None
    signature_last_updated: datetime | None = utc_field(default=None, nullable=True)
    signature_age_days: int | None = None
    last_quick_scan: datetime | None = utc_field(default=None, nullable=True)
    last_full_scan: datetime | None = utc_field(default=None, nullable=True)
    # AMRunningMode: Normal / Passive / SxS Passive Mode / EDR Block Mode. What
    # explains the two flags above reading "off" on a machine that is in fact
    # protected — a third-party antivirus pushed Defender aside.
    running_mode: str | None = None
    is_up_to_date: bool | None = None

    # Antivirus registered with the Windows Security Center, the only place a
    # *third-party* product is visible (the Defender columns above describe
    # Defender alone). Refreshed on each heartbeat.
    #
    # Three states on the name, all distinct: NULL = never reported (an agent
    # older than the feature, or a host with no Security Center — Windows Server
    # has none); "" = the registry was read and is empty, i.e. no antivirus at
    # all, which is a finding rather than an absence of data; a name = the
    # elected product. No index: the console searches this with a substring
    # ILIKE, which no btree would serve, and groups it over a table this size.
    av_product_name: str | None = None
    av_product_enabled: bool | None = None
    av_product_signatures_up_to_date: bool | None = None
    # Whether the product above is Defender itself. Decided by the agent, which
    # holds the evidence (instanceGuid); matching product names here would be
    # brittle and locale-dependent.
    av_product_is_defender: bool | None = None

    # Windows Update state, refreshed on the agent's own slow cycle (hours) and
    # not on every heartbeat: a WU search takes minutes. NULL on the count means
    # "never reported" — an agent older than the feature, or a host whose WU
    # service could not be queried — which the console renders as unknown rather
    # than as "nothing to install".
    #
    # wu_pending_count is derived server-side from the reported list, not taken
    # from the agent: the badge in the list and the table on the detail page then
    # cannot disagree.
    wu_pending_count: int | None = None
    # NOT NULL, unlike the columns around it: a machine that never reported is
    # not "pending a reboot", and false is the honest default. The console shows
    # nothing for it, so there is no unknown state to represent.
    wu_reboot_required: bool = Field(default=False)
    wu_last_search: datetime | None = utc_field(default=None, nullable=True)
    wu_last_install: datetime | None = utc_field(default=None, nullable=True)

    # --- Inventory (dev/plan-inventaire.md), refreshed on the agent's own daily
    # cycle and only when something actually changed. Everything here has
    # cardinality one: the sticks, disks, volumes, adapters, GPUs and programs
    # live in the inventory_* tables. NULL = never reported, throughout.
    hw_manufacturer: str | None = None
    hw_model: str | None = None
    hw_serial: str | None = None  # chassis serial, the sticker an asset tag copies
    hw_chassis_type: str | None = None  # desktop / laptop / mini / virtual…
    # NOT NULL: a machine that never reported is not a virtual one, and false is
    # the honest default. Load-bearing beyond display — a VM has no battery, no
    # SMART and no BIOS to flash, so half the hardware alerts have to skip it.
    hw_is_virtual: bool = Field(default=False)
    hw_hypervisor: str | None = None
    mb_manufacturer: str | None = None
    mb_model: str | None = None
    mb_serial: str | None = None
    bios_vendor: str | None = None
    bios_version: str | None = None
    # A date and not a timestamp: firmware is dated to the day, and a midnight-UTC
    # instant would shift across the date line for no reason. It is also the
    # closest thing to the machine's age, which is what a renewal plan reads.
    bios_date: date | None = None
    secure_boot: bool | None = None
    tpm_version: str | None = None
    # One CPU, in columns rather than in a table as GLPI has it: a workstation is
    # single-socket, and the rare dual-socket one carries two identical
    # processors by construction. cpu_count says how many.
    cpu_model: str | None = None
    cpu_manufacturer: str | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    cpu_speed_mhz: int | None = None
    cpu_count: int | None = None
    # Totals, so the machine list can show memory without joining to the sticks.
    ram_total_mb: int | None = None
    ram_slots_total: int | None = None
    ram_slots_used: int | None = None
    os_architecture: str | None = None
    os_install_date: datetime | None = utc_field(default=None, nullable=True)
    last_boot_time: datetime | None = utc_field(default=None, nullable=True)
    # The system volume's size and free space, derived server-side from the
    # reported volumes rather than sent as fields of their own — the same
    # reasoning as wu_pending_count. They are here, denormalised out of
    # inventory_volumes, because "quels postes n'ont plus de place" is a
    # fleet-wide question: a column sorts, filters and counts, where a
    # correlated subquery over a child table would do none of the three cheaply.
    # It is also the disk figure that matters — a full C: is the first cause of
    # a poste that stops taking Windows updates.
    system_volume_total_mb: int | None = None
    system_volume_free_mb: int | None = None
    # The agent's own hash of the inventory it last sent. Compared before writing:
    # an agent that restarted re-sends an inventory the server already holds, and
    # matching this lets the whole set replacement be skipped.
    inventory_hash: str | None = None
    # When that inventory was taken — deliberately *not* last_seen. A poste seen
    # a minute ago whose inventory is three weeks old is an anomaly to show, not
    # to hide behind a fresh heartbeat.
    inventory_last_seen: datetime | None = utc_field(default=None, nullable=True)

    # Interactive session (WTS), refreshed on each heartbeat. NULL means "never
    # reported" — an agent older than the feature, or a failed read — which is
    # distinct from False, "nobody is logged on". session_username stays NULL
    # when the agent reports presence only (report_session_username=false), so
    # the console can tell "name withheld by policy" from "agent too old".
    session_user_present: bool | None = None
    session_username: str | None = None
    session_state: str | None = None  # active / disconnected
    session_is_remote: bool | None = None

    # Per-machine auth: only the token hash is stored.
    token_hash: str | None = None
    token_revoked: bool = Field(default=False)

    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
