"""Pytest fixtures.

Unit tests (security, permissions, fingerprint) need no database.

API tests use a real Postgres test database — set ``TIAI_TEST_DATABASE_URL``
(e.g. postgresql+psycopg://tiai:tiai@localhost:5432/tiai_test). Without it the
DB fixtures skip, so ``pytest`` stays green locally without a database.

A skip is the wrong answer where the database is *supposed* to be there: a CI
whose variable went missing would report two thirds of the suite as skipped and
the run as green. ``TIAI_REQUIRE_TEST_DB=1`` (set by the CI workflow) turns the
missing variable into an error before the first test runs.
"""

import asyncio
import os
import sys

import pytest_asyncio

# psycopg's async driver cannot run on Windows' default ProactorEventLoop.
# Use the selector loop there (no-op on Linux/CI).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# A long-enough key avoids PyJWT's HMAC key-length warning in tests (set before
# app.core.config is imported). Real deployments override SECRET_KEY via env.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-0123456789")

TEST_DATABASE_URL = os.getenv("TIAI_TEST_DATABASE_URL")
REQUIRE_TEST_DB = os.getenv("TIAI_REQUIRE_TEST_DB", "").lower() in {"1", "true", "yes"}


def pytest_configure(config) -> None:
    """Refuse to run a suite that would silently skip its database tests."""
    import pytest

    if REQUIRE_TEST_DB and not TEST_DATABASE_URL:
        raise pytest.UsageError(
            "TIAI_REQUIRE_TEST_DB is set but TIAI_TEST_DATABASE_URL is not: "
            "the DB-backed tests would be skipped, not run."
        )


@pytest_asyncio.fixture
async def engine():
    """Fresh schema on the test database for each test."""
    import pytest

    if not TEST_DATABASE_URL:
        pytest.skip("set TIAI_TEST_DATABASE_URL to run DB-backed tests")

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel

    import app.features.models  # noqa: F401  (populate SQLModel.metadata)

    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    """Async HTTP client bound to the app, backed by the test database."""
    from httpx import ASGITransport, AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.db import get_db
    from app.main import app

    async def override_get_db():
        async with AsyncSession(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
def _fresh_rate_limits():
    """Forget rate-limit state between tests.

    The limiters are process-global, and every API test logs in from the same
    test client IP: without this, the login budget (10 per 5 min) runs out ten
    tests into the suite and everything after fails 429.
    """
    from app.core import ratelimit

    ratelimit.reset_all()
    yield


@pytest_asyncio.fixture
async def db_session(engine):
    """Direct session on the test database (for asserting persisted state)."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    async with AsyncSession(engine) as session:
        yield session
