"""Assets around a poste: read, written, moved on a merge, and the clauses
the list, the dashboard and the alerts read them through."""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, not_, update
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, exists, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.asset.models import Asset, AssetStatus
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


async def move_to(
    session: AsyncSession, *, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """A merge: the duplicate's asset follows the poste, unless the kept
    record already has its own — which wins, the duplicate's then left
    unbound rather than lost (still listed among the equipment)."""
    if await for_machine(session, target_id) is not None:
        await session.exec(
            update(Asset)
            .where(col(Asset.machine_id) == source_id)
            .values(machine_id=None)
        )
        return
    await session.exec(
        update(Asset)
        .where(col(Asset.machine_id) == source_id)
        .values(machine_id=target_id)
    )
