"""Renewing a poste's token without ever locking its agent out.

A per-machine token used to be issued once and honoured for the life of the
poste: one copied off a disk image or a ProgramData backup kept working until
somebody thought to revoke it. Rotation bounds that to AGENT_TOKEN_ROTATE_DAYS.

The protocol has one constraint above all: the server must never stop
honouring a token the agent may still be holding. Hence two hashes on the row
and three moves:

* **offer** — on a heartbeat authenticated by the current token, from an agent
  that announced ``supports_token_rotation``, past the age: a new token is
  minted, its hash stored in ``pending_token_hash``, the token returned in the
  response. The current token stays valid.
* **re-offer** — the same agent still calling with the current token while an
  offer is pending means the response was lost, or the agent could not store
  the token. A fresh one replaces the pending hash; there is no way to tell
  which, and a lost token must not stay valid either.
* **promotion** — the first request carrying the pending token proves the agent
  has it: it becomes the current token, the old one dies, the clock restarts.

An agent that never announces the capability is never offered anything — an
agent too old to store a new token would otherwise be handed one, ignore it,
and carry on with the old one forever, which is harmless but pointless.

Not audited: a rotation is routine machine traffic, once a month per poste,
and would drown the administrative actions the log is for. It is logged.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.features.machine.models import Machine

security_log = logging.getLogger("app.security")


def rotation_due(machine: Machine, now: datetime, rotate_days: int) -> bool:
    """Whether this machine's agent should be offered a new token now.

    ``rotate_days`` at 0 turns rotation off entirely: no new offer, and no
    re-offer either — an offer left pending stays usable (its first use still
    promotes it), and the current token stays valid regardless.
    """
    if rotate_days <= 0:
        return False
    if machine.pending_token_hash is not None:
        return True
    return now - machine.token_issued_at >= timedelta(days=rotate_days)


def offer_new_token(machine: Machine) -> str:
    """Mint a token, keep its hash as pending, return it for the response.

    Overwrites any previous pending hash: that one was never used, and a
    token the agent may have lost is not one to leave valid.
    """
    token = security.generate_token()
    machine.pending_token_hash = security.hash_token(token)
    return token


def promote_pending(machine: Machine, now: datetime) -> None:
    """Make the pending token the current one; the previous one dies here."""
    machine.token_hash = machine.pending_token_hash
    machine.pending_token_hash = None
    machine.token_issued_at = now


def reset_rotation(machine: Machine) -> None:
    """Forget a rotation in flight — revocation, allow-reenroll, enrollment.

    A pending token is a credential like the current one: a revocation that
    left it in place would leave the poste one request away from working
    again, and an enrollment replaces every token the poste had.
    """
    machine.pending_token_hash = None


async def machine_for_token(
    session: AsyncSession, token: str, now: datetime
) -> Machine | None:
    """The machine this bearer token belongs to, promoting a pending token.

    Matches the current token or the pending one. On a match with the pending
    one — the agent stored the offer and switched — the promotion is committed
    here, before the endpoint runs: some agent endpoints return without
    committing (an ignored command result), and the old token must die with
    the first request that proved the new one, not with whichever comes next.

    A revoked machine is returned untouched: refusing it is the caller's
    business, and a revocation must not be what promotes a token.
    """
    token_hash = security.hash_token(token)
    result = await session.exec(
        select(Machine).where(
            or_(
                col(Machine.token_hash) == token_hash,
                col(Machine.pending_token_hash) == token_hash,
            )
        )
    )
    # first(), not one_or_none(): two rows sharing a hash would take 2^128
    # tokens to happen, and must not turn into a 500 on every heartbeat.
    machine = result.first()
    if machine is None or machine.token_revoked:
        return machine
    if machine.token_hash != token_hash:
        promote_pending(machine, now)
        machine_uuid = machine.machine_uuid
        await session.commit()
        await session.refresh(machine)
        security_log.info("token rotated for machine %s", machine_uuid)
    return machine
