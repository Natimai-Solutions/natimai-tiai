from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.auth import router as auth_router
from app.api.routes.commands import router as commands_router
from app.api.routes.machines import router as machines_router
from app.api.routes.stats import router as stats_router
from app.api.routes.threats import router as threats_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(agent_router)
api_router.include_router(machines_router)
api_router.include_router(commands_router)
api_router.include_router(stats_router)
api_router.include_router(threats_router)
api_router.include_router(users_router)
