"""Turning two consecutive heartbeats into seconds on — the one rule.

A heartbeat proves the poste was on since the previous one *if the gap is
short*: exactly the window ``is_online`` already draws (``OFFLINE_AFTER_
SECONDS``). Same threshold, same side of it, so the dot in the machine list,
the ``online`` filter and this counter agree on what "on" means. A gap at or
past it is a hole — switched off, asleep, or unreachable — and credits
nothing; which is also why the first heartbeat after a boot credits nothing,
and a poste's count runs about a minute short per power cycle. That, and a
server outage longer than the window being lost for the whole parc, are the
two known under-counts, both small against a question asked in tens of hours.

Pure arithmetic, no database: the heartbeat handler calls it, the tests call
it directly.
"""

import math
from datetime import UTC, datetime, timedelta

_HOUR = timedelta(hours=1)


def hour_start(instant: datetime) -> datetime:
    """The whole UTC hour ``instant`` falls in."""
    return instant.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def credit_for_gap(
    previous: datetime, now: datetime, offline_after_seconds: int
) -> list[tuple[datetime, int]]:
    """Seconds on between two heartbeats, split on the UTC hours they span.

    Returns ``(hour_start, seconds)`` pairs, oldest first, or ``[]`` when the
    gap credits nothing: not positive (a clock step, a duplicate), or at or
    past ``offline_after_seconds``.

    Seconds are counted on whole epoch seconds — ``floor(end) − floor(start)``
    for each piece — rather than rounding each gap. The pieces then telescope:
    the credits of a run of heartbeats add up to its span to the second,
    where rounding every ~60.3 s gap on its own would drift by up to half a
    second a beat, half a minute an hour.

    Written for any number of hours although, at the default three-minute
    window, a gap spans two at most: the window can be raised on a slow parc.
    """
    if previous.tzinfo is None or now.tzinfo is None:
        # A naive instant is an ambiguous one; every stored timestamp is an
        # aware UTC instant (``utc_field``), so a naive one here is a bug.
        raise ValueError("credit_for_gap needs timezone-aware instants")
    gap = (now - previous).total_seconds()
    if gap <= 0 or gap >= offline_after_seconds:
        return []

    credits: list[tuple[datetime, int]] = []
    start = previous.astimezone(UTC)
    end = now.astimezone(UTC)
    while start < end:
        hour = hour_start(start)
        piece_end = min(end, hour + _HOUR)
        seconds = math.floor(piece_end.timestamp()) - math.floor(start.timestamp())
        if seconds > 0:
            credits.append((hour, seconds))
        start = piece_end
    return credits
