"""The trends' Excel report (C9, §5): what the Tendances page shows, laid out
for a meeting. On demand; a sheet only for what its author may read.

Every value is a day or a month already computed in the console's zone; the
« generated on » line is written in that zone too.
"""

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from app.features.trend.failures import FailureRow
from app.features.trend.indicators import (
    CheckMonth,
    CommandMonth,
    Deployments,
    MaintenanceMonth,
)
from app.features.user.models import Language

# The counters of the « Parc » sheet, in its column order.
REPORT_KEYS: tuple[str, ...] = (
    "total",
    "up_to_date",
    "outdated",
    "with_active_threats",
    "machines_with_alerts",
    "machines_noncompliant",
    "machines_maintenance_overdue",
    "open_checks",
    "machines_low_disk",
    "machines_unencrypted",
    "machines_aging",
    "machines_wu_pending",
    "machines_retired",
)


@dataclass(frozen=True)
class ReportTexts:
    filename: str
    generated: str
    fleet_sheet: str
    month: str
    day: str
    counters: dict[str, str]
    indicators_sheet: str
    indicator: str
    rows: dict[str, str]
    models_sheet: str
    rooms_sheet: str
    model: str
    room: str
    building: str
    unknown_model: str
    no_room: str
    other_room: str
    failure_columns: tuple[str, ...]


REPORT_TEXTS: dict[Language, ReportTexts] = {
    Language.FR: ReportTexts(
        filename="tendances",
        generated="Rapport Tia'i généré le {when} ({zone}), sur {months} mois",
        fleet_sheet="Parc",
        month="Mois",
        day="Dernier jour suivi",
        counters={
            "total": "Postes",
            "up_to_date": "À jour",
            "outdated": "Pas à jour",
            "with_active_threats": "Avec menace active",
            "machines_with_alerts": "Avec alerte",
            "machines_noncompliant": "Non conformes",
            "machines_maintenance_overdue": "Maintenance en retard",
            "open_checks": "Vérifications ouvertes",
            "machines_low_disk": "Disque presque plein",
            "machines_unencrypted": "Non chiffrés",
            "machines_aging": "À renouveler",
            "machines_wu_pending": "Mises à jour Windows en attente",
            "machines_retired": "Réformés",
        },
        indicators_sheet="Indicateurs",
        indicator="Indicateur",
        rows={
            "checks.closed": "Vérifications closes",
            "checks.median_hours": "Délai de clôture médian (h)",
            "checks.p90_hours": "Délai de clôture, 9e décile (h)",
            "checks.with_due": "Vérifications closes avec échéance",
            "checks.on_time_due": "Closes avant l'échéance",
            "maintenance.done": "Maintenances faites",
            "maintenance.on_time": "Maintenances faites à l'heure",
            "commands.succeeded": "Commandes réussies",
            "commands.failed": "Commandes échouées",
            "commands.expired": "Commandes expirées (jamais délivrées)",
            "commands.unanswered": "Commandes sans réponse du poste",
            "direct.succeeded": "Déploiements directs réussis",
            "direct.failed": "Déploiements directs échoués",
            "direct.expired": "Déploiements directs expirés",
            "direct.unanswered": "Déploiements directs sans réponse",
            "scheduled.succeeded": "Déploiements planifiés réussis",
            "scheduled.failed": "Déploiements planifiés échoués",
            "scheduled.expired": "Déploiements planifiés expirés",
            "scheduled.unanswered": "Déploiements planifiés sans réponse",
            "halted_runs": "Déploiements en anneaux arrêtés",
        },
        models_sheet="Pannes par modèle",
        rooms_sheet="Pannes par salle",
        model="Modèle",
        room="Salle",
        building="Bâtiment",
        unknown_model="Modèle inconnu",
        no_room="Sans salle",
        other_room="Autre salle (hors de votre périmètre)",
        failure_columns=(
            "Incidents",
            "Postes touchés",
            "Postes en parc",
            "Incidents pour 100 postes",
            "Incidents (postes réformés)",
            "Postes réformés touchés",
            "Dernier incident",
        ),
    ),
    Language.EN: ReportTexts(
        filename="trends",
        generated="Tia'i report generated on {when} ({zone}), over {months} months",
        fleet_sheet="Fleet",
        month="Month",
        day="Last day tracked",
        counters={
            "total": "Computers",
            "up_to_date": "Up to date",
            "outdated": "Not up to date",
            "with_active_threats": "With an active threat",
            "machines_with_alerts": "With an alert",
            "machines_noncompliant": "Non-compliant",
            "machines_maintenance_overdue": "Maintenance overdue",
            "open_checks": "Open checks",
            "machines_low_disk": "Disk almost full",
            "machines_unencrypted": "Not encrypted",
            "machines_aging": "Due for renewal",
            "machines_wu_pending": "Windows updates pending",
            "machines_retired": "Retired",
        },
        indicators_sheet="Indicators",
        indicator="Indicator",
        rows={
            "checks.closed": "Checks closed",
            "checks.median_hours": "Median closing time (h)",
            "checks.p90_hours": "Closing time, 90th percentile (h)",
            "checks.with_due": "Checks closed with a due date",
            "checks.on_time_due": "Closed by the due date",
            "maintenance.done": "Maintenance done",
            "maintenance.on_time": "Maintenance done on time",
            "commands.succeeded": "Commands succeeded",
            "commands.failed": "Commands failed",
            "commands.expired": "Commands expired (never delivered)",
            "commands.unanswered": "Commands never answered",
            "direct.succeeded": "Direct deployments succeeded",
            "direct.failed": "Direct deployments failed",
            "direct.expired": "Direct deployments expired",
            "direct.unanswered": "Direct deployments never answered",
            "scheduled.succeeded": "Scheduled deployments succeeded",
            "scheduled.failed": "Scheduled deployments failed",
            "scheduled.expired": "Scheduled deployments expired",
            "scheduled.unanswered": "Scheduled deployments never answered",
            "halted_runs": "Ring deployments halted",
        },
        models_sheet="Failures by model",
        rooms_sheet="Failures by room",
        model="Model",
        room="Room",
        building="Building",
        unknown_model="Unknown model",
        no_room="No room",
        other_room="Other room (outside your scope)",
        failure_columns=(
            "Incidents",
            "Computers affected",
            "Computers in the fleet",
            "Incidents per 100 computers",
            "Incidents (retired computers)",
            "Retired computers affected",
            "Last incident",
        ),
    ),
}


