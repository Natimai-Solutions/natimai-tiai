"""Emitting the magic packet from the server.

The one piece of this feature that touches a socket, kept apart from
``packet.py`` so the addressing rules stay testable without one — and so a test
can watch what would have gone out without putting anything on the wire.
"""

import asyncio
import logging
import socket
from dataclasses import dataclass

from app.core.config import settings
from app.features.wol.packet import destinations_for, magic_packet, normalize_mac

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WakeOutcome:
    """What happened, in the words the console will store and show.

    ``detail`` lands in the command row — ``result_output`` when it worked,
    ``error`` when it did not — so it is written in French like the agent's own
    verdicts, and it names the destination rather than the rule: an
    administrator whose poste did not come back needs to know which address the
    packet went to before anything else.

    A successful outcome means the datagrams left this host, and nothing more.
    Wake-on-LAN is unacknowledged by design: the poste is off, and a machine
    that never wakes looks from here exactly like one that does. Every message
    below is worded to promise only what was actually done.
    """

    ok: bool
    detail: str


def _emit(destinations: list[str], port: int, payload: bytes, count: int) -> None:
    """Send ``count`` copies of the payload to each destination (blocking)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # Without this the kernel refuses a sendto() aimed at a broadcast
        # address outright — it is a per-socket opt-in, not a privilege.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(count):
            for destination in destinations:
                sock.sendto(payload, (destination, port))


async def wake(
    *, mac: str | None, ip: str | None, prefix_length: int | None = None
) -> WakeOutcome:
    """Wake one machine, and say what was done or why it could not be.

    ``prefix_length`` is the mask the poste reported for ``ip``; None falls back
    on the configured default. It is the difference between a packet broadcast on
    10.4.255.255 and one broadcast on 10.4.7.255, on a parc addressed in /16.

    Never raises: a failure here is an outcome to record against the machine,
    not an error to propagate — a bulk wake of thirty postes must not abort on
    the one that has no MAC.
    """
    target = normalize_mac(mac)
    if target is None:
        return WakeOutcome(
            ok=False,
            detail=(
                "Aucune adresse MAC connue pour ce poste : son agent n'en a jamais "
                "remonté (agent antérieur à la fonction, ou carte réseau sans "
                "adresse exploitable). Un poste ne peut être réveillé qu'après au "
                "moins une remontée de son agent."
            ),
        )

    destinations = destinations_for(
        ip,
        configured=list(settings.WOL_BROADCAST_ADDRESSES),
        prefixlen=settings.WOL_SUBNET_PREFIXLEN,
        reported_prefixlen=prefix_length,
    )
    if not destinations:
        return WakeOutcome(
            ok=False,
            detail=(
                "Aucune adresse de diffusion pour ce poste : sa dernière adresse IP "
                "connue est absente ou n'est pas de l'IPv4. Renseigner "
                "WOL_BROADCAST_ADDRESSES côté serveur pour émettre malgré tout."
            ),
        )

    port = settings.WOL_PORT
    count = settings.WOL_PACKET_COUNT
    payload = magic_packet(target)
    try:
        # In a thread: sendto() on a broadcast is prompt, but it is a blocking
        # call all the same, and the event loop serves every agent heartbeat in
        # the parc. A handful of datagrams is not worth a stalled poll.
        await asyncio.to_thread(_emit, destinations, port, payload, count)
    except OSError as exc:
        logger.warning("wol: sending to %s failed: %s", destinations, exc)
        return WakeOutcome(
            ok=False,
            detail=f"Émission du paquet magique impossible : {exc}",
        )

    targets = ", ".join(f"{d}:{port}" for d in destinations)
    return WakeOutcome(
        ok=True,
        detail=(
            f"Paquet magique émis vers {target} — {count} copie(s) sur {targets}.\n"
            "L'émission ne prouve pas le réveil : le protocole n'accuse rien, et le "
            "poste ne réapparaîtra dans la console qu'à la remontée de son agent."
        ),
    )
