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
        # window at most, not for the life of the process.
        if len(self._hits) > 1024:
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

# Heartbeat: keyed on the poste. An agent polls once a minute, a few more
# times around a command or a retry; a token in a loop — filling the software
# catalogue, filing itself in rooms — is cut here (audit S21).
heartbeat_limiter = RateLimiter(max_attempts=30, window_seconds=60)

_ALL = (
    login_limiter,
    password_reset_limiter,
    enroll_limiter,
    password_change_limiter,
    heartbeat_limiter,
)


class FailureMemory:
    """When each (account, address) pair last failed a login.

    What a locked account is guarded by (audit S03): the lock refuses the
    addresses that failed on the account recently, not the account itself —
    so anyone can no longer keep an administrator out by failing five times
    from a poste, while the addresses doing the guessing stay shut out.
    """

    def __init__(self) -> None:
        self._last: dict[tuple[str, str], float] = {}

    def note(self, account: str, ip: str) -> None:
        now = time.monotonic()
        self._last[(account, ip)] = now
        if len(self._last) > 4096:
            horizon = now - settings.LOGIN_LOCKOUT_MINUTES * 60
            for key, at in list(self._last.items()):
                if at <= horizon:
                    del self._last[key]

    def failed_recently(self, account: str, ip: str) -> bool:
        at = self._last.get((account, ip))
        return at is not None and (
            time.monotonic() - at < settings.LOGIN_LOCKOUT_MINUTES * 60
        )

    def forget(self, account: str, ip: str | None = None) -> None:
        """Forget ``ip`` on ``account``, or every address when ``ip`` is None
        (a new password: what was guessed before no longer matters)."""
        for key in list(self._last):
            if key[0] == account and (ip is None or key[1] == ip):
                del self._last[key]

    def reset(self) -> None:
        self._last.clear()


login_failures = FailureMemory()


def reset_all() -> None:
    """Forget every recorded attempt (tests)."""
    for limiter in _ALL:
        limiter.reset()
    login_failures.reset()


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
