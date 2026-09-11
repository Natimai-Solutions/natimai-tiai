"""Console settings: the parc-wide maintenance defaults, editable without a
restart. ``settings:read`` to see them, ``settings:write`` to change them —
the administrators hold both implicitly; nobody else does by default.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.core.config import settings as env
from app.core.errors import AppError, ErrorCode
from app.features.audit import crud as audit
from app.features.setting import crud
from app.features.user.models import User
from app.features.user.permissions import Action, Resource

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(require_permission(Resource.SETTINGS, Action.READ))],
)
_WRITE = Depends(require_permission(Resource.SETTINGS, Action.WRITE))


class UserRef(BaseModel):
    id: uuid.UUID
    name: str


class SettingsOut(BaseModel):
    maintenance_default_cycle_days: int
    maintenance_default_owner: UserRef | None
    maintenance_due_soon_days: int
    # What the environment says, for the page to show where a value comes
    # from before the console ever wrote one.
    env_default_cycle_days: int
    env_due_soon_days: int
    room_source: str
    updated_at: datetime | None


class SettingsUpdate(BaseModel):
    """Partial: only the supplied fields are written. ``owner_id`` set to
    null clears the default owner."""

    maintenance_default_cycle_days: int | None = Field(default=None, ge=0, le=3650)
    maintenance_default_owner_id: uuid.UUID | None = None
    maintenance_due_soon_days: int | None = Field(default=None, ge=0, le=365)


async def _out(session: SessionDep) -> SettingsOut:
    policy = await crud.maintenance_policy(session)
    owner = await session.get(User, policy.owner_id) if policy.owner_id else None
    values = await crud.get_all(session)
    updated: datetime | None = None
    from sqlmodel import col, func, select

    from app.features.setting.models import AppSetting

    latest = await session.exec(select(func.max(col(AppSetting.updated_at))))
    updated = latest.one()
    del values
    return SettingsOut(
        maintenance_default_cycle_days=policy.cycle_days,
        maintenance_default_owner=(
            UserRef(id=owner.id, name=owner.full_name or owner.email) if owner else None
        ),
        maintenance_due_soon_days=policy.due_soon_days,
        env_default_cycle_days=env.MAINTENANCE_DEFAULT_CYCLE_DAYS,
        env_due_soon_days=env.MAINTENANCE_DUE_SOON_DAYS,
        room_source=env.ROOM_SOURCE,
        updated_at=updated,
    )


@router.get("", response_model=SettingsOut)
async def get_settings(session: SessionDep) -> SettingsOut:
    return await _out(session)


@router.patch("", response_model=SettingsOut, dependencies=[_WRITE])
async def update_settings(
    payload: SettingsUpdate, session: SessionDep, current: CurrentUser
) -> SettingsOut:
    fields = payload.model_dump(exclude_unset=True)
    if "maintenance_default_cycle_days" in fields:
        await crud.set_value(
            session,
            crud.KEY_CYCLE,
            fields["maintenance_default_cycle_days"],
            actor=current.email,
        )
    if "maintenance_due_soon_days" in fields:
        await crud.set_value(
            session,
            crud.KEY_DUE_SOON,
            fields["maintenance_due_soon_days"],
            actor=current.email,
        )
    if "maintenance_default_owner_id" in fields:
        owner_id = fields["maintenance_default_owner_id"]
        if owner_id is not None:
            owner = await session.get(User, owner_id)
            if owner is None or not owner.is_active:
                raise AppError(
                    code=ErrorCode.USER_NOT_FOUND,
                    status_code=404,
                    message="User not found",
                )
        await crud.set_value(
            session,
            crud.KEY_OWNER,
            str(owner_id) if owner_id else None,
            actor=current.email,
        )
    audit.record(
        session,
        actor=current.email,
        action="settings.update",
        resource_type="settings",
        resource_id="",
        details={k: (str(v) if v is not None else None) for k, v in fields.items()},
    )
    await session.commit()
    return await _out(session)
