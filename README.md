# sre-slo-burn-rate-alerts

![ci](https://github.com/Supp3r-Man/sre-slo-burn-rate-alerts/actions/workflows/ci.yml/badge.svg)

SLO **error-budget math** and the Google SRE Workbook **multi-window multi-burn-rate** alert policy (14.4x over 1h and 5m pages, 6x over 6h and 30m pages, 1x over 3d and 6h tickets), with dedupe/resolve semantics, a seeded incident simulator, two fair baselines, and a **measured** comparison of where the policy is fast, slow, or silent.

> **What is verified, and what is not.** 45 tests pass locally on Python 3.13 (stdlib only; the GitHub Actions workflow on Python 3.11 and 3.13 ran green after the first push). The tests include seeded property tests against trivial reference implementations (window sums, rolling budget, the whole alert state machine) and exact-threshold boundary tests. I broke 11 behaviours on purpose (short window dropped, no dedupe, resolve hold ignored, guard off-by-one, first evaluation late, tolerance flipped, group dedupe off, burn formula, budget-at-detection off by one, retry amplification, start-at-zero): 10 were caught, 1 survived and is an equivalent mutant (starting the loop at 0 only reads negative-wrapped prefix sums, which give a negative total and never fire). **All traffic is synthetic** (Poisson/normal approximations, one sine diurnal curve, fictional service) with 12 seeds per cell, so the numbers show how these policies behave on these shapes, not how they would behave on your production traffic. Nothing here measures time-to-resolve, multiple SLOs, or real alert routing.

## Measured results

`python -m slo_burn demo` (12 seeds, 10 simulated days, SLO 99.9% unless noted, ~200 req/min mean, +-50% diurnal swing). ttd = minutes from incident start to first alert of any severity (0 = inside the first minute); budget% = median % of the 30-day budget burned by then (by incident end if silent); pages/tickets = mean notifications per run. `guard` rows equal `multiwindow` on these shapes and are omitted.

```
scenario           policy         detect%  ttd_min  budget%  pages  tickets
hard_outage        static-2%/10m      100        0      2.8   1.00     0.00
hard_outage        single-window      100        0      2.9   1.00     1.00
hard_outage        multiwindow        100        0      2.9   1.00     1.00
ramp (0->5%, 3h)   static-2%/10m      100       70      1.8   1.00     0.00
ramp               multiwindow        100       81      2.6   1.00     1.00
flapping (5m/30m)  static-2%/10m      100        0      2.8  12.00     0.00
flapping           multiwindow        100        0      2.9   1.00     1.00
retry_storm (3x)   static-2%/10m      100        0      4.0   1.00     0.00
retry_storm        multiwindow        100        0      4.0   1.00     1.00
latency_regression static-2%/10m      100        2      0.1   1.00     0.00
latency_regression multiwindow        100      270      5.4   1.00     0.33
blip (3m @ 20%)    static-2%/10m      100        0      0.7   1.00     0.00
blip               multiwindow          0   silent      1.5   0.00     0.00
slow_burn_2x       static-2%/10m        0   silent     33.2   0.00     0.00
slow_burn_2x       multiwindow        100     2101      9.5   0.00     1.00
slow_burn_0.9x     static / single /
                   multiwindow          0   silent     14.7   0.00     0.00
```

False alerts on traffic that is within the SLO, per 7 post-warm-up days:

```
scenario        static-2%/10m  single-window  multiwindow  multiwindow+guard(min_bad=3)
healthy         0 pages        0              0            0
noisy_but_fine  4.17 pages     0.08 (+0.42 t) 0.08 (+0.33 t)  0.08 (+0.33 t)   # 0.67 blips/day, ~0.6x burn
tiny_healthy    2.58 pages     2.25 (+1.08 t) 2.58 (+1.50 t)  0.08 (+0.67 t)   # 0.3 req/min, ~0.8x burn
```

Low-traffic guard trade-off (0.3 req/min, a 30-day budget of only ~13 failures; min_bad = bad events required in the long window):

```
min_bad  healthy false pages/7d | 10m outage: detect% ttd budget% | 120m outage: detect% ttd budget%
0        2.58                   |             100      2   7.7     |              100      2   7.7
3        0.08                   |              83      3  15.4     |              100      5  19.3
5        0.00                   |              50      6  15.4     |              100     10  34.7
```

Flapping (5 min down, 25 min up, 6h): per-rule fires with resolve hold 1 or 10 min = 13, with hold 30 or 60 = 2; the notified count stays 1 because the slow rule keeps firing and group dedupe absorbs the fast rule's re-fires.

What the numbers say, and what they do not:
- A hard outage at about 200 req/min (100 to 300 across the diurnal swing) paged inside the first minute in all 12 seeds (one minute of failures is 1.7% of an hour's requests, above the 1.44% that 14.4x needs), burning about 3% of the monthly budget.
- **Slow burn is the policy's blind spot.** 2x burn is found only by the 3-day ticket rule after about 35 hours (9.5% of budget gone); 0.9x is never found while burning 14.7% of the month's budget in 5 days. A static threshold finds neither.
- **Moderate burn is slow.** An 8% slow-request ratio on a 99% latency SLO (8x) took 270 minutes under the 6h rule; the fixed 2% threshold caught it in 2 minutes, at the price of 4.17 false pages a week on noisy-but-fine traffic.
- Single-window and multi-window detect identically on every shape here. The short window's real benefit (the alert resets soon after recovery) is not measured by this repo.
- The guard removes about 97% of false pages at 0.3 req/min but a 10-minute outage is missed 17% (min_bad=3) to 50% (min_bad=5) of the time and a real outage is detected later with more budget burned.

## Run

```
python -m slo_burn demo            # the tables above (~20 s); --seeds N to change seeds
python -m pytest                   # 45 tests, ~7 s
```

## Layout

```
slo_burn/slo.py      SLO (availability, latency), Traffic, prefix-sum Stats, burn rate, ErrorBudget
slo_burn/alerts.py   Rule/Policy, evaluate() state machine, notifications() dedupe, 3 policy builders
slo_burn/sim.py      seeded diurnal traffic, 9 incident shapes, 3 profiles, 13 scenarios
slo_burn/measure.py  ttd, budget burned, pages, false pages, aggregation, parameter sweeps
slo_burn/__main__.py demo tables
tests/               slo, alerts (boundaries + reference model), sim, measure
```

Semantics: a rule fires when burn >= threshold on the long AND short window (full windows only, relative tolerance 1e-9 at exact thresholds), fires once per episode, and resolves after the condition is false for `resolve_hold` minutes (default 10). `notifications()` merges rules of the same severity into one page or ticket.

## Known gaps

- Time to resolve and alert flapping after recovery are not measured, so the short window looks free of benefit here.
- Single SLO per run, no multi-service grouping, no alert routing, escalation or silences.
- Traffic is approximated (Poisson/normal), one diurnal curve, errors independent per request; real failures are correlated and heavy-tailed.
- Incident parameters (3 min at 20%, 8% slow ratio, 0.3 req/min) were picked by me; results move with them. The static baseline uses a 2% / 10 min threshold I chose.
- The budget denominator uses nominal volume (base rate x 30 days), not the observed 30-day total.
- The ticket rule for 0.9x slow burn is silent by design; catching it needs a longer window or a budget-remaining alert.
