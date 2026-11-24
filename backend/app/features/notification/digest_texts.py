"""The daily digest's texts, in French and in English (``digest.py``).

The French is the mail as it has always read, word for word — pinned by
``tests/test_mail_languages.py``. ``poste(s)`` stays as written; the English
agrees its nouns with the count instead (``language.plural``).
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.features.notification.language import plural
from app.features.user.models import Language


def _computers(n: int) -> str:
    return plural(n, "computer", "computers")


# The alert rules, as the digest names them (``alert.models.AlertRule``).
RULE_LABELS_FR = {
    "disk_low": "Disque système presque plein",
    "disk_unhealthy": "Disque en mauvaise santé",
    "volume_unencrypted": "Volume système non chiffré",
    "reboot_pending": "Redémarrage en attente depuis trop longtemps",
    "os_unsupported": "Windows hors support",
    "forbidden_software": "Logiciel interdit installé",
    "inactive": "Sans contact",
    "warranty_ending": "Garantie bientôt terminée",
}
RULE_LABELS_EN = {
    "disk_low": "System disk nearly full",
    "disk_unhealthy": "Unhealthy disk",
    "volume_unencrypted": "System volume not encrypted",
    "reboot_pending": "Restart pending for too long",
    "os_unsupported": "Windows out of support",
    "forbidden_software": "Forbidden software installed",
    "inactive": "No contact",
    "warranty_ending": "Warranty ending soon",
}


@dataclass(frozen=True)
class DigestTexts:
    # --- why a poste is named in a section
    threats_detail: Callable[[int], str]
    updates_detail: Callable[[int], str]
    signature_age_detail: Callable[[int], str]
    protection_inactive: str
    more_machines: Callable[[int], str]
    # --- subject
    subject: Callable[[str, str, str], str]
    headline_threats: Callable[[int], str]
    headline_updates: Callable[[int], str]
    headline_verify: Callable[[int], str]
    headline_quiet: str
    # --- body
    state_at: Callable[[str], str]
    totals: Callable[[int, int], str]
    to_handle: str
    threats_line: Callable[[int], str]
    new_threats_line: Callable[[int, int], str]
    updates_line: Callable[[int], str]
    verify_line: Callable[[int], str]
    nothing_urgent: str
    current_state: str
    outdated_antivirus: Callable[[int], str]
    wu_pending: Callable[[int], str]
    reboot_required: Callable[[int], str]
    inactive: Callable[[int, int], str]
    title_threats: str
    title_updates: str
    title_antivirus: str
    title_alerts: str
    alert_line: Callable[[str, int], str]
    open_console: Callable[[str], str]
    footer: str
    # --- the digest of an account that reads no poste
    tasks_subject: Callable[[str, str], str]
    tasks_intro: Callable[[str], str]


FR = DigestTexts(
    threats_detail=lambda n: f"{n} menace(s) active(s)",
    updates_detail=lambda n: f"{n} MAJ critique(s)/importante(s)",
    signature_age_detail=lambda age: f"signatures vieilles de {age} j",
    protection_inactive="protection inactive ou jamais relevée",
    more_machines=lambda n: f"  … et {n} autre(s) poste(s)",
    subject=lambda project, date, headline: f"{project} — parc du {date} : {headline}",
    headline_threats=lambda n: f"{n} poste(s) avec menace active",
    headline_updates=lambda n: f"{n} poste(s) à mettre à jour",
    headline_verify=lambda n: f"{n} poste(s) dont l'identité est à confirmer",
    headline_quiet="rien à signaler",
    state_at=lambda date: f"État du parc au {date}.",
    totals=lambda total, online: (
        f"{total} poste(s) enregistré(s), {online} en ligne à l'instant du relevé."
    ),
    to_handle="À TRAITER",
    threats_line=lambda n: f"  {n} poste(s) avec au moins une menace active",
    new_threats_line=lambda n, hours: (
        f"  {n} détection(s) enregistrée(s) dans les dernières {hours} h"
    ),
    updates_line=lambda n: (
        f"  {n} poste(s) avec une mise à jour critique ou importante en attente"
    ),
    verify_line=lambda n: (
        f"  {n} poste(s) dont l'identité est à confirmer "
        "(empreinte matérielle divergente ou doublon)"
    ),
    nothing_urgent="Aucune menace active, aucun correctif urgent en attente.",
    current_state="ÉTAT COURANT",
    outdated_antivirus=lambda n: f"  Antivirus périmé ou inactif : {n} poste(s)",
    wu_pending=lambda n: f"  Mises à jour Windows en attente : {n} poste(s)",
    reboot_required=lambda n: f"  Redémarrage requis : {n} poste(s)",
    inactive=lambda days, n: f"  Sans contact depuis plus de {days} j : {n} poste(s)",
    title_threats="MENACES ACTIVES",
    title_updates="MISES À JOUR CRITIQUES OU IMPORTANTES",
    title_antivirus="ANTIVIRUS À REPRENDRE",
    title_alerts="ALERTES OUVERTES",
    alert_line=lambda rule, n: f"  {RULE_LABELS_FR.get(rule, rule)} : {n} poste(s)",
    open_console=lambda url: f"Ouvrir la console : {url}",
    footer=(
        "Vous recevez ce message parce que votre compte est réglé sur un résumé "
        "quotidien. Changez-le dans la console, page « Mon compte »."
    ),
    tasks_subject=lambda project, date: f"{project} — vos tâches au {date}",
    tasks_intro=lambda date: f"Vos tâches au {date}.",
)

EN = DigestTexts(
    threats_detail=lambda n: plural(n, "active threat", "active threats"),
    updates_detail=lambda n: plural(
        n, "critical or important update", "critical or important updates"
    ),
    signature_age_detail=lambda age: f"signatures {plural(age, 'day', 'days')} old",
    protection_inactive="protection off or never reported",
    more_machines=lambda n: f"  … and {plural(n, 'more computer', 'more computers')}",
    subject=lambda project, date, headline: f"{project} — fleet on {date}: {headline}",
    headline_threats=lambda n: f"{_computers(n)} with an active threat",
    headline_updates=lambda n: f"{_computers(n)} to update",
    headline_verify=lambda n: f"{_computers(n)} with an identity to confirm",
    headline_quiet="nothing to report",
    state_at=lambda date: f"State of the fleet on {date}.",
    totals=lambda total, online: (
        f"{_computers(total)} registered, {online} online at the time of the report."
    ),
    to_handle="NEEDS ATTENTION",
    threats_line=lambda n: f"  {_computers(n)} with at least one active threat",
    new_threats_line=lambda n, hours: (
        f"  {plural(n, 'detection', 'detections')} recorded in the last {hours} h"
    ),
    updates_line=lambda n: (
        f"  {_computers(n)} with a critical or important update waiting"
    ),
    verify_line=lambda n: (
        f"  {_computers(n)} with an identity to confirm "
        "(hardware fingerprint mismatch or duplicate)"
    ),
    nothing_urgent="No active threat, no urgent update waiting.",
    current_state="CURRENT STATE",
    outdated_antivirus=lambda n: f"  Antivirus outdated or off: {_computers(n)}",
    wu_pending=lambda n: f"  Windows updates waiting: {_computers(n)}",
    reboot_required=lambda n: f"  Restart required: {_computers(n)}",
    inactive=lambda days, n: (
        f"  No contact for more than {plural(days, 'day', 'days')}: {_computers(n)}"
    ),
    title_threats="ACTIVE THREATS",
    title_updates="CRITICAL OR IMPORTANT UPDATES",
    title_antivirus="ANTIVIRUS TO FIX",
    title_alerts="OPEN ALERTS",
    alert_line=lambda rule, n: f"  {RULE_LABELS_EN.get(rule, rule)}: {_computers(n)}",
    open_console=lambda url: f"Open the console: {url}",
    footer=(
        "You receive this message because your account is set to a daily "
        "digest. Change it in the console, under My account."
    ),
    tasks_subject=lambda project, date: f"{project} — your tasks on {date}",
    tasks_intro=lambda date: f"Your tasks on {date}.",
)

TEXTS: dict[Language, DigestTexts] = {Language.FR: FR, Language.EN: EN}
