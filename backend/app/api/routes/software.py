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

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, true
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression
from sqlmodel import col, select

from app.api.csv_export import csv_response
from app.api.deps import CurrentScope, SessionDep, require_permission
from app.api.xlsx_export import xlsx_response
from app.core.errors import AppError, ErrorCode
from app.features.asset import crud as asset_crud
from app.features.base import contains
from app.features.inventory.models import MachineSoftware, Software, WingetPackage
from app.features.machine.agent_version import latest_version
from app.features.machine.models import Machine
from app.features.user.models import Language
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope, machine_clause, machine_ids_clause, restrict

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
    return or_(
        contains(col(Software.name), search), contains(col(Software.publisher), search)
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


def _catalogue_query(search: str | None, scope: Scope | None) -> Any:
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
            # The scope sits in the join, not the WHERE: it narrows what is
            # counted, and ``HAVING`` then drops what nobody in scope carries.
            and_(
                col(MachineSoftware.software_id) == col(Software.id),
                machine_ids_clause(scope, col(MachineSoftware.machine_id))
                if scope is not None
                else true(),
            ),
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
    scope: CurrentScope,
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
    stmt = _catalogue_query(search, scope)
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


@dataclass(frozen=True)
class SoftwareExportTexts:
    """The export's words in one language: the header, the sheet, the file."""

    header: list[str]
    sheet_title: str
    file_stem: str


# The language the console asks the file in (``lang``, plan
# ``dev/plan-console-bilingue.md`` I4). French when absent: a script or an
# older console gets the file it always got.
EXPORT_TEXTS: dict[Language, SoftwareExportTexts] = {
    Language.FR: SoftwareExportTexts(EXPORT_HEADER, "Logiciels", "logiciels"),
    Language.EN: SoftwareExportTexts(
        ["Name", "Version", "Publisher", "Computers", "First seen"],
        "Software",
        "software",
    ),
}

ExportLanguage = Annotated[Language, Query(description="fr or en; fr when absent")]


async def _export_rows(
    session: SessionDep, search: str | None, scope: Scope | None
) -> list[tuple[Software, int]]:
    """The catalogue, every row, most widespread first.

    The same query as the listing without the pagination, because an export
    of the first fifty rows is not an export.
    """
    stmt = _catalogue_query(search, scope).order_by(
        _installed_count().desc(), func.lower(col(Software.name)), col(Software.version)
    )
    rows = await session.exec(stmt)
    return list(rows.all())


# Kept next to the listing it mirrors: the two exports are the same rows, and
# differ only in what lands in the cells — text for the CSV, a real date for
# Excel, which is what makes the column sortable there.
class WingetUpdateOut(BaseModel):
    """One program winget knows, across the postes that report it (C5)."""

    winget_id: str
    name: str | None
    # Postes that have it, and those of them winget would upgrade.
    installed: int
    outdated: int
    # The newest version winget offers anywhere in the parc.
    available: str | None
    # Share of the postes having it that are up to date, in percent.
    up_to_date_percent: float


class WingetUpdateList(BaseModel):
    items: list[WingetUpdateOut]
    # Postes reporting their winget packages, in scope: what the figures are
    # out of — the collection is a switch of the agent.
    reporting: int


# Distinct programs listed at most: a parc has a few hundred.
MAX_WINGET_ROWS = 1000


@router.get("/updates", response_model=WingetUpdateList)
async def list_winget_updates(
    session: SessionDep,
    scope: CurrentScope,
    search: str | None = None,
    outdated_only: bool = False,
) -> WingetUpdateList:
    """Third-party updates: per program, how many postes winget would
    upgrade, most behind first. Retired postes left out, like every count."""
    in_scope = (
        machine_ids_clause(scope, col(WingetPackage.machine_id))
        if scope is not None
        else true()
    )
    in_parc = asset_crud.in_parc_ids_clause(col(WingetPackage.machine_id))
    is_outdated = and_(
        col(WingetPackage.available).is_not(None), col(WingetPackage.available) != ""
    )
    outdated = func.count().filter(is_outdated)
    stmt = (
        select(
            col(WingetPackage.winget_id),
            func.max(col(WingetPackage.name)),
            func.count(),
            outdated,
        )
        .where(in_scope, in_parc)
        .group_by(col(WingetPackage.winget_id))
    )
    if search:
        stmt = stmt.where(
            or_(
                contains(col(WingetPackage.winget_id), search),
                contains(col(WingetPackage.name), search),
            )
        )
    if outdated_only:
        stmt = stmt.having(outdated > 0)
    stmt = stmt.order_by(
        outdated.desc(), func.lower(func.max(col(WingetPackage.name)))
    ).limit(MAX_WINGET_ROWS)
    rows = (await session.exec(stmt)).all()

    # The newest version offered, by a human's reading of version numbers.
    ids = [r[0] for r in rows]
    offered: dict[str, list[str]] = {}
    if ids:
        avail = await session.exec(
            select(col(WingetPackage.winget_id), col(WingetPackage.available))
            .where(
                col(WingetPackage.winget_id).in_(ids), is_outdated, in_scope, in_parc
            )
            .distinct()
        )
        for winget_id, version in avail.all():
            if version:
                offered.setdefault(winget_id, []).append(version)

    reporting = (
        await session.scalar(
            restrict(
                select(func.count()).select_from(Machine),
                machine_clause(scope),
            ).where(
                col(Machine.winget_reported_at).is_not(None),
                asset_crud.in_parc_clause(),
            )
        )
        or 0
    )
    return WingetUpdateList(
        items=[
            WingetUpdateOut(
                winget_id=winget_id,
                name=name,
                installed=installed,
                outdated=behind,
                available=latest_version(offered.get(winget_id, [])),
                up_to_date_percent=round(100 * (installed - behind) / installed, 1)
                if installed
                else 100.0,
            )
            for winget_id, name, installed, behind in rows
        ],
        reporting=reporting,
    )


@router.get("/export.csv")
async def export_software(
    session: SessionDep,
    scope: CurrentScope,
    search: str | None = None,
    lang: ExportLanguage = Language.FR,
) -> Response:
    """The catalogue as CSV, honouring the same search."""
    texts = EXPORT_TEXTS[lang]
    return csv_response(
        f"{texts.file_stem}.csv",
        texts.header,
        [
            (
                entry.name,
                entry.version,
                entry.publisher,
                count,
                entry.first_seen.date().isoformat(),
            )
            for entry, count in await _export_rows(session, search, scope)
        ],
        lang,
    )


@router.get("/export.xlsx")
async def export_software_xlsx(
    session: SessionDep,
    scope: CurrentScope,
    search: str | None = None,
    lang: ExportLanguage = Language.FR,
) -> Response:
    """The catalogue as an Excel workbook, honouring the same search."""
    texts = EXPORT_TEXTS[lang]
    return await xlsx_response(
        f"{texts.file_stem}.xlsx",
        texts.header,
        [
            (entry.name, entry.version, entry.publisher, count, entry.first_seen.date())
            for entry, count in await _export_rows(session, search, scope)
        ],
        sheet_title=texts.sheet_title,
    )


class SoftwareRef(BaseModel):
    """What names a catalogue entry — for the filter chip of the machine list
    (audit U08). The catalogue is the parc's, not scoped: it names programs,
    not postes."""

    id: int
    name: str
    version: str
    publisher: str


@router.get("/{software_id}", response_model=SoftwareRef)
async def get_software(software_id: int, session: SessionDep) -> SoftwareRef:
    entry = await session.get(Software, software_id)
    if entry is None or entry.id is None:
        raise AppError(
            code=ErrorCode.HTTP_NOT_FOUND, status_code=404, message="Software not found"
        )
    return SoftwareRef(
        id=entry.id, name=entry.name, version=entry.version, publisher=entry.publisher
    )
