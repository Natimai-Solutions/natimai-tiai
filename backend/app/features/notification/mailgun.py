"""Minimal Mailgun client — the one channel this console sends mail through."""

import httpx

from app.core.config import settings


async def send_email(subject: str, text: str, to: list[str]) -> bool:
    """Send a plain-text e-mail via the Mailgun API.

    Returns False (no-op) when Mailgun is not configured, or when handed no
    recipient.

    ``to`` is required and has no configured default. Every caller knows who it
    is writing to — an account holder, or the operators whose cadence asked for
    this message — and a client that could fall back on an address from the
    environment is a client that can mail someone nobody chose.
    """
    if not settings.alerts_enabled or not to:
        return False

    from_name = settings.MAILGUN_FROM_NAME or settings.PROJECT_NAME
    sender = f"{from_name} <{settings.MAILGUN_FROM_EMAIL}>"
    url = f"{settings.MAILGUN_API_BASE_URL}/{settings.MAILGUN_DOMAIN}/messages"

    async with httpx.AsyncClient(
        timeout=settings.MAILGUN_TIMEOUT_SECONDS,
        proxy=settings.MAILGUN_PROXY_URL,
    ) as client:
        resp = await client.post(
            url,
            auth=("api", settings.MAILGUN_API_KEY or ""),
            data={
                "from": sender,
                "to": to,
                "subject": subject,
                "text": text,
            },
        )
        resp.raise_for_status()
    return True
