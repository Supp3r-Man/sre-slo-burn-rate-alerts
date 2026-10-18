import random

import pytest

from slo_burn.slo import (SLO, ErrorBudget, Stats, Traffic, burn_rate, hours_to_exhaust,
                          threshold_for)

A = SLO("a", 0.999)


def test_error_budget_value():
    assert A.error_budget == 0.001


def test_objective_must_be_strictly_inside_unit_interval():
    for o in (0, 1, -0.1, 1.5):
        with pytest.raises(ValueError):
            SLO("x", o)
    with pytest.raises(ValueError):
        SLO("x", 0.99, "latency")            # latency SLO needs a threshold
    with pytest.raises(ValueError):
        SLO("x", 0.99, "throughput")


def test_traffic_validation():
    with pytest.raises(ValueError):
        Traffic([1, 2], [0], [0, 0])
    with pytest.raises(ValueError):
        Traffic([10], [6], [5])        # errors + slow > total
    with pytest.raises(ValueError):
        Traffic([10], [-1], [0])


def test_bad_series_depends_on_sli_kind_and_sli_ratio():
    tr = Traffic([100, 100], [3, 0], [0, 7])
    assert A.bad(tr) == [3, 0]
    assert SLO("l", 0.99, "latency", 300).bad(tr) == [0, 7]
    tr = Traffic([100, 100, 0], [10, 0, 0], [0, 0, 0])
    assert A.sli(tr, 0, 2) == pytest.approx(0.95)
    assert A.sli(tr, 2, 3) == 1.0


def test_burn_rate_is_one_when_exactly_at_slo_and_zero_without_traffic():
    assert burn_rate(1, 1000, 0.001) == pytest.approx(1.0)
    assert burn_rate(5, 1000, 0.001) == pytest.approx(5.0)
    assert burn_rate(0, 0, 0.001) == 0.0
    assert hours_to_exhaust(1) == pytest.approx(720)
    assert hours_to_exhaust(14.4) == pytest.approx(50)
    assert hours_to_exhaust(0) == float("inf")


def test_workbook_thresholds_follow_from_budget_fractions():
    assert threshold_for(0.02, 60) == pytest.approx(14.4)
    assert threshold_for(0.05, 360) == pytest.approx(6.0)
    assert threshold_for(0.10, 4320) == pytest.approx(1.0)


def test_budget_exactly_consumed_and_overspent():
    tr = Traffic([1000] * 100, [1] * 100, [0] * 100)    # 100 bad of 100000 = 0.1% = budget
    eb = ErrorBudget(A, tr)
    assert eb.consumed(99) == pytest.approx(1.0)
    assert eb.remaining(99) == pytest.approx(0.0, abs=1e-9)
    over = ErrorBudget(A, Traffic([1000] * 100, [2] * 100, [0] * 100))
    assert over.remaining(99) == pytest.approx(-1.0)


def test_window_truncates_at_series_start():
    st = Stats([10, 10, 10], [1, 2, 3])
    assert st.window(1, 60) == (3, 20)
    assert st.window(2, 2) == (5, 20)


def _rand_traffic(rng, n):
    total = [rng.randrange(0, 40) for _ in range(n)]
    bad = [rng.randrange(0, t + 1) if rng.random() < 0.3 else 0 for t in total]
    return total, bad


def test_window_matches_naive_sums():
    for seed in range(5):
        rng = random.Random(seed)
        total, bad = _rand_traffic(rng, 300)
        st = Stats(total, bad)
        for _ in range(200):
            t, w = rng.randrange(300), rng.randrange(1, 400)
            lo = max(0, t + 1 - w)
            assert st.window(t, w) == (sum(bad[lo:t + 1]), sum(total[lo:t + 1]))


def test_rolling_budget_matches_reference():
    for seed in range(3):
        rng = random.Random(100 + seed)
        total, bad = _rand_traffic(rng, 400)
        eb = ErrorBudget(A, Traffic(total, bad, [0] * 400))
        for t in range(0, 400, 7):
            lo = max(0, t + 1 - 90)
            n, b = sum(total[lo:t + 1]), sum(bad[lo:t + 1])
            ref = 0.0 if n == 0 else b / (0.001 * n)
            assert eb.consumed(t, 90) == pytest.approx(ref)
            assert eb.burn_rate(t, 90) == pytest.approx(ref)    # same window => burn == consumed fraction
