"""In-memory rate limiting for the authentication surface.

In-process on purpose: this stack has no Redis (the same trade-off as the
worker and the e-mail outbox — one moving part less), and it runs one API
process, so "N attempts per window per process" simply is "N per window".
State dies with the process; so does an attacker's progress, and a legitimate
user loses nothing they had.

Sliding window over a deque of monotonic timestamps per key (client IP). No
locks: FastAPI dependencies run on the event loop and nothing here awaits.
"""

import logging
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip

security_log = logging.getLogger("app.security")


class RateLimiter:
    """Sliding-window counter: at most ``max_attempts`` per window per key."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = float("-inf")

    def allow(self, key: str) -> bool:
        """Record one attempt for ``key``; False when the window is full."""
        now = time.monotonic()
        window_start = now - self.window
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= window_start:
            hits.popleft()
        if len(hits) >= self.max_attempts:
            return False
        hits.append(now)
        # An attacker cycling through source addresses must cost memory for a
        # window at most, not for the life of the process. At most one sweep
        # per window: above the threshold with keys all still live (a parc of
        # more than 1,024 postes heartbeating), a sweep frees nothing, and
        # running it on every call would make each call walk the whole table.
        if len(self._hits) > 1024 and now - self._last_sweep >= self.window:
            self._last_sweep = now
            self._sweep(window_start)
        return True

    def _sweep(self, window_start: float) -> None:
        for key, hits in list(self._hits.items()):
            while hits and hits[0] <= window_start:
                hits.popleft()
            if not hits:
                del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()
        self._last_sweep = float("-inf")


class Quota:
    """A budget of units per key over a sliding window: ``take`` grants what
    is left of it, possibly less than asked. Where a limiter counts requests,
    this counts what they create — the software catalogue entries a poste
    adds, say, whatever the number of heartbeats they ride (audit S21)."""

    def __init__(self, units: int, window_seconds: float) -> None:
        self.units = units
        self.window = window_seconds
        self._taken: dict[str, deque[tuple[float, int]]] = {}
        self._last_sweep = float("-inf")

    def _used(self, key: str, window_start: float) -> int:
        taken = self._taken.get(key)
        if taken is None:
            return 0
        while taken and taken[0][0] <= window_start:
            taken.popleft()
        return sum(n for _, n in taken)

    def take(self, key: str, wanted: int) -> int:
        """Grant up to ``wanted`` units to ``key`` and return how many."""
        now = time.monotonic()
        window_start = now - self.window
        granted = max(0, min(wanted, self.units - self._used(key, window_start)))
        if granted:
            self._taken.setdefault(key, deque()).append((now, granted))
        if len(self._taken) > 1024 and now - self._last_sweep >= self.window:
            self._last_sweep = now
            for k in list(self._taken):
                if not self._used(k, window_start):
                    del self._taken[k]
        return granted

    def remaining(self, key: str) -> int:
        """What ``key`` could still be granted right now, taking nothing."""
        used = self._used(key, time.monotonic() - self.window)
        return max(0, self.units - used)

    def give_back(self, key: str, units: int) -> None:
        """Return ``units`` granted to ``key`` and not used after all — what
        they were to create was rolled back. The latest grants go first."""
        taken = self._taken.get(key)
        while taken and units > 0:
            at, granted = taken[-1]
            if granted <= units:
                taken.pop()
                units -= granted
            else:
                taken[-1] = (at, granted - units)
                units = 0

    def reset(self) -> None:
        self._taken.clear()
        self._last_sweep = float("-inf")


# One limiter per guarded surface, so hammering /enroll never locks the
# console's /login. Keyed on client IP: the parc is a LAN where every poste
# has its own address, and the console reaches us through Caddy, which
# forwards the real one (app.core.net.client_ip).

# Login: a human retries a handful of times; a bcrypt oracle needs thousands.
login_limiter = RateLimiter(max_attempts=10, window_seconds=300)
# Reset requests: each accepted call may send a mail — the tightest budget,
# because the cost (mail to a known operator, Mailgun quota) starts at one.
password_reset_limiter = RateLimiter(max_attempts=5, window_seconds=900)
# Enroll: one poste enrolls once in its life, but a re-imaged salle can come
# back all at once — roomy, since each poste still arrives from its own IP.
enroll_limiter = RateLimiter(max_attempts=30, window_seconds=300)

# Self-service password change: keyed on the account, not the address — a
# stolen access token is the threat, and it works from anywhere (audit S04).
password_change_limiter = RateLimiter(max_attempts=5, window_seconds=900)

# Heartbeat: keyed on the poste. The agent polls every
# heartbeat_interval_seconds (60 by default), once more at a service restart,
# and backs off (doubling from that interval) after a failure: a legitimate
# poste sends one or two a minute. AGENT_HEARTBEAT_MAX_PER_MINUTE (12, one per
# five seconds on average) leaves room for an interval lowered to ten seconds
# plus a restart, and cuts a token in a loop (filling the software catalogue,
# filing itself in rooms) to about one request per five seconds (audit S21).
heartbeat_limiter = RateLimiter(
    max_attempts=settings.AGENT_HEARTBEAT_MAX_PER_MINUTE, window_seconds=60
)

# New software catalogue entries one poste may create per day
# (SOFTWARE_NEW_ENTRIES_PER_DAY). A first inventory names at most MAX_SOFTWARE
# (2,000) entries, and on a parc whose catalogue already exists nearly all of
# them are known; a token in a loop used to add 2,000 new names per heartbeat
# (audit S21). Same in-process trade-off as the limiters above.
software_quota = Quota(
    units=settings.SOFTWARE_NEW_ENTRIES_PER_DAY, window_seconds=24 * 3600
)
# The same entries, all postes together (SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET).
# The budget above is per poste, and the fleet secret enrolls as many postes
# as one cares to forge, each with a budget of its own: twenty-nine of them
# added 58,000 rows in under a minute. One key, since there is one catalogue.
software_fleet_quota = Quota(
    units=settings.SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET, window_seconds=24 * 3600
)
_FLEET = "fleet"


def software_fleet_budget_left() -> int:
    """New catalogue entries the postes together may still create."""
    return software_fleet_quota.remaining(_FLEET)


def software_budget_left(machine_key: str) -> int:
    """New catalogue entries this poste could be granted right now: the
    smaller of what is left of its own budget and of the fleet's."""
    return min(software_quota.remaining(machine_key), software_fleet_budget_left())


