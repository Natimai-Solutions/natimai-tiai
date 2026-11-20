"""Assets around a poste: read, written, moved on a merge, and the clauses
the list, the dashboard and the alerts read them through."""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, not_, update
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, exists, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.asset.models import Asset, AssetStatus
from app.features.base import utcnow
from app.features.machine.models import Machine


async def for_machine(session: AsyncSession, machine_id: uuid.UUID) -> Asset | None:
    return (
        await session.exec(select(Asset).where(col(Asset.machine_id) == machine_id))
    ).first()


async def by_token(session: AsyncSession, token: str) -> Asset | None:
    return (
        await session.exec(select(Asset).where(col(Asset.public_token) == token))
    ).first()


def retired_clause() -> ColumnElement[bool]:
    """Postes whose asset is retired — out of the parc."""
    return exists().where(
        col(Asset.machine_id) == col(Machine.id),
        col(Asset.status) == AssetStatus.RETIRED,
    )


def in_parc_clause() -> ColumnElement[bool]:
    """Postes still in the parc: every poste but the retired ones (a poste
    with no asset at all is in the parc)."""
    return not_(retired_clause())


def in_parc_ids_clause(machine_id: Any) -> ColumnElement[bool]:
    """``in_parc_clause`` for a table that names its poste by ``machine_id``
    (a threat, an alert, a verification) without joining ``machines``."""
    return not_(
        exists().where(
            col(Asset.machine_id) == machine_id,
            col(Asset.status) == AssetStatus.RETIRED,
        )
    )


def purchase_date_expr() -> ColumnElement[date | None]:
    """A poste's purchase date, as SQL: its asset's, NULL without one."""
    return (
        select(col(Asset.purchase_date))
        .where(col(Asset.machine_id) == col(Machine.id))
        .correlate(Machine)
        .scalar_subquery()
    )


def age_reference_expr() -> ColumnElement[date | None]:
    """The date a poste's age counts from: when it was bought, when that is
    known, else the date of its BIOS — the only age a poste knows about
    itself."""
    return func.coalesce(purchase_date_expr(), col(Machine.bios_date))


def aging_clause(now: datetime, years: int) -> ColumnElement[bool]:
    """Postes older than ``years`` — the renewal plan's figure. NULL on both
    dates matches nothing: never reported is not old."""
    cutoff = (now - timedelta(days=365 * years)).date()
    return age_reference_expr() < cutoff


# What a duplicate's asset can fill in on the kept record's, field by field.
_PURCHASE_FIELDS = (
    "inventory_number",
    "purchase_date",
    "supplier",
    "order_reference",
    "warranty_end",
    "purchase_price",
    "borrower",
    "loan_due",
    "notes",
)


_LOAN_FIELDS = ("borrower", "loan_due")


async def dropped_asset(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> Asset | None:
    """The duplicate's asset a merge into ``target_id`` will drop: there is
    one only when both records have their own (``move_to``)."""
    if await for_machine(session, target_id) is None:
        return None
    return await for_machine(session, source_id)


def dropped_asset_details(asset: Asset) -> dict[str, str | None]:
    """The audit line of an asset a merge drops: what it held, the price
    recorded as set, not its value — like every asset write."""

    def text(value: object) -> str | None:
        return None if value is None else str(value)

    return {
        "inventory_number": asset.inventory_number,
        "status": asset.status,
        "purchase_date": text(asset.purchase_date),
        "supplier": asset.supplier,
        "order_reference": asset.order_reference,
        "warranty_end": text(asset.warranty_end),
        "purchase_price": "•" if asset.purchase_price is not None else None,
        "borrower": asset.borrower,
        "loan_due": text(asset.loan_due),
    }


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge: the duplicate's asset follows the poste. When the kept record
    already has its own, the two describe one machine: the kept one wins,
    the duplicate's fills only what it leaves empty — the inventory number
    on the sticker among them — and is then dropped. Left unbound instead, it
    would be a nameless asset no confined account sees, holding its
    inventory number out of their reach. A label printed from the
    duplicate's token stops resolving: the kept one's is to be printed. The
    route records what the dropped asset held (``dropped_asset_details``)."""
    target = await for_machine(session, target_id)
    source = await for_machine(session, source_id)
    if target is not None and source is not None:
        filled = {
            name: getattr(source, name)
            for name in _PURCHASE_FIELDS
            if getattr(target, name) is None
            and getattr(source, name) is not None
            # A loan means something only on an asset on loan.
            and (name not in _LOAN_FIELDS or target.status == AssetStatus.ON_LOAN)
        }
        # The inventory number is unique: the duplicate goes before the kept
        # record takes it.
        await session.delete(source)
        await session.flush()
        for name, value in filled.items():
            setattr(target, name, value)
        if filled:
            target.updated_at = utcnow()
            session.add(target)
        return
    await session.exec(
        update(Asset)
        .where(col(Asset.machine_id) == source_id)
        .values(machine_id=target_id)
    )
