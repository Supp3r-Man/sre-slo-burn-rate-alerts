import random

import pytest

from slo_burn.sim import (AVAIL, PROFILES, SCENARIOS, SHAPES, WARMUP, binomial, build, generate,
                          poisson)
from slo_burn.slo import MIN_PER_DAY


def test_same_seed_same_traffic_different_seed_differs():
    a, b = generate(PROFILES["normal"], "ramp", 7), generate(PROFILES["normal"], "ramp", 7)
    c = generate(PROFILES["normal"], "ramp", 8)
    assert (a.traffic.total, a.traffic.errors, a.start) == (b.traffic.total, b.traffic.errors, b.start)
    assert a.traffic.total != c.traffic.total


def test_poisson_mean_in_both_regimes():
    rng = random.Random(1)
    for lam in (5.0, 100.0):
        mean = sum(poisson(rng, lam) for _ in range(4000)) / 4000
        assert abs(mean - lam) < 0.06 * lam
    assert poisson(rng, 0) == 0


def test_binomial_property_bounds_and_exact_ends():
    rng = random.Random(2)
    for _ in range(1000):
        n, p = rng.randrange(0, 500), rng.choice([0, 1, rng.random(), rng.random() ** 4])
        k = binomial(rng, n, p)
        assert 0 <= k <= n
        assert p != 0 or k == 0
        assert p != 1 or k == n


def test_every_scenario_builds_with_valid_incident_window():
    for name, prof, shape, slo in SCENARIOS:
        s = build(name, 0)                           # Traffic() validates errors + slow <= total per minute
        if shape:
            assert WARMUP <= s.start < WARMUP + MIN_PER_DAY
            assert s.end == s.start + SHAPES[shape].duration
        else:
            assert s.start is None and s.end is None


def test_hard_outage_fails_every_request_in_window_only():
    s = build("hard_outage", 3)
    t, e = s.traffic.total, s.traffic.errors
    assert e[s.start:s.end] == t[s.start:s.end]
    assert sum(e[:s.start]) < 0.01 * sum(t[:s.start]) and sum(e[s.end:]) < 0.01 * sum(t[s.end:])


def test_diurnal_load_noon_busier_than_midnight():
    t = build("healthy", 0).traffic.total
    noon = sum(sum(t[d * MIN_PER_DAY + 690:d * MIN_PER_DAY + 750]) for d in range(10))      # 60 min around 12:00
    night = sum(sum(t[d * MIN_PER_DAY + 1410:d * MIN_PER_DAY + 1440]) * 2 for d in range(10))  # 60 min-equivalent at ~00:00
    assert noon > 2 * night


def test_retry_storm_triples_volume():
    s = build("retry_storm", 1)
    now = sum(s.traffic.total[s.start:s.end])
    yesterday = sum(s.traffic.total[s.start - MIN_PER_DAY:s.end - MIN_PER_DAY])
    assert 2.7 < now / yesterday < 3.3


def test_slow_burn_error_ratio_and_budget_denominator():
    s = build("slow_burn_0.9x", 0)
    ratio = sum(s.traffic.errors[s.start:s.end]) / sum(s.traffic.total[s.start:s.end])
    assert abs(ratio - 0.0009) < 0.00005
    assert s.budget_bad == pytest.approx(0.001 * 200 * 43200)


def test_noisy_profile_has_blips_and_tiny_has_few_requests():
    noisy, normal = build("noisy_but_fine", 0).traffic, build("healthy", 0).traffic
    assert sum(noisy.errors) > 2 * sum(normal.errors)
    assert sum(build("tiny_healthy", 0).traffic.total) < 10 * MIN_PER_DAY * 0.3 * 1.2