@dataclass(frozen=True)
class Sheet:
    """A sheet of the report, as ``api/xlsx_export.Sheet`` takes it."""

    title: str
    header: list[str]
    rows: list[list[object]]
    caption: str | None = None


@dataclass(frozen=True)
class ReportData:
    months: list[str]
    fleet: dict[str, tuple[date, list[int]]]
    checks: list[CheckMonth] | None
    maintenance: list[MaintenanceMonth] | None
    commands: list[CommandMonth] | None
    deployments: Deployments | None
    by_model: list[FailureRow] | None
    by_room: list[FailureRow] | None


def _local(value: datetime | None, zone: tzinfo) -> datetime | None:
    return None if value is None else value.astimezone(zone).replace(tzinfo=None)


def _command_rows(
    prefix: str, months: list[CommandMonth], t: ReportTexts
) -> list[list[object]]:
    return [
        [t.rows[f"{prefix}.{field}"], *(getattr(m, field) for m in months)]
        for field in ("succeeded", "failed", "expired", "unanswered")
    ]


def sheets(
    data: ReportData,
    lang: Language,
    *,
    now: datetime,
    zone_name: str,
    zone: tzinfo,
) -> list[Sheet]:
    t = REPORT_TEXTS[lang]
    caption = t.generated.format(
        when=now.astimezone(zone).strftime("%Y-%m-%d %H:%M"),
        zone=zone_name,
        months=len(data.months),
    )
    fleet_rows: list[list[object]] = []
    for month in data.months:
        found = data.fleet.get(month)
        if found is None:
            fleet_rows.append([month, None, *([None] * len(REPORT_KEYS))])
        else:
            fleet_rows.append([month, found[0], *found[1]])
    out = [
        Sheet(
            t.fleet_sheet,
            [t.month, t.day, *(t.counters[k] for k in REPORT_KEYS)],
            fleet_rows,
            caption,
        )
    ]

    rows: list[list[object]] = []
    if data.checks is not None:
        for field in ("closed", "median_hours", "p90_hours", "with_due", "on_time_due"):
            rows.append(
                [t.rows[f"checks.{field}"], *(getattr(m, field) for m in data.checks)]
            )
    if data.maintenance is not None:
        for field in ("done", "on_time"):
            rows.append(
                [
                    t.rows[f"maintenance.{field}"],
                    *(getattr(m, field) for m in data.maintenance),
                ]
            )
    if data.commands is not None:
        rows.extend(_command_rows("commands", data.commands, t))
    if data.deployments is not None:
        rows.extend(_command_rows("direct", data.deployments.direct, t))
        rows.extend(_command_rows("scheduled", data.deployments.scheduled, t))
        if data.deployments.halted_runs is not None:
            rows.append([t.rows["halted_runs"], *data.deployments.halted_runs])
    if rows:
        out.append(
            Sheet(t.indicators_sheet, [t.indicator, *data.months], rows, caption)
        )

    if data.by_model is not None:
        out.append(
            Sheet(
                t.models_sheet,
                [t.model, *t.failure_columns],
                [
                    [r.hw_model or t.unknown_model, *_failure_values(r, zone)]
                    for r in data.by_model
                ],
                caption,
            )
        )
    if data.by_room is not None:
        out.append(
            Sheet(
                t.rooms_sheet,
                [t.room, t.building, *t.failure_columns],
                [
                    [
                        t.other_room if r.out_of_scope else (r.room_name or t.no_room),
                        r.building_name,
                        *_failure_values(r, zone),
                    ]
                    for r in data.by_room
                ],
                caption,
            )
        )
    return out


def _failure_values(row: FailureRow, zone: tzinfo) -> list[object]:
    return [
        row.incidents,
        row.machines,
        row.parc,
        row.per_100,
        row.retired_incidents,
        row.retired_machines,
        _local(row.last_at, zone),
    ]
