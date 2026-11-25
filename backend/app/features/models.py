"""Aggregate import of all table models.

Importing this module guarantees every table is registered on
``SQLModel.metadata`` (used by app.core.db and Alembic).
"""

from app.features.alert.models import MachineAlert  # noqa: F401
from app.features.api_token.models import ApiToken  # noqa: F401
from app.features.approval.models import (  # noqa: F401
    ApprovalRequest,
    ApprovalRequestMachine,
)
from app.features.asset.models import Asset  # noqa: F401
from app.features.attachment.models import InterventionAttachment  # noqa: F401
from app.features.audit.models import AuditEntry  # noqa: F401
from app.features.auth_session.models import AuthSession, LoginChallenge  # noqa: F401
from app.features.check.models import MachineCheck  # noqa: F401
from app.features.command.models import Command  # noqa: F401
from app.features.counter.models import SharedCounter  # noqa: F401
from app.features.directory.models import DirectoryDomain, DirectoryRecord  # noqa: F401
from app.features.intervention.models import Intervention  # noqa: F401
from app.features.inventory.models import (  # noqa: F401
    Disk,
    Gpu,
    MachineSoftware,
    MemoryModule,
    Nic,
    Software,
    Volume,
)
from app.features.license.models import License  # noqa: F401
from app.features.machine.models import Machine  # noqa: F401
from app.features.maintenance.models import Maintenance  # noqa: F401
from app.features.notification.models import EmailOutbox  # noqa: F401
from app.features.oidc.models import OidcLogin  # noqa: F401
from app.features.package.models import Package, PackageFile  # noqa: F401
from app.features.procedure.models import Procedure  # noqa: F401
from app.features.report.models import Report  # noqa: F401
from app.features.room.models import Building, Room  # noqa: F401
from app.features.schedule.models import Schedule, ScheduleRun  # noqa: F401
from app.features.setting.models import AppSetting  # noqa: F401
from app.features.threat.models import Threat  # noqa: F401
from app.features.trend.models import TrendDay, TrendSnapshot  # noqa: F401
from app.features.usage.models import MachineUptime  # noqa: F401
from app.features.user.models import (  # noqa: F401
    Group,
    GroupIdpLink,
    GroupPermission,
    GroupScope,
    LoginAddress,
    PasswordResetToken,
    User,
    UserBackupCode,
    UserGroup,
)
from app.features.webhook.models import Webhook, WebhookDelivery  # noqa: F401
from app.features.windows_update.models import WindowsUpdate  # noqa: F401

__all__ = [
    "Machine",
    "Threat",
    "Command",
    "User",
    "PasswordResetToken",
    "AuthSession",
    "Group",
    "GroupPermission",
    "UserGroup",
    "WindowsUpdate",
    "MemoryModule",
    "Disk",
    "Volume",
    "Nic",
    "Gpu",
    "Software",
    "MachineSoftware",
    "EmailOutbox",
    "AuditEntry",
    "Building",
    "Room",
    "Intervention",
    "MachineCheck",
    "Maintenance",
    "AppSetting",
    "MachineAlert",
    "Asset",
]
