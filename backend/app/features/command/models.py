import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class CommandType(enum.StrEnum):
    """Supported agent command types — a closed catalogue, by design.

    The wire protocol carries the *name* of a type and nothing else: no
    arguments, no command line, no script. The executable and its fixed
    arguments live in the agent's own binary, so even a compromised server can
    only ever trigger an entry of this list — never arbitrary code
    (``plan-commandes-distantes.md`` §1). Adding a command is one value here,
    one row in the agent's table and one entry in the console catalogue; the
    protocol and the schema stay untouched (``type`` is stored as a plain str).
    """

    # Defender (Phase 1).
    QUICK_SCAN = "quick_scan"
    FULL_SCAN = "full_scan"
    UPDATE_SIGNATURES = "update_signatures"

    # Maintenance: changes something on the machine, hence a confirmation in
    # the console.
    GPO_UPDATE = "gpo_update"
    FLUSH_DNS = "flush_dns"
    TIME_RESYNC = "time_resync"
    CERT_PULSE = "cert_pulse"
    SPOOLER_RESET = "spooler_reset"
    SFC_SCAN = "sfc_scan"
    DISM_RESTORE_HEALTH = "dism_restore_health"
    DISM_COMPONENT_CLEANUP = "dism_component_cleanup"
    CHKDSK_SCAN = "chkdsk_scan"

    # Windows Update (Phase 2). Two install types rather than one carrying a
    # "drivers included" flag: the protocol deliberately carries a type name and
    # nothing else, so a variant is a value here and not a payload.
    WU_SCAN = "wu_scan"
    WU_INSTALL = "wu_install"
    WU_INSTALL_FULL = "wu_install_full"
    # Moves the update store aside so Windows rebuilds it — the repair for a
    # poste whose updates no longer search, download or install. In this family
    # rather than in Maintenance because it is Windows Update it repairs, and
    # because the search that verifies it sits right beside it in the menu.
    WU_RESET = "wu_reset"
    # Never triggered on the agent's own initiative, whatever it reports as
    # needing one: a reboot is an admin decision, taken in the console behind a
    # confirmation.
    REBOOT = "reboot"

    # Diagnostics: read-only, the value is in reading ``result_output``.
    GPO_REPORT = "gpo_report"
    NET_CONFIG = "net_config"


class CommandStatus(enum.StrEnum):
    """Lifecycle of a queued command."""

    PENDING = "pending"
    DELIVERED = "delivered"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


# What an agent is allowed to report on POST /agent/commands/{id}/result. The
# rest of the lifecycle is the server's to write: an agent that could post
# "pending" or "expired" would be rewriting the queue it is only meant to drain.
AGENT_REPORTABLE_STATUSES = frozenset(
    {CommandStatus.RUNNING, CommandStatus.SUCCEEDED, CommandStatus.FAILED}
)

# States a command never leaves. A late "running" must not reopen one of these.
TERMINAL_STATUSES = frozenset(
    {CommandStatus.SUCCEEDED, CommandStatus.FAILED, CommandStatus.EXPIRED}
)


class Command(SQLModel, table=True):
    """A command queued for a single machine (one row per target, even in broadcast)."""

    __tablename__ = "commands"
    __table_args__ = (
        Index("ix_commands_machine_status", "machine_id", "status"),
        Index("ix_commands_expires_at", "expires_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    machine_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    )
    # Stored as plain strings; CommandType/CommandStatus are str enums used as
    # constants (members compare/serialize as their values, e.g. "quick_scan").
    type: str
    status: str = Field(default=CommandStatus.PENDING)
    created_by: str | None = None
    created_at: datetime = utc_field(default_factory=utcnow)
    expires_at: datetime = utc_field()
    delivered_at: datetime | None = utc_field(default=None, nullable=True)
    started_at: datetime | None = utc_field(default=None, nullable=True)
    finished_at: datetime | None = utc_field(default=None, nullable=True)
    result_output: str | None = None
    error: str | None = None
