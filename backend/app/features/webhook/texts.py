"""The chat formats' texts (C8): one line per event, in the webhook's
language, composed from the payload the JSON format sends as it is."""

from collections.abc import Callable
from typing import Any

from app.features.notification.digest_texts import RULE_LABELS_EN, RULE_LABELS_FR

_FR: dict[str, Callable[[dict[str, Any]], str]] = {
    "threat.detected": lambda d: (
        f"Menace détectée sur {d['machine']['hostname'] or d['machine']['id']} : "
        + ", ".join(t.get("name") or "?" for t in d.get("items", []))
    ),
    "alert.opened": lambda d: (
        f"{d['total']} alerte(s) ouverte(s) : " + _alerts(d, "fr")
    ),
    "alert.resolved": lambda d: (
        f"{d['total']} alerte(s) résolue(s) : " + _alerts(d, "fr")
    ),
    "check.created": lambda d: (
        f"Vérification demandée sur {_machines(d)}"
        + (f" : {d['instructions']}" if d.get("instructions") else "")
    ),
    "check.closed": lambda d: (
        f"Vérification close sur {d['machine']['hostname'] or d['machine']['id']}"
    ),
    "command.failed": lambda d: (
        f"Commande « {d['type']} » échouée sur "
        f"{d['machine']['hostname'] or d['machine']['id']}"
    ),
    "test": lambda d: "Essai du webhook Tia'i : il fonctionne.",
}

_EN: dict[str, Callable[[dict[str, Any]], str]] = {
    "threat.detected": lambda d: (
        f"Threat detected on {d['machine']['hostname'] or d['machine']['id']}: "
        + ", ".join(t.get("name") or "?" for t in d.get("items", []))
    ),
    "alert.opened": lambda d: f"{d['total']} alert(s) opened: " + _alerts(d, "en"),
    "alert.resolved": lambda d: f"{d['total']} alert(s) resolved: " + _alerts(d, "en"),
    "check.created": lambda d: (
        f"Check requested on {_machines(d)}"
        + (f": {d['instructions']}" if d.get("instructions") else "")
    ),
    "check.closed": lambda d: (
        f"Check closed on {d['machine']['hostname'] or d['machine']['id']}"
    ),
    "command.failed": lambda d: (
        f"Command “{d['type']}” failed on "
        f"{d['machine']['hostname'] or d['machine']['id']}"
    ),
    "test": lambda d: "Tia'i webhook test: it works.",
}


def _machines(d: dict[str, Any]) -> str:
    # Each poste with its own reason where the request has none of its own
    # (the checks the alerts open: one reason per poste).
    per_item = not d.get("instructions")
    shown = [
        f"{m.get('hostname') or m.get('id')}"
        + (f" ({m['instructions']})" if per_item and m.get("instructions") else "")
        for m in d.get("items", [])[:10]
    ]
    more = d.get("total", len(shown)) - len(shown)
    return ", ".join(str(n) for n in shown) + (f", … +{more}" if more > 0 else "")


def rule_label(rule: str, language: str) -> str:
    labels = RULE_LABELS_EN if language == "en" else RULE_LABELS_FR
    return labels.get(rule, rule)


def _alerts(d: dict[str, Any], language: str) -> str:
    shown = [
        f"{a.get('hostname') or a.get('machine_id')} ({rule_label(a['rule'], language)})"
        for a in d.get("items", [])[:10]
    ]
    more = d["total"] - len(shown)
    tail = f", … +{more}" if more > 0 else ""
    return ", ".join(shown) + tail


def text(event: str, data: dict[str, Any], language: str) -> str:
    table = _EN if language == "en" else _FR
    build = table.get(event)
    if build is None:
        return event
    try:
        return build(data)
    except (KeyError, TypeError):
        # A payload missing a field still says what happened.
        return event


def chat_body(event: str, data: dict[str, Any], language: str) -> dict[str, Any]:
    """What Teams (incoming webhook) and Mattermost (and Slack) both take."""
    return {"text": text(event, data, language)}
