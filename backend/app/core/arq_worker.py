"""ARQ worker: periodic cleanup of inactive machines and alert notifications.

Run with: arq app.core.arq_worker.WorkerSettings
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from arq import cron
from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.arq_pool import redis_settings
from app.core.config import settings
from app.core.db import engine
from app.features.command.models import Command, CommandStatus
from app.features.machine.models import Machine
from app.features.notification import digest


async def expire_stale_commands(ctx: dict[str, Any]) -> int:
    """Mark pending commands past their expires_at as expired."""
    now = datetime.now(UTC)
    async with AsyncSession(engine) as session:
        result = await session.execute(
            update(Command)
            .where(col(Command.status) == CommandStatus.PENDING)
            .where(col(Command.expires_at) < now)
            .values(status=CommandStatus.EXPIRED)
        )
        await session.commit()
        return result.rowcount or 0  # type: ignore[attr-defined]


async def flag_inactive_machines(ctx: dict[str, Any]) -> int:
    """Count machines that have not checked in recently (alert candidates)."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.INACTIVE_AFTER_DAYS)
    async with AsyncSession(engine) as session:
        rows = await session.exec(
            select(Machine).where(col(Machine.last_seen) < cutoff)
        )
        inactive = rows.all()
        return len(inactive)


async def send_daily_digest(ctx: dict[str, Any]) -> int:
    """Mail the daily fleet digest to the accounts that asked for one.

    Runs once a day at ``DIGEST_HOUR_UTC``. Which accounts hear from it, and on
    which days, is decided per account — see ``features/notification/digest``.
    """
    async with AsyncSession(engine) as session:
        return await digest.send_daily_digest(session)


class WorkerSettings:
    """ARQ worker configuration."""

    redis_settings = redis_settings()
    functions = [expire_stale_commands, flag_inactive_machines, send_daily_digest]
    cron_jobs = [
        cron(expire_stale_commands, minute=set(range(0, 60, 5))),  # every 5 min
        cron(flag_inactive_machines, hour={8}, minute={0}),  # daily 08:00 UTC
        # One digest a day, at the hour the deployment chose. Minute 0 of a
        # single hour: ARQ crons fire on every matching minute otherwise, and a
        # digest sent sixty times over is worse than one not sent at all.
        cron(send_daily_digest, hour={settings.DIGEST_HOUR_UTC}, minute={0}),
    ]
