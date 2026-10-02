"""The one ``send_email`` the rest of the application calls.

Which way a mail leaves the console — Mailgun's HTTP API or an SMTP server —
is a choice of the resolved ``EmailPolicy``: the environment's
``EMAIL_PROVIDER`` unless the page Paramètres chose otherwise. Invisible to
every caller: the outbox hands a subject, a body, a recipient and the policy it
resolved for this drain, and gets back whether they went out.
"""

from app.features.notification import mailgun, smtp
from app.features.setting.email_policy import EmailPolicy


async def send_email(
    subject: str, text: str, to: list[str], *, policy: EmailPolicy
) -> bool:
    """Send a plain-text e-mail through the provider the policy chose.

    Returns False (no-op) when that provider is not configured, or when handed
    no recipient. Anything the provider raises propagates: the outbox is what
    turns a failure into a retry, and it needs the error to keep.
    """
    if not policy.enabled or not to:
        return False
    if policy.provider == "smtp":
        return await smtp.send_email(subject, text, to, policy=policy)
    return await mailgun.send_email(subject, text, to, policy=policy)
