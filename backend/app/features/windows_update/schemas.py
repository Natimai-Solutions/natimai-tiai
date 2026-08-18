"""Wire schemas for the heartbeat's ``windows_update`` block.

Shared by the agent route and the crud layer, like ``ThreatReport``.

Every field is bounded or defaulted rather than validated strictly: these
strings come from a vendor catalogue nobody here controls (an update title runs
to a couple of hundred characters and is localized), and a 422 on one malformed
entry would cost the Defender state, the threats and the command pickup riding
along in the same heartbeat. Same trade-off as ``AVProduct`` and ``ip_address``.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

# Bounds on what one reported update can write to the database and pour into the
# console. Titles are the long field ("2025-08 Mise à jour cumulative pour
# Windows 11 Version 24H2 pour les systèmes x64 (KB5063878)" is ~110 chars);
# the rest are identifiers and short labels.
UPDATE_ID_MAX = 200
KB_MAX = 40
TITLE_MAX = 512
SEVERITY_MAX = 40
CATEGORIES_MAX = 512

# The pending set of a machine that has never been patched runs to a few dozen
# updates; a machine reporting hundreds is a broken agent or a hostile one, and
# either way the excess is dropped rather than stored. The cap is applied to the
# *list*, so the machine's other columns still get through.
MAX_PENDING_UPDATES = 500

# software / driver. Anything else is normalised to "software": WUA has only the
# two types, and the console filters on the distinction.
UPDATE_TYPE_DRIVER = "driver"
UPDATE_TYPE_SOFTWARE = "software"


class PendingUpdateReport(BaseModel):
    """One update WUA reports as applicable and not yet installed."""

    model_config = ConfigDict(extra="ignore")

    # The dedup key (UNIQUE (machine_id, update_id) server-side). An entry
    # without one is dropped by the crud layer: there is nothing to key on.
    update_id: str = ""
    kb: str | None = None
    title: str = ""
    severity: str | None = None
    type: str = UPDATE_TYPE_SOFTWARE
    # A list on the wire, one comma-joined string in the column: the console
    # displays them and never queries them individually, so a table of
    # categories would buy nothing.
    categories: list[str] = []
    is_downloaded: bool = False
    size_mb: float | None = None

    @field_validator("update_id")
    @classmethod
    def _bound_update_id(cls, value: str) -> str:
        return value.strip()[:UPDATE_ID_MAX]

    @field_validator("kb")
    @classmethod
    def _bound_kb(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # An empty KB is stored as NULL, not "": most drivers have no KB at all
        # and the console renders the absence as a dash either way.
        return value.strip()[:KB_MAX] or None

    @field_validator("title")
    @classmethod
    def _bound_title(cls, value: str) -> str:
        return value.strip()[:TITLE_MAX]

    @field_validator("severity")
    @classmethod
    def _normalize_severity(cls, value: str | None) -> str | None:
        """Lowercase the MSRC rating, NULL when unrated.

        Lowercased here rather than at the agent so an older agent sending
        "Critical" and a newer one sending "critical" land on the same value —
        the console's badge colours key on it.
        """
        if value is None:
            return None
        return value.strip().lower()[:SEVERITY_MAX] or None

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        return (
            UPDATE_TYPE_DRIVER
            if normalized == UPDATE_TYPE_DRIVER
            else UPDATE_TYPE_SOFTWARE
        )

    @field_validator("size_mb")
    @classmethod
    def _sane_size(cls, value: float | None) -> float | None:
        """Drop a negative size rather than store it — WUA reports 0 for unknown."""
        if value is None or value < 0:
            return None
        return value

    def categories_text(self) -> str | None:
        """The categories as the column stores them, or NULL when there are none."""
        joined = ", ".join(c.strip() for c in self.categories if c.strip())
        return joined[:CATEGORIES_MAX] or None


class WUStateReport(BaseModel):
    """Windows Update state, reported on its own slow cycle (not every heartbeat).

    Optional on the heartbeat exactly like the ``defender`` block: an absent
    block leaves every stored value alone. A WU search takes minutes and runs
    every few hours, so most heartbeats carry nothing here.
    """

    model_config = ConfigDict(extra="ignore")

    reboot_required: bool = False
    last_search_time: datetime | None = None
    last_install_time: datetime | None = None
    pending: list[PendingUpdateReport] = []

    @field_validator("pending", mode="before")
    @classmethod
    def _tolerate_null_list(cls, value: object) -> object:
        """A null list is "nothing pending", not a malformed heartbeat.

        Go marshals a nil slice as ``null``, and the whole point of this block is
        that an empty pending set *clears* the stored one — losing that report to
        a 422 would leave the console showing updates the machine has installed.
        """
        return [] if value is None else value

    @field_validator("pending")
    @classmethod
    def _cap_pending(
        cls, value: list[PendingUpdateReport]
    ) -> list[PendingUpdateReport]:
        return value[:MAX_PENDING_UPDATES]
