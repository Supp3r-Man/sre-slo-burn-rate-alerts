import random

import pytest

from slo_burn.alerts import (Event, Policy, Rule, evaluate, multiwindow, notifications, single_window,
                             static_threshold)
from slo_burn.slo import SLO, Stats

A = SLO("a", 0.999)


def run(policy, errors, total=1000, slo=A):
    tot = total if isinstance(total, list) else [total] * len(errors)
    return evaluate(policy, slo, Stats(tot, errors))


def boundary_errors(long_delta=0, short_delta=0):
    """20 min at 1000/min. 14.4x needs 288 errors in 20m and 72 in the last 5m: exactly at both limits."""
    early = [14] * 15
    early[0] += 6                                  # 216 in the first 15 minutes
    late = [14, 14, 14, 15, 15]                    # 72 in the last 5
    late[-1] += short_delta
    early[1] += long_delta + (-short_delta)         # keep long total fixed unless long_delta given
    return early + late


P = Policy("p", (Rule("r", "page", 20, 5, 14.4),), 0, 10)


def test_exact_threshold_on_both_windows_fires():
    ev = run(P, boundary_errors())
    assert [(e.t, e.kind) for e in ev] == [(19, "fire")]
    assert len(run(P, boundary_errors(long_delta=1, short_delta=1))) == 1     # one above both also fires


def test_one_error_below_long_window_threshold_does_not_fire():
    assert run(P, boundary_errors(long_delta=-1)) == []


def test_one_error_below_short_window_threshold_does_not_fire():
    assert run(P, boundary_errors(short_delta=-1)) == []   # long window stays at exactly 288


def test_long_high_but_short_low_is_an_and_not_an_or():
    errors = [100] * 15 + [0] * 5                  # long = 1500/20000 = 75x, short = 0
    assert run(P, errors) == []


def test_short_high_but_long_low_does_not_fire():
    assert run(P, [0] * 15 + [30] * 5) == []       # short 150/5000 = 30x but long 150/20000 = 7.5x


def test_sustained_condition_fires_once():
    ev = run(Policy("p", (Rule("r", "page", 5, 2, 14.4),), 0, 10), [1000] * 200)
    assert [e.kind for e in ev] == ["fire"]


def test_resolve_after_hold_minutes_of_calm():
    rule = (Rule("r", "page", 5, None, 14.4),)
    errors = [1000] * 10 + [0] * 30                # window of 5 stays hot through t=13, calm from t=14
    assert [(e.t, e.kind) for e in run(Policy("p", rule, 0, 3), errors)] == [(4, "fire"), (16, "resolve")]
    assert [(e.t, e.kind) for e in run(Policy("p", rule, 0, 1), errors)] == [(4, "fire"), (14, "resolve")]
    assert [e.t for e in run(Policy("p", rule, 0, 0), errors)] == [4, 14]   # hold 0 behaves like 1


def test_refire_inside_hold_is_deduped_but_after_hold_pages_again():
    errors = [1000, 1000, 0, 0] * 4
    rule = (Rule("r", "page", 1, None, 14.4),)
    assert [e.kind for e in run(Policy("p", rule, 0, 3), errors)] == ["fire"]
    assert [e.kind for e in run(Policy("p", rule, 0, 1), errors)].count("fire") == 4


def test_no_events_before_long_window_is_full():
    ev = run(Policy("p", (Rule("r", "page", 10, None, 1.0),), 0, 5), [1000] * 30)
    assert ev[0].t == 9


def test_partial_window_at_start_is_not_treated_as_a_full_window():
    pol = Policy("p", (Rule("r", "page", 10, None, 14.4),), 0, 5)
    assert run(pol, [100] + [0] * 29) == []        # minute 0 alone is 100x, but the first full window is 1% = 10x
    assert [e.t for e in run(pol, [100] * 3 + [0] * 27)][:1] == [9]    # 300/10000 = 3% >= 1.44% at the first full window


def test_zero_traffic_never_fires():
    assert run(P, [0] * 50, total=0) == []


