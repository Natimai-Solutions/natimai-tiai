import uuid
from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class Machine(SQLModel, table=True):
    """A managed Windows endpoint, identified by its stable MachineGuid."""

    __tablename__ = "machines"
    __table_args__ = (
        Index("ix_machines_hostname", "hostname"),
        Index("ix_machines_domain", "domain"),
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
