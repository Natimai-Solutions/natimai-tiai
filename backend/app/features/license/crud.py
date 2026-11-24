"""Licences against the installed programs: how many postes each one covers,
how many carry what it covers, and whether its contract is ending."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import and_, exists, func, or_, true
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.asset import crud as asset_crud
from app.features.base import contains
from app.features.inventory.models import MachineSoftware, Software
from app.features.license.models import License
from app.features.machine.models import Machine
from app.features.user.scope import Scope, machine_ids_clause

ExpiryState = Literal["none", "active", "soon", "expired"]

# Licences a parc holds at most: a school has a few dozen contracts.
MAX_LICENSES = 500
# Patterns of one licence at most.
MAX_PATTERNS = 20


def count_stmt() -> Any:
    return select(func.count()).select_from(License)


def expiry_state(end: date | None, today: date, soon_days: int) -> ExpiryState:
    """Where a contract stands: « bientôt échue » over the days of Paramètres
    (``LICENSE_EXPIRY_DAYS``), so the page, the dashboard and the digest
    cannot disagree."""
    if end is None:
        return "none"
    if end < today:
        return "expired"
    return "soon" if end <= today + timedelta(days=soon_days) else "active"


def software_clause(lic: License) -> ColumnElement[bool]:
    """The catalogue entries a licence covers: any of its patterns inside
    the program name, and its publisher inside the entry's when it names one.
    Literal substrings, as for the « logiciels interdits » list."""
    patterns = [p for p in lic.patterns if p.strip()]
    if not patterns:
        # A licence always has a pattern (the API refuses one without); a
        # row edited by hand to an empty list covers nothing, not everything.
        return col(Software.id).is_(None)
    clause = or_(*(contains(col(Software.name), p.strip()) for p in patterns))
    if lic.publisher:
        clause = and_(clause, contains(col(Software.publisher), lic.publisher))
    return clause


def machine_clause(lic: License) -> ColumnElement[bool]:
    """The postes that carry a program the licence covers — the list's
    ``license_id`` filter. An EXISTS: a poste with Office and Visio both
    covered is one installation, not two."""
    return exists().where(
        col(MachineSoftware.machine_id) == col(Machine.id),
        col(MachineSoftware.software_id).in_(
            select(col(Software.id)).where(software_clause(lic))
        ),
    )


async def installed(session: AsyncSession, lic: License, scope: Scope | None) -> int:
    """How many postes in scope carry what the licence covers, once each.
    Retired postes left out: a poste out of the parc no longer uses a seat
    (its programs are still listed until it is wiped)."""
    stmt = (
        select(func.count(func.distinct(col(MachineSoftware.machine_id))))
        .join(Software, col(Software.id) == col(MachineSoftware.software_id))
        .where(
            software_clause(lic),
            asset_crud.in_parc_ids_clause(col(MachineSoftware.machine_id)),
            machine_ids_clause(scope, col(MachineSoftware.machine_id))
            if scope is not None
            else true(),
        )
    )
    return int(await session.scalar(stmt) or 0)


async def programs(
    session: AsyncSession, lic: License, scope: Scope | None, limit: int = 50
) -> list[str]:
    """The distinct program names the licence covers, for the reader to check
    a pattern catches what was meant — and nothing else. Those installed on a
    poste of the reader's scope, as the catalogue lists them."""
    rows = await session.exec(
        select(col(Software.name))
        .where(
            software_clause(lic),
            exists().where(
                col(MachineSoftware.software_id) == col(Software.id),
                machine_ids_clause(scope, col(MachineSoftware.machine_id))
                if scope is not None
                else true(),
            ),
        )
        .group_by(col(Software.name))
        .order_by(func.lower(col(Software.name)))
        .limit(limit)
    )
    return list(rows.all())


@dataclass(frozen=True)
class LicenseState:
    license: License
    installed: int
    # More postes carry it than it covers; None when not known (a reader
    # confined to some places sees only their postes, not the parc's).
    over: bool | None
    expiry: ExpiryState


def is_over(lic: License, count: int) -> bool:
    return lic.seats is not None and count > lic.seats


async def states(
    session: AsyncSession,
    scope: Scope | None,
    today: date,
    soon_days: int,
    license_id: uuid.UUID | None = None,
) -> list[LicenseState]:
    """Every licence (or one) with its count in scope and its verdicts."""
    stmt = select(License).order_by(func.lower(col(License.name)), col(License.id))
    if license_id is not None:
        stmt = stmt.where(col(License.id) == license_id)
    licenses = list((await session.exec(stmt.limit(MAX_LICENSES))).all())
    out = []
    for lic in licenses:
        count = await installed(session, lic, scope)
        out.append(
            LicenseState(
                license=lic,
                installed=count,
                over=is_over(lic, count) if scope is None else None,
                expiry=expiry_state(lic.expires_on, today, soon_days),
            )
        )
    return out


def needs_attention(state: LicenseState) -> bool:
    """Over its count, or its contract over or ending: what the dashboard
    and the digest raise."""
    return bool(state.over) or state.expiry in ("soon", "expired")


async def attention(
    session: AsyncSession, today: date, soon_days: int
) -> list[LicenseState]:
    """The licences to look at, judged on the whole parc."""
    return [
        s for s in await states(session, None, today, soon_days) if needs_attention(s)
    ]


def audit_details(lic: License) -> dict[str, Any]:
    return {
        "name": lic.name,
        "patterns": ", ".join(lic.patterns),
        "publisher": lic.publisher,
        "seats": str(lic.seats) if lic.seats is not None else None,
        "expires_on": lic.expires_on.isoformat() if lic.expires_on else None,
        "vendor": lic.vendor,
        "reference": lic.reference,
    }
