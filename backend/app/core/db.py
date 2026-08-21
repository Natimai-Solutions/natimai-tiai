from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings

# Import all models so SQLModel.metadata is fully populated before use.
from app.features.models import *  # noqa: F401,F403

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=settings.POSTGRES_POOL_SIZE,
    max_overflow=settings.POSTGRES_MAX_OVERFLOW,
    pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
    pool_pre_ping=True,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session."""
    async with AsyncSession(engine) as session:
        yield session


async def ping() -> bool:
    """Return True if the database answers a trivial query."""
    async with AsyncSession(engine) as session:
        await session.exec(select(1))
        return True
