"""An asset: where a piece of equipment stands in its life.

The inventory says what a poste *is*; nothing said when it was bought, until
when it is under warranty, whether it is in service, lent, or retired. An
asset holds that — for a poste (``machine_id``, one asset at most per poste)
or for equipment no agent runs on: a projector, a printer, a screen, filed in
a room.

A table of its own rather than more columns on ``machines``: that table is
the agent's picture of the poste, already a hundred columns wide, and a
projector has no machine record to hang them on (plan
``dev/plan-evolutions-itil.md``, C2).
"""

import enum
import secrets
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, ForeignKey, Index, Numeric
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class AssetStatus(enum.StrEnum):
    IN_STOCK = "in_stock"
    IN_SERVICE = "in_service"
    IN_REPAIR = "in_repair"
    ON_LOAN = "on_loan"
    # Out of the parc: left out of the dashboard's counts and of the alerts.
    RETIRED = "retired"


class AssetKind(enum.StrEnum):
    # A poste with an agent: the kind of every asset bound to a machine.
    COMPUTER = "computer"
    PRINTER = "printer"
    PROJECTOR = "projector"
    SCREEN = "screen"
    NETWORK = "network"
    OTHER = "other"


def new_public_token() -> str:
    """The opaque token an asset's QR label carries. 128 bits, URL-safe: the
    label must name the asset to whoever scans it signed in, and nothing to
    whoever only photographs it — not its id, not its serial."""
    return secrets.token_urlsafe(16)


class Asset(SQLModel, table=True):
    __tablename__ = "assets"
    __table_args__ = (
        # The number written on the sticker: unique where given.
        Index(
            "uq_assets_inventory_number",
            "inventory_number",
            unique=True,
            postgresql_where="inventory_number IS NOT NULL",
        ),
        Index("ix_assets_status", "status"),
        Index("ix_assets_warranty_end", "warranty_end"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # The poste this is the asset of; NULL for equipment without an agent.
    # SET NULL rather than CASCADE: a poste record deleted does not erase
    # what was paid for it (a merge moves the asset to the kept record).
    machine_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("machines.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
    )
    kind: str = Field(default=AssetKind.COMPUTER, max_length=20)
    # For equipment without an agent: what it is called, where it is, what
    # it is. A poste's own come from its machine record.
    name: str | None = Field(default=None, max_length=200)
    room_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)

    inventory_number: str | None = Field(default=None, max_length=100)
    status: str = Field(default=AssetStatus.IN_SERVICE, max_length=20)
    purchase_date: date | None = None
    supplier: str | None = Field(default=None, max_length=200)
    order_reference: str | None = Field(default=None, max_length=200)
    warranty_end: date | None = None
    purchase_price: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(12, 2), nullable=True)
    )
    # A loan: to whom, and until when.
    borrower: str | None = Field(default=None, max_length=200)
    loan_due: date | None = None
    notes: str | None = Field(default=None, max_length=5000)

    public_token: str = Field(
        default_factory=new_public_token, max_length=64, unique=True
    )
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
    updated_by: str | None = Field(default=None, max_length=255)
