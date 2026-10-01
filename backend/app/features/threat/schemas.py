import json
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# Bounds on what one detection may write. ``threat_name`` is Defender's
# family name ("Trojan:Win32/Wacatac.B!ml"), the others are short enums or
# identifiers; each limit leaves ample room over what Defender reports.
DETECTION_TEXT_MAX = 300
# The unknown fields go verbatim into the ``raw`` JSONB column. The agent sends
# none today; the door stays open for a later one, but not for megabytes.
EXTRA_JSON_MAX = 4 * 1024


class ThreatReport(BaseModel):
    """A Defender detection as reported by the agent on a heartbeat.

    Unknown fields are preserved (``extra='allow'``) and kept in the row's
    ``raw`` JSONB column.
    """

    model_config = ConfigDict(extra="allow")

    detection_id: str | None = None
    threat_name: str | None = None
    severity: str | None = None
    category: str | None = None
    status: str | None = None
    action_taken: str | None = None
    detected_at: datetime | None = None

    @field_validator(
        "detection_id",
        "threat_name",
        "severity",
        "category",
        "status",
        "action_taken",
    )
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        """Cap each field rather than 422 — the detection still lands."""
        if value is None:
            return None
        return value[:DETECTION_TEXT_MAX]

    @model_validator(mode="after")
    def _bound_extra(self) -> Self:
        """Drop the unknown fields when, together, they exceed the budget.

        All or nothing rather than field by field: a partial set of fields we
        do not understand is not more useful than none, and the known fields
        above — what the console reads — are kept either way.
        """
        extra = self.__pydantic_extra__
        if extra and len(json.dumps(extra, default=str)) > EXTRA_JSON_MAX:
            extra.clear()
        return self
