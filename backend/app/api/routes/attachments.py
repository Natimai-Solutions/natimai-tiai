"""Attachments of the journal (C11): photos and PDFs on a line of a poste's
journal.

An attachment is data of its line: read and downloaded with
``intervention:read``, added and deleted with ``intervention:write``, every
route through the line and so through the poste's scope — out of reach is
« introuvable ». The server never serves a file a browser would interpret:
the type is recognised from the content (``attachment/storage.py``), the
download is always ``attachment``, ``nosniff``, sandboxed.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.api.routes.interventions import _require_intervention
from app.core.config import settings
from app.core.errors import AppError, ErrorCode, violated_constraint
from app.features.attachment import crud, storage
from app.features.attachment.models import InterventionAttachment
from app.features.attachment.schemas import AttachmentOut
from app.features.audit import crud as audit
from app.features.intervention.models import Intervention
from app.features.setting import crud as setting_crud
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope, machine_visible

_READ = Depends(require_permission(Resource.INTERVENTION, Action.READ))
_WRITE = Depends(require_permission(Resource.INTERVENTION, Action.WRITE))

# An attachment by its own id; the upload under its line.
router = APIRouter(prefix="/attachments", tags=["attachments"], dependencies=[_READ])
intervention_router = APIRouter(
    prefix="/interventions", tags=["attachments"], dependencies=[_READ]
)

_UNIQUE = "uq_intervention_attachments_intervention_sha"

# Opening the file in the console's origin must run nothing (plan §2.1).
_DOWNLOAD_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "private, no-store",
}


class AttachmentPolicy(BaseModel):
    max_bytes: int
    max_per_intervention: int
    types: list[str]
    quota_bytes: int
    # Null for an account confined to some sites: a total of the whole parc.
    used_bytes: int | None
    retention_days: int
    store_available: bool


def _not_found() -> AppError:
    return AppError(
        code=ErrorCode.ATTACHMENT_NOT_FOUND,
        status_code=404,
        message="Attachment not found",
    )


def _intervention_gone() -> AppError:
    return AppError(
        code=ErrorCode.INTERVENTION_NOT_FOUND,
        status_code=404,
        message="Intervention not found",
    )


def _too_many() -> AppError:
    return AppError(
        code=ErrorCode.ATTACHMENT_TOO_MANY,
        status_code=409,
        message="Too many attachments on this line",
        details={"max": crud.MAX_PER_INTERVENTION},
    )


def _duplicate() -> AppError:
    return AppError(
        code=ErrorCode.ATTACHMENT_DUPLICATE,
        status_code=409,
        message="This file is already attached to this line",
    )


async def _require_attachment(
    session: SessionDep, attachment_id: uuid.UUID, scope: Scope | None
) -> tuple[InterventionAttachment, uuid.UUID]:
    """The attachment and its line's poste, when that poste is in reach;
    404 otherwise."""
    found = await session.exec(
        select(InterventionAttachment, Intervention.machine_id)
        .join(
            Intervention,
            col(Intervention.id) == col(InterventionAttachment.intervention_id),
        )
        .where(col(InterventionAttachment.id) == attachment_id)
    )
    row = found.first()
    if row is None:
        raise _not_found()
    attachment, machine_id = row
    if not await machine_visible(session, machine_id, scope):
        raise _not_found()
    return attachment, machine_id


@router.get("/policy", response_model=AttachmentPolicy)
async def attachment_policy(
    session: SessionDep, scope: CurrentScope
) -> AttachmentPolicy:
    """The limits the console checks before sending — it copies none."""
    return AttachmentPolicy(
        max_bytes=settings.ATTACHMENT_MAX_BYTES,
        max_per_intervention=crud.MAX_PER_INTERVENTION,
        types=list(storage.TYPES),
        quota_bytes=settings.ATTACHMENT_QUOTA_BYTES,
        used_bytes=None if scope is not None else await crud.used_bytes(session),
        retention_days=await setting_crud.attachment_retention_days(session),
        store_available=storage.store_available(),
    )


@intervention_router.post(
    "/{intervention_id}/attachments",
    response_model=AttachmentOut,
    status_code=201,
    dependencies=[_WRITE],
)
async def upload_attachment(
    intervention_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> AttachmentOut:
    """One file per request. Sniffed on its first bytes before anything is
    written; counted, checked against duplicates and the quota under
    ``ATTACHMENT_QUOTA_LOCK``, so that two uploads at once cannot both pass."""
    line = await _require_intervention(session, intervention_id, scope)
    machine_id = line.machine_id
    actor = current.email
    if not storage.store_available():
        raise AppError(
            code=ErrorCode.ATTACHMENT_STORE_UNAVAILABLE,
            status_code=503,
            message="The attachments volume is not mounted",
        )
    # Before receiving anything: refused without uploading.
    if await crud.count_for(session, intervention_id) >= crud.MAX_PER_INTERVENTION:
        raise _too_many()
    max_bytes = settings.ATTACHMENT_MAX_BYTES
    try:
        stored = await storage.save(
            file, max_bytes, lambda sha: crud.hold_file(session, sha)
        )
    except storage.TooLarge:
        await session.rollback()
        raise AppError(
            code=ErrorCode.ATTACHMENT_TOO_LARGE,
            status_code=413,
            message="File too large",
            details={"max_bytes": max_bytes},
        ) from None
    except storage.Unrecognised:
        await session.rollback()
        raise AppError(
            code=ErrorCode.ATTACHMENT_TYPE_REFUSED,
            status_code=415,
            message="Only JPEG, PNG, WebP and PDF files are accepted",
            details={"types": list(storage.TYPES)},
        ) from None
    except BaseException:
        await session.rollback()
        raise
    sha = stored.sha256
    content_type = stored.content_type or "application/octet-stream"
    filename = storage.clean_filename(file.filename, content_type)
    try:
        out = await _insert(
            session,
            intervention_id=intervention_id,
            machine_id=machine_id,
            sha=sha,
            size=stored.size,
            content_type=content_type,
            filename=filename,
            actor=actor,
        )
    except IntegrityError as exc:
        await session.rollback()
        await crud.discard_if_orphan(session, sha)
        if violated_constraint(exc) == _UNIQUE:
            raise _duplicate() from None
        # The line's foreign key: it was deleted under the upload.
        raise _intervention_gone() from None
    except BaseException:
        await session.rollback()
        await crud.discard_if_orphan(session, sha)
        raise
    return out


async def _insert(
    session: SessionDep,
    *,
    intervention_id: uuid.UUID,
    machine_id: uuid.UUID,
    sha: str,
    size: int,
    content_type: str,
    filename: str,
    actor: str,
) -> AttachmentOut:
    """Steps 4 to 6 of the upload (plan §2.3): under the quota lock, the
    line read again ``FOR SHARE`` — a deletion waits for the upload's end —,
    counted again, the duplicate and the quota checked, then the row, its
    audit entry, the commit."""
    await crud.lock_quota(session)
    line = (
        await session.exec(
            select(Intervention)
            .where(col(Intervention.id) == intervention_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).first()
    if line is None:
        raise _intervention_gone()
    if await crud.count_for(session, intervention_id) >= crud.MAX_PER_INTERVENTION:
        raise _too_many()
    if await crud.named_on(session, intervention_id, sha):
        raise _duplicate()
    quota = settings.ATTACHMENT_QUOTA_BYTES
    # A file already stored for another line takes no more room.
    if quota > 0 and not await crud.sha_in_use(session, sha):
        if await crud.used_bytes(session) + size > quota:
            raise AppError(
                code=ErrorCode.ATTACHMENT_QUOTA_EXCEEDED,
                status_code=413,
                message="The attachments quota is reached",
                details={"quota_bytes": quota},
            )
    row = InterventionAttachment(
        intervention_id=intervention_id,
        sha256=sha,
        size=size,
        content_type=content_type,
        filename=filename,
        uploaded_by=actor,
    )
    session.add(row)
    out = AttachmentOut(
        id=row.id,
        intervention_id=intervention_id,
        filename=filename,
        content_type=content_type,
        size=size,
        uploaded_by=actor,
        created_at=row.created_at,
    )
    await session.flush()
    audit.record(
        session,
        actor=actor,
        action="intervention.attachment_add",
        resource_type="intervention",
        resource_id=str(intervention_id),
        details=_details(machine_id, out, sha),
    )
    await session.commit()
    return out


def _details(machine_id: uuid.UUID, a: AttachmentOut, sha: str) -> dict[str, Any]:
    return {
        "machine_id": str(machine_id),
        "attachment_id": str(a.id),
        "filename": a.filename,
        "size": a.size,
        "sha256": sha,
        "content_type": a.content_type,
    }


@router.get("/{attachment_id}/content")
async def download_attachment(
    attachment_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> FileResponse:
    """The file, as an attachment, under the type recognised at upload."""
    attachment, _ = await _require_attachment(session, attachment_id, scope)
    path = storage.path_for(attachment.sha256)
    if not path.is_file():
        raise AppError(
            code=ErrorCode.ATTACHMENT_FILE_MISSING,
            status_code=404,
            message="The file is missing from the server",
        )
    # Starlette writes ``filename="…"`` or ``filename*=utf-8''…`` itself:
    # quotes, backslashes, semicolons and accents never reach the header raw.
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type="attachment",
        headers=_DOWNLOAD_HEADERS,
    )


@router.delete("/{attachment_id}", status_code=204, dependencies=[_WRITE])
async def delete_attachment(
    attachment_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> None:
    attachment, machine_id = await _require_attachment(session, attachment_id, scope)
    out = AttachmentOut.model_validate(attachment)
    sha = attachment.sha256
    audit.record(
        session,
        actor=current.email,
        action="intervention.attachment_delete",
        resource_type="intervention",
        resource_id=str(out.intervention_id),
        details=_details(machine_id, out, sha),
    )
    await session.delete(attachment)
    await session.commit()
    # Gone from the disk too, unless another line names the same file.
    await crud.discard_if_orphan(session, sha)