def test_low_traffic_guard_boundary_on_min_bad():
    errors, total = [0] * 18 + [1, 1], [1] * 20    # 2 failures of 20 requests: 100x burn
    rule = (Rule("r", "page", 20, 5, 14.4),)
    assert len(run(Policy("p", rule, 0), errors, total)) == 1
    assert len(run(Policy("p", rule, 2), errors, total)) == 1     # >= min_bad
    assert run(Policy("p", rule, 3), errors, total) == []


def test_static_threshold_converts_ratio_and_has_exact_boundary():
    pol = static_threshold(A, 0.02, 10)
    assert pol.rules[0].burn == pytest.approx(20.0) and pol.rules[0].short_min is None
    assert len(run(pol, [0] * 9 + [200])) == 1     # 200 / 10000 = exactly 2%
    assert run(pol, [0] * 9 + [199]) == []


def test_workbook_policy_parameters_and_single_window_ablation():
    mw = multiwindow()
    assert [(r.severity, r.long_min, r.short_min, r.burn) for r in mw.rules] == [
        ("page", 60, 5, 14.4), ("page", 360, 30, 6.0), ("ticket", 4320, 360, 1.0)]
    sw = single_window()
    assert [(r.long_min, r.burn, r.short_min) for r in sw.rules] == [(60, 14.4, None), (360, 6.0, None), (4320, 1.0, None)]


def test_group_level_notification_dedupe():
    ev = [Event(1, "a", "page", "fire"), Event(2, "b", "page", "fire"), Event(3, "t", "ticket", "fire"),
          Event(5, "a", "page", "resolve"), Event(6, "b", "page", "resolve"), Event(7, "a", "page", "fire")]
    assert [(e.t, e.rule) for e in notifications(ev)] == [(1, "a"), (3, "t"), (7, "a")]
    handover = [Event(1, "a", "page", "fire"), Event(5, "a", "page", "resolve"), Event(5, "b", "page", "fire")]
    assert [e.t for e in notifications(handover)] == [1]


def reference(policy, eb, total, bad):
    out = []
    for rule in policy.rules:
        firing, calm = False, 0
        for t in range(len(total)):
            if t + 1 < rule.long_min:
                continue

            def hot(w):
                n, b = sum(total[t + 1 - w:t + 1]), sum(bad[t + 1 - w:t + 1])
                return n > 0 and b / n / eb >= rule.burn - 1e-9

            on = hot(rule.long_min) and sum(bad[t + 1 - rule.long_min:t + 1]) >= policy.min_bad
            on = on and (not rule.short_min or hot(rule.short_min))
            if on:
                calm = 0
                if not firing:
                    firing = True
                    out.append((t, rule.name, "fire"))
            elif firing:
                calm += 1
                if calm >= max(1, policy.resolve_hold):
                    firing, calm = False, 0
                    out.append((t, rule.name, "resolve"))
    return sorted(out, key=lambda x: (x[0], x[1]))


def test_evaluate_matches_trivial_reference_on_random_traffic():
    total_events = 0
    for seed in range(8):
        total_events += _compare_with_reference(seed)
    assert total_events > 20                              # the comparison saw real alert activity


def _compare_with_reference(seed):
    rng = random.Random(seed)
    n = 500
    total = [rng.randrange(0, 60) for _ in range(n)]
    bad, hot = [], 0
    for t in total:
        hot = hot - 1 if hot else (rng.randrange(5, 40) if rng.random() < 0.01 else 0)
        bad.append(min(t, sum(rng.random() < (0.6 if hot else 0.01) for _ in range(t))))
    pol = Policy("p", (Rule("fast", "page", 30, 5, 14.4), Rule("slow", "page", 90, 15, 6.0),
                       Rule("tick", "ticket", 200, 40, 1.0)), min_bad=seed % 3, resolve_hold=1 + seed % 4)
    got = [(e.t, e.rule, e.kind) for e in evaluate(pol, A, Stats(total, bad))]
    assert got == reference(pol, A.error_budget, total, bad)
    return len(got)
