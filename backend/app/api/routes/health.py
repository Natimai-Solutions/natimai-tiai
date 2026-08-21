from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import SessionDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health probe payload."""

    status: str
    timestamp: datetime
    database: bool


@router.get("/health", response_model=HealthResponse)
async def health(session: SessionDep) -> HealthResponse:
    """Liveness + DB readiness probe."""
    database_ok = False
    try:
        await session.exec(select(1))
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False

    return HealthResponse(
        status="ok" if database_ok else "degraded",
        timestamp=datetime.now(UTC),
        database=database_ok,
    )
