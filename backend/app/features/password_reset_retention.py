"""Retention of the "forgot password" tokens.

A reset token is worth something for an hour (``PASSWORD_RESET_EXPIRE_MINUTES``)
and then never again: once expired or used, the row only answers "was a reset
requested for this account yesterday?". A password change already drops the
account's tokens; the ones nobody followed through stayed for good — one row
per mistyped address of a user who then remembered their password.

Kept a day past their end rather than dropped on the spot, so the morning
after a suspicious burst of reset requests the rows are still there to look at.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, or_
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.user.models import PasswordResetToken

# How long a spent token is kept. Not a setting: nothing reads these rows but
# a person investigating, and a day is what such an investigation needs.
RESET_TOKEN_GRACE = timedelta(days=1)


async def purge_spent_reset_tokens(session: AsyncSession, now: datetime) -> int:
    """Delete the tokens expired or used more than a day before ``now``.

    A token neither used nor expired is never touched, whatever its age —
    the user may be opening the mail right now. Commits; returns the count.
    """
    cutoff = now - RESET_TOKEN_GRACE
    result = await session.exec(
        delete(PasswordResetToken).where(
            or_(
                col(PasswordResetToken.expires_at) < cutoff,
                col(PasswordResetToken.used_at) < cutoff,
            )
        )
    )
    await session.commit()
    return result.rowcount or 0
