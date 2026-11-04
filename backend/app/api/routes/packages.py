"""Software packages: the catalogue the console deploys from.

``package:read`` lists and shows them; ``package:write`` composes them —
creating, uploading files, attaching the administrator's signature, retiring.
Deploying one is a command (``package_install``), which takes
``risky_command:execute`` like every command that changes a poste for good.

Nothing here decides whether a poste will run a package. The poste does, from
anchors its GPO set (``dev/plan-deploiement-logiciel.md`` §1); what this module
stores about signatures and publishers is for the console to show, and to
refuse what could not possibly verify.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.inventory.models import MachineSoftware
from app.features.package import authenticode, crud, manifest, signature, storage
from app.features.package.models import (
    DEFAULT_SUCCESS_CODES,
    Package,
    PackageFile,
    PackageKind,
)
from app.features.user.permissions import Action, Resource
from app.features.user.scope import machine_ids_clause

_READ = Depends(require_permission(Resource.PACKAGE, Action.READ))
_WRITE = Depends(require_permission(Resource.PACKAGE, Action.WRITE))

router = APIRouter(prefix="/packages", tags=["packages"], dependencies=[_READ])

# What winget accepts as an identifier and a version, narrowed to what the
# community repository actually uses. The agent applies the same pattern: the
# identifier is the one argument of a winget deployment, and it must never be
# able to read as an option.
WINGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}$")
WINGET_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_MAX_ARGS = 64
_MAX_ARG_LEN = 1024


def _invalid(message: str, **details: Any) -> AppError:
    return AppError(
        code=ErrorCode.PACKAGE_INVALID,
        status_code=422,
        message=message,
        details=details,
    )


def _check_args(args: list[str]) -> list[str]:
    if len(args) > _MAX_ARGS:
        raise ValueError(f"au plus {_MAX_ARGS} arguments")
    for a in args:
        if len(a) > _MAX_ARG_LEN or "\0" in a:
            raise ValueError("argument trop long ou invalide")
    return args


def _check_codes(codes: list[int]) -> list[int]:
    if not codes or len(codes) > 32:
        raise ValueError("entre 1 et 32 codes de succès")
    for c in codes:
        if not -(2**31) <= c < 2**32:
            raise ValueError("code de sortie hors limites")
    return codes


class PackageBody(BaseModel):
    """Create or update. On update only the supplied fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    winget_id: str | None = None
    winget_version: str | None = None
    install_run: str | None = Field(default=None, max_length=255)
    install_args: list[str] | None = None
    uninstall_run: str | None = Field(default=None, max_length=255)
    uninstall_args: list[str] | None = None
    success_codes: list[int] | None = None
    detect_name: str | None = Field(default=None, max_length=200)

    @field_validator("install_args", "uninstall_args")
    @classmethod
    def _args(cls, v: list[str] | None) -> list[str] | None:
        return _check_args(v) if v is not None else v

    @field_validator("success_codes")
    @classmethod
    def _codes(cls, v: list[int] | None) -> list[int] | None:
        return _check_codes(v) if v is not None else v


class PackageCreate(PackageBody):
    kind: PackageKind
    name: str = Field(min_length=1, max_length=200)


class PackageFileOut(BaseModel):
    name: str
    sha256: str
    size: int
    publisher_name: str | None


class ProblemOut(BaseModel):
    code: str
    message: str


class PackageOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    version: str | None
    notes: str | None
    winget_id: str | None
    winget_version: str | None
    install_run: str | None
    install_args: list[str]
    uninstall_run: str | None
    uninstall_args: list[str]
    success_codes: list[int]
    detect_name: str | None
    files: list[PackageFileOut]
    # Method B: present once the administrator's signature is attached.
    signed: bool
    signer_subject: str | None
    signer_thumbprint: str | None
    signed_at: datetime | None
    signed_by: str | None
    # Method A: signer of the file ``install_run`` names, if any.
    publisher_name: str | None
    # What stands between this package and a deployment; empty when ready.
    problems: list[ProblemOut]
    # Postes (within the caller's scope) whose inventory shows the program;
    # null when ``detect_name`` is empty.
    installed_count: int | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None


