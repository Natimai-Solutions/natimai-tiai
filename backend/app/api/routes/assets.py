"""Assets: purchase, warranty, status and loans of the postes, and the
equipment no agent runs on (dev/plan-evolutions-itil.md, C2).

``asset:read`` to read, ``asset:write`` to write — a resource of its own, so
that a purchase price is not read by everyone who reads the parc. Within the
caller's scope: a poste's asset follows its poste, an asset without a poste
follows its room (and one in no room is seen by the unrestricted only).

Also here: the import (a sheet matched on serial numbers, previewed before
it is written), the QR labels' token, and the lookup a scanned label makes —
the one route of this file read with ``machine:read``, since whoever scans a
poste's sticker wants its fiche, purchase price or not.
"""

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.api.fields import not_null
from app.core.errors import AppError, ErrorCode
from app.features.asset import crud, importer
from app.features.asset.models import Asset, AssetKind, AssetStatus, new_public_token
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.room import crud as room_crud
from app.features.room.models import Room
from app.features.setting import crud as setting_crud
from app.features.user.permissions import Action, Resource
from app.features.user.scope import (
    Scope,
    machine_clause,
    machine_visible,
    room_clause,
)

router = APIRouter(prefix="/assets", tags=["assets"])
machine_router = APIRouter(prefix="/machines", tags=["assets"])

_READ = Depends(require_permission(Resource.ASSET, Action.READ))
_WRITE = Depends(require_permission(Resource.ASSET, Action.WRITE))
_MACHINE_READ = Depends(require_permission(Resource.MACHINE, Action.READ))

# An import file read at most: a delivery note or an accounting export.
MAX_IMPORT_BYTES = 8 * 1024 * 1024

WarrantyState = Literal["none", "active", "soon", "expired"]


def warranty_state(end: date | None, today: date, soon_days: int) -> WarrantyState:
    """Where a warranty stands: « bientôt terminée » over the same days as
    the alert « Garantie bientôt terminée » (Paramètres), so the fiche, the
    list's filter and the alert cannot disagree."""
    if end is None:
        return "none"
    if end < today:
        return "expired"
    return "soon" if end <= today + timedelta(days=soon_days) else "active"


def _trim(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class AssetFields(BaseModel):
    """The fields a person writes. Absent = unchanged on a patch; null clears."""

    kind: AssetKind | None = None
    name: str | None = Field(default=None, max_length=200)
    room_id: uuid.UUID | None = None
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)
    inventory_number: str | None = Field(default=None, max_length=100)
    status: AssetStatus | None = None
    purchase_date: date | None = None
    supplier: str | None = Field(default=None, max_length=200)
    order_reference: str | None = Field(default=None, max_length=200)
    warranty_end: date | None = None
    purchase_price: Decimal | None = Field(
        default=None, ge=0, lt=Decimal("1e10"), decimal_places=2
    )
    borrower: str | None = Field(default=None, max_length=200)
    loan_due: date | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator(
        "name",
        "manufacturer",
        "model",
        "serial_number",
        "inventory_number",
        "supplier",
        "order_reference",
        "borrower",
        "notes",
        mode="before",
    )
    @classmethod
    def _blank_is_null(cls, value: Any) -> Any:
        return _trim(value)

    # Absent leaves it as it is; null would clear a column that is never
    # empty (a null kind reads as « autre », below).
    _not_null = not_null("status")


class AssetCreate(AssetFields):
    # A poste's asset is written under the poste (``PUT /machines/{id}/asset``);
    # this creates equipment without an agent, which needs a name.
    name: str = Field(min_length=1, max_length=200)


class AssetMachineRef(BaseModel):
    id: uuid.UUID
    hostname: str | None
    hw_manufacturer: str | None
    hw_model: str | None
    hw_serial: str | None


class AssetOut(BaseModel):
    id: uuid.UUID
    machine_id: uuid.UUID | None
    kind: str
    # What the asset is called: its poste's name, else its own.
    display_name: str | None
    name: str | None
    room_id: uuid.UUID | None
    room_name: str | None
    building_name: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    inventory_number: str | None
    status: str
    purchase_date: date | None
    supplier: str | None
    order_reference: str | None
    warranty_end: date | None
    warranty_state: WarrantyState = "none"
    purchase_price: Decimal | None
    borrower: str | None
    loan_due: date | None
    notes: str | None
    public_token: str
    updated_at: Any
    updated_by: str | None
    machine: AssetMachineRef | None = None


