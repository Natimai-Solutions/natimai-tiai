"""Software licences (dev/plan-evolutions-itil.md, C6).

``license:read`` to read, ``license:write`` to write — a resource of its own,
like the assets: a contract and its order number are purchase material.

A licence is the parc's, not a place's: writing one needs the whole parc. An
account confined to some places reads the licences with the installations
counted on its own postes, and no « dépassée » verdict — its count is not the
one the contract is held to.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.api.fields import not_null
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.license import crud
from app.features.license.models import License
from app.features.setting import crud as setting_crud
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope

router = APIRouter(prefix="/licenses", tags=["licenses"])

_READ = Depends(require_permission(Resource.LICENSE, Action.READ))
_WRITE = Depends(require_permission(Resource.LICENSE, Action.WRITE))

Pattern = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)
]


def _blank_is_null(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _dedupe(patterns: list[str]) -> list[str]:
    """In the order written, a pattern repeated (any case) kept once."""
    seen: set[str] = set()
    out = []
    for p in patterns:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


class LicenseFields(BaseModel):
    """What a person writes. Absent = unchanged on a patch; null clears.
    No field for the key: it has nothing to do here."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    patterns: list[Pattern] | None = Field(
        default=None, min_length=1, max_length=crud.MAX_PATTERNS
    )
    publisher: str | None = Field(default=None, max_length=200)
    seats: int | None = Field(default=None, ge=0, le=1_000_000)
    expires_on: date | None = None
    vendor: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name", "publisher", "vendor", "reference", "notes", mode="before")
    @classmethod
    def _trim(cls, value: Any) -> Any:
        return _blank_is_null(value)

    @field_validator("patterns")
    @classmethod
    def _unique(cls, value: list[str] | None) -> list[str] | None:
        return _dedupe(value) if value is not None else None

    _not_null = not_null("name", "patterns")


class LicenseCreate(LicenseFields):
    name: str = Field(min_length=1, max_length=200)
    patterns: list[Pattern] = Field(min_length=1, max_length=crud.MAX_PATTERNS)


class LicenseOut(BaseModel):
    id: uuid.UUID
    name: str
    patterns: list[str]
    publisher: str | None
    seats: int | None
    expires_on: date | None
    vendor: str | None
    reference: str | None
    notes: str | None
    # Postes carrying what it covers, in the reader's scope, once each.
    installed: int
    # More installations than seats; null when the reader's count is not the
    # parc's (account confined to some places).
    over: bool | None
    expiry: crud.ExpiryState
    created_at: datetime
    updated_at: datetime


class LicenseList(BaseModel):
    items: list[LicenseOut]
    # The reader is confined to some places: the counts are its postes'.
    restricted: bool
    # « Bientôt échue » threshold, in days — what the page says it means.
    expiry_days: int


class LicenseDetail(LicenseOut):
    # The program names its patterns catch in the catalogue (50 at most).
    programs: list[str]


class PreviewIn(BaseModel):
    patterns: list[Pattern] = Field(min_length=1, max_length=crud.MAX_PATTERNS)
    publisher: str | None = Field(default=None, max_length=200)

    @field_validator("publisher", mode="before")
    @classmethod
    def _trim(cls, value: Any) -> Any:
        return _blank_is_null(value)


class PreviewOut(BaseModel):
    programs: list[str]
    installed: int


def _out(state: crud.LicenseState) -> dict[str, Any]:
    lic = state.license
    return {
        "id": lic.id,
        "name": lic.name,
        "patterns": list(lic.patterns),
        "publisher": lic.publisher,
        "seats": lic.seats,
        "expires_on": lic.expires_on,
        "vendor": lic.vendor,
        "reference": lic.reference,
        "notes": lic.notes,
        "installed": state.installed,
        "over": state.over,
        "expiry": state.expiry,
        "created_at": lic.created_at,
        "updated_at": lic.updated_at,
    }


