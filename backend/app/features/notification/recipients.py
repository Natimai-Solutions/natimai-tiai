"""Who receives which notification, read from the accounts themselves.

The recipients of a supervision message are the console's own operators and the
cadence each of them chose — there is no configured address list beside them.
A console already knows who its operators are, and an address held in an
environment variable cannot be turned off by the person receiving the mail.

Nobody on a given cadence therefore means nobody is mailed, which is an answer
and not a gap: a fresh install seeds its first admin (``scripts/seed_admin``)
with the daily digest as the default, so an unattended deployment is watched
from its first morning — at a real address, changeable from the console.
"""

from collections.abc import Iterable

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

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
