"""The in-process limiters: the sweep that bounds their memory (audit S21).
No database. The software catalogue budgets, counted in PostgreSQL, are
tested in test_shared_state.py."""

from app.core import ratelimit


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_sweep_runs_at_most_once_per_window(monkeypatch):
    """Above 1,024 live keys a sweep frees nothing: it must not run on every
    call, or each call walks the whole table."""
    clock = _Clock()
    monkeypatch.setattr(ratelimit.time, "monotonic", clock)
    limiter = ratelimit.RateLimiter(max_attempts=5, window_seconds=60)
    sweeps = 0
    real_sweep = limiter._sweep

    def counting_sweep(window_start: float) -> None:
        nonlocal sweeps
        sweeps += 1
        real_sweep(window_start)

    monkeypatch.setattr(limiter, "_sweep", counting_sweep)
    for i in range(3000):
        clock.now += 0.001
        assert limiter.allow(f"k{i}")
    assert sweeps == 1
    assert len(limiter._hits) > 1024

    # A window later, the next call sweeps again and drops every stale key.
    clock.now += 61
    assert limiter.allow("fresh")
    assert sweeps == 2
    assert list(limiter._hits) == ["fresh"]


def test_the_heartbeat_budget_is_about_one_per_five_seconds():
    """Audit S21: no more than twelve heartbeats a minute per poste."""
    limiter = ratelimit.heartbeat_limiter
    assert limiter.window == 60
    assert limiter.max_attempts <= 12
