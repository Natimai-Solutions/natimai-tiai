"""Send what the webhooks are owed (C8): the worker's side of the queue.

At-least-once, like the mail outbox: each delivery's outcome is committed as
soon as it is known. A failure is retried, 1 minute doubling to an hour,
WEBHOOK_MAX_ATTEMPTS times, then given up. The destination is checked again
before each send (``destination.check``), and no redirect is followed.

The body is signed: ``X-Tiai-Signature: t=<unix time>,v1=<hex>``, the hex an
HMAC-SHA256 of ``"<t>.<body>"`` under the webhook's secret. A receiver
recomputes it and refuses a time too far from its own, which bounds replay.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import secretbox
from app.core.config import settings
from app.features.base import utcnow
from app.features.webhook import destination, texts
from app.features.webhook.models import (
    DeliveryStatus,
    Webhook,
    WebhookDelivery,
    WebhookFormat,
)

logger = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 60
RETRY_MAX_SECONDS = 3600
USER_AGENT = "Tiai-Webhook/1"

# Replaced by the tests with a receiver of their own.
TRANSPORT: httpx.AsyncBaseTransport | None = None


def signature(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def body_of(hook_format: str, language: str, payload: dict[str, Any]) -> bytes:
    if hook_format == WebhookFormat.JSON:
        document: dict[str, Any] = payload
    else:
        document = texts.chat_body(payload["event"], payload.get("data", {}), language)
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()


def _retry_delay(attempts: int) -> timedelta:
    return timedelta(
        seconds=min(RETRY_BASE_SECONDS * 2 ** (attempts - 1), RETRY_MAX_SECONDS)
    )


async def post(url: str, body: bytes, secret: str, event: str, delivery_id: str) -> int:
    """Send one body; returns the HTTP status. Raises on a refused
    destination or a transport error."""
    await destination.check(url)
    timestamp = int(time.time())
    async with httpx.AsyncClient(
        timeout=settings.WEBHOOK_TIMEOUT_SECONDS,
        proxy=settings.WEBHOOK_PROXY_URL if TRANSPORT is None else None,
        transport=TRANSPORT,
        follow_redirects=False,
    ) as client:
        resp = await client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": USER_AGENT,
                "X-Tiai-Event": event,
                "X-Tiai-Delivery": delivery_id,
                "X-Tiai-Signature": signature(secret, timestamp, body),
            },
        )
    return resp.status_code


async def send_pending(
    session: AsyncSession,
    *,
    batch_size: int = 50,
    budget_seconds: float | None = 60,
    stop: asyncio.Event | None = None,
) -> int:
    """Try every due delivery once; returns how many went through."""
    started = time.monotonic()
    now = utcnow()
    rows = await session.exec(
        select(WebhookDelivery, Webhook)
        .join(Webhook, col(Webhook.id) == col(WebhookDelivery.webhook_id))
        .where(
            col(WebhookDelivery.status) == DeliveryStatus.PENDING,
            col(WebhookDelivery.next_attempt_at) <= now,
        )
        .order_by(col(WebhookDelivery.created_at))
        .limit(batch_size)
        .with_for_update(skip_locked=True, of=WebhookDelivery)
    )
    due = [
        (
            d.id,
            d.event,
            d.payload,
            d.attempts,
            w.id,
            w.url,
            w.format,
            w.language,
            w.secret,
            w.enabled,
        )
        for d, w in rows.all()
    ]
    sent = 0
    for (
        delivery_id,
        event,
        payload,
        attempts,
        webhook_id,
        url,
        hook_format,
        language,
        sealed,
        enabled,
    ) in due:
        if stop is not None and stop.is_set():
            break
        if budget_seconds is not None and time.monotonic() - started >= budget_seconds:
            break
        status_code: int | None = None
        error: str | None = None
        if not enabled:
            error = "webhook disabled"
        else:
            secret = secretbox.decrypt(sealed)
            if secret is None:
                error = "signing secret unreadable (SECRET_KEY changed): renew it"
            else:
                try:
                    status_code = await post(
                        url,
                        body_of(hook_format, language, payload),
                        secret,
                        event,
                        str(delivery_id),
                    )
                    if not 200 <= status_code < 300:
                        error = f"HTTP {status_code}"
                except destination.DestinationError as exc:
                    error = f"destination refused: {exc}"
                except httpx.HTTPError as exc:
                    error = f"{type(exc).__name__}: {exc}"
        error = error[:500] if error else None
        stamp = utcnow()
        values: dict[str, Any] = {"response_status": status_code}
        if error is None:
            values |= {"status": DeliveryStatus.SENT, "sent_at": stamp}
            sent += 1
            hook_values: dict[str, Any] = {
                "last_success_at": stamp,
                "consecutive_failures": 0,
            }
        else:
            attempts += 1
            values |= {"attempts": attempts, "last_error": error}
            if attempts >= settings.WEBHOOK_MAX_ATTEMPTS or not enabled:
                values["status"] = DeliveryStatus.FAILED
            else:
                values["next_attempt_at"] = stamp + _retry_delay(attempts)
            hook_values = {
                "last_failure_at": stamp,
                "last_error": error,
                "consecutive_failures": col(Webhook.consecutive_failures) + 1,
            }
            logger.warning("Webhook %s: %s failed (%s)", webhook_id, event, error)
        await session.exec(
            update(WebhookDelivery)
            .where(col(WebhookDelivery.id) == delivery_id)
            .values(**values)
        )
        await session.exec(
            update(Webhook).where(col(Webhook.id) == webhook_id).values(**hook_values)
        )
        await session.commit()
    await session.commit()
    return sent


async def purge(session: AsyncSession) -> int:
    """Drop the settled deliveries past WEBHOOK_DELIVERY_RETENTION_DAYS.
    Pending ones are kept: still owed. Commits."""
    cutoff = utcnow() - timedelta(days=settings.WEBHOOK_DELIVERY_RETENTION_DAYS)
    result = await session.exec(
        delete(WebhookDelivery).where(
            col(WebhookDelivery.status) != DeliveryStatus.PENDING,
            col(WebhookDelivery.created_at) < cutoff,
        )
    )
    await session.commit()
    return result.rowcount or 0
