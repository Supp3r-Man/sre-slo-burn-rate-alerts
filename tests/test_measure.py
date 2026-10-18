from statistics import median

import pytest

from slo_burn.__main__ import main
from slo_burn.alerts import Event, multiwindow
from slo_burn.measure import measure, policies, run_scenario, sweep
from slo_burn.sim import AVAIL, WARMUP, Scenario, build
from slo_burn.slo import Traffic

SEEDS = range(4)


def runs(name, seeds=SEEDS, **kw):
    out = {}
    for s in seeds:
        for p, r in run_scenario(build(name, s), policies(AVAIL, **kw)).items():
            out.setdefault(p, []).append(r)
    return out


def test_hard_outage_pages_within_minutes_under_multiwindow():
    for r in runs("hard_outage")["multiwindow"]:
        assert r.detected and r.ttd <= 3 and r.first_severity == "page"
        assert r.pages == 1                          # fast+slow rules fire, one notification


def test_blip_static_pages_multiwindow_stays_quiet():
    out = runs("blip")
    assert all(r.pages >= 1 for r in out["static-2%/10m"])
    assert all(r.pages == 0 and not r.detected for r in out["multiwindow"])


def test_slow_burn_just_below_1x_is_silent_but_burns_budget():
    for r in runs("slow_burn_0.9x", range(3))["multiwindow"]:
        assert not r.detected and r.pages == 0 and r.tickets == 0
        assert r.budget_pct > 8                      # ~0.9x for 5 days = ~15% of the 30-day budget


def test_slow_burn_2x_is_a_late_ticket_not_a_page():
    for r in runs("slow_burn_2x", range(3))["multiwindow"]:
        assert r.detected and r.first_severity == "ticket" and r.pages == 0
        assert r.ttd > 1440                          # >1 day: the 3d window needs time to fill


def test_static_threshold_false_pages_on_noisy_but_fine_traffic_multiwindow_does_not():
    sw = runs("noisy_but_fine", range(3))
    assert sum(r.pre_pages for r in sw["static-2%/10m"]) > sum(r.pre_pages for r in sw["multiwindow"])


def test_low_traffic_guard_removes_false_pages_and_costs_detection_time():
    h = runs("tiny_healthy", range(6))
    assert sum(r.pre_pages for r in h["multiwindow"]) >= 6
    assert sum(r.pre_pages for r in h["multiwindow+guard"]) < sum(r.pre_pages for r in h["multiwindow"]) / 3
    o = runs("tiny_outage_120m", range(6))
    assert median(r.budget_pct for r in o["multiwindow+guard"]) > median(r.budget_pct for r in o["multiwindow"])
    assert all(r.detected for r in o["multiwindow+guard"])


def _scn(bad_per_min=5, n=WARMUP + 200):
    tr = Traffic([1000] * n, [bad_per_min if m >= WARMUP + 10 else 0 for m in range(n)], [0] * n)
    return Scenario("x", AVAIL, tr, WARMUP + 10, WARMUP + 20, 100.0)


def test_measure_budget_and_ttd_arithmetic():
    s = _scn()
    r = measure(s, [Event(WARMUP + 12, "r", "page", "fire")])
    assert (r.ttd, r.budget_pct) == (2, 15.0)        # minutes start..start+2 inclusive = 3 * 5 bad / 100
    silent = measure(s, [])
    assert not silent.detected and silent.budget_pct == 50.0     # 10 incident minutes * 5 / 100


def test_alert_already_firing_at_incident_start_counts_as_zero_ttd_not_a_new_page():
    s = _scn()
    r = measure(s, [Event(WARMUP + 5, "r", "page", "fire")])
    assert r.detected and r.ttd == 0 and r.pre_pages == 1 and r.pages == 0
    resolved = measure(s, [Event(WARMUP + 5, "r", "page", "fire"), Event(WARMUP + 8, "r", "page", "resolve")])
    assert not resolved.detected


def test_longer_resolve_hold_cuts_flapping_pages():
    res = sweep(range(3), "flapping", lambda h: multiwindow("mw", 0, h), [1, 30])
    assert res[1]["rule_pages"] > 3 * res[30]["rule_pages"]
    assert res[30]["pages"] <= res[30]["rule_pages"]


def test_demo_prints_all_tables(capsys):
    assert main(["demo", "--seeds", "1"]) == 0
    out = capsys.readouterr().out
    for needle in ("## Incidents", "tiny_healthy", "Low-traffic guard", "Flapping", "slow_burn_0.9x"):
        assert needle in out
    assert main(["nope"]) == 2
