"""What the server writes into a command's result, as a code and its words.

Since the bilingual console (plan ``dev/plan-console-bilingue.md``, I3), a
verdict the server writes itself — a command lost, cancelled by a merge or a
retired package, a wake refused or emitted — is stored twice: the French
sentence in ``error`` or ``result_output``, as before, for an older console
and whatever reads the API without one; and a ``code`` with its ``params`` in
``result_code`` and ``result_params``, which the console words in its
reader's language. A row stored before keeps its text and no code, and reads
as it always did.

Each sentence is written here, from its parameters, and nowhere else: the
console's French catalogue (``frontend/src/i18n/messages/commands.ts``) must
read the same, word for word, and ``tests/test_command_texts.py`` checks it on
a shared set of cases (``tests/data/command_texts_fr.json``).

The code words the verdict: the ``error`` of a failed command, the
``result_output`` of a succeeded one. The agent's own messages (I5) follow
the same rule, with their codes sent by the agent (``message_code``).
"""

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Verdict:
    """A sentence the server writes for the console: its code, its
    parameters, and the French text stored beside them."""

    code: str
    text: str
    params: dict[str, Any] = field(default_factory=dict)


# --- Commands closed by the server -------------------------------------------


def unanswered(hours: int) -> Verdict:
    """A command delivered and never answered (audit B10)."""
    return Verdict(
        "command.unanswered",
        f"Sans réponse du poste {hours} h après la remise : commande considérée "
        "comme perdue (poste éteint, agent arrêté ou mis à jour pendant "
        "l'exécution). Relancez-la si besoin.",
        {"hours": hours},
    )


def merged() -> Verdict:
    """An open command of a poste merged into another one."""
    return Verdict("command.merged", "Poste fusionné : commande annulée")


# --- Deployments refused or cancelled ----------------------------------------


def directory_not_reader() -> Verdict:
    """A directory reading whose poste is no longer a reader: its designation
    fell between the queue and the delivery."""
    return Verdict(
        "directory.not_reader",
        "Lecture d'annuaire annulée : ce poste n'est plus lecteur d'annuaire",
    )


def package_deleted() -> Verdict:
    """A deployment whose package was deleted before delivery."""
    return Verdict("package.deleted", "Paquet supprimé avant l'exécution")


def package_retired_after_queue() -> Verdict:
    """An installation whose package was retired before delivery."""
    return Verdict(
        "package.retired_after_queue",
        "Paquet retiré après la mise en file : installation annulée",
    )


def package_changed_after_queue() -> Verdict:
    """A deployment whose package changed since it was queued (audit S08)."""
    return Verdict(
        "package.changed_after_queue",
        "Paquet modifié après la mise en file (fichiers, ligne de commande ou "
        "signature) : relancez le déploiement pour envoyer la nouvelle version",
    )


def package_retired() -> Verdict:
    """A pending installation cancelled by retiring its package (audit T08)."""
    return Verdict("package.retired", "Paquet retiré : installation annulée")


def package_superseded() -> Verdict:
    """A pending deployment replaced by one of another version."""
    return Verdict("package.superseded", "Remplacée par un nouveau déploiement")


# --- Wake-on-LAN ---------------------------------------------------------------

_NOT_WOKEN_HINT = (
    "L'émission ne prouve pas le réveil : le protocole n'accuse rien, et le "
    "poste ne réapparaîtra dans la console qu'à la remontée de son agent."
)


def wake_no_mac() -> Verdict:
    """No MAC address known for the poste: nothing to name in a packet."""
    return Verdict(
        "wol.no_mac",
        "Aucune adresse MAC connue pour ce poste : son agent n'en a jamais "
        "remonté (agent antérieur à la fonction, ou carte réseau sans adresse "
        "exploitable). Un poste ne peut être réveillé qu'après au moins une "
        "remontée de son agent.",
    )


def wake_no_ipv4() -> Verdict:
    """No IPv4 address known to broadcast to."""
    return Verdict(
        "wol.no_ipv4",
        "Aucune adresse de diffusion pour ce poste : sa dernière adresse IP "
        "connue est absente ou n'est pas de l'IPv4. Renseigner "
        "WOL_BROADCAST_ADDRESSES côté serveur pour émettre malgré tout.",
    )


