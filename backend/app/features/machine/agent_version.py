"""Which agent versions run on the parc, and which of them are behind.

The agent reports its version on every heartbeat (``agent_version``), and until
now the console showed it as a string on the fiche and nowhere else — which
answers "quelle version a ce poste" and not the question actually asked after a
deployment, "lesquels ne l'ont pas encore".

"Behind" needs a reference. By default it is the highest version seen anywhere
on the parc: a deployment is what makes the new version appear, and from that
moment every poste still on the old one is a poste the deployment has not
reached. No configuration, no call to GitHub — a server on an internal network
may have no way to ask what the latest release is — and it is right in the one
case that matters: the morning after a push. ``AGENT_EXPECTED_VERSION`` pins
the reference instead, for a parc that rolls out to a pilot group first and
does not want the rest of the fleet flagged on the pilot's account.
"""

import re
from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.features.machine.models import Machine

# A version as the release workflow stamps it: "0.4.2", "v0.4.2", "0.4.2-dev.abc1234".
_NUMERIC = re.compile(r"\d+")


def version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    """A sort key that orders versions the way a human reads them.

    Numeric fields compare as numbers ("0.10.0" after "0.9.0", which a string
    compare gets wrong), a pre-release ("-dev.abc") sorts *below* the release
    it precedes, and anything unparseable sorts lowest of all — an agent
    built from an untagged tree is not the reference for the parc.
    """
    text = version.strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    main, _, pre = text.partition("-")
    numbers = tuple(int(n) for n in _NUMERIC.findall(main))
    # Release (no suffix) outranks its own pre-releases; the suffix text only
    # orders pre-releases among themselves.
    return (numbers, 0 if pre else 1, pre)


def latest_version(versions: list[str]) -> str | None:
    """The highest version among those reported, or None when none is."""
    candidates = [v for v in versions if v and v.strip()]
    if not candidates:
        return None
    return max(candidates, key=version_key)


def outdated_versions(versions: list[str], latest: str | None) -> list[str]:
    """The reported versions that rank below ``latest``.

    Computed here, on the handful of distinct strings a parc carries, and
    handed to SQL as a list: a version compare has no honest translation into
    an ORDER BY, and the machine list must not have to pretend it does.
    """
    if latest is None:
        return []
    reference = version_key(latest)
    return [v for v in versions if v and version_key(v) < reference]


@dataclass(frozen=True)
class FleetVersions:
    """What the parc runs: the reference, the versions behind it, the counts."""

    # The configured reference, or the highest version reported; None on an
    # empty parc.
    latest: str | None
    # Configured (``AGENT_EXPECTED_VERSION``) rather than derived from the
    # fleet: the console says which, because "latest" means two different
    # things in the two cases.
    pinned: bool
    # Versions ranking below the reference — what the SQL clause is fed.
    outdated: list[str]
    # (version, machines) newest first: the reference on top, the stragglers
    # below it — the order a deployment is read in.
    counts: list[tuple[str, int]]


async def fleet_versions(session: AsyncSession) -> FleetVersions:
    """Distinct agent versions on the parc, the reference, and which are behind.

    One query over a column of a handful of distinct values — cheap enough to
    run on every list page, which is what makes the "behind" flag live: it
    moves the moment a poste reports a version nobody had seen before.
    """
    version = col(Machine.agent_version)
    rows = await session.exec(
        select(version, func.count().label("count"))
        .where(version.is_not(None))
        .where(version != "")
        .group_by(version)
    )
    counts = [(name, count) for name, count in rows.all() if name]
    names = [name for name, _ in counts]
    pinned = settings.AGENT_EXPECTED_VERSION
    latest = pinned or latest_version(names)
    return FleetVersions(
        latest=latest,
        pinned=pinned is not None,
        outdated=outdated_versions(names, latest),
        counts=sorted(counts, key=lambda item: version_key(item[0]), reverse=True),
    )
