from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
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


async def assert_not_superuser(bind: AsyncEngine | None = None) -> None:
    """Refuse to run outside `local` as a PostgreSQL superuser.

    A superuser reads and writes any file of the database server and runs
    programs there (``COPY … TO PROGRAM``): an SQL injection or a compromised
    dependency in this process would own the database host. The application
    role owns Tia'i's tables and nothing more (deploy/db/app-role.sh).
    """
    async with (bind or engine).connect() as conn:
        result = await conn.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        )
        is_super = bool(result.scalar_one())
    if is_super and settings.ENVIRONMENT != "local":
        raise RuntimeError(
            f"POSTGRES_USER={settings.POSTGRES_USER} is a PostgreSQL superuser; "
            f"refusing to start in {settings.ENVIRONMENT}. Run deploy/db/app-role.sh "
            "and point the backend at the application role (DEPLOYMENT.md)."
        )