class AssetList(BaseModel):
    items: list[AssetOut]
    total: int
    page: int
    page_size: int


async def _out(session: SessionDep, rows: list[Asset]) -> list[AssetOut]:
    machine_ids = {a.machine_id for a in rows if a.machine_id}
    machines: dict[uuid.UUID, Machine] = {}
    if machine_ids:
        found = await session.exec(
            select(Machine).where(col(Machine.id).in_(machine_ids))
        )
        machines = {m.id: m for m in found.all()}
    # A poste's room is its machine's; equipment has its own.
    room_of: dict[uuid.UUID, uuid.UUID | None] = {}
    for a in rows:
        m = machines.get(a.machine_id) if a.machine_id else None
        room_of[a.id] = m.room_id if m is not None else a.room_id
    placements = await room_crud.placements(session, room_of.values())
    soon_days = (await setting_crud.alert_policy(session)).warranty_days
    today = utcnow().date()
    out = []
    for a in rows:
        m = machines.get(a.machine_id) if a.machine_id else None
        room_id = room_of[a.id]
        placement = placements.get(room_id) if room_id else None
        out.append(
            AssetOut(
                id=a.id,
                machine_id=a.machine_id,
                kind=a.kind,
                display_name=(m.hostname if m is not None and m.hostname else a.name),
                name=a.name,
                room_id=room_id,
                room_name=placement.room.name if placement and placement.room else None,
                building_name=(
                    placement.building.name
                    if placement and placement.building
                    else None
                ),
                manufacturer=m.hw_manufacturer if m is not None else a.manufacturer,
                model=m.hw_model if m is not None else a.model,
                serial_number=m.hw_serial if m is not None else a.serial_number,
                inventory_number=a.inventory_number,
                status=a.status,
                purchase_date=a.purchase_date,
                supplier=a.supplier,
                order_reference=a.order_reference,
                warranty_end=a.warranty_end,
                warranty_state=warranty_state(a.warranty_end, today, soon_days),
                purchase_price=a.purchase_price,
                borrower=a.borrower,
                loan_due=a.loan_due,
                notes=a.notes,
                public_token=a.public_token,
                updated_at=a.updated_at,
                updated_by=a.updated_by,
                machine=(
                    AssetMachineRef(
                        id=m.id,
                        hostname=m.hostname,
                        hw_manufacturer=m.hw_manufacturer,
                        hw_model=m.hw_model,
                        hw_serial=m.hw_serial,
                    )
                    if m is not None
                    else None
                ),
            )
        )
    return out


def _scope_clause(scope: Scope | None) -> Any:
    """Assets in scope: a poste's by its poste, equipment by its room."""
    if scope is None:
        return None
    poste_in_scope = col(Asset.machine_id).in_(
        select(col(Machine.id)).where(machine_clause(scope)).correlate(None)
    )
    equipment_in_scope = and_(
        col(Asset.machine_id).is_(None),
        col(Asset.room_id).in_(
            select(col(Room.id)).where(room_clause(scope)).correlate(None)
        ),
    )
    return or_(poste_in_scope, equipment_in_scope)


async def _get_in_scope(
    session: SessionDep, asset_id: uuid.UUID, scope: Scope | None
) -> Asset:
    stmt = select(Asset).where(col(Asset.id) == asset_id)
    clause = _scope_clause(scope)
    if clause is not None:
        stmt = stmt.where(clause)
    asset = (await session.exec(stmt)).first()
    if asset is None:
        raise AppError(
            code=ErrorCode.ASSET_NOT_FOUND, status_code=404, message="Asset not found"
        )
    return asset


async def _require_room(
    session: SessionDep, room_id: uuid.UUID | None, scope: Scope | None
) -> None:
    if room_id is None:
        return
    stmt = select(Room.id).where(col(Room.id) == room_id)
    clause = room_clause(scope)
    if clause is not None:
        stmt = stmt.where(clause)
    if (await session.exec(stmt)).first() is None:
        raise AppError(
            code=ErrorCode.ROOM_NOT_FOUND, status_code=404, message="Room not found"
        )


def _apply(asset: Asset, fields: dict[str, Any]) -> None:
    for name, value in fields.items():
        if name in ("kind", "status") and value is not None:
            value = str(value)
        setattr(asset, name, value)