def reserve_software_entries(machine_key: str, wanted: int) -> int:
    """Take up to ``wanted`` new catalogue entries from both budgets, and
    return how many were granted. Nothing awaits in here, so the two budgets
    move together. To be given back with ``release_software_entries`` when
    the transaction that was to create them does not commit."""
    granted = min(wanted, software_budget_left(machine_key))
    if granted <= 0:
        return 0
    software_quota.take(machine_key, granted)
    software_fleet_quota.take(_FLEET, granted)
    return granted


def release_software_entries(machine_key: str, units: int) -> None:
    """Give back a reservation whose entries were never committed."""
    software_quota.give_back(machine_key, units)
    software_fleet_quota.give_back(_FLEET, units)


_ALL = (
    login_limiter,
    password_reset_limiter,
    enroll_limiter,
    password_change_limiter,
    heartbeat_limiter,
)


def reset_all() -> None:
    """Forget every recorded attempt (tests)."""
    for limiter in _ALL:
        limiter.reset()
    software_quota.reset()
    software_fleet_quota.reset()


def check_account(limiter: RateLimiter, key: str, surface: str) -> None:
    """``rate_limit`` for a key the route knows, such as the account."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    if not limiter.allow(key):
        security_log.warning("rate limit exceeded on %s for %s", surface, key)
        raise AppError(
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            message="Too many attempts; try again later",
            headers={"Retry-After": str(int(limiter.window))},
        )


def rate_limit(limiter: RateLimiter, surface: str) -> Callable[[Request], None]:
    """Dependency refusing requests beyond ``limiter``'s budget with a 429.

    ``surface`` names the endpoint in the security log — the log line, not the
    429, is what an operator greps when someone reports being locked out.
    """

    def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        ip = client_ip(request)
        if not limiter.allow(ip):
            security_log.warning("rate limit exceeded on %s from %s", surface, ip)
            raise AppError(
                code=ErrorCode.RATE_LIMITED,
                status_code=429,
                message="Too many attempts; try again later",
                headers={"Retry-After": str(int(limiter.window))},
            )

    return dependency
