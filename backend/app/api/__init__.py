from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.audit import router as audit_router
from app.api.routes.auth import router as auth_router
from app.api.routes.commands import router as commands_router
from app.api.routes.groups import router as groups_router
from app.api.routes.interventions import machine_router as machine_interventions_router
from app.api.routes.interventions import router as interventions_router
from app.api.routes.machines import router as machines_router
from app.api.routes.rooms import buildings_router, rooms_router
from app.api.routes.software import router as software_router
from app.api.routes.stats import router as stats_router
from app.api.routes.threats import router as threats_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(agent_router)
api_router.include_router(machines_router)
api_router.include_router(buildings_router)
api_router.include_router(rooms_router)
api_router.include_router(machine_interventions_router)
api_router.include_router(interventions_router)
api_router.include_router(commands_router)
api_router.include_router(software_router)
api_router.include_router(stats_router)
api_router.include_router(threats_router)
api_router.include_router(users_router)
api_router.include_router(groups_router)
api_router.include_router(audit_router)
