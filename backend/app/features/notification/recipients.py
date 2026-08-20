"""Who receives which notification, read from the accounts themselves.

Recipients are console accounts and their chosen cadence, not the static
``ALERT_RECIPIENTS`` list: a supervision console already knows who its operators
are, and an address in an environment variable cannot be turned off by the
person receiving the mail.

``ALERT_RECIPIENTS`` survives as a fallback for a deployment that has not
created its accounts yet — a fresh install whose only user is the seeded admin
still has someone to tell.
"""

from collections.abc import Iterable

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.user.models import EmailPreference, User


async def recipients_for(
    session: AsyncSession, preferences: Iterable[EmailPreference]
) -> list[str]:
    """Active accounts whose cadence is one of ``preferences``.

    Deactivated accounts are excluded: someone who has lost their console access
    must stop receiving what the console knows.
    """
    wanted = [str(p) for p in preferences]
    if not wanted:
        return []
    rows = await session.exec(
        select(User.email)
        .where(col(User.is_active).is_(True))
        .where(col(User.email_preference).in_(wanted))
        .order_by(col(User.email))
    )
    return list(rows.all())


async def has_active_accounts(session: AsyncSession) -> bool:
    """Whether any active console account exists.

    Separates "nobody has been asked yet" from "everybody answered no" — which
    is the difference between a deployment that needs the configured fallback
    and a team that has deliberately turned the mail off.
    """
    found = await session.exec(
        select(User.id).where(col(User.is_active).is_(True)).limit(1)
    )
    return found.first() is not None


def fallback_recipients() -> list[str]:
    """The configured alert addresses, for a deployment with no accounts yet."""
    return list(settings.ALERT_RECIPIENTS)
