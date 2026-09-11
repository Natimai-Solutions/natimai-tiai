"""The fleet export's column catalogue.

One row per poste, and the reader chooses the columns — the way an Odoo export
works: a default set that answers the usual meeting, and everything else the
machine record holds on offer beside it. The catalogue lives here rather than
in the route so that the two formats (CSV and Excel) and the endpoint that
*lists* the columns to the console all read the same definition.

Every entry knows how to read itself off a ``Machine`` and what kind of value
it produces, because the two writers disagree on rendering: the CSV wants
text throughout, the workbook wants real dates and booleans it can filter on.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.features.base import utcnow
from app.features.machine.models import Machine
from app.features.machine.status import is_online

Kind = Literal["text", "int", "float", "bool", "date", "datetime"]
Group = Literal["identity", "antivirus", "windows_update", "hardware"]

GROUP_LABELS: dict[Group, str] = {
    "identity": "Identité",
    "antivirus": "Antivirus",
    "windows_update": "Windows Update",
    "hardware": "Matériel",
}

# The words the console uses for the same values, so a spreadsheet and the
# fiche never disagree about what a poste is.
CHASSIS_LABELS = {
    "desktop": "Poste fixe",
    "laptop": "Portable",
    "tablet": "Tablette",
    "all-in-one": "Tout-en-un",
    "server": "Serveur",
}

BOOL_LABELS = {True: "Oui", False: "Non"}


@dataclass(frozen=True)
class ExportColumn:
    """One column the export can produce."""

    key: str
    label: str
    group: Group
    kind: Kind
    read: Callable[[Machine], object]
    # Part of the set a reader gets without choosing anything.
    default: bool = False


def _attr(name: str) -> Callable[[Machine], object]:
    return lambda m: getattr(m, name)


def _chassis(m: Machine) -> object:
    value = m.hw_chassis_type
    return CHASSIS_LABELS.get(value, value) if value else None


def _ram_gb(m: Machine) -> object:
    """Nominal size in GiB — 16, not 15.9.

    Windows reports the memory it can address, which is a few hundred MiB short
    of the sticks' sum; rounding up recovers the figure printed on the box, and
    the one the reader will filter and sort on.
    """
    return None if m.ram_total_mb is None else math.ceil(m.ram_total_mb / 1024)


def _free_percent(m: Machine) -> object:
    """Free space as a whole percentage, or NULL when there is nothing to divide.

    Rounded for the spreadsheet: "12" is what the column is read for, and
    "12.34567901234568" is what a float would put in the cell.
    """
    total = m.system_volume_total_mb
    free = m.system_volume_free_mb
    if not total or free is None:
        return None
    return round(free * 100 / total)


def _online(m: Machine) -> object:
    return is_online(m.last_seen, utcnow(), settings.OFFLINE_AFTER_SECONDS)


def _session(m: Machine) -> object:
    """The logged-on user, or what the poste said instead of a name."""
    if m.session_user_present is None:
        return None
    if not m.session_user_present:
        return "Aucun utilisateur"
    return m.session_username or "Utilisateur connecté"


def _antivirus(m: Machine) -> object:
    """The Security Center product; "" is a finding and reads as such."""
    if m.av_product_name is None:
        return None
    return m.av_product_name or "Aucun"


# Order matters twice: it is the order the console lists the catalogue in, and
# the default set is exported in this order too.
COLUMNS: Sequence[ExportColumn] = (
    # --- Identité
    ExportColumn("hostname", "Nom", "identity", "text", _attr("hostname"), True),
    ExportColumn("domain", "Domaine", "identity", "text", _attr("domain"), True),
    # On offer, not in the default set: a single-site parc would export an
    # empty column, and the multi-site one adds it in two clicks.
    ExportColumn("location", "Emplacement", "identity", "text", _attr("location")),
    ExportColumn(
        "ip_address", "Adresse IP", "identity", "text", _attr("ip_address"), True
    ),
    ExportColumn(
        "mac_address", "Adresse MAC", "identity", "text", _attr("mac_address")
    ),
    ExportColumn("os_version", "OS", "identity", "text", _attr("os_version"), True),
    ExportColumn(
        "os_architecture",
        "Architecture",
        "identity",
        "text",
        _attr("os_architecture"),
        True,
    ),
    ExportColumn(
        "machine_uuid", "UUID machine", "identity", "text", _attr("machine_uuid")
    ),
    ExportColumn(
        "agent_version", "Version agent", "identity", "text", _attr("agent_version")
    ),
    ExportColumn("session", "Session", "identity", "text", _session),
    ExportColumn("is_online", "Allumé", "identity", "bool", _online),
    ExportColumn(
        "needs_verification",
        "À vérifier",
        "identity",
        "bool",
        _attr("needs_verification"),
    ),
    ExportColumn(
        "last_seen", "Vu le", "identity", "datetime", _attr("last_seen"), True
    ),
    ExportColumn(
        "first_seen", "Premier contact", "identity", "datetime", _attr("first_seen")
    ),
    # --- Antivirus
    ExportColumn("av_product_name", "Antivirus", "antivirus", "text", _antivirus, True),
    ExportColumn(
        "is_up_to_date", "Antivirus à jour", "antivirus", "bool", _attr("is_up_to_date")
    ),
    ExportColumn(
        "av_product_enabled",
        "Protection active",
        "antivirus",
        "bool",
        _attr("av_product_enabled"),
    ),
    ExportColumn(
        "rtp_enabled",
        "Protection temps réel (Defender)",
        "antivirus",
        "bool",
        _attr("rtp_enabled"),
    ),
    ExportColumn(
        "running_mode", "Mode Defender", "antivirus", "text", _attr("running_mode")
    ),
    ExportColumn(
        "signature_version",
        "Version signatures",
        "antivirus",
        "text",
        _attr("signature_version"),
    ),
    ExportColumn(
        "signature_last_updated",
        "Signatures mises à jour le",
        "antivirus",
        "datetime",
        _attr("signature_last_updated"),
    ),
    ExportColumn(
        "signature_age_days",
        "Âge signatures (j)",
        "antivirus",
        "int",
        _attr("signature_age_days"),
    ),
    ExportColumn(
        "last_quick_scan",
        "Dernier scan rapide",
        "antivirus",
        "datetime",
        _attr("last_quick_scan"),
    ),
    ExportColumn(
        "last_full_scan",
        "Dernier scan complet",
        "antivirus",
        "datetime",
        _attr("last_full_scan"),
    ),
    # --- Windows Update
    ExportColumn(
        "wu_pending_count",
        "MAJ en attente",
        "windows_update",
        "int",
        _attr("wu_pending_count"),
        True,
    ),
    ExportColumn(
        "wu_reboot_required",
        "Redémarrage requis",
        "windows_update",
        "bool",
        _attr("wu_reboot_required"),
    ),
    ExportColumn(
        "wu_last_search",
        "Dernière recherche MAJ",
        "windows_update",
        "datetime",
        _attr("wu_last_search"),
    ),
    ExportColumn(
        "wu_last_install",
        "Dernière installation MAJ",
        "windows_update",
        "datetime",
        _attr("wu_last_install"),
    ),
    # --- Matériel
    ExportColumn(
        "hw_manufacturer",
        "Constructeur",
        "hardware",
        "text",
        _attr("hw_manufacturer"),
        True,
    ),
    ExportColumn("hw_model", "Modèle", "hardware", "text", _attr("hw_model"), True),
    ExportColumn(
        "hw_serial", "N° de série", "hardware", "text", _attr("hw_serial"), True
    ),
    ExportColumn("hw_chassis_type", "Châssis", "hardware", "text", _chassis, True),
    ExportColumn(
        "hw_is_virtual", "Machine virtuelle", "hardware", "bool", _attr("hw_is_virtual")
    ),
    ExportColumn(
        "hw_hypervisor", "Hyperviseur", "hardware", "text", _attr("hw_hypervisor")
    ),
    ExportColumn(
        "mb_manufacturer",
        "Carte mère (constructeur)",
        "hardware",
        "text",
        _attr("mb_manufacturer"),
    ),
    ExportColumn(
        "mb_model", "Carte mère (modèle)", "hardware", "text", _attr("mb_model")
    ),
    ExportColumn(
        "bios_vendor", "BIOS (éditeur)", "hardware", "text", _attr("bios_vendor")
    ),
    ExportColumn(
        "bios_version", "BIOS", "hardware", "text", _attr("bios_version"), True
    ),
    ExportColumn(
        "bios_date", "Date BIOS", "hardware", "date", _attr("bios_date"), True
    ),
    ExportColumn(
        "secure_boot", "Secure Boot", "hardware", "bool", _attr("secure_boot")
    ),
    ExportColumn("tpm_version", "TPM", "hardware", "text", _attr("tpm_version")),
    ExportColumn(
        "cpu_model", "Processeur", "hardware", "text", _attr("cpu_model"), True
    ),
    ExportColumn(
        "cpu_manufacturer",
        "Processeur (fabricant)",
        "hardware",
        "text",
        _attr("cpu_manufacturer"),
    ),
    ExportColumn("cpu_cores", "Cœurs", "hardware", "int", _attr("cpu_cores"), True),
    ExportColumn("cpu_threads", "Threads", "hardware", "int", _attr("cpu_threads")),
    ExportColumn(
        "cpu_speed_mhz", "Fréquence (MHz)", "hardware", "int", _attr("cpu_speed_mhz")
    ),
    ExportColumn("cpu_count", "Processeurs", "hardware", "int", _attr("cpu_count")),
    ExportColumn("ram_total_gb", "RAM (Gio)", "hardware", "int", _ram_gb, True),
    ExportColumn("ram_total_mb", "RAM (Mio)", "hardware", "int", _attr("ram_total_mb")),
    ExportColumn(
        "ram_slots_used",
        "Barrettes utilisées",
        "hardware",
        "int",
        _attr("ram_slots_used"),
    ),
    ExportColumn(
        "ram_slots_total",
        "Emplacements mémoire",
        "hardware",
        "int",
        _attr("ram_slots_total"),
    ),
    ExportColumn(
        "system_volume_total_mb",
        "Disque système (Mio)",
        "hardware",
        "int",
        _attr("system_volume_total_mb"),
        True,
    ),
    ExportColumn(
        "system_volume_free_mb",
        "Libre (Mio)",
        "hardware",
        "int",
        _attr("system_volume_free_mb"),
        True,
    ),
    ExportColumn(
        "disk_free_percent", "Libre (%)", "hardware", "int", _free_percent, True
    ),
    ExportColumn(
        "os_install_date",
        "Windows installé le",
        "hardware",
        "datetime",
        _attr("os_install_date"),
    ),
    ExportColumn(
        "last_boot_time",
        "Dernier démarrage",
        "hardware",
        "datetime",
        _attr("last_boot_time"),
    ),
    ExportColumn(
        "inventory_last_seen",
        "Inventaire du",
        "hardware",
        "datetime",
        _attr("inventory_last_seen"),
        True,
    ),
)

_BY_KEY: dict[str, ExportColumn] = {c.key: c for c in COLUMNS}

DEFAULT_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.default)


def resolve_columns(keys: str | None) -> list[ExportColumn]:
    """The columns a request asks for, in the order it asks for them.

    ``keys`` is the comma-separated list the console sends; ``None`` or empty
    means the default set. An unknown key is a 422 rather than a silently
    shorter file: an export missing a column the reader ticked is the kind of
    error that is only noticed in the meeting.
    """
    if not keys or not keys.strip():
        return [_BY_KEY[k] for k in DEFAULT_KEYS]
    columns: list[ExportColumn] = []
    unknown: list[str] = []
    for raw in keys.split(","):
        key = raw.strip()
        if not key:
            continue
        column = _BY_KEY.get(key)
        if column is None:
            unknown.append(key)
        elif column not in columns:
            columns.append(column)
    if unknown:
        raise AppError(
            code=ErrorCode.REQUEST_VALIDATION_ERROR,
            status_code=422,
            message="Unknown export column(s)",
            details={"unknown": unknown},
        )
    if not columns:
        return [_BY_KEY[k] for k in DEFAULT_KEYS]
    return columns


def resolve_timezone(name: str | None) -> tzinfo:
    """The zone timestamps are written in — the reader's, when the console says.

    Everything is stored in UTC, but a spreadsheet read in Papeete or Paris
    should say "09:58" for the contact the console showed at 09:58. An unknown
    or absent name falls back to UTC rather than failing: the times are still
    right, only their zone is not the reader's.
    """
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def csv_value(column: ExportColumn, value: object, tz: tzinfo) -> object:
    """A cell for the CSV: text throughout, dates in ISO order so they sort."""
    if value is None:
        return None
    if column.kind == "bool":
        return BOOL_LABELS.get(bool(value), "")
    if column.kind == "datetime" and isinstance(value, datetime):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    if column.kind == "date" and isinstance(value, date):
        return value.isoformat()
    return value


def xlsx_value(column: ExportColumn, value: object, tz: tzinfo) -> object:
    """A cell for the workbook: real dates and numbers, booleans in words.

    Booleans as "Oui"/"Non" rather than TRUE/FALSE: Excel's own rendering is
    locale-dependent and its filter menu then lists the English words on a
    French installation. Datetimes are made naive in the reader's zone, since
    Excel has no notion of a zone at all.
    """
    if value is None:
        return None
    if column.kind == "bool":
        return BOOL_LABELS.get(bool(value), "")
    if column.kind == "datetime" and isinstance(value, datetime):
        return value.astimezone(tz).replace(tzinfo=None)
    return value
