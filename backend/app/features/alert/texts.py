"""The texts the server writes for an alert: the instructions of the
verification it opens. Coded (``alert.<rule>`` and the alert's detail as
parameters) for the console to word in its reader's language; the French
written beside it for an older console (``dev/plan-console-bilingue.md``)."""

from datetime import date, datetime
from typing import Any

from app.features.alert.models import AlertRule


def _day(value: Any) -> str:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).strftime("%d/%m/%Y")
        except ValueError:
            return value
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return "?"


def _names(items: list[dict[str, Any]] | None, key: str) -> str:
    names = [str(i.get(key)) for i in items or [] if i.get(key)]
    return ", ".join(names) if names else "?"


def french(rule: str, detail: dict[str, Any]) -> str:
    """The alert in one French sentence."""
    match rule:
        case AlertRule.DISK_LOW:
            return (
                f"Il reste {detail.get('free_percent')} % d'espace libre sur le "
                f"volume système (seuil : {detail.get('threshold_percent')} %)."
            )
        case AlertRule.DISK_UNHEALTHY:
            return (
                "Un disque est signalé en mauvaise santé : "
                f"{_names(detail.get('disks'), 'model')}."
            )
        case AlertRule.VOLUME_UNENCRYPTED:
            return f"Le volume système {detail.get('letter')} n'est pas chiffré."
        case AlertRule.REBOOT_PENDING:
            return (
                "Un redémarrage demandé par Windows Update attend depuis le "
                f"{_day(detail.get('since'))}."
            )
        case AlertRule.OS_UNSUPPORTED:
            end = detail.get("end_of_support")
            suffix = f" depuis le {_day(end)}" if end else ""
            return (
                f"{detail.get('os_version')} n'est plus pris en charge par "
                f"Microsoft{suffix}."
            )
        case AlertRule.FORBIDDEN_SOFTWARE:
            return (
                "Logiciel interdit installé : "
                f"{_names(detail.get('programs'), 'name')}."
            )
        case AlertRule.WARRANTY_ENDING:
            return f"La garantie se termine le {_day(detail.get('warranty_end'))}."
        case AlertRule.INACTIVE:
            return (
                "Aucun contact avec le poste depuis le "
                f"{_day(detail.get('last_seen'))}."
            )
    return "Alerte."


def check_instructions(
    rule: str, detail: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    """``(code, params, French)`` for the verification an alert opens."""
    return f"alert.{rule}", dict(detail), f"Alerte : {french(rule, detail)}"
