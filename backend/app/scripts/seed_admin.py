"""Seed the built-in groups, and the first admin user from
FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD.

Idempotent: the groups are created only if missing, the user only if absent
and the env set. Run via: python -m app.scripts.seed_admin
"""

import asyncio

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import engine
from app.features.user import crud
from app.features.user.models import normalize_email
from app.features.user.permissions import BuiltinGroup


async def main() -> None:
    """Create the built-in groups and the first admin if needed."""
    async with AsyncSession(engine) as session:
        # Before the admin, and whatever the env says: a database migrated from
        # a version without groups gets its three from the migration, but the
        # groups a later version adds arrive here.
        await crud.ensure_builtin_groups(session)
        await session.commit()

        if not settings.FIRST_ADMIN_EMAIL or not settings.FIRST_ADMIN_PASSWORD:
            print("seed_admin: FIRST_ADMIN_EMAIL/PASSWORD unset, skipping.")
            return
        # Normalised like any address the console writes: an `.env` saying
        # Admin@… must find the account seeded as admin@… on the last boot,
        # not trip over the case-insensitive unique index trying to add it.
        email = normalize_email(settings.FIRST_ADMIN_EMAIL)
        existing = await crud.get_by_email(session, email)
        if existing is not None:
            print(f"seed_admin: {email} already exists.")
            return
        await crud.create_user(
            session,
            email=email,
            password=settings.FIRST_ADMIN_PASSWORD,
            groups=[BuiltinGroup.ADMIN],
        )
        print(f"seed_admin: created admin {email}.")


if __name__ == "__main__":
    asyncio.run(main())
