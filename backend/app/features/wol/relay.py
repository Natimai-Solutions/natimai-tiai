"""Relaying a wake through a poste that is on.

The server emits the magic packet itself when it can — when it sits on the
postes' network. A server hosted elsewhere cannot: no route carries a
broadcast across the Internet, and no router relays a directed one into a
school's VLAN. What the remote server does have is the parc itself, and every
poste still running on the site is a host on the target's wire.

So, with ``WOL_RELAY_ENABLED``, a wake is not emitted but *queued*: a
``wake_on_lan`` row on the machine to wake, PENDING, that the target's own
heartbeat never picks up (it is off, and if it is not, the wake is moot) but
that the first eligible poste to contact the server claims. Eligibility is the
one question that matters — is this poste on the same wire as the target? —
and it is answered from what the agents report:

* the **location** first, when the target has one. It is the setting made for
  this: a domain spans every site of an académie, a site name does not.
* the **domain** otherwise — the only signal left for a poste whose agent was
  deployed without a location. Right on a single-site parc, and the reason to
  set locations on any other.
* within a site, a poste on the target's **own IPv4 subnet** goes first: its
  broadcast is certain to reach the target where a poste on another VLAN of
  the same building only might. It claims at once; the others wait a
  heartbeat's worth (``WOL_RELAY_SUBNET_GRACE_SECONDS``) and then claim too,
  because a site with nothing on the right subnet still deserves a try.

What crosses the wire to the relay is the target's MAC, and that is the one
argument the command protocol has ever carried. The agent bounds it (an EUI-48
or a refusal, broadcast on its own subnets only, UDP/9), and the effect of a
forged one is bounded by construction — it wakes machines on the relay's
segment, which is the feature. The pure rules are here so they can be tested
without a database; the queries around them are thin.
"""

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.base import utcnow
from app.features.command.models import Command, CommandStatus, CommandType
from app.features.machine.models import Machine
from app.features.machine.status import online_clause
from app.features.wol.packet import normalize_mac
from app.features.wol.sender import WakeOutcome


def shares_wire(relay: Machine, target: Machine) -> bool:
    """Whether ``relay`` may be on the same broadcast domain as ``target``.

    Location when the target has one, domain otherwise — and never the target
    itself, which is off by hypothesis. A target with neither has no peer the
    server can name, and is refused at queueing time rather than left waiting.
    """
    if relay.id == target.id:
        return False
    if target.location:
        return relay.location == target.location
    if target.domain:
        return relay.domain == target.domain
    return False


def _network(machine: Machine) -> ipaddress.IPv4Network | None:
    """The IPv4 subnet a machine reported itself on, or None."""
    if not machine.ip_address or machine.ip_prefix_length is None:
        return None
    try:
        interface = ipaddress.ip_interface(
            f"{machine.ip_address}/{machine.ip_prefix_length}"
        )
    except ValueError:
        return None
    if not isinstance(interface, ipaddress.IPv4Interface):
        return None
    return interface.network


def same_subnet(relay: Machine, target: Machine) -> bool:
    """Whether both machines reported addresses on one IPv4 subnet.

    Strict: two addresses and two masks, all four usable. A poste that never
    reported a mask is not "on the same subnet", it is unknown — and unknown
    waits the grace like a poste on another VLAN, rather than jumping the
    queue on a guess.
    """
    a = _network(relay)
    b = _network(target)
    return a is not None and a == b


def may_claim(
    relay: Machine, target: Machine, *, queued_at: datetime, now: datetime
) -> bool:
    """Whether ``relay``, heartbeating now, takes a wake queued at ``queued_at``.

    The rule with the subnet preference folded in: a same-subnet poste at once,
    any other poste of the site once the grace has run.
    """
    if not shares_wire(relay, target):
        return False
    if same_subnet(relay, target):
        return True
    grace = timedelta(seconds=settings.WOL_RELAY_SUBNET_GRACE_SECONDS)
    return now - queued_at >= grace


def peer_clause(target: Machine) -> ColumnElement[bool] | None:
    """SQL for ``shares_wire`` with ``target`` fixed: the postes that could relay.

    None when nothing could — the target has neither location nor domain — so
    a caller can refuse rather than query for nobody. The self-exclusion is
    left to the caller, which has the id at hand.
    """
    if target.location:
        return col(Machine.location) == target.location
    if target.domain:
        return col(Machine.domain) == target.domain
    return None


def _site_label(target: Machine) -> str:
    """How the message names the set of possible relays."""
    if target.location:
        return f"l'emplacement « {target.location} »"
    return f"le domaine « {target.domain} »"


