from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.assets import machine_router as machine_assets_router
from app.api.routes.assets import router as assets_router
from app.api.routes.audit import router as audit_router
from app.api.routes.auth import router as auth_router
from app.api.routes.checks import assignable_router as checks_assignable_router
from app.api.routes.checks import machine_router as machine_checks_router
from app.api.routes.checks import router as checks_router
from app.api.routes.commands import router as commands_router
from app.api.routes.directory import router as directory_router
from app.api.routes.groups import router as groups_router
from app.api.routes.interventions import machine_router as machine_interventions_router
from app.api.routes.interventions import router as interventions_router
from app.api.routes.licenses import router as licenses_router
from app.api.routes.machines import router as machines_router
from app.api.routes.maintenance import machine_router as machine_maintenance_router
from app.api.routes.maintenance import owners_router as maintenance_owners_router
from app.api.routes.maintenance import room_router as room_maintenance_router
from app.api.routes.maintenance import router as maintenance_router
from app.api.routes.oidc import router as oidc_router
from app.api.routes.packages import router as packages_router
from app.api.routes.reports import public_router as public_reports_router
from app.api.routes.reports import router as reports_router
from app.api.routes.rooms import buildings_router, rooms_router
from app.api.routes.schedules import router as schedules_router
from app.api.routes.settings_routes import router as settings_router
from app.api.routes.software import router as software_router
from app.api.routes.stats import router as stats_router
from app.api.routes.threats import router as threats_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(agent_router)
api_router.include_router(machines_router)
api_router.include_router(alerts_router)
api_router.include_router(assets_router)
api_router.include_router(schedules_router)
api_router.include_router(reports_router)
api_router.include_router(licenses_router)
api_router.include_router(oidc_router)
api_router.include_router(directory_router)
api_router.include_router(public_reports_router)
api_router.include_router(machine_assets_router)
api_router.include_router(buildings_router)
api_router.include_router(rooms_router)
api_router.include_router(machine_interventions_router)
api_router.include_router(interventions_router)
api_router.include_router(machine_checks_router)
api_router.include_router(checks_assignable_router)
api_router.include_router(checks_router)
api_router.include_router(maintenance_owners_router)
api_router.include_router(maintenance_router)
api_router.include_router(room_maintenance_router)
api_router.include_router(machine_maintenance_router)
api_router.include_router(settings_router)
api_router.include_router(commands_router)
api_router.include_router(software_router)
api_router.include_router(packages_router)
api_router.include_router(stats_router)
api_router.include_router(threats_router)
api_router.include_router(users_router)
api_router.include_router(groups_router)
api_router.include_router(audit_router)
