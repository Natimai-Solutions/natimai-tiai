"""The parc's software catalogue.

The reason the inventory module is worth building. A fiche answers "what is on
this poste"; this answers "qui a encore Java 8", which is the question an
administrator actually arrives with — and the one a per-machine list of programs
cannot answer at all.

There is deliberately no ``/software/{id}/machines`` here. The machine list
already carries pagination, sorting and a dozen filters, so the drill-down is
``GET /machines?software_id=…`` — the console links straight to a pre-filtered
list, and "qui a Java 8 *et* est allumé" costs nothing extra.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression
from sqlmodel import col, select

from app.api.csv_export import csv_response
from app.api.deps import SessionDep, require_permission
from app.api.xlsx_export import xlsx_response
from app.features.inventory.models import MachineSoftware, Software
from app.features.user.permissions import Action, Resource

router = APIRouter(
    prefix="/software",
    tags=["software"],
    # Machine data under another name: a read-only operator sees it, and no new
    # permission is minted for it.
    dependencies=[Depends(require_permission(Resource.MACHINE, Action.READ))],
)


class SoftwareOut(BaseModel):
    """One catalogue entry and how much of the parc carries it."""

    id: int
    name: str
    version: str
    publisher: str
    machine_count: int
    # When this exact version first appeared anywhere in the parc — which is
    # what says whether a rollout has started or is finished.
    first_seen: datetime


class SoftwareList(BaseModel):
    """Paginated catalogue."""

    items: list[SoftwareOut]
    total: int
    page: int
    page_size: int


SoftwareSortField = Literal["name", "version", "publisher", "machine_count"]


def _search_clause(search: str) -> ColumnElement[bool]:
    """Name or publisher. Substring on both: nobody types a version string in full."""
    pattern = f"%{search}%"
    return or_(
        col(Software.name).ilike(pattern), col(Software.publisher).ilike(pattern)
    )


def _installed_count() -> ColumnElement[int]:
    """How many machines carry this entry.

    ``count`` over the joined column and not ``count(*)``: the join is an outer
    one, so a catalogue entry nobody carries would otherwise count as one.
    """
    return func.count(col(MachineSoftware.machine_id))


def _sort_clause(field: SoftwareSortField, descending: bool) -> UnaryExpression[Any]:
    """ORDER BY expression for one sortable column."""
    if field == "machine_count":
        key: ColumnElement[Any] = _installed_count()
    else:
        # Case-folded: under a C collation "Zoom" would come before "abcde",
        # which no reader of an alphabetical list expects.
        key = func.lower(col(getattr(Software, field)))
    return key.desc() if descending else key.asc()


def _catalogue_query(search: str | None) -> Any:
    """The grouped catalogue, entries nobody carries excluded.

    ``HAVING count > 0`` is the whole difference between a catalogue and a
    graveyard: deleting a machine leaves its programs behind (the rows are the
    stable ids a deployed package will hang on, so they are not cascaded away),
    and a page titled "logiciels du parc" listing programs no poste has is
    telling the reader something false.
    """
    count = _installed_count()
    stmt = (
        select(Software, count.label("machine_count"))
        .join(
            MachineSoftware,
            col(MachineSoftware.software_id) == col(Software.id),
            isouter=True,
        )
        .group_by(col(Software.id))
        .having(count > 0)
    )
    if search:
        stmt = stmt.where(_search_clause(search))
    return stmt


@router.get("", response_model=SoftwareList)
async def list_software(
    session: SessionDep,
    search: str | None = None,
    sort_by: SoftwareSortField = "machine_count",
    sort_desc: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> SoftwareList:
    """The parc's software catalogue, most widespread first.

    That default order is the useful one: the top of the list is the standard
    the parc actually runs, and the bottom is where the one poste with an
    unapproved program sits.
    """
    stmt = _catalogue_query(search)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    # Name then version behind the requested column: ties must land on the same
    # page from one request to the next, or rows duplicate across page
    # boundaries — the same rule the machine list follows.
    stmt = stmt.order_by(
        _sort_clause(sort_by, sort_desc),
        func.lower(col(Software.name)),
        col(Software.version),
    )
    rows = await session.exec(stmt.offset((page - 1) * page_size).limit(page_size))
    items = [
        SoftwareOut(
            id=entry.id if entry.id is not None else 0,
            name=entry.name,
            version=entry.version,
            publisher=entry.publisher,
            machine_count=count,
            first_seen=entry.first_seen,
        )
        for entry, count in rows.all()
    ]
    return SoftwareList(items=items, total=total or 0, page=page, page_size=page_size)


EXPORT_HEADER = ["Nom", "Version", "Éditeur", "Postes", "Vu pour la première fois"]


async def _export_rows(
    session: SessionDep, search: str | None
) -> list[tuple[Software, int]]:
    """The catalogue, every row, most widespread first.

    The same query as the listing without the pagination, because an export
    of the first fifty rows is not an export.
    """
    stmt = _catalogue_query(search).order_by(
        _installed_count().desc(), func.lower(col(Software.name)), col(Software.version)
    )
    rows = await session.exec(stmt)
    return list(rows.all())


# Kept next to the listing it mirrors: the two exports are the same rows, and
# differ only in what lands in the cells — text for the CSV, a real date for
# Excel, which is what makes the column sortable there.
@router.get("/export.csv")
async def export_software(session: SessionDep, search: str | None = None) -> Response:
    """The catalogue as CSV, honouring the same search."""
    return csv_response(
        "logiciels.csv",
        EXPORT_HEADER,
        [
            (
                entry.name,
                entry.version,
                entry.publisher,
                count,
                entry.first_seen.date().isoformat(),
            )
            for entry, count in await _export_rows(session, search)
        ],
    )


@router.get("/export.xlsx")
async def export_software_xlsx(
    session: SessionDep, search: str | None = None
) -> Response:
    """The catalogue as an Excel workbook, honouring the same search."""
    return xlsx_response(
        "logiciels.xlsx",
        EXPORT_HEADER,
        [
            (entry.name, entry.version, entry.publisher, count, entry.first_seen.date())
            for entry, count in await _export_rows(session, search)
        ],
        sheet_title="Logiciels",
    )