@dataclass(frozen=True)
class ClaimedWake:
    """A wake handed to a relay on its heartbeat: the row, and the MAC to name."""

    command: Command
    target_mac: str


async def count_online_peers(
    session: AsyncSession, target: Machine, now: datetime
) -> int:
    """How many postes that could relay a wake for ``target`` are on right now.

    Informational: the claim happens on a later heartbeat, by whichever of
    them comes first. But "zero" at queueing time is an answer the console can
    give at once — a site with nothing on has nothing to relay with — instead
    of a wake that sits pending until it expires.
    """
    peers = peer_clause(target)
    if peers is None:
        return 0
    count = await session.scalar(
        select(func.count())
        .select_from(Machine)
        .where(peers)
        .where(col(Machine.id) != target.id)
        .where(online_clause(True, now, settings.OFFLINE_AFTER_SECONDS))
    )
    return int(count or 0)


async def open_wake_for(
    session: AsyncSession, target: Machine, now: datetime
) -> Command | None:
    """The wake already waiting for (or claimed by) a relay for this target.

    A second click while the first is still inside its TTL adds nothing but
    a second packet; the console is told the first is still on its way.
    """
    rows = await session.exec(
        select(Command)
        .where(col(Command.machine_id) == target.id)
        .where(col(Command.type) == CommandType.WAKE_ON_LAN.value)
        .where(
            col(Command.status).in_(
                [CommandStatus.PENDING.value, CommandStatus.DELIVERED.value]
            )
        )
        .where(col(Command.expires_at) > now)
        .order_by(col(Command.created_at).desc())
    )
    return rows.first()


async def queue_relayed_wake(
    session: AsyncSession, target: Machine, *, created_by: str | None
) -> WakeOutcome:
    """Queue a wake for ``target`` to be relayed, and say what will happen.

    Mirrors ``sender.wake`` in shape — one outcome per poste, never an
    exception — and in what it promises: a queued wake is a wake some poste
    will *emit*, and nothing about the target coming back. The row is added
    to the session; the caller commits.

    Three refusals, each recorded as a failed row like the server-side ones:
    no MAC to name, no location and no domain to find a peer by, and no peer
    on at the moment — a site where every poste is off has nothing to relay
    with, and saying so now beats a wake that expires unclaimed in ten
    minutes.
    """
    now = utcnow()
    mac = normalize_mac(target.mac_address)
    if mac is None:
        return _closed(
            session,
            target,
            created_by,
            now,
            ok=False,
            detail=(
                "Aucune adresse MAC connue pour ce poste : son agent n'en a jamais "
                "remonté (agent antérieur à la fonction, ou carte réseau sans "
                "adresse exploitable). Un poste ne peut être réveillé qu'après au "
                "moins une remontée de son agent."
            ),
        )
    if peer_clause(target) is None:
        return _closed(
            session,
            target,
            created_by,
            now,
            ok=False,
            detail=(
                "Ce poste n'a ni emplacement ni domaine connu : le serveur ne peut "
                "désigner aucun poste voisin pour relayer le réveil. Renseigner "
                "l'emplacement dans la configuration de l'agent (location)."
            ),
        )

    already = await open_wake_for(session, target, now)
    if already is not None:
        # Not a new row: the one waiting is the one that will be emitted, and
        # its own history line is the record.
        state = (
            "déjà transmis à un poste relais"
            if already.status == CommandStatus.DELIVERED.value
            else "déjà en attente d'un poste relais"
        )
        return WakeOutcome(
            ok=True,
            detail=(
                f"Réveil {state} depuis {already.created_at:%H:%M} UTC ; rien de "
                "nouveau n'a été mis en file."
            ),
        )

    peers = await count_online_peers(session, target, now)
    site = _site_label(target)
    if peers == 0:
        return _closed(
            session,
            target,
            created_by,
            now,
            ok=False,
            detail=(
                f"Aucun poste allumé sur {site} pour relayer le réveil : le "
                "paquet magique doit partir d'un poste du même réseau que la "
                "cible, et aucun n'est en contact avec le serveur en ce moment."
            ),
        )

    ttl = timedelta(minutes=settings.WOL_RELAY_TTL_MINUTES)
    session.add(
        Command(
            machine_id=target.id,
            type=CommandType.WAKE_ON_LAN.value,
            status=CommandStatus.PENDING.value,
            created_by=created_by,
            created_at=now,
            expires_at=now + ttl,
        )
    )
    return WakeOutcome(
        ok=True,
        detail=(
            f"Réveil confié aux postes de {site} : {peers} poste(s) allumé(s) "
            "peuvent relayer le paquet magique, le premier à contacter le serveur "
            f"s'en charge (sous {settings.WOL_RELAY_TTL_MINUTES} min, sinon le "
            "réveil expire).\n"
            "L'émission ne prouvera pas le réveil : le protocole n'accuse rien, "
            "et le poste ne réapparaîtra dans la console qu'à la remontée de son "
            "agent."
        ),
    )