def _allowed(allowed: str | None) -> str:
    return (
        allowed
        if allowed is not None
        else "les plages privées 10.0.0.0/8, 172.16.0.0/12 et 192.168.0.0/16"
    )


def wake_address_not_allowed(ip: str, allowed: str | None) -> Verdict:
    """The poste's address lies outside the networks the server may wake on.

    ``allowed`` is ``WOL_ALLOWED_NETWORKS`` joined, None for the default (the
    private ranges)."""
    return Verdict(
        "wol.address_not_allowed",
        f"Réveil refusé : la dernière adresse IP connue du poste ({ip}) est hors "
        "des réseaux sur lesquels le serveur peut émettre un réveil "
        f"({_allowed(allowed)}). Ajouter le réseau du poste à WOL_ALLOWED_NETWORKS "
        "côté serveur, ou renseigner WOL_BROADCAST_ADDRESSES.",
        {"ip": ip, "allowed": allowed},
    )


def wake_subnet_not_allowed(
    ip: str, prefix_length: int | None, default_prefix_length: int, allowed: str | None
) -> Verdict:
    """The poste's address is allowed, its whole subnet is not."""
    default = f"/{default_prefix_length} de WOL_SUBNET_PREFIXLEN"
    masks = (
        f"masque /{prefix_length} remonté par le poste, à défaut {default}"
        if prefix_length is not None
        else f"masque {default}"
    )
    return Verdict(
        "wol.subnet_not_allowed",
        f"Réveil refusé : l'adresse du poste ({ip}) est autorisée, mais son "
        f"sous-réseau ({masks}) n'est pas contenu en entier dans les réseaux sur "
        f"lesquels le serveur peut émettre un réveil ({_allowed(allowed)}). "
        "Élargir WOL_ALLOWED_NETWORKS au sous-réseau entier du poste, ou "
        "renseigner WOL_BROADCAST_ADDRESSES.",
        {
            "ip": ip,
            "prefix_length": prefix_length,
            "default_prefix_length": default_prefix_length,
            "allowed": allowed,
        },
    )


def wake_send_failed(detail: str) -> Verdict:
    """The socket refused the datagrams. ``detail`` is the system's own error."""
    return Verdict(
        "wol.send_failed",
        f"Émission du paquet magique impossible : {detail}",
        {"detail": detail},
    )


def wake_sent(mac: str, copies: int, targets: str) -> Verdict:
    """The server emitted the packet — and nothing more is known."""
    return Verdict(
        "wol.sent",
        f"Paquet magique émis vers {mac} — {copies} copie(s) sur {targets}.\n"
        + _NOT_WOKEN_HINT,
        {"mac": mac, "copies": copies, "targets": targets},
    )


def _site(site_kind: str, site: str) -> str:
    if site_kind == "location":
        return f"l'emplacement « {site} »"
    return f"le domaine « {site} »"


def wake_no_site() -> Verdict:
    """Relay mode: no location and no domain to find a neighbour by."""
    return Verdict(
        "wol.no_site",
        "Ce poste n'a ni emplacement ni domaine connu : le serveur ne peut "
        "désigner aucun poste voisin pour relayer le réveil. Renseigner "
        "l'emplacement dans la configuration de l'agent (location).",
    )


def wake_no_relay(site_kind: str, site: str) -> Verdict:
    """Relay mode: no poste on at the site to emit the packet.

    ``site_kind`` is ``location`` or ``domain``, what ``site`` names."""
    return Verdict(
        "wol.no_relay",
        f"Aucun poste allumé sur {_site(site_kind, site)} pour relayer le réveil : "
        "le paquet magique doit partir d'un poste du même réseau que la cible, et "
        "aucun poste habilité à relayer (agent à jour, inscrit depuis assez "
        "longtemps, identité confirmée) n'est en contact avec le serveur en ce "
        "moment.",
        {"site_kind": site_kind, "site": site},
    )


def wake_relay_queued(
    site_kind: str, site: str, peers: int, ttl_minutes: int
) -> Verdict:
    """Relay mode: the wake is queued for the postes of the site."""
    return Verdict(
        "wol.relay_queued",
        f"Réveil confié aux postes de {_site(site_kind, site)} : {peers} poste(s) "
        "allumé(s) peuvent relayer le paquet magique, le premier à contacter le "
        f"serveur s'en charge (sous {ttl_minutes} min, sinon le réveil expire).\n"
        "L'émission ne prouvera pas le réveil : le protocole n'accuse rien, et le "
        "poste ne réapparaîtra dans la console qu'à la remontée de son agent.",
        {
            "site_kind": site_kind,
            "site": site,
            "peers": peers,
            "ttl_minutes": ttl_minutes,
        },
    )


