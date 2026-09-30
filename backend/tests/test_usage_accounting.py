"""The usage rule, as pure arithmetic: no database."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.features.usage.accounting import credit_for_gap, hour_start

WINDOW = 180
T = datetime(2026, 9, 30, 8, 20, 0, tzinfo=UTC)


def test_a_short_gap_is_credited_whole_to_its_hour():
    assert credit_for_gap(T, T + timedelta(seconds=61), WINDOW) == [
        (datetime(2026, 9, 30, 8, 0, tzinfo=UTC), 61)
    ]


def test_a_gap_across_the_hour_is_split_on_it():
    previous = datetime(2026, 9, 30, 8, 59, 30, tzinfo=UTC)
    now = previous + timedelta(seconds=90)
    assert credit_for_gap(previous, now, WINDOW) == [
        (datetime(2026, 9, 30, 8, 0, tzinfo=UTC), 30),
        (datetime(2026, 9, 30, 9, 0, tzinfo=UTC), 60),
    ]


def test_a_gap_ending_exactly_on_the_hour_stays_in_the_hour_it_ran_in():
    previous = datetime(2026, 9, 30, 8, 59, 0, tzinfo=UTC)
    now = datetime(2026, 9, 30, 9, 0, 0, tzinfo=UTC)
    assert credit_for_gap(previous, now, WINDOW) == [
        (datetime(2026, 9, 30, 8, 0, tzinfo=UTC), 60)
    ]


def test_a_gap_starting_exactly_on_the_hour_belongs_to_that_hour():
    previous = datetime(2026, 9, 30, 9, 0, 0, tzinfo=UTC)
    assert credit_for_gap(previous, previous + timedelta(seconds=60), WINDOW) == [
        (previous, 60)
    ]


def test_a_gap_spanning_several_hours_is_split_on_each():
    # A parc with a raised window: the rule is written for N hours, not two.
    previous = datetime(2026, 9, 30, 8, 30, tzinfo=UTC)
    now = datetime(2026, 9, 30, 10, 15, tzinfo=UTC)
    assert credit_for_gap(previous, now, 3 * 3600) == [
        (datetime(2026, 9, 30, 8, 0, tzinfo=UTC), 1800),
        (datetime(2026, 9, 30, 9, 0, tzinfo=UTC), 3600),
        (datetime(2026, 9, 30, 10, 0, tzinfo=UTC), 900),
    ]


@pytest.mark.parametrize("gap", [WINDOW, WINDOW + 1, 8 * 3600])
def test_a_gap_at_or_past_the_online_window_credits_nothing(gap):
    # The same side of the threshold as ``is_online``: at exactly the window
    # the console already shows the poste as off.
    assert credit_for_gap(T, T + timedelta(seconds=gap), WINDOW) == []


@pytest.mark.parametrize("gap", [0, -30])
def test_a_gap_that_is_not_positive_credits_nothing(gap):
    assert credit_for_gap(T, T + timedelta(seconds=gap), WINDOW) == []


def test_credits_telescope_to_the_span_they_cover():
    # Heartbeats ~60.4 s apart: rounding each gap on its own would drift;
    # whole epoch seconds add up to the span, to the second.
    beats = [T + timedelta(seconds=60.4 * i) for i in range(120)]
    total = sum(
        seconds
        for previous, now in zip(beats, beats[1:], strict=False)
        for _, seconds in credit_for_gap(previous, now, WINDOW)
    )
    span = beats[-1] - beats[0]
    assert abs(total - span.total_seconds()) < 1


def test_hours_are_utc_whatever_zone_the_instants_come_in():
    tahiti = timezone(timedelta(hours=-10))
    previous = datetime(2026, 9, 29, 22, 59, 50, tzinfo=tahiti)  # 08:59:50 UTC
    credits = credit_for_gap(previous, previous + timedelta(seconds=20), WINDOW)
    assert credits == [
        (datetime(2026, 9, 30, 8, 0, tzinfo=UTC), 10),
        (datetime(2026, 9, 30, 9, 0, tzinfo=UTC), 10),
    ]
    assert all(hour.tzinfo is UTC for hour, _ in credits)


def test_naive_instants_are_refused():
    with pytest.raises(ValueError):
        credit_for_gap(T.replace(tzinfo=None), T + timedelta(seconds=60), WINDOW)
    with pytest.raises(ValueError):
        credit_for_gap(T, (T + timedelta(seconds=60)).replace(tzinfo=None), WINDOW)


def test_hour_start_truncates_to_the_whole_utc_hour():
    assert hour_start(datetime(2026, 9, 30, 8, 59, 59, 999, tzinfo=UTC)) == datetime(
        2026, 9, 30, 8, 0, tzinfo=UTC
    )
