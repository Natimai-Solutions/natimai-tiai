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


# One limiter per guarded surface, so hammering /enroll never locks the
# console's /login. Keyed on client IP: the parc is a LAN where every poste
# has its own address, and the console reaches us through Caddy, which
# forwards the real one (app.core.net.client_ip).

# Login: a human retries a handful of times; a bcrypt oracle needs thousands.
login_limiter = RateLimiter(max_attempts=10, window_seconds=300)
# Reset requests: each accepted call may send a mail — the tightest budget,
# because the cost (mail to a known operator, Mailgun quota) starts at one.
password_reset_limiter = RateLimiter(max_attempts=5, window_seconds=900)
# Checking a reset link before the form is shown: sends nothing, so roomier
# than the requests — a page reloaded a few times must not spend the budget a
# new link would need — but bounded the same way, per address.
password_reset_check_limiter = RateLimiter(max_attempts=20, window_seconds=900)
# Enroll: one poste enrolls once in its life, but a re-imaged salle can come
# back all at once — roomy, since each poste still arrives from its own IP.
enroll_limiter = RateLimiter(max_attempts=30, window_seconds=300)

# Self-service password change: keyed on the session, not the address — a
# stolen access token is the threat, and it works from anywhere (audit S04)
# — nor the account, whose budget the thief would spend for its owner's
# other sessions (audit T07).
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

_ALL = (
    login_limiter,
    password_reset_limiter,
    password_reset_check_limiter,
    enroll_limiter,
    password_change_limiter,
    heartbeat_limiter,
)


def reset_all() -> None:
    """Forget every recorded attempt (tests)."""
    for limiter in _ALL:
        limiter.reset()


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
