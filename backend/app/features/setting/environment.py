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
credentials, the first admin's password. ``_NEVER_SHOWN`` is the list, and a
test holds the catalogue to it. A value that may carry one — the Mailgun
proxy's URL, ``http://user:password@proxy:3128`` — is shown by its host and
port alone (``_proxy_host``).

Each line is written in French (``value``, ``description``), for the clients
that print it as it comes, and also carries what a console in another language
needs to word it itself (plan ``dev/plan-console-bilingue.md``, I2): the group's
stable ``code``, the value as the environment holds it (``raw``, never a
secret), and how to show it (``format``, with ``params`` where the French
sentence has variable parts). The console words a description by the
variable's name.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.core.config import Settings, settings

# Variables the page must never print, whatever else is added to the catalogue.
_NEVER_SHOWN = frozenset(
    {
        "SECRET_KEY",
        "TOTP_ENCRYPTION_KEY",
        "OIDC_CLIENT_SECRET",
        "ENROLLMENT_SECRET",
        "ENROLLMENT_SECRET_PREVIOUS",
        "FIRST_ADMIN_EMAIL",
        "FIRST_ADMIN_PASSWORD",
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "MAILGUN_API_KEY",
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
    would say it, and what it decides.

    ``raw`` is the value itself, JSON-ready, and ``format`` says how ``value``
    words it, for a console that words it in its own language:

    - ``plain``: ``value`` is ``raw`` as is (a number, a name, a path);
    - ``bool``: « oui » or « non »;
    - ``list``: the entries joined by « , »;
    - ``bytes``: a size in bytes, with its amount in Gio or Mio;
    - ``weekday``: 0 = Monday … 6 = Sunday, with the day's name;
    - ``room_source``: the mode, with what it means;
    - ``mail_state``: the provider, and whether the environment alone sends
      mail (``params.configured``);
    - ``proxy``: the proxy's host and port, never more; ``raw`` is null and
      ``params.unreadable`` true when it does not read cleanly.
    """

    key: str
    value: str | None
    description: str
    raw: Any = None
    format: str = "plain"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvGroup:
    # Stable, for a console to name the group in its own language.
    code: str
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


# A host name as a proxy URL may carry it: letters, digits, dots and hyphens.
_HOST_NAME = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")

_UNREADABLE = "défini (illisible)"


def _proxy_host(url: str | None) -> str | None:
    """A proxy URL reduced to ``host:port``: what tells a reader where mail
    goes out through, without the account and password it may embed.

    Anything that does not read cleanly is said to be set, not printed. A
    password holding « / », « # » or « ? » ends the authority early for the
    parser, which then takes the account for the host and the digits that
    open the password for the port: so an « @ » anywhere but once inside
    the authority, a host that is neither a name nor an address, a port
    that is not one — none of it is shown, not even in part.
    """
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return _UNREADABLE
    if not parts.scheme or not host or parts.netloc.count("@") > 1:
        return _UNREADABLE
    if "@" in parts.path + parts.query + parts.fragment:
        return _UNREADABLE
    if ":" in host:
        try:
            host = f"[{ipaddress.IPv6Address(host)}]"
        except ValueError:
            return _UNREADABLE
    elif not _HOST_NAME.fullmatch(host):
        return _UNREADABLE
    return f"{host}:{port}" if port else host


def _bytes(value: int) -> str:
    """A size as written in ``.env`` and in words: ``2147483648 (2 Gio)``."""
    for unit, size in (("Gio", 1024**3), ("Mio", 1024**2)):
        if value >= size:
            amount = value / size
            shown = f"{amount:.0f}" if amount == int(amount) else f"{amount:.1f}"
            return f"{value} ({shown.replace('.', ',')} {unit})"
    return f"{value} octets"


def _format_of(raw: Any) -> str:
    if isinstance(raw, bool):
        return "bool"
    if isinstance(raw, list | tuple):
        return "list"
    return "plain"


def _item(
    env: Settings,
    key: str,
    description: str,
    value: Any = ...,
    *,
    raw: Any = ...,
    fmt: str | None = None,
    params: dict[str, Any] | None = None,
) -> EnvItem:
    """An item read off ``env`` by name, unless a rendered value is given —
    then with the ``raw`` value it words and its ``format``."""
    if key in _NEVER_SHOWN:  # pragma: no cover - a catalogue bug, caught by test
        raise ValueError(f"{key} must not be shown")
    shown = getattr(env, key) if value is ... else value
    if raw is ...:
        raw = shown
    if isinstance(raw, tuple):
        raw = list(raw)
    return EnvItem(
        key=key,
        value=_fmt(shown),
        description=description,
        raw=raw,
        format=fmt or _format_of(raw),
        params=params or {},
    )


# Appended to every mail variable the card « Envoi des e-mails » can override:
# the value read here is where the console starts from, not necessarily what
# it sends with.
_MAIL_INITIAL = " — valeur initiale : la carte « Envoi des e-mails » prend le dessus"


def _email_group(env: Settings) -> EnvGroup:
    """The mail channel as the environment describes it: the provider chosen,
    whether the environment alone is complete, and the variables of that
    provider — the other's are ignored by the server and would only confuse
    here. Every one of them is an initial value the console's card may
    override; the credentials are not listed at all (``_NEVER_SHOWN``)."""
    state = (
        "configuré dans l'environnement"
        if env.alerts_enabled
        else "incomplet dans l'environnement : aucun e-mail ne part sans "
        "réglage dans la console"
    )
    items = [
        _item(
            env,
            "EMAIL_PROVIDER",
            "Canal de sortie du courrier : l'API Mailgun ou un serveur SMTP"
            + _MAIL_INITIAL,
            f"{env.EMAIL_PROVIDER} ({state})",
            raw=env.EMAIL_PROVIDER,
            fmt="mail_state",
            params={"configured": env.alerts_enabled},
        ),
        _item(
            env,
            "EMAIL_FROM_EMAIL",
            "Adresse d'expéditeur (ou MAILGUN_FROM_EMAIL pour un .env plus ancien)"
            + _MAIL_INITIAL,
            env.email_from_email,
        ),
        _item(
            env,
            "EMAIL_FROM_NAME",
            "Nom d'expéditeur affiché" + _MAIL_INITIAL,
            env.email_from_name,
        ),
    ]
    proxy = _proxy_host(env.MAILGUN_PROXY_URL)
    if env.EMAIL_PROVIDER == "smtp":
        items += [
            _item(
                env,
                "SMTP_HOST",
                "Serveur SMTP ; vide = SMTP non configuré" + _MAIL_INITIAL,
            ),
            _item(env, "SMTP_PORT", "Port du serveur SMTP" + _MAIL_INITIAL),
            _item(
                env,
                "SMTP_SECURITY",
                "starttls (587), tls (465) ou none (relais interne sur 25)"
                + _MAIL_INITIAL,
            ),
            _item(
                env,
                "SMTP_VERIFY_TLS",
                "Vérification du certificat du serveur ; non = relais à certificat privé"
                + _MAIL_INITIAL,
            ),
            _item(
                env,
                "SMTP_TIMEOUT_SECONDS",
                "Délai d'attente du serveur SMTP, en secondes" + _MAIL_INITIAL,
            ),
        ]
    else:
        items += [
            _item(
                env,
                "MAILGUN_DOMAIN",
                "Domaine d'envoi Mailgun ; vide = Mailgun non configuré"
                + _MAIL_INITIAL,
            ),
            _item(
                env,
                "MAILGUN_API_BASE_URL",
                "Point d'entrée de l'API Mailgun (EU ou US)" + _MAIL_INITIAL,
            ),
            _item(
                env,
                "MAILGUN_TIMEOUT_SECONDS",
                "Délai d'attente de l'API Mailgun, en secondes",
            ),
            _item(
                env,
                "MAILGUN_PROXY_URL",
                "Proxy HTTP par lequel passent les appels à Mailgun, et eux seuls ; "
                "vide = connexion directe. Seuls l'hôte et le port sont affichés, "
                "jamais un identifiant ni un mot de passe",
                proxy,
                # Never the URL itself: it may carry an account and a password.
                raw=None if proxy == _UNREADABLE else proxy,
                fmt="proxy",
                params={"unreadable": proxy == _UNREADABLE},
            ),
        ]
    items += [
        _item(
            env,
            "DIGEST_HOUR_UTC",
            "Heure UTC d'envoi du résumé quotidien et du rappel de maintenance "
            "— valeur initiale : le réglage enregistré prend le dessus",
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
            "DEFAULT_LANGUAGE",
            "Langue des e-mails d'un compte qui n'a pas choisi la sienne (fr ou en)",
        ),
        _item(
            env,
            "EMAIL_MAX_ATTEMPTS",
            "Tentatives d'envoi d'un e-mail (de 1 min à 1 h d'écart) avant qu'il "
            "soit abandonné et gardé avec sa dernière erreur",
        ),
        _item(
            env,
            "EMAIL_OUTBOX_RETENTION_DAYS",
            "Jours de conservation des e-mails envoyés ou abandonnés dans la file de sortie",
        ),
    ]
    return EnvGroup(code="email", label="E-mails", items=items)


def environment_overview(env: Settings = settings) -> list[EnvGroup]:
    """The environment, grouped the way the console's pages are."""
    weekday = env.MAINTENANCE_REMINDER_WEEKDAY
    return [
        EnvGroup(
            code="fleet",
            label="Postes et seuils",
            items=[
                _item(
                    env,
                    "SIGNATURE_MAX_AGE_DAYS",
                    "Âge maximal des signatures antivirus, en jours, avant qu'un poste "
                    "soit « base antivirus périmée » — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
                ),
                _item(
                    env,
                    "INACTIVE_AFTER_DAYS",
                    "Jours sans contact de l'agent avant qu'un poste soit « inactif »"
                    " — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
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
                    "système en dessous duquel un poste est signalé — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
                ),
                _item(
                    env,
                    "HARDWARE_AGING_YEARS",
                    "Âge du poste (date d’achat, à défaut date du BIOS) à partir duquel il "
                    "est compté à "
                    "renouveler — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
                ),
                _item(
                    env,
                    "AGENT_EXPECTED_VERSION",
                    "Version d'agent de référence pour « agent obsolète » ; vide = la plus "
                    "haute version remontée par le parc — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
                ),
                _item(
                    env,
                    "COMMAND_DEFAULT_TTL_MINUTES",
                    "Durée de vie, en minutes, d'une commande encore en attente avant "
                    "qu'elle soit périmée — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
                ),
                _item(
                    env,
                    "COMMAND_UNANSWERED_HOURS",
                    "Heures laissées à un poste pour répondre d'une commande qu'il a "
                    "reçue avant qu'elle soit close en échec « sans réponse du poste » "
                    "(une réponse plus tardive l'emporte encore)",
                ),
                _item(
                    env,
                    "COMMAND_RETENTION_DAYS",
                    "Jours de conservation de l'historique des commandes terminées "
                    "(0 = indéfiniment)",
                ),
                _item(
                    env,
                    "AGENT_TOKEN_ROTATE_DAYS",
                    "Âge, en jours, au-delà duquel le token d'un poste est renouvelé "
                    "(0 = jamais)",
                ),
                _item(
                    env,
                    "AGENT_HEARTBEAT_MAX_PER_MINUTE",
                    "Battements qu'un même poste peut envoyer par minute ; au-delà, "
                    "le serveur répond 429 (l'agent en envoie un par intervalle, "
                    "plus un au redémarrage)",
                ),
                _item(
                    env,
                    "SOFTWARE_NEW_ENTRIES_PER_DAY",
                    "Nouvelles entrées du catalogue logiciel qu'un même poste peut "
                    "créer par 24 heures ; au-delà, son inventaire est signalé partiel "
                    "et redemandé quand le budget le permet",
                ),
                _item(
                    env,
                    "SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET",
                    "Nouvelles entrées du catalogue logiciel que tous les postes "
                    "réunis peuvent créer par 24 heures ; un poste reçoit le plus "
                    "petit de ce qui reste de son budget et de celui-ci",
                ),
                _item(
                    env,
                    "AUDIT_RETENTION_DAYS",
                    "Jours de conservation du journal d'audit (0 = indéfiniment)",
                ),
                _item(
                    env,
                    "TREND_RETENTION_DAYS",
                    "Jours de conservation des photos quotidiennes du tableau de "
                    "bord, lues par la page Tendances",
                ),
            ],
        ),
        EnvGroup(
            code="maintenance",
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
                    "6 = dimanche), à l'heure du résumé — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
                    f"{weekday} ({_WEEKDAYS[weekday]})",
                    raw=weekday,
                    fmt="weekday",
                ),
            ],
        ),
        EnvGroup(
            code="usage",
            label="Utilisation des postes",
            items=[
                _item(
                    env,
                    "USAGE_WINDOW_DAYS",
                    "Fenêtre d'observation, en jours — valeur initiale : le réglage "
                    "enregistré ci-dessus prend le dessus",
                ),
                _item(
                    env,
                    "USAGE_LOW_HOURS",
                    "Heures allumées en dessous desquelles un poste est « peu utilisé » "
                    "— même règle",
                ),
                _item(
                    env,
                    "USAGE_HIGH_HOURS",
                    "Heures allumées au-dessus desquelles un poste est « toujours "
                    "allumé » — même règle",
                ),
                _item(
                    env,
                    "USAGE_RETENTION_DAYS",
                    "Durée de conservation, en jours, des compteurs horaires "
                    "d'utilisation",
                ),
            ],
        ),
        EnvGroup(
            code="rooms",
            label="Salles",
            items=[
                _item(
                    env,
                    "ROOM_SOURCE",
                    "Comment les postes sont rangés en salles : manual, ad_ou ou ad_location. "
                    "Dans un mode annuaire, le rattachement manuel est verrouillé",
                    f"{env.ROOM_SOURCE} ({_ROOM_SOURCES.get(env.ROOM_SOURCE, env.ROOM_SOURCE)})",
                    raw=env.ROOM_SOURCE,
                    fmt="room_source",
                ),
            ],
        ),
        _email_group(env),
        EnvGroup(
            code="wol",
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
                _item(
                    env,
                    "WOL_ALLOWED_NETWORKS",
                    "Réseaux (CIDR) sur lesquels le serveur peut émettre lui-même un "
                    "réveil ; vide = les plages privées 10.0.0.0/8, 172.16.0.0/12 et "
                    "192.168.0.0/16. Une adresse de poste hors de ces réseaux n'est "
                    "pas une destination",
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
                _item(
                    env,
                    "WOL_RELAY_MIN_AGE_MINUTES",
                    "Ancienneté minimale, en minutes, d'un poste dans le parc avant "
                    "qu'il puisse relayer un réveil",
                ),
                _item(
                    env,
                    "WOL_RELAY_MIN_AGENT_VERSION",
                    "Version d'agent minimale d'un poste relais ; un agent plus ancien, "
                    "ou sans version lisible, ne reçoit aucun réveil à relayer",
                ),
                _item(
                    env,
                    "WOL_RELAY_CLAIM_TIMEOUT_SECONDS",
                    "Secondes sans réponse après lesquelles un réveil pris par un "
                    "relais est remis en file pour un autre",
                ),
            ],
        ),
        EnvGroup(
            code="console",
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
                    "TIAI_SERVER_NAME",
                    "Nom sous lequel le serveur est joint (site de Caddy, nom du "
                    "certificat) ; la console en déduit son URL publique",
                ),
                _item(
                    env,
                    "CONSOLE_BASE_URL",
                    "URL publique de la console, dans les liens des e-mails ; "
                    "déduite de TIAI_SERVER_NAME quand elle n'est pas renseignée. "
                    "Vide = aucun e-mail de réinitialisation",
                    env.console_base_url,
                ),
                _item(
                    env,
                    "ACCESS_TOKEN_EXPIRE_MINUTES",
                    "Durée de vie, en minutes, du jeton d'accès console (renouvelé seul "
                    "par la session)",
                ),
                _item(
                    env,
                    "REFRESH_TOKEN_EXPIRE_DAYS",
                    "Jours sans usage avant qu'une session console se ferme (glissant)",
                ),
                _item(
                    env,
                    "SESSION_MAX_DAYS",
                    "Durée maximale d'une session console depuis la connexion, en jours",
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
                    "PASSWORD_RESET_COOLDOWN_MINUTES",
                    "Minutes pendant lesquelles une même adresse ne fait pas "
                    "envoyer de nouvel e-mail « mot de passe oublié » pour un "
                    "compte après le précédent qu'elle a demandé",
                ),
                _item(
                    env,
                    "PASSWORD_RESET_MAX_LIVE_LINKS",
                    "Nombre de liens de réinitialisation valides à la fois pour un "
                    "même compte et une même adresse qui les demande ; une demande "
                    "n'annule jamais un lien encore valide",
                ),
                _item(
                    env,
                    "PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS",
                    "Plafond de liens valides à la fois pour un même compte, toutes "
                    "adresses confondues ; une demande venue d'une adresse "
                    "habituelle du compte n'y est pas soumise",
                ),
                _item(
                    env,
                    "LOGIN_MAX_FAILED_ATTEMPTS",
                    "Échecs de connexion rapprochés (chacun à moins de "
                    "LOGIN_LOCKOUT_MINUTES du précédent) avant qu'un compte soit "
                    "verrouillé pour les adresses qui ont échoué",
                ),
                _item(
                    env,
                    "LOGIN_LOCKOUT_MINUTES",
                    "Durée, en minutes, du verrouillage, et délai au-delà duquel un "
                    "échec ancien ne compte plus ; une réinitialisation du mot de "
                    "passe le lève",
                ),
                _item(
                    env,
                    "LOGIN_SIEGE_ADDRESSES",
                    "Nombre d'adresses distinctes en échec sur un même compte, en "
                    "LOGIN_LOCKOUT_MINUTES (sous le verrou des essais lents : depuis "
                    "le début de sa fenêtre), à partir duquel le verrouillage écarte "
                    "toutes les adresses sauf celles qui ont ouvert le compte récemment",
                ),
                _item(
                    env,
                    "LOGIN_KNOWN_ADDRESS_DAYS",
                    "Jours pendant lesquels une adresse qui a ouvert un compte reste "
                    "connue de lui, et n'est pas écartée par ce verrouillage étendu",
                ),
                _item(
                    env,
                    "LOGIN_SLOW_MAX_FAILED_ATTEMPTS",
                    "Échecs de connexion, même espacés, en LOGIN_SLOW_WINDOW_HOURS "
                    "heures qui verrouillent un compte pour ce nombre d'heures ; ce "
                    "verrou ferme le compte aux adresses qui ont échoué pendant "
                    "cette fenêtre. Non défini : 20, ou quatre fois "
                    "LOGIN_MAX_FAILED_ATTEMPTS si c'est davantage",
                ),
                _item(
                    env,
                    "LOGIN_SLOW_WINDOW_HOURS",
                    "Fenêtre, en heures, de ce second compteur, et durée du verrou "
                    "qu'il pose ; seul un nouveau mot de passe le lève. Non défini : "
                    "24, ou le double de LOGIN_LOCKOUT_MINUTES si c'est davantage",
                ),
                _item(
                    env,
                    "ENROLLMENT_REENROLL_REQUIRES_APPROVAL",
                    "Un poste déjà enrôlé qui redemande un token attend l'approbation "
                    "d'un administrateur",
                ),
                _item(
                    env,
                    "RATE_LIMIT_ENABLED",
                    "Limitation du débit par adresse (connexion, mot de passe oublié, "
                    "enrôlement), par session (changement de mot de passe) et par poste "
                    "(battements) ; non = tout cela est levé, à réserver à des "
                    "opérateurs qui arrivent tous d'une même adresse. Ni le "
                    "verrouillage des comptes ni le budget du catalogue logiciel "
                    "n'en dépendent",
                ),
                _item(
                    env,
                    "TRUSTED_PROXIES",
                    "Réseaux (CIDR) des proxys dont l'en-tête X-Forwarded-For est cru "
                    "pour connaître l'adresse du client, en plus de la boucle locale",
                ),
                _item(
                    env,
                    "TRUSTED_PROXIES_ALLOW_WIDE",
                    "oui = TRUSTED_PROXIES peut lister un réseau plus large qu'un /24 "
                    "(IPv4) ou un /64 (IPv6) ; non = le serveur refuse de démarrer, "
                    "car tout client de ce réseau pourrait choisir son adresse",
                ),
                _item(
                    env,
                    "TRUSTED_PROXY_HOSTS",
                    "Noms d'hôte de ces proxys, résolus dans le réseau du serveur "
                    "(le service caddy par défaut)",
                ),
                _item(
                    env,
                    "EXPOSE_OPENAPI",
                    "oui = le schéma OpenAPI et ses pages (/docs, /redoc) sont servis "
                    "hors développement local",
                ),
                _item(
                    env,
                    "POSTGRES_POOL_SIZE",
                    "Connexions à la base gardées ouvertes par processus (API, worker)",
                ),
                _item(
                    env,
                    "POSTGRES_MAX_OVERFLOW",
                    "Connexions supplémentaires ouvertes au-delà, le temps d'un pic",
                ),
                _item(
                    env,
                    "POSTGRES_POOL_TIMEOUT",
                    "Secondes d'attente d'une connexion libre avant qu'une requête "
                    "échoue",
                ),
            ],
        ),
        EnvGroup(
            code="packages",
            label="Paquets logiciels",
            items=[
                _item(
                    env,
                    "PACKAGES_DIR",
                    "Dossier du serveur où sont rangés les fichiers des paquets "
                    "(un fichier par empreinte SHA-256)",
                ),
                _item(
                    env,
                    "PACKAGE_MAX_BYTES",
                    "Taille maximale d'un fichier de paquet déposé, en octets ; le "
                    "proxy devant le serveur est dimensionné en conséquence",
                    _bytes(env.PACKAGE_MAX_BYTES),
                    raw=env.PACKAGE_MAX_BYTES,
                    fmt="bytes",
                ),
                _item(
                    env,
                    "PACKAGE_METHOD_A_MAX_GB",
                    "Poids total, en Gio, au-delà duquel les postes refusent de "
                    "télécharger un paquet non signé (méthode A) ; doit valoir le "
                    "DeployMethodAMaxGB de la GPO des agents",
                ),
            ],
        ),
    ]


def never_shown() -> frozenset[str]:
    """The names the catalogue refuses, for the test that holds it to them."""
    return _NEVER_SHOWN
