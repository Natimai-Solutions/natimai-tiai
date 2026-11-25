"""Outbound webhooks (C8): written and read by ``webhook:write`` and
``webhook:read``, for the whole parc only — the events they carry are the
parc's. The signing secret is returned at creation and at its renewal, never
otherwise."""

import secrets
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlmodel import col, select

from app.api.deps import CurrentScope, CurrentUser, SessionDep, require_permission
from app.api.fields import not_null
from app.core import secretbox
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.base import utcnow
from app.features.user.models import Language
from app.features.user.permissions import Action, Resource
from app.features.user.scope import Scope
from app.features.webhook import deliver, destination
from app.features.webhook.emit import envelope
from app.features.webhook.models import (
    SUBSCRIBABLE,
    DeliveryStatus,
    Webhook,
    WebhookDelivery,
    WebhookEvent,
    WebhookFormat,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_READ = Depends(require_permission(Resource.WEBHOOK, Action.READ))
_WRITE = Depends(require_permission(Resource.WEBHOOK, Action.WRITE))

MAX_WEBHOOKS = 50


def _whole_parc(scope: Scope | None) -> None:
    if scope is not None:
        raise AppError(
            code=ErrorCode.AUTH_SCOPE_RESTRICTED,
            status_code=403,
            message="Webhooks carry the whole parc's events",
        )


class WebhookFields(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    format: WebhookFormat | None = None
    language: Language | None = None
    events: list[WebhookEvent] | None = Field(
        default=None, max_length=len(SUBSCRIBABLE)
    )
    enabled: bool | None = None

    @field_validator("name", "url", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("events")
    @classmethod
    def _subscribable(
        cls, value: list[WebhookEvent] | None
    ) -> list[WebhookEvent] | None:
        if value is None:
            return None
        if WebhookEvent.TEST in value:
            raise ValueError("« test » is sent on demand, not subscribed to")
        return list(dict.fromkeys(value))

    _not_null = not_null("name", "url", "format", "language", "events", "enabled")


class WebhookCreate(WebhookFields):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8, max_length=2000)
    format: WebhookFormat = WebhookFormat.JSON
    language: Language = Language.FR
    events: list[WebhookEvent] = Field(min_length=1, max_length=len(SUBSCRIBABLE))
    enabled: bool = True


class WebhookOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    format: str
    language: str
    events: list[str]
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    # Deliveries still owed.
    pending: int = 0


class WebhookWithSecret(WebhookOut):
    # Shown now and never again: the receiver checks the signature with it.
    secret: str


class DeliveryOut(BaseModel):
    id: uuid.UUID
    event: str
    status: str
    attempts: int
    response_status: int | None
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    next_attempt_at: datetime


class TestOut(BaseModel):
    ok: bool
    response_status: int | None
    error: str | None


async def _check_destination(url: str) -> None:
    try:
        await destination.check(url)
    except destination.DestinationError as exc:
        raise AppError(
            code=ErrorCode.WEBHOOK_DESTINATION_REFUSED,
            status_code=422,
            message=str(exc),
            details={"reason": exc.code},
        ) from None


async def _require(
    session: SessionDep, webhook_id: uuid.UUID, lock: bool = False
) -> Webhook:
    hook = await session.get(Webhook, webhook_id, with_for_update=lock)
    if hook is None:
        raise AppError(
            code=ErrorCode.WEBHOOK_NOT_FOUND, status_code=404, message="No such webhook"
        )
    return hook


async def _pending(session: SessionDep, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    from sqlalchemy import func

    if not ids:
        return {}
    rows = await session.exec(
        select(col(WebhookDelivery.webhook_id), func.count())
        .where(
            col(WebhookDelivery.webhook_id).in_(ids),
            col(WebhookDelivery.status) == DeliveryStatus.PENDING,
        )
        .group_by(col(WebhookDelivery.webhook_id))
    )
    return dict(rows.all())


def _out(hook: Webhook, pending: int = 0) -> dict[str, Any]:
    return {
        "id": hook.id,
        "name": hook.name,
        "url": hook.url,
        "format": hook.format,
        "language": hook.language,
        "events": list(hook.events),
        "enabled": hook.enabled,
        "created_by": hook.created_by,
        "created_at": hook.created_at,
        "updated_at": hook.updated_at,
        "last_success_at": hook.last_success_at,
        "last_failure_at": hook.last_failure_at,
        "last_error": hook.last_error,
        "consecutive_failures": hook.consecutive_failures,
        "pending": pending,
    }


def _audit_details(hook: Webhook) -> dict[str, Any]:
    return {
        "name": hook.name,
        "url": hook.url,
        "format": hook.format,
        "events": ", ".join(hook.events),
        "enabled": hook.enabled,
    }


@router.get("", response_model=list[WebhookOut], dependencies=[_READ])
async def list_webhooks(session: SessionDep, scope: CurrentScope) -> list[WebhookOut]:
    _whole_parc(scope)
    hooks = list(
        (await session.exec(select(Webhook).order_by(col(Webhook.created_at)))).all()
    )
    pending = await _pending(session, [h.id for h in hooks])
    return [WebhookOut(**_out(h, pending.get(h.id, 0))) for h in hooks]


@router.post(
    "", response_model=WebhookWithSecret, status_code=201, dependencies=[_WRITE]
)
async def create_webhook(
    payload: WebhookCreate,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> WebhookWithSecret:
    _whole_parc(scope)
    await _check_destination(payload.url)
    from sqlalchemy import func

    count = await session.scalar(select(func.count()).select_from(Webhook))
    if (count or 0) >= MAX_WEBHOOKS:
        raise AppError(
            code=ErrorCode.REQUEST_VALIDATION_ERROR,
            status_code=409,
            message=f"{MAX_WEBHOOKS} webhooks at most",
        )
    secret = secrets.token_urlsafe(32)
    hook = Webhook(
        name=payload.name,
        url=payload.url,
        format=payload.format,
        language=payload.language,
        events=[e.value for e in payload.events],
        enabled=payload.enabled,
        secret=secretbox.encrypt(secret),
        created_by=current.email,
    )
    session.add(hook)
    audit.record(
        session,
        actor=current.email,
        action="webhook.create",
        resource_type="webhook",
        resource_id=str(hook.id),
        details=_audit_details(hook),
    )
    await session.commit()
    await session.refresh(hook)
    return WebhookWithSecret(**_out(hook), secret=secret)


@router.get("/{webhook_id}", response_model=WebhookOut, dependencies=[_READ])
async def get_webhook(
    webhook_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> WebhookOut:
    _whole_parc(scope)
    hook = await _require(session, webhook_id)
    pending = await _pending(session, [hook.id])
    return WebhookOut(**_out(hook, pending.get(hook.id, 0)))


@router.patch("/{webhook_id}", response_model=WebhookOut, dependencies=[_WRITE])
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookFields,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> WebhookOut:
    _whole_parc(scope)
    hook = await _require(session, webhook_id, lock=True)
    fields = payload.model_dump(exclude_unset=True)
    if "url" in fields and fields["url"] != hook.url:
        await _check_destination(fields["url"])
    if "events" in fields:
        fields["events"] = [WebhookEvent(e).value for e in fields["events"]]
    for name, value in fields.items():
        setattr(hook, name, value)
    if fields.get("enabled") is True:
        hook.consecutive_failures = 0
    hook.updated_at = utcnow()
    session.add(hook)
    audit.record(
        session,
        actor=current.email,
        action="webhook.update",
        resource_type="webhook",
        resource_id=str(hook.id),
        details={**_audit_details(hook), "fields": sorted(fields)},
    )
    await session.commit()
    await session.refresh(hook)
    return WebhookOut(**_out(hook))


@router.delete("/{webhook_id}", status_code=204, dependencies=[_WRITE])
async def delete_webhook(
    webhook_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> None:
    _whole_parc(scope)
    hook = await _require(session, webhook_id, lock=True)
    audit.record(
        session,
        actor=current.email,
        action="webhook.delete",
        resource_type="webhook",
        resource_id=str(hook.id),
        details=_audit_details(hook),
    )
    await session.delete(hook)
    await session.commit()


@router.post(
    "/{webhook_id}/secret", response_model=WebhookWithSecret, dependencies=[_WRITE]
)
async def renew_secret(
    webhook_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> WebhookWithSecret:
    """A new signing secret: the old one stops being used at once."""
    _whole_parc(scope)
    hook = await _require(session, webhook_id, lock=True)
    secret = secrets.token_urlsafe(32)
    hook.secret = secretbox.encrypt(secret)
    hook.updated_at = utcnow()
    session.add(hook)
    audit.record(
        session,
        actor=current.email,
        action="webhook.secret_renew",
        resource_type="webhook",
        resource_id=str(hook.id),
        details={"name": hook.name},
    )
    await session.commit()
    await session.refresh(hook)
    return WebhookWithSecret(**_out(hook), secret=secret)


@router.post("/{webhook_id}/test", response_model=TestOut, dependencies=[_WRITE])
async def test_webhook(
    webhook_id: uuid.UUID,
    session: SessionDep,
    scope: CurrentScope,
    current: CurrentUser,
) -> TestOut:
    """Send a ``test`` event now and say what came back. Recorded in the
    history like any delivery, never retried."""
    _whole_parc(scope)
    hook = await _require(session, webhook_id)
    payload = envelope(WebhookEvent.TEST, {"by": current.email})
    secret = secretbox.decrypt(hook.secret)
    status_code: int | None = None
    error: str | None = None
    delivery_id = uuid.uuid4()
    if secret is None:
        error = "signing secret unreadable (SECRET_KEY changed): renew it"
    else:
        try:
            status_code = await deliver.post(
                hook.url,
                deliver.body_of(hook.format, hook.language, payload),
                secret,
                WebhookEvent.TEST.value,
                str(delivery_id),
            )
            if not 200 <= status_code < 300:
                error = f"HTTP {status_code}"
        except destination.DestinationError as exc:
            error = f"destination refused: {exc}"
        except Exception as exc:  # noqa: BLE001 — any transport failure, said
            error = f"{type(exc).__name__}: {exc}"
    now = utcnow()
    session.add(
        WebhookDelivery(
            id=delivery_id,
            webhook_id=hook.id,
            event=WebhookEvent.TEST.value,
            payload=payload,
            status=DeliveryStatus.SENT if error is None else DeliveryStatus.FAILED,
            attempts=1,
            response_status=status_code,
            last_error=error[:500] if error else None,
            sent_at=now if error is None else None,
        )
    )
    await session.commit()
    return TestOut(
        ok=error is None,
        response_status=status_code,
        error=error[:500] if error else None,
    )


@router.get(
    "/{webhook_id}/deliveries", response_model=list[DeliveryOut], dependencies=[_READ]
)
async def list_deliveries(
    webhook_id: uuid.UUID, session: SessionDep, scope: CurrentScope
) -> list[DeliveryOut]:
    """The 50 latest deliveries, newest first."""
    _whole_parc(scope)
    await _require(session, webhook_id)
    rows = await session.exec(
        select(WebhookDelivery)
        .where(col(WebhookDelivery.webhook_id) == webhook_id)
        .order_by(col(WebhookDelivery.created_at).desc())
        .limit(50)
    )
    return [
        DeliveryOut(
            id=d.id,
            event=d.event,
            status=d.status,
            attempts=d.attempts,
            response_status=d.response_status,
            last_error=d.last_error,
            created_at=d.created_at,
            sent_at=d.sent_at,
            next_attempt_at=d.next_attempt_at,
        )
        for d in rows.all()
    ]