def elapsed(minutes: int) -> str:
    """« 12 min », « 1 h 05 » — a duration rather than a clock time: the
    server's clock is UTC and the console reads local time, and an hour
    printed in one zone is read in the other (« depuis 07:45 UTC »)."""
    if minutes < 1:
        return "moins d'une minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def wake_relay_already(delivered: bool, minutes: int) -> Verdict:
    """Relay mode: a wake is already waiting for — or claimed by — a relay."""
    state = (
        "déjà transmis à un poste relais"
        if delivered
        else "déjà en attente d'un poste relais"
    )
    return Verdict(
        "wol.relay_already",
        f"Réveil {state} depuis {elapsed(minutes)} ; rien de nouveau n'a été mis "
        "en file.",
        {"state": "delivered" if delivered else "pending", "minutes": minutes},
    )


def wake_back_online() -> Verdict:
    """A relayed wake closed by the target's own heartbeat."""
    return Verdict(
        "wol.back_online",
        "Poste revenu en ligne : son agent a contacté le serveur — le seul accusé "
        "de réception qu'un réveil puisse avoir.",
    )


def wake_unknown_machine() -> Verdict:
    """A wake asked for a poste that no longer exists (answer only, no row)."""
    return Verdict(
        "wol.unknown_machine", "Poste introuvable : il a été supprimé ou fusionné."
    )


# --- The agent's verdicts, as stored ------------------------------------------


def relayed(who: str, text: str) -> str:
    """A relayed wake's verdict, signed by the relay. The console words it
    from the agent's code and the ``relay`` parameter the server adds."""
    return f"Relayé par {who} — {text}"


# What the server appends to a text it cut (``agent.CommandResult``). Not a
# code: the console recognises it at the end of the text and words it.
TRUNCATED_NOTE = "\n[…] sortie tronquée par le serveur"


# --- The agent's codes (I5) ----------------------------------------------------

# What an agent may send as ``message_code`` and ``message_params``: a code
# of the console's catalogue, and a few flat values to fill it. Anything else
# is dropped — the French text the agent sends beside them is kept, and reads
# as before — rather than refused: a verdict without its code beats none.
MESSAGE_CODE_PATTERN = re.compile(r"^[a-z0-9_.]{1,64}$")
_PARAM_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MESSAGE_PARAMS_MAX_KEYS = 16
MESSAGE_PARAM_TEXT_MAX = 1024
MESSAGE_PARAMS_MAX_BYTES = 4096


def _param_ok(value: object) -> bool:
    if value is None or isinstance(value, bool | int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= MESSAGE_PARAM_TEXT_MAX
    return False


def clean_message(
    code: object, params: object
) -> tuple[str | None, dict[str, Any] | None]:
    """The agent's code and parameters if they are well-formed, else
    ``(None, None)``: a code matching ``MESSAGE_CODE_PATTERN``; parameters
    absent, or a flat JSON object of at most ``MESSAGE_PARAMS_MAX_KEYS``
    keys, each a short name, each value null, a boolean, a number or a text
    of at most ``MESSAGE_PARAM_TEXT_MAX`` characters, the whole at most
    ``MESSAGE_PARAMS_MAX_BYTES`` bytes. Parameters without a code mean
    nothing, and are dropped too."""
    if not isinstance(code, str) or not MESSAGE_CODE_PATTERN.fullmatch(code):
        return None, None
    if params is None:
        return code, {}
    if not isinstance(params, dict) or len(params) > MESSAGE_PARAMS_MAX_KEYS:
        return None, None
    for key, value in params.items():
        if not isinstance(key, str) or not _PARAM_KEY_PATTERN.fullmatch(key):
            return None, None
        if not _param_ok(value):
            return None, None
    size = len(json.dumps(params, ensure_ascii=False).encode("utf-8"))
    if size > MESSAGE_PARAMS_MAX_BYTES:
        return None, None
    return code, dict(params)
