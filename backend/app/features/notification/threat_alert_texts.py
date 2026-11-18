"""The threat alert's texts (``threat_alert.py``), in French and in English.

The French is the mail as it has always read, word for word — pinned by
``tests/test_mail_languages.py``. The values Defender reports (threat name,
severity, status) are its own words and stay as reported.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.features.notification.language import plural
from app.features.user.models import Language


@dataclass(frozen=True)
class ThreatAlertTexts:
    subject_one: Callable[[str, str], str]
    subject_many: Callable[[str, int, str], str]
    intro: Callable[[int, str], str]
    unnamed: str
    severity: Callable[[str], str]
    status: Callable[[str], str]
    detected_at: Callable[[datetime], str]
    more: Callable[[int], str]
    machine: str
    uuid: str
    domain: str
    ip_address: str
    session: str
    open_page: Callable[[str], str]
    footer: str


FR = ThreatAlertTexts(
    subject_one=lambda project, name: f"{project} — menace détectée sur {name}",
    subject_many=lambda project, n, name: (
        f"{project} — {n} menaces détectées sur {name}"
    ),
    intro=lambda n, name: (
        f"Microsoft Defender a signalé {n} détection(s) sur le poste {name}."
    ),
    unnamed="menace non nommée",
    severity=lambda value: f"sévérité {value}",
    status=lambda value: f"statut {value}",
    detected_at=lambda at: f"détectée le {at.strftime('%d/%m/%Y à %H:%M UTC')}",
    more=lambda n: f"  … et {n} autre(s) détection(s)",
    machine="Poste : ",
    uuid="UUID : ",
    domain="Domaine : ",
    ip_address="Adresse IP : ",
    session="Session ouverte : ",
    open_page=lambda url: f"Ouvrir la fiche du poste : {url}",
    footer=(
        "Vous recevez ce message parce que votre compte est réglé sur les alertes "
        "immédiates. Changez-le dans la console, page « Mon compte »."
    ),
)

EN = ThreatAlertTexts(
    subject_one=lambda project, name: f"{project} — threat detected on {name}",
    subject_many=lambda project, n, name: f"{project} — {n} threats detected on {name}",
    intro=lambda n, name: (
        f"Microsoft Defender reported {plural(n, 'detection', 'detections')} "
        f"on the computer {name}."
    ),
    unnamed="unnamed threat",
    severity=lambda value: f"severity {value}",
    status=lambda value: f"status {value}",
    detected_at=lambda at: f"detected on {at.strftime('%d/%m/%Y at %H:%M UTC')}",
    more=lambda n: f"  … and {plural(n, 'more detection', 'more detections')}",
    machine="Computer: ",
    uuid="UUID: ",
    domain="Domain: ",
    ip_address="IP address: ",
    session="Logged-on user: ",
    open_page=lambda url: f"Open the computer's page: {url}",
    footer=(
        "You receive this message because your account is set to immediate "
        "alerts. Change it in the console, under My account."
    ),
)

TEXTS: dict[Language, ThreatAlertTexts] = {Language.FR: FR, Language.EN: EN}
