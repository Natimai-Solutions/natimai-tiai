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


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge: the duplicate's asset follows the poste. When the kept record
    already has its own, the two describe one machine: the kept one wins,
    the duplicate's fills only what it leaves empty — the inventory number
    on the sticker among them — and is then dropped. Left unbound instead, it
    would be a nameless asset no confined account sees, holding its
    inventory number out of their reach. A label printed from the
    duplicate's token stops resolving: the kept one's is to be printed."""
    target = await for_machine(session, target_id)
    source = await for_machine(session, source_id)
    if target is not None and source is not None:
        filled = {
            name: getattr(source, name)
            for name in _PURCHASE_FIELDS
            if getattr(target, name) is None and getattr(source, name) is not None
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
