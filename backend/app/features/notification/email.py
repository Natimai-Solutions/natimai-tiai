"""The one ``send_email`` the rest of the application calls.

Which way a mail leaves the console — Mailgun's HTTP API or an SMTP server —
is a deployment choice (``EMAIL_PROVIDER``), made once in the environment and
invisible to every caller: the outbox hands a subject, a body and a recipient
to this function and gets back whether they went out.
"""

from app.core.config import settings
from app.features.notification import mailgun, smtp


async def send_email(subject: str, text: str, to: list[str]) -> bool:
    """Send a plain-text e-mail through the provider the deployment chose.

    Returns False (no-op) when that provider is not configured, or when handed
    no recipient. Anything the provider raises propagates: the outbox is what
    turns a failure into a retry, and it needs the error to keep.
    """
    if not settings.alerts_enabled or not to:
        return False
    if settings.EMAIL_PROVIDER == "smtp":
        return await smtp.send_email(subject, text, to)
    return await mailgun.send_email(subject, text, to)
