"""Aggregate import of all table models.

Importing this module guarantees every table is registered on
``SQLModel.metadata`` (used by app.core.db and Alembic).
"""

from app.features.audit.models import AuditEntry  # noqa: F401
from app.features.command.models import Command  # noqa: F401
from app.features.inventory.models import (  # noqa: F401
    Disk,
    Gpu,
    MachineSoftware,
    MemoryModule,
    Nic,
    Software,
    Volume,
)
from app.features.machine.models import Machine  # noqa: F401
from app.features.notification.models import EmailOutbox  # noqa: F401
from app.features.threat.models import Threat  # noqa: F401
from app.features.user.models import (  # noqa: F401
    Group,
    GroupPermission,
    PasswordResetToken,
    User,
    UserGroup,
)
from app.features.windows_update.models import WindowsUpdate  # noqa: F401

__all__ = [
    "Machine",
    "Threat",
    "Command",
    "User",
    "PasswordResetToken",
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
]
