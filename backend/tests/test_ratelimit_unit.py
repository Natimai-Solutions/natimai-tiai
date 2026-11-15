"""The in-process limiters: the sweep that bounds their memory, and the quota
that counts units rather than requests (audit S21). No database."""

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


def test_the_quota_grants_what_is_left_per_key_and_window(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(ratelimit.time, "monotonic", clock)
    quota = ratelimit.Quota(units=10, window_seconds=100)
    assert quota.take("a", 7) == 7
    assert quota.take("a", 7) == 3
    assert quota.take("a", 1) == 0
    assert quota.take("b", 4) == 4
    clock.now += 101
    assert quota.take("a", 20) == 10


def test_the_quota_says_what_is_left_and_takes_back_what_was_not_used(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(ratelimit.time, "monotonic", clock)
    quota = ratelimit.Quota(units=10, window_seconds=100)
    assert quota.remaining("a") == 10
    quota.take("a", 4)
    clock.now += 10
    quota.take("a", 5)
    assert quota.remaining("a") == 1
    # Looking takes nothing.
    assert quota.remaining("a") == 1
    # The latest grant goes first, and a part of one can be returned.
    quota.give_back("a", 2)
    assert quota.remaining("a") == 3
    quota.give_back("a", 7)
    assert quota.remaining("a") == 10
    # More than was taken, or a key never seen: nothing below zero.
    quota.give_back("a", 5)
    quota.give_back("nobody", 5)
    assert quota.remaining("a") == 10 and quota.remaining("nobody") == 10


def test_a_poste_is_granted_the_smaller_of_its_budget_and_the_fleets(monkeypatch):
    """The per-poste budget does not bound many postes; the fleet's does."""
    monkeypatch.setattr(ratelimit.software_quota, "units", 4)
    monkeypatch.setattr(ratelimit.software_fleet_quota, "units", 6)
    ratelimit.reset_all()
    assert ratelimit.reserve_software_entries("a", 10) == 4
    assert ratelimit.software_budget_left("a") == 0
    assert ratelimit.software_budget_left("b") == 2
    assert ratelimit.reserve_software_entries("b", 10) == 2
    assert ratelimit.reserve_software_entries("c", 10) == 0
    assert ratelimit.software_fleet_budget_left() == 0
    # What was reserved and never committed comes back to both budgets.
    ratelimit.release_software_entries("b", 2)
    assert ratelimit.software_fleet_budget_left() == 2
    assert ratelimit.software_budget_left("b") == 2
    assert ratelimit.software_budget_left("c") == 2
    ratelimit.reset_all()
    assert ratelimit.software_fleet_budget_left() == 6


def test_the_heartbeat_budget_is_about_one_per_five_seconds():
    """Audit S21: no more than twelve heartbeats a minute per poste."""
    limiter = ratelimit.heartbeat_limiter
    assert limiter.window == 60
    assert limiter.max_attempts <= 12
