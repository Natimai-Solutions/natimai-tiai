"""Aggregate import of all table models.

Importing this module guarantees every table is registered on
``SQLModel.metadata`` (used by app.core.db and Alembic).
"""

from app.features.command.models import Command  # noqa: F401
from app.features.machine.models import Machine  # noqa: F401
from app.features.threat.models import Threat  # noqa: F401
from app.features.user.models import PasswordResetToken, User  # noqa: F401

__all__ = ["Machine", "Threat", "Command", "User", "PasswordResetToken"]
