"""The server's environment as the page Paramètres shows it.

The console's own settings (``app_settings``) are the few an administrator
changes from the page; everything else that shapes what the console says — how
old a signature may be before a poste reads « périmé », how long before a
silent poste is « inactif », where mail leaves from — is a variable of the
server's environment, set once in ``deploy/.env`` and then hard to remember. This
module lists them, in groups and with a line each, so the page can answer
« pourquoi ce poste est-il signalé ? » without a shell on the server.

Read-only by construction: the page shows values, it cannot write them. And
never a secret — the signing key, the enrollment secret, database and mail
credentials, the first admin's password — nor anything that may carry one
(a proxy URL). ``_NEVER_SHOWN`` is the list, and a test holds the catalogue
to it.
"""

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, settings

# Variables the page must never print, whatever else is added to the catalogue.
_NEVER_SHOWN = frozenset(
    {
        "SECRET_KEY",
        "ENROLLMENT_SECRET",
        "FIRST_ADMIN_EMAIL",
        "FIRST_ADMIN_PASSWORD",
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "MAILGUN_API_KEY",
        "MAILGUN_PROXY_URL",
        "SMTP_USER",
        "SMTP_PASSWORD",
    }
)

_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

_ROOM_SOURCES = {
    "manual": "à la main, depuis la console",
    "ad_ou": "par l'unité d'organisation de l'annuaire",
    "ad_location": "par l'attribut Emplacement de l'annuaire",
}


@dataclass(frozen=True)
class EnvItem:
    """One variable: its name as written in ``.env``, its value as a reader
    would say it, and what it decides."""

    key: str
    value: str | None
    description: str


@dataclass(frozen=True)
class EnvGroup:
    label: str
    items: list[EnvItem]


def _fmt(value: Any) -> str | None:
    """A value as the page prints it: booleans in words, lists joined, an
    empty value as an absence (the page shows a dash and « non défini »)."""
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return str(value)


def _item(env: Settings, key: str, description: str, value: Any = ...) -> EnvItem:
    """An item read off ``env`` by name, unless a rendered value is given."""
    if key in _NEVER_SHOWN:  # pragma: no cover - a catalogue bug, caught by test
        raise ValueError(f"{key} must not be shown")
    raw = getattr(env, key) if value is ... else value
    return EnvItem(key=key, value=_fmt(raw), description=description)


def _email_group(env: Settings) -> EnvGroup:
    """The mail channel: the provider chosen, whether it is complete, and the
    variables of that provider alone — the other's are ignored by the server
    and would only confuse here."""
    configured = env.alerts_enabled
    state = (
        "configuré, les e-mails partent"
        if configured
        else "incomplet, aucun e-mail ne part"
    )
    items = [
        _item(
            env,
            "EMAIL_PROVIDER",
            "Canal de sortie du courrier : l'API Mailgun ou un serveur SMTP",
            f"{env.EMAIL_PROVIDER} ({state})",
        ),
        _item(
            env,
            "EMAIL_FROM_EMAIL",
            "Adresse d'expéditeur (ou MAILGUN_FROM_EMAIL pour un .env plus ancien)",
            env.email_from_email,
        ),
        _item(env, "EMAIL_FROM_NAME", "Nom d'expéditeur affiché", env.email_from_name),
    ]
    if env.EMAIL_PROVIDER == "smtp":
        items += [
            _item(env, "SMTP_HOST", "Serveur SMTP ; vide = SMTP non configuré"),
            _item(env, "SMTP_PORT", "Port du serveur SMTP"),
            _item(
                env,
                "SMTP_SECURITY",
                "starttls (587), tls (465) ou none (relais interne sur 25)",
            ),
            _item(
                env,
                "SMTP_VERIFY_TLS",
                "Vérification du certificat du serveur ; non = relais à certificat privé",
            ),
        ]
    else:
        items += [
            _item(
                env,
                "MAILGUN_DOMAIN",
                "Domaine d'envoi Mailgun ; vide = Mailgun non configuré",
            ),
            _item(
                env,
                "MAILGUN_API_BASE_URL",
                "Point d'entrée de l'API Mailgun (EU ou US)",
            ),
        ]
    items += [
        _item(
            env,
            "DIGEST_HOUR_UTC",
            "Heure UTC d'envoi du résumé quotidien et du rappel de maintenance",
        ),
        _item(
            env,
            "THREAT_ALERT_MAX_AGE_HOURS",
            "Une détection plus ancienne que ce nombre d'heures ne déclenche pas "
            "d'alerte immédiate (historique d'un poste qui s'enrôle)",
        ),
        _item(
            env,
            "NOTIFICATION_MAX_ITEMS",
            "Nombre de postes ou de détections détaillés dans un e-mail avant « et N autres »",
        ),
        _item(
            env,
            "EMAIL_OUTBOX_RETENTION_DAYS",
            "Jours de conservation des e-mails envoyés ou abandonnés dans la file de sortie",
        ),
    ]
    return EnvGroup(label="E-mails", items=items)


