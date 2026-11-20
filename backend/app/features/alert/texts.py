"""The texts the server writes for an alert: the instructions of the
verification it opens. Coded (``alert.<rule>`` and the alert's detail as
parameters) for the console to word in its reader's language; the French
written beside it for an older console (``dev/plan-console-bilingue.md``).

The mails and the export, which leave without a browser to word them, word
the code here in their reader's language (``worded_instructions``).
"""

from datetime import date, datetime, tzinfo
from typing import Any

from app.features.alert.models import AlertRule
from app.features.user.models import Language

CODE_PREFIX = "alert."


def _day(value: Any, zone: tzinfo | None = None) -> str:
    """A date as the sentence writes it. An instant (« last seen », « pending
    since ») is the day it was in ``zone`` — the export's reader's — and in
    UTC without one (a mail: the server does not know where its reader is)."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        if zone is not None and parsed.tzinfo is not None:
            parsed = parsed.astimezone(zone)
        return parsed.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return "?"


def _names(items: list[dict[str, Any]] | None, key: str) -> str:
    names = [str(i.get(key)) for i in items or [] if i.get(key)]
    return ", ".join(names) if names else "?"


def _days(value: Any, one: str, many: str) -> str:
    """« 1 jour », « 30 jours »: the threshold agrees with its count."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"{value} {many}"
    return f"{n} {one if n == 1 else many}"


def french(rule: str, detail: dict[str, Any], zone: tzinfo | None = None) -> str:
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
                f"{_day(detail.get('since'), zone)}."
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
            if detail.get("warranty_end"):
                return f"La garantie se termine le {_day(detail.get('warranty_end'))}."
            return (
                "La garantie se termine dans moins de "
                f"{_days(detail.get('threshold_days'), 'jour', 'jours')}."
            )
        case AlertRule.INACTIVE:
            return (
                "Aucun contact avec le poste depuis le "
                f"{_day(detail.get('last_seen'), zone)}."
            )
    return "Alerte."


def english(rule: str, detail: dict[str, Any], zone: tzinfo | None = None) -> str:
    """The alert in one English sentence."""
    match rule:
        case AlertRule.DISK_LOW:
            return (
                f"{detail.get('free_percent')} % free space left on the system "
                f"volume (threshold: {detail.get('threshold_percent')} %)."
            )
        case AlertRule.DISK_UNHEALTHY:
            return (
                f"A disk is reported unhealthy: {_names(detail.get('disks'), 'model')}."
            )
        case AlertRule.VOLUME_UNENCRYPTED:
            return f"System volume {detail.get('letter')} is not encrypted."
        case AlertRule.REBOOT_PENDING:
            return (
                "A restart requested by Windows Update has been pending since "
                f"{_day(detail.get('since'), zone)}."
            )
        case AlertRule.OS_UNSUPPORTED:
            end = detail.get("end_of_support")
            suffix = f" since {_day(end)}" if end else ""
            return (
                f"{detail.get('os_version')} is no longer supported by "
                f"Microsoft{suffix}."
            )
        case AlertRule.FORBIDDEN_SOFTWARE:
            return (
                "Forbidden software installed: "
                f"{_names(detail.get('programs'), 'name')}."
            )
        case AlertRule.WARRANTY_ENDING:
            if detail.get("warranty_end"):
                return f"The warranty ends on {_day(detail.get('warranty_end'))}."
            days = _days(detail.get("threshold_days"), "day", "days")
            return f"The warranty ends within {days}."
        case AlertRule.INACTIVE:
            return f"No contact with the computer since {_day(detail.get('last_seen'), zone)}."
    return "Alert."


_PREFIX = {Language.FR: "Alerte : ", Language.EN: "Alert: "}


def _sentence(
    rule: str, detail: dict[str, Any], language: Language, zone: tzinfo | None = None
) -> str:
    text = (
        english(rule, detail, zone)
        if language == Language.EN
        else french(rule, detail, zone)
    )
    return f"{_PREFIX[language]}{text}"


def check_params(rule: str, detail: dict[str, Any]) -> dict[str, Any]:
    """What of an alert's detail its verification carries. The warranty's end
    date is purchase data (``asset:read``) and a verification is read with
    ``check:read``: it only says the warranty ends within the threshold."""
    if rule == AlertRule.WARRANTY_ENDING:
        return {"threshold_days": detail.get("threshold_days")}
    return dict(detail)


def check_instructions(
    rule: str, detail: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    """``(code, params, French)`` for the verification an alert opens."""
    params = check_params(rule, detail)
    return f"{CODE_PREFIX}{rule}", params, _sentence(rule, params, Language.FR)


def worded_instructions(
    instructions: str | None,
    code: str | None,
    params: dict[str, Any] | None,
    language: Language,
    zone: tzinfo | None = None,
) -> str | None:
    """A verification's instructions in ``language``: worded from the code when
    the server opened it for an alert, as typed otherwise. Its instants are
    the day they were in ``zone`` (an export's), in UTC without one."""
    if code and code.startswith(CODE_PREFIX):
        rule = code.removeprefix(CODE_PREFIX)
        if rule in {r.value for r in AlertRule}:
            return _sentence(rule, params or {}, language, zone)
    return instructions