async def _out(
    session: SessionDep,
    package: Package,
    scope: Any,
    files: list[PackageFile] | None = None,
) -> PackageOut:
    files = files if files is not None else await crud.files_of(session, package.id)
    problems = (
        manifest.problems(package, files) if package.kind == PackageKind.FILES else []
    )
    run_file = next((f for f in files if f.name == package.install_run), None)
    return PackageOut(
        id=package.id,
        kind=package.kind,
        name=package.name,
        version=package.version,
        notes=package.notes,
        winget_id=package.winget_id,
        winget_version=package.winget_version,
        install_run=package.install_run,
        install_args=list(package.install_args),
        uninstall_run=package.uninstall_run,
        uninstall_args=list(package.uninstall_args),
        success_codes=list(package.success_codes),
        detect_name=package.detect_name,
        files=[
            PackageFileOut(
                name=f.name,
                sha256=f.sha256,
                size=f.size,
                publisher_name=f.publisher_name,
            )
            for f in files
        ],
        signed=package.signature is not None,
        signer_subject=package.signer_subject,
        signer_thumbprint=package.signer_thumbprint,
        signed_at=package.signed_at,
        signed_by=package.signed_by,
        publisher_name=run_file.publisher_name if run_file else None,
        problems=[ProblemOut(code=p.code, message=p.message) for p in problems],
        installed_count=await crud.installed_count(
            session, package, machine_ids_clause(scope, col(MachineSoftware.machine_id))
        ),
        created_by=package.created_by,
        created_at=package.created_at,
        updated_at=package.updated_at,
        retired_at=package.retired_at,
    )


async def require_package(session: SessionDep, package_id: uuid.UUID) -> Package:
    package = await session.get(Package, package_id)
    if package is None:
        raise AppError(
            code=ErrorCode.PACKAGE_NOT_FOUND,
            status_code=404,
            message="Package not found",
        )
    return package


def _apply(package: Package, fields: dict[str, Any]) -> None:
    """Write the supplied fields, normalised, and check the result is a
    coherent package of its kind."""
    for key in ("version", "notes", "detect_name", "winget_version", "uninstall_run"):
        if key in fields and isinstance(fields[key], str):
            fields[key] = fields[key].strip() or None
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    for key, value in fields.items():
        setattr(package, key, value)

    if package.kind == PackageKind.WINGET:
        if not package.winget_id or not WINGET_ID.match(package.winget_id):
            raise _invalid("Identifiant winget invalide (ex. Mozilla.Firefox)")
        if package.winget_version and not WINGET_VERSION.match(package.winget_version):
            raise _invalid("Version winget invalide")
        if package.install_run or package.uninstall_run:
            raise _invalid("Un paquet winget ne lance pas de fichier")
        if not package.detect_name:
            package.detect_name = package.name
    else:
        if package.winget_id or package.winget_version:
            raise _invalid("Un paquet de fichiers n'a pas d'identifiant winget")
        for key in ("install_run", "uninstall_run"):
            value = getattr(package, key)
            if value is None:
                continue
            if value == manifest.MSIEXEC:
                # An MSI is not an executable: msiexec runs it, with the
                # package's .msi among the arguments ("/i {dir}\\app.msi").
                continue
            if not manifest.valid_file_name(value):
                raise _invalid("Nom de fichier à lancer invalide", field=key)
        if package.uninstall_run == manifest.MSIEXEC and not package.uninstall_args:
            raise _invalid(
                "Désinstallation par msiexec : indiquer les arguments (ex. /x {code produit} /qn)"
            )
        if package.install_run == manifest.MSIEXEC and not package.install_args:
            raise _invalid(
                "Installation par msiexec : indiquer les arguments (ex. /i {dir}\\app.msi /qn)"
            )


@router.get("", response_model=list[PackageOut])
async def list_packages(
    session: SessionDep, scope: CurrentScope, retired: bool = False
) -> list[PackageOut]:
    """The catalogue, by name; retired packages only when asked."""
    stmt = select(Package).order_by(col(Package.name), col(Package.version))
    stmt = stmt.where(
        col(Package.retired_at).is_not(None)
        if retired
        else col(Package.retired_at).is_(None)
    )
    packages = list((await session.exec(stmt)).all())
    files = await crud.files_of_many(session, [p.id for p in packages])
    return [await _out(session, p, scope, files[p.id]) for p in packages]


