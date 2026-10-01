"""Minimal Mailgun client — one of the two channels this console sends mail through."""

import httpx

from app.core.config import settings
from app.features.setting.email_policy import EmailPolicy


async def send_email(
    subject: str, text: str, to: list[str], *, policy: EmailPolicy
) -> bool:
    """Send a plain-text e-mail via the Mailgun API.

    Returns False (no-op) when Mailgun is not configured, or when handed no
    recipient.

    ``to`` is required and has no configured default. Every caller knows who it
    is writing to — an account holder, or the operators whose cadence asked for
    this message — and a client that could fall back on an address from the
    configuration is a client that can mail someone nobody chose.

    The account (domain, key, region) comes from the resolved ``policy``; the
    proxy stays an environment setting: it describes the server's network,
    which the console has no business changing.
    """
    if not policy.mailgun_configured or not to:
        return False

    sender = f"{policy.from_name} <{policy.from_email}>"
    url = f"{policy.mailgun_base_url.rstrip('/')}/{policy.mailgun_domain}/messages"

    async with httpx.AsyncClient(
        timeout=policy.mailgun_timeout_seconds,
        proxy=settings.MAILGUN_PROXY_URL,
    ) as client:
        resp = await client.post(
            url,
            auth=("api", policy.mailgun_api_key or ""),
            data={
                "from": sender,
                "to": to,
                "subject": subject,
                "text": text,
            },
        )
        resp.raise_for_status()
    return True