async def _commit(session: SessionDep) -> None:
    """Commit, turning the one constraint a person can trip — a sticker
    number already used — into its own error."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_assets_inventory_number" in str(exc.orig):
            raise AppError(
                code=ErrorCode.ASSET_INVENTORY_NUMBER_TAKEN,
                status_code=409,
                message="Inventory number already used",
            ) from None
        if "machine_id" in str(exc.orig):
            raise AppError(
                code=ErrorCode.ASSET_MACHINE_TAKEN,
                status_code=409,
                message="This computer already has an asset",
            ) from None
        raise


def _audit_details(fields: dict[str, Any]) -> dict[str, str | None]:
    # The price is recorded as changed, not its value.
    return {
        k: (
            "•"
            if k == "purchase_price" and v is not None
            else (None if v is None else str(v))
        )
        for k, v in fields.items()
    }


# --- The list and one asset ---------------------------------------------------


@router.get("", response_model=AssetList, dependencies=[_READ])
async def list_assets(
    session: SessionDep,
    scope: CurrentScope,
    search: str | None = Query(None, max_length=200),
    kind: AssetKind | None = None,
    status: AssetStatus | None = None,
    room_id: uuid.UUID | None = None,
    with_machine: bool | None = None,
    warranty: Literal["active", "soon", "expired", "none"] | None = None,
    ids: str | None = Query(
        None, max_length=20_000, description="Comma-separated asset ids (labels)"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> AssetList:
    """Assets, postes and equipment alike, by name. ``with_machine=false``
    is the page Matériels' own list: the equipment without an agent."""
    stmt = select(Asset).outerjoin(Machine, col(Machine.id) == col(Asset.machine_id))
    clause = _scope_clause(scope)
    if clause is not None:
        stmt = stmt.where(clause)
    if ids:
        try:
            wanted = [uuid.UUID(part) for part in ids.split(",") if part.strip()]
        except ValueError:
            raise AppError(
                code=ErrorCode.REQUEST_VALIDATION_ERROR,
                status_code=422,
                message="ids must be asset ids",
            ) from None
        stmt = stmt.where(col(Asset.id).in_(wanted))
    if kind is not None:
        stmt = stmt.where(col(Asset.kind) == kind)
    if status is not None:
        stmt = stmt.where(col(Asset.status) == status)
    if room_id is not None:
        stmt = stmt.where(
            func.coalesce(col(Machine.room_id), col(Asset.room_id)) == room_id
        )
    if with_machine is not None:
        stmt = stmt.where(
            col(Asset.machine_id).is_not(None)
            if with_machine
            else col(Asset.machine_id).is_(None)
        )
    today = utcnow().date()
    if warranty == "active":
        stmt = stmt.where(col(Asset.warranty_end) >= today)
    elif warranty == "soon":
        soon_days = (await setting_crud.alert_policy(session)).warranty_days
        stmt = stmt.where(
            col(Asset.warranty_end) >= today,
            col(Asset.warranty_end) <= today + timedelta(days=soon_days),
        )
    elif warranty == "expired":
        stmt = stmt.where(col(Asset.warranty_end) < today)
    elif warranty == "none":
        stmt = stmt.where(col(Asset.warranty_end).is_(None))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                col(Asset.name).ilike(like),
                col(Asset.inventory_number).ilike(like),
                col(Asset.serial_number).ilike(like),
                col(Asset.supplier).ilike(like),
                col(Asset.borrower).ilike(like),
                col(Machine.hostname).ilike(like),
                col(Machine.hw_serial).ilike(like),
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    name = func.lower(func.coalesce(col(Machine.hostname), col(Asset.name), ""))
    rows = list(
        (
            await session.exec(
                stmt.order_by(name, col(Asset.id))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return AssetList(
        items=await _out(session, rows), total=total, page=page, page_size=page_size
    )


@router.post("", response_model=AssetOut, status_code=201, dependencies=[_WRITE])
async def create_asset(
    payload: AssetCreate, session: SessionDep, current: CurrentUser, scope: CurrentScope
) -> AssetOut:
    """Equipment without an agent: a projector, a printer, a screen."""
    await _require_room(session, payload.room_id, scope)
    if scope is not None and payload.room_id is None:
        # Equipment in no room is seen by the unrestricted only: created by a
        # confined account, it would vanish from its own list.
        raise AppError(
            code=ErrorCode.ROOM_NOT_FOUND, status_code=404, message="Room not found"
        )
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("kind") in (None, AssetKind.COMPUTER):
        fields["kind"] = AssetKind.OTHER
    asset = Asset(updated_by=current.email)
    _apply(asset, fields)
    session.add(asset)
    audit.record(
        session,
        actor=current.email,
        action="asset.create",
        resource_type="asset",
        resource_id=str(asset.id),
        details=_audit_details(fields),
    )
    await _commit(session)
    await session.refresh(asset)
    return (await _out(session, [asset]))[0]


class CompletedOut(BaseModel):
    created: int


@router.post(
    "/rooms/{room_id}/complete", response_model=CompletedOut, dependencies=[_WRITE]
)
async def complete_room(
    room_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> CompletedOut:
    """Give each poste of a room that has none its asset (in service, nothing
    else known): a label is an asset's, and a room's sheet of labels is to
    cover the whole room. The postes the caller does not see are left alone."""
    await _require_room(session, room_id, scope)
    stmt = select(col(Machine.id)).where(
        col(Machine.room_id) == room_id,
        ~exists().where(col(Asset.machine_id) == col(Machine.id)),
    )
    clause = machine_clause(scope)
    if clause is not None:
        stmt = stmt.where(clause)
    machine_ids = list((await session.exec(stmt)).all())
    for machine_id in machine_ids:
        session.add(
            Asset(
                machine_id=machine_id,
                kind=AssetKind.COMPUTER,
                updated_by=current.email,
            )
        )
    if machine_ids:
        audit.record(
            session,
            actor=current.email,
            action="asset.create",
            resource_type="asset",
            resource_id="",
            details={"room_id": str(room_id), "count": str(len(machine_ids))},
        )
        await _commit(session)
    return CompletedOut(created=len(machine_ids))


@router.get("/by-token/{token}", dependencies=[_MACHINE_READ])
async def asset_by_token(
    token: str, session: SessionDep, scope: CurrentScope
) -> dict[str, uuid.UUID | None]:
    """What a scanned label names: the poste to open, else the asset. Out of
    scope, or unknown: the same 404 — a label does not say what it is to
    whoever may not see it."""
    asset = await crud.by_token(session, token)
    if asset is None:
        raise AppError(
            code=ErrorCode.ASSET_NOT_FOUND, status_code=404, message="Asset not found"
        )
    if asset.machine_id is not None:
        if not await machine_visible(session, asset.machine_id, scope):
            raise AppError(
                code=ErrorCode.ASSET_NOT_FOUND,
                status_code=404,
                message="Asset not found",
            )
        return {"machine_id": asset.machine_id, "asset_id": asset.id}
    await _get_in_scope(session, asset.id, scope)
    return {"machine_id": None, "asset_id": asset.id}


@router.get("/{asset_id}", response_model=AssetOut, dependencies=[_READ])
async def get_asset(
    asset_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> AssetOut:
    return (await _out(session, [await _get_in_scope(session, asset_id, scope)]))[0]


@router.patch("/{asset_id}", response_model=AssetOut, dependencies=[_WRITE])
async def update_asset(
    asset_id: uuid.UUID,
    payload: AssetFields,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> AssetOut:
    asset = await _get_in_scope(session, asset_id, scope)
    fields = payload.model_dump(exclude_unset=True)
    if asset.machine_id is not None:
        # A poste's name, room and hardware are its machine's.
        for name in (
            "kind",
            "name",
            "room_id",
            "manufacturer",
            "model",
            "serial_number",
        ):
            fields.pop(name, None)
    else:
        if "name" in fields and not fields["name"]:
            raise AppError(
                code=ErrorCode.REQUEST_VALIDATION_ERROR,
                status_code=422,
                message="Equipment needs a name",
            )
        if "kind" in fields and fields["kind"] in (None, AssetKind.COMPUTER):
            fields["kind"] = AssetKind.OTHER
        if "room_id" in fields:
            await _require_room(session, fields["room_id"], scope)
            if scope is not None and fields["room_id"] is None:
                raise AppError(
                    code=ErrorCode.ROOM_NOT_FOUND,
                    status_code=404,
                    message="Room not found",
                )
    _apply(asset, fields)
    asset.updated_at = utcnow()
    asset.updated_by = current.email
    session.add(asset)
    audit.record(
        session,
        actor=current.email,
        action="asset.update",
        resource_type="asset",
        resource_id=str(asset.id),
        details=_audit_details(fields),
    )
    await _commit(session)
    await session.refresh(asset)
    return (await _out(session, [asset]))[0]


@router.delete("/{asset_id}", status_code=204, dependencies=[_WRITE])
async def delete_asset(
    asset_id: uuid.UUID, session: SessionDep, current: CurrentUser, scope: CurrentScope
) -> None:
    asset = await _get_in_scope(session, asset_id, scope)
    audit.record(
        session,
        actor=current.email,
        action="asset.delete",
        resource_type="asset",
        resource_id=str(asset.id),
        details={
            "name": asset.name,
            "machine_id": str(asset.machine_id) if asset.machine_id else None,
            "inventory_number": asset.inventory_number,
        },
    )
    await session.delete(asset)
    await session.commit()


@router.post("/{asset_id}/token", response_model=AssetOut, dependencies=[_WRITE])
async def renew_token(
    asset_id: uuid.UUID, session: SessionDep, current: CurrentUser, scope: CurrentScope
) -> AssetOut:
    """A new token for the label: the printed one stops naming the asset —
    for a sticker photographed somewhere it should not have been."""
    asset = await _get_in_scope(session, asset_id, scope)
    asset.public_token = new_public_token()
    asset.updated_at = utcnow()
    asset.updated_by = current.email
    session.add(asset)
    audit.record(
        session,
        actor=current.email,
        action="asset.token_renew",
        resource_type="asset",
        resource_id=str(asset.id),
    )
    await session.commit()
    await session.refresh(asset)
    return (await _out(session, [asset]))[0]


# --- A poste's asset -------------------------------------------------------------


async def _visible_machine(
    session: SessionDep, machine_id: uuid.UUID, scope: Scope | None
) -> Machine:
    machine = await session.get(Machine, machine_id)
    if machine is None or not await machine_visible(session, machine_id, scope):
        raise AppError(
            code=ErrorCode.MACHINE_NOT_FOUND,
            status_code=404,
            message="Machine not found",
        )
    return machine


@machine_router.get(
    "/{machine_id}/asset", response_model=AssetOut | None, dependencies=[_READ]
)
async def get_machine_asset(
    machine_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> AssetOut | None:
    """A poste's asset, null when none was ever written."""
    await _visible_machine(session, machine_id, scope)
    asset = await crud.for_machine(session, machine_id)
    return (await _out(session, [asset]))[0] if asset is not None else None


@machine_router.put(
    "/{machine_id}/asset", response_model=AssetOut, dependencies=[_WRITE]
)
async def put_machine_asset(
    machine_id: uuid.UUID,
    payload: AssetFields,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> AssetOut:
    """Write a poste's asset, created on first write."""
    await _visible_machine(session, machine_id, scope)
    fields = payload.model_dump(exclude_unset=True)
    for name in ("kind", "name", "room_id", "manufacturer", "model", "serial_number"):
        fields.pop(name, None)
    asset = await crud.for_machine(session, machine_id)
    created = asset is None
    if asset is None:
        asset = Asset(machine_id=machine_id, kind=AssetKind.COMPUTER)
    _apply(asset, fields)
    asset.updated_at = utcnow()
    asset.updated_by = current.email
    session.add(asset)
    audit.record(
        session,
        actor=current.email,
        action="asset.create" if created else "asset.update",
        resource_type="asset",
        resource_id=str(asset.id),
        details={"machine_id": str(machine_id), **_audit_details(fields)},
    )
    await _commit(session)
    await session.refresh(asset)
    return (await _out(session, [asset]))[0]


# --- Import ------------------------------------------------------------------------


ImportAction = Literal[
    "create", "update", "unchanged", "unmatched", "ambiguous", "invalid"
]


class ImportRowOut(BaseModel):
    line: int
    serial: str
    action: ImportAction
    machine_id: uuid.UUID | None = None
    hostname: str | None = None
    # The fields the row would write (or wrote), as text.
    changes: dict[str, str | None] = Field(default_factory=dict)
    # The cells that could not be read, by field.
    errors: list[str] = Field(default_factory=list)


class ImportOut(BaseModel):
    dry_run: bool
    rows: list[ImportRowOut]
    counts: dict[str, int]


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@router.post("/import", response_model=ImportOut, dependencies=[_WRITE])
async def import_assets(
    file: Annotated[UploadFile, File()],
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
    dry_run: bool = True,
) -> ImportOut:
    """Read a sheet of postes matched on their serial number; say what each
    row would change (``dry_run``, the default), or write it.

    A row is written only when its serial names exactly one poste in the
    caller's scope and every cell of it reads; the others are reported and
    left alone. An inventory number already another asset's fails the row,
    not the import."""
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise AppError(
            code=ErrorCode.ASSET_IMPORT_TOO_LARGE,
            status_code=422,
            message="Import file too large",
            details={
                "cause": {
                    "code": "file_too_large",
                    "params": {"max_mb": MAX_IMPORT_BYTES // (1024 * 1024)},
                }
            },
        )
    try:
        # CPU work, off the event loop that answers every heartbeat.
        rows = await asyncio.to_thread(importer.parse, file.filename or "", content)
    except importer.TooManyRows as exc:
        raise AppError(
            code=ErrorCode.ASSET_IMPORT_TOO_LARGE,
            status_code=422,
            message="Too many rows in the import file",
            details={"cause": {"code": exc.cause, "params": {"max": exc.limit}}},
        ) from None
    except importer.UnreadableFile as exc:
        raise AppError(
            code=ErrorCode.ASSET_IMPORT_UNREADABLE,
            status_code=422,
            message="Unreadable import file",
            details={"cause": {"code": str(exc)}},
        ) from None

    serials = {r.serial.strip().upper() for r in rows if r.serial}
    by_serial: dict[str, list[Machine]] = {}
    if serials:
        stmt = select(Machine).where(
            func.upper(func.trim(col(Machine.hw_serial))).in_(serials)
        )
        clause = machine_clause(scope)
        if clause is not None:
            stmt = stmt.where(clause)
        for m in (await session.exec(stmt)).all():
            by_serial.setdefault((m.hw_serial or "").strip().upper(), []).append(m)
    machine_ids = [m.id for ms in by_serial.values() for m in ms]
    existing: dict[uuid.UUID, Asset] = {}
    if machine_ids:
        found = await session.exec(
            select(Asset).where(col(Asset.machine_id).in_(machine_ids))
        )
        existing = {a.machine_id: a for a in found.all() if a.machine_id}
    numbers_taken = dict(
        (
            await session.exec(
                select(col(Asset.inventory_number), col(Asset.id)).where(
                    col(Asset.inventory_number).is_not(None)
                )
            )
        ).all()
    )

    out: list[ImportRowOut] = []
    # What the rows above already write: an inventory number, a poste. The
    # preview and the import read them alike, so the preview says what the
    # import will do.
    seen_numbers: set[str] = set()
    seen_machines: set[uuid.UUID] = set()
    for row in rows:
        matches = by_serial.get(row.serial.strip().upper(), []) if row.serial else []
        result = ImportRowOut(line=row.line, serial=row.serial, action="invalid")
        target = matches[0] if len(matches) == 1 else None
        if target is not None:
            result.machine_id = target.id
            result.hostname = target.hostname
        errors = list(row.errors)
        number = row.values.get("inventory_number")
        if number:
            own = existing.get(target.id) if target is not None else None
            holder = numbers_taken.get(number)
            if (
                holder is not None and (own is None or holder != own.id)
            ) or number in seen_numbers:
                errors.append("inventory_number_taken")
        if target is not None:
            if target.id in seen_machines:
                # Two rows for one poste: which one would win is not for the
                # file's order to decide.
                errors.append("duplicate_serial")
        result.errors = errors
        if not row.serial or errors:
            result.action = "invalid"
        elif not matches:
            result.action = "unmatched"
        elif target is None:
            result.action = "ambiguous"
        else:
            asset = existing.get(target.id)
            changes = {
                k: v
                for k, v in row.values.items()
                if asset is None or getattr(asset, k) != v
            }
            result.changes = {k: _as_text(v) for k, v in changes.items()}
            if asset is None:
                result.action = "create"
            elif changes:
                result.action = "update"
            else:
                result.action = "unchanged"
            seen_machines.add(target.id)
            if number:
                seen_numbers.add(number)
            if not dry_run and result.action in ("create", "update"):
                if asset is None:
                    asset = Asset(machine_id=target.id, kind=AssetKind.COMPUTER)
                    existing[target.id] = asset
                _apply(asset, changes)
                asset.updated_at = utcnow()
                asset.updated_by = current.email
                session.add(asset)
                if number:
                    numbers_taken[number] = asset.id
        out.append(result)

    counts: dict[str, int] = {}
    for r in out:
        counts[r.action] = counts.get(r.action, 0) + 1
    if not dry_run:
        audit.record(
            session,
            actor=current.email,
            action="asset.import",
            resource_type="asset",
            resource_id="",
            details={k: str(v) for k, v in sorted(counts.items())},
        )
        await _commit(session)
    return ImportOut(dry_run=dry_run, rows=out, counts=counts)