@router.post("", response_model=PackageOut, status_code=201, dependencies=[_WRITE])
async def create_package(
    payload: PackageCreate,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> PackageOut:
    package = Package(kind=payload.kind, name=payload.name, created_by=current.email)
    fields = payload.model_dump(exclude_unset=True, exclude={"kind"})
    fields.setdefault("success_codes", list(DEFAULT_SUCCESS_CODES))
    _apply(package, fields)
    session.add(package)
    await session.flush()
    await crud.refresh_manifest(session, package)
    audit.record(
        session,
        actor=current.email,
        action="package.create",
        resource_type="package",
        resource_id=str(package.id),
        details={"name": package.name, "kind": package.kind},
    )
    await session.commit()
    await session.refresh(package)
    return await _out(session, package, scope)


@router.get("/{package_id}", response_model=PackageOut)
async def get_package(
    package_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> PackageOut:
    return await _out(session, await require_package(session, package_id), scope)


@router.patch("/{package_id}", response_model=PackageOut, dependencies=[_WRITE])
async def update_package(
    package_id: uuid.UUID,
    payload: PackageBody,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> PackageOut:
    package = await require_package(session, package_id)
    fields = payload.model_dump(exclude_unset=True)
    _apply(package, fields)
    package.updated_at = utcnow()
    session.add(package)
    voided = await crud.refresh_manifest(session, package)
    audit.record(
        session,
        actor=current.email,
        action="package.update",
        resource_type="package",
        resource_id=str(package.id),
        details={
            "name": package.name,
            "fields": sorted(fields),
            "signature_voided": voided,
        },
    )
    await session.commit()
    await session.refresh(package)
    return await _out(session, package, scope)


def _require_files_kind(package: Package) -> None:
    if package.kind != PackageKind.FILES:
        raise _invalid("Ce paquet est un paquet winget : il n'a pas de fichiers")


@router.post("/{package_id}/files", response_model=PackageOut, dependencies=[_WRITE])
async def upload_files(
    package_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
    files: Annotated[list[UploadFile], File()],
) -> PackageOut:
    """Add files to the package, replacing any of the same name. Streamed to
    the store and hashed on the way; the manifest — and so the signature —
    follows."""
    package = await require_package(session, package_id)
    _require_files_kind(package)
    added: list[dict[str, Any]] = []
    for upload in files:
        name = (upload.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if not manifest.valid_file_name(name):
            raise AppError(
                code=ErrorCode.PACKAGE_FILE_NAME_INVALID,
                status_code=422,
                message="Nom de fichier refusé",
                details={"name": name},
            )
        try:
            stored = await storage.save(upload, settings.PACKAGE_MAX_BYTES)
        except storage.TooLarge:
            raise AppError(
                code=ErrorCode.PACKAGE_FILE_TOO_LARGE,
                status_code=413,
                message="Fichier trop volumineux",
                details={"max_bytes": settings.PACKAGE_MAX_BYTES},
            ) from None
        with stored.path.open("rb") as f:
            publisher = authenticode.signer_name(f)
        existing = await session.get(PackageFile, (package.id, name))
        if existing is not None:
            await session.delete(existing)
            await session.flush()
        session.add(
            PackageFile(
                package_id=package.id,
                name=name,
                sha256=stored.sha256,
                size=stored.size,
                publisher_name=publisher,
            )
        )
        added.append({"name": name, "sha256": stored.sha256, "size": stored.size})
    await session.flush()
    await crud.refresh_manifest(session, package)
    audit.record(
        session,
        actor=current.email,
        action="package.upload",
        resource_type="package",
        resource_id=str(package.id),
        details={"name": package.name, "files": added},
    )
    await session.commit()
    await session.refresh(package)
    return await _out(session, package, scope)


@router.delete(
    "/{package_id}/files/{name}", response_model=PackageOut, dependencies=[_WRITE]
)
async def delete_file(
    package_id: uuid.UUID,
    name: str,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> PackageOut:
    package = await require_package(session, package_id)
    _require_files_kind(package)
    row = await session.get(PackageFile, (package.id, name))
    if row is None:
        raise AppError(
            code=ErrorCode.PACKAGE_NOT_FOUND, status_code=404, message="File not found"
        )
    sha = row.sha256
    await session.delete(row)
    await session.flush()
    await crud.refresh_manifest(session, package)
    audit.record(
        session,
        actor=current.email,
        action="package.file_delete",
        resource_type="package",
        resource_id=str(package.id),
        details={"name": package.name, "file": name},
    )
    await session.commit()
    if not await crud.sha_in_use(session, sha):
        storage.remove_unreferenced(sha)
    await session.refresh(package)
    return await _out(session, package, scope)


@router.get("/{package_id}/manifest", dependencies=[_WRITE])
async def download_manifest(package_id: uuid.UUID, session: SessionDep) -> Response:
    """The bytes to sign, exactly as the postes will receive them."""
    package = await require_package(session, package_id)
    _require_files_kind(package)
    if package.manifest is None:
        await crud.refresh_manifest(session, package)
        await session.commit()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{package.name}-{package.version or ''}")
    return Response(
        content=package.manifest or b"",
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{safe.strip("-")}.tiai-manifest.json"'
        },
    )


@router.put("/{package_id}/signature", response_model=PackageOut, dependencies=[_WRITE])
async def attach_signature(
    package_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
    document: Annotated[dict[str, Any], Body()],
) -> PackageOut:
    """Attach the signature ``Sign-TiaiPackage.ps1`` produced. Refused unless
    it verifies over the manifest as it stands — a signature made before the
    last change would be refused by every poste anyway, better to say so now."""
    import json

    package = await require_package(session, package_id)
    _require_files_kind(package)
    problems = manifest.problems(package, await crud.files_of(session, package.id))
    if problems:
        raise AppError(
            code=ErrorCode.PACKAGE_NOT_READY,
            status_code=409,
            message="Le paquet n'est pas complet",
            details={"problems": [p.message for p in problems]},
        )
    try:
        verified = signature.verify(
            package.manifest or b"", json.dumps(document).encode("utf-8")
        )
    except signature.SignatureError as exc:
        raise AppError(
            code=ErrorCode.PACKAGE_SIGNATURE_INVALID, status_code=422, message=str(exc)
        ) from None
    package.signature = verified.signature
    package.signature_algorithm = verified.algorithm
    package.signer_certificate = verified.certificate
    package.signer_thumbprint = verified.thumbprint
    package.signer_subject = verified.subject
    package.signed_at = utcnow()
    package.signed_by = current.email
    session.add(package)
    audit.record(
        session,
        actor=current.email,
        action="package.sign",
        resource_type="package",
        resource_id=str(package.id),
        details={
            "name": package.name,
            "signer": verified.subject,
            "thumbprint": verified.thumbprint,
        },
    )
    await session.commit()
    await session.refresh(package)
    return await _out(session, package, scope)


@router.delete(
    "/{package_id}/signature", response_model=PackageOut, dependencies=[_WRITE]
)
async def remove_signature(
    package_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> PackageOut:
    package = await require_package(session, package_id)
    package.signature = None
    package.signature_algorithm = None
    package.signer_certificate = None
    package.signer_thumbprint = None
    package.signer_subject = None
    package.signed_at = None
    package.signed_by = None
    session.add(package)
    audit.record(
        session,
        actor=current.email,
        action="package.unsign",
        resource_type="package",
        resource_id=str(package.id),
        details={"name": package.name},
    )
    await session.commit()
    await session.refresh(package)
    return await _out(session, package, scope)


@router.post("/{package_id}/retire", response_model=PackageOut, dependencies=[_WRITE])
async def retire_package(
    package_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> PackageOut:
    """No longer offered for deployment. Its files stay until it is deleted:
    a poste that already received the command still needs to download them."""
    package = await require_package(session, package_id)
    package.retired_at = package.retired_at or utcnow()
    session.add(package)
    audit.record(
        session,
        actor=current.email,
        action="package.retire",
        resource_type="package",
        resource_id=str(package.id),
        details={"name": package.name},
    )
    await session.commit()
    await session.refresh(package)
    return await _out(session, package, scope)


@router.post("/{package_id}/restore", response_model=PackageOut, dependencies=[_WRITE])
async def restore_package(
    package_id: uuid.UUID,
    session: SessionDep,
    current: CurrentUser,
    scope: CurrentScope,
) -> PackageOut:
    package = await require_package(session, package_id)
    package.retired_at = None
    session.add(package)
    audit.record(
        session,
        actor=current.email,
        action="package.restore",
        resource_type="package",
        resource_id=str(package.id),
        details={"name": package.name},
    )
    await session.commit()
    await session.refresh(package)
    return await _out(session, package, scope)