def _whole_parc(scope: Scope | None) -> None:
    """A licence is held to the parc's count: an account confined to some
    places neither writes one nor knows that count."""
    if scope is not None:
        raise AppError(
            code=ErrorCode.AUTH_SCOPE_RESTRICTED,
            status_code=403,
            message="Licences are written for the whole parc",
        )


async def _require(session: SessionDep, license_id: uuid.UUID) -> License:
    lic = await session.get(License, license_id, with_for_update=True)
    if lic is None:
        raise AppError(
            code=ErrorCode.LICENSE_NOT_FOUND, status_code=404, message="No such licence"
        )
    return lic


async def _state(
    session: SessionDep, lic: License, scope: Scope | None
) -> crud.LicenseState:
    soon = await setting_crud.license_expiry_days(session)
    found = await crud.states(session, scope, utcnow().date(), soon, lic.id)
    return found[0]


@router.get("", response_model=LicenseList, dependencies=[_READ])
async def list_licenses(session: SessionDep, scope: CurrentScope) -> LicenseList:
    """Every licence, by name, with its installations counted."""
    soon = await setting_crud.license_expiry_days(session)
    found = await crud.states(session, scope, utcnow().date(), soon)
    return LicenseList(
        items=[LicenseOut(**_out(s)) for s in found],
        restricted=scope is not None,
        expiry_days=soon,
    )


@router.post("/preview", response_model=PreviewOut, dependencies=[_READ])
async def preview(
    payload: PreviewIn, session: SessionDep, scope: CurrentScope
) -> PreviewOut:
    """What patterns would catch, before they are saved: the program names,
    and how many postes in scope carry one."""
    draft = License(name="", patterns=payload.patterns, publisher=payload.publisher)
    return PreviewOut(
        programs=await crud.programs(session, draft, scope),
        installed=await crud.installed(session, draft, scope),
    )


@router.get("/{license_id}", response_model=LicenseDetail, dependencies=[_READ])
async def get_license(
    license_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> LicenseDetail:
    lic = await session.get(License, license_id)
    if lic is None:
        raise AppError(
            code=ErrorCode.LICENSE_NOT_FOUND, status_code=404, message="No such licence"
        )
    state = await _state(session, lic, scope)
    return LicenseDetail(
        **_out(state), programs=await crud.programs(session, lic, scope)
    )


@router.post("", response_model=LicenseOut, status_code=201, dependencies=[_WRITE])
async def create_license(
    payload: LicenseCreate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> LicenseOut:
    _whole_parc(scope)
    count = await session.scalar(crud.count_stmt())
    if (count or 0) >= crud.MAX_LICENSES:
        raise AppError(
            code=ErrorCode.LICENSE_TOO_MANY,
            status_code=409,
            message=f"{crud.MAX_LICENSES} licences at most",
        )
    lic = License(**payload.model_dump())
    session.add(lic)
    audit.record(
        session,
        actor=current.email,
        action="license.create",
        resource_type="license",
        resource_id=str(lic.id),
        details=crud.audit_details(lic),
    )
    await session.commit()
    await session.refresh(lic)
    return LicenseOut(**_out(await _state(session, lic, scope)))


@router.patch("/{license_id}", response_model=LicenseOut, dependencies=[_WRITE])
async def update_license(
    license_id: uuid.UUID,
    payload: LicenseFields,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> LicenseOut:
    _whole_parc(scope)
    lic = await _require(session, license_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lic, field, value)
    lic.updated_at = utcnow()
    session.add(lic)
    audit.record(
        session,
        actor=current.email,
        action="license.update",
        resource_type="license",
        resource_id=str(lic.id),
        details=crud.audit_details(lic),
    )
    await session.commit()
    await session.refresh(lic)
    return LicenseOut(**_out(await _state(session, lic, scope)))


@router.delete("/{license_id}", status_code=204, dependencies=[_WRITE])
async def delete_license(
    license_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> None:
    _whole_parc(scope)
    lic = await _require(session, license_id)
    audit.record(
        session,
        actor=current.email,
        action="license.delete",
        resource_type="license",
        resource_id=str(lic.id),
        details=crud.audit_details(lic),
    )
    await session.delete(lic)
    await session.commit()