def environment_overview(env: Settings = settings) -> list[EnvGroup]:
    """The environment, grouped the way the console's pages are."""
    weekday = env.MAINTENANCE_REMINDER_WEEKDAY
    return [
        EnvGroup(
            label="Postes et seuils",
            items=[
                _item(
                    env,
                    "SIGNATURE_MAX_AGE_DAYS",
                    "Âge maximal des signatures antivirus, en jours, avant qu'un poste "
                    "soit « base antivirus périmée »",
                ),
                _item(
                    env,
                    "INACTIVE_AFTER_DAYS",
                    "Jours sans contact de l'agent avant qu'un poste soit « inactif »",
                ),
                _item(
                    env,
                    "OFFLINE_AFTER_SECONDS",
                    "Secondes sans battement avant qu'un poste soit compté éteint "
                    "(3 × l'intervalle de l'agent par défaut)",
                ),
                _item(
                    env,
                    "LOW_DISK_FREE_PERCENT",
                    "Seuil « disque presque plein » : pourcentage libre sur le volume "
                    "système en dessous duquel un poste est signalé",
                ),
                _item(
                    env,
                    "HARDWARE_AGING_YEARS",
                    "Âge du poste (date du BIOS) à partir duquel il est compté à renouveler",
                ),
                _item(
                    env,
                    "AGENT_EXPECTED_VERSION",
                    "Version d'agent de référence pour « agent obsolète » ; vide = la plus "
                    "haute version remontée par le parc",
                ),
                _item(
                    env,
                    "COMMAND_DEFAULT_TTL_MINUTES",
                    "Durée de vie, en minutes, d'une commande encore en attente avant "
                    "qu'elle soit périmée",
                ),
            ],
        ),
        EnvGroup(
            label="Maintenance",
            items=[
                _item(
                    env,
                    "MAINTENANCE_DEFAULT_CYCLE_DAYS",
                    "Cycle par défaut, en jours — valeur initiale : le réglage "
                    "enregistré ci-dessus prend le dessus",
                ),
                _item(
                    env,
                    "MAINTENANCE_DUE_SOON_DAYS",
                    "Fenêtre « à échéance », en jours — même règle",
                ),
                _item(
                    env,
                    "MAINTENANCE_REMINDER_WEEKDAY",
                    "Jour du rappel hebdomadaire envoyé aux responsables (0 = lundi … "
                    "6 = dimanche), à l'heure du résumé",
                    f"{weekday} ({_WEEKDAYS[weekday]})",
                ),
            ],
        ),
        EnvGroup(
            label="Salles",
            items=[
                _item(
                    env,
                    "ROOM_SOURCE",
                    "Comment les postes sont rangés en salles : manual, ad_ou ou ad_location. "
                    "Dans un mode annuaire, le rattachement manuel est verrouillé",
                    f"{env.ROOM_SOURCE} ({_ROOM_SOURCES.get(env.ROOM_SOURCE, env.ROOM_SOURCE)})",
                ),
            ],
        ),
        _email_group(env),
        EnvGroup(
            label="Réveil des postes (Wake-on-LAN)",
            items=[
                _item(
                    env,
                    "WOL_RELAY_ENABLED",
                    "oui = le serveur confie le réveil à un poste allumé du même "
                    "emplacement (serveur hébergé hors site) ; non = il émet lui-même",
                ),
                _item(
                    env,
                    "WOL_BROADCAST_ADDRESSES",
                    "Adresses de diffusion explicites ; renseignées, elles remplacent "
                    "l'adresse déduite du poste",
                ),
                _item(
                    env,
                    "WOL_SUBNET_PREFIXLEN",
                    "Masque de repli pour déduire l'adresse de diffusion d'un poste "
                    "dont l'agent n'a pas remonté le sien",
                ),
                _item(env, "WOL_PORT", "Port UDP du paquet magique"),
                _item(env, "WOL_PACKET_COUNT", "Nombre de copies du paquet émises"),
                _item(
                    env,
                    "WOL_RELAY_TTL_MINUTES",
                    "Délai, en minutes, laissé à un poste relais pour prendre un réveil",
                ),
                _item(
                    env,
                    "WOL_RELAY_SUBNET_GRACE_SECONDS",
                    "Avance laissée à un relais du même sous-réseau que la cible ; 0 = aucune",
                ),
            ],
        ),
        EnvGroup(
            label="Console et sécurité",
            items=[
                _item(
                    env,
                    "ENVIRONMENT",
                    "local, staging ou production ; hors local, les secrets de "
                    "démonstration sont refusés et les erreurs internes masquées",
                ),
                _item(
                    env,
                    "CONSOLE_BASE_URL",
                    "URL publique de la console, pour le lien « mot de passe oublié » ; "
                    "vide = aucun e-mail de réinitialisation",
                ),
                _item(
                    env,
                    "ACCESS_TOKEN_EXPIRE_MINUTES",
                    "Durée de vie d'une session console, en minutes",
                ),
                _item(
                    env,
                    "PASSWORD_MIN_LENGTH",
                    "Longueur minimale imposée à tout mot de passe",
                ),
                _item(
                    env,
                    "PASSWORD_RESET_EXPIRE_MINUTES",
                    "Validité, en minutes, d'un lien de réinitialisation",
                ),
                _item(
                    env,
                    "RATE_LIMIT_ENABLED",
                    "Limitation des tentatives de connexion ; non = à réserver à des "
                    "opérateurs qui arrivent tous d'une même adresse",
                ),
            ],
        ),
    ]


def never_shown() -> frozenset[str]:
    """The names the catalogue refuses, for the test that holds it to them."""
    return _NEVER_SHOWN
