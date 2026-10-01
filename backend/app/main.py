import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.routes.health import router as health_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.features.setting import email_policy

# uvicorn wires handlers for its own loggers only: without this, the app's
# lines — the security log above all — would have no handler and vanish. Same
# format as the worker (app.core.worker); a no-op if a handler already exists
# (pytest, an embedding process).
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Read the console's mail settings once, before the first request.

    ``queue_email`` decides synchronously whether mail is configured, off the
    last policy this process resolved; without this load, a password reset
    asked for right after a restart would be judged on the environment alone
    and dropped on a server whose mail is configured in the console. Best
    effort: a database not answering yet must not keep the API down — the
    next resolution (a settings page, a threat alert) fills the gap.
    """
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.db import engine

    try:
        async with AsyncSession(engine) as session:
            await email_policy.load_stored(session)
    except Exception:
        logging.getLogger(__name__).exception(
            "Could not read the e-mail settings at startup; using the environment"
        )
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Standardized error envelope for every error response (plan §2.14).
register_error_handlers(app)

if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# /health at the root (probed by Caddy / docker healthchecks).
app.include_router(health_router)
# Versioned API.
app.include_router(api_router, prefix=settings.API_V1_STR)