def _closed(
    session: AsyncSession,
    target: Machine,
    created_by: str | None,
    now: datetime,
    *,
    ok: bool,
    detail: str,
) -> WakeOutcome:
    """Record an outcome decided here and now, as the server-side path does."""
    status = CommandStatus.SUCCEEDED if ok else CommandStatus.FAILED
    session.add(
        Command(
            machine_id=target.id,
            type=CommandType.WAKE_ON_LAN.value,
            status=status.value,
            created_by=created_by,
            created_at=now,
            expires_at=now,
            started_at=now,
            finished_at=now,
            result_output=detail if ok else None,
            error=None if ok else detail,
        )
    )
    return WakeOutcome(ok=ok, detail=detail)


async def claim_wakes(
    session: AsyncSession, relay: Machine, now: datetime
) -> list[ClaimedWake]:
    """Hand ``relay`` every unclaimed wake it is eligible for, and mark them.

    Called from the heartbeat, after the relay's own commands. The candidates
    are the pending, unclaimed wakes whose target shares a site with this
    poste — a lookup by type and status, then the eligibility rules in
    Python, since a subnet comparison is not something to write in SQL twice.

    Two relays heartbeating in the same second can both pass and both emit:
    two magic packets wake a poste exactly once, so the race is left alone
    rather than locked against.
    """
    stmt = (
        select(Command, Machine)
        .join(Machine, col(Command.machine_id) == col(Machine.id))
        .where(col(Command.type) == CommandType.WAKE_ON_LAN.value)
        .where(col(Command.status) == CommandStatus.PENDING.value)
        .where(col(Command.relay_machine_id).is_(None))
        .where(col(Command.expires_at) > now)
        .where(col(Command.machine_id) != relay.id)
    )
    claimed: list[ClaimedWake] = []
    for command, target in (await session.exec(stmt)).all():
        if not may_claim(relay, target, queued_at=command.created_at, now=now):
            continue
        mac = normalize_mac(target.mac_address)
        if mac is None:
            # Refused at queueing time, so this is a row somebody wrote by
            # hand; there is nothing to name, and no poste should be handed
            # an empty argument.
            continue
        command.relay_machine_id = relay.id
        command.status = CommandStatus.DELIVERED.value
        command.delivered_at = now
        claimed.append(ClaimedWake(command=command, target_mac=mac))
    return claimed


async def close_wakes_for_awake_machine(
    session: AsyncSession, machine: Machine, now: datetime
) -> int:
    """A machine that heartbeats is awake: its open wakes have succeeded.

    The one acknowledgement Wake-on-LAN will ever give, read off the only
    evidence there is. Pending or delivered rows alone — the server-side path
    writes its rows closed, and a relay's verdict on a row already closed here
    is dropped at the result endpoint. Returns how many were closed.
    """
    rows = await session.exec(
        select(Command)
        .where(col(Command.machine_id) == machine.id)
        .where(col(Command.type) == CommandType.WAKE_ON_LAN.value)
        .where(
            col(Command.status).in_(
                [CommandStatus.PENDING.value, CommandStatus.DELIVERED.value]
            )
        )
    )
    closed = 0
    for command in rows.all():
        command.status = CommandStatus.SUCCEEDED.value
        command.finished_at = now
        command.result_output = (
            "Poste revenu en ligne : son agent a contacté le serveur — le seul "
            "accusé de réception qu'un réveil puisse avoir."
        )
        closed += 1
    return closed


def relay_label(relay: Machine | None) -> str:
    """How a relayed verdict names the poste that emitted it."""
    if relay is None:
        return "un poste relais"
    return relay.hostname or str(relay.id)


__all__ = [
    "ClaimedWake",
    "claim_wakes",
    "close_wakes_for_awake_machine",
    "count_online_peers",
    "may_claim",
    "open_wake_for",
    "peer_clause",
    "queue_relayed_wake",
    "relay_label",
    "same_subnet",
    "shares_wire",
]
