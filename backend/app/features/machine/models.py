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

    # Defender state (derived from MSFT_MpComputerStatus)
    rtp_enabled: bool | None = None
    av_enabled: bool | None = None
    signature_version: str | None = None
    signature_last_updated: datetime | None = utc_field(default=None, nullable=True)
    signature_age_days: int | None = None
    last_quick_scan: datetime | None = utc_field(default=None, nullable=True)
    last_full_scan: datetime | None = utc_field(default=None, nullable=True)
    is_up_to_date: bool | None = None

    # Per-machine auth: only the token hash is stored.
    token_hash: str | None = None
    token_revoked: bool = Field(default=False)

    first_seen: datetime = utc_field(default_factory=utcnow)
    last_seen: datetime = utc_field(default_factory=utcnow)
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
