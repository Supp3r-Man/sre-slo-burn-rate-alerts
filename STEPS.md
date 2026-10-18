# STEPS

**Part A** is what I did, in order. **Part B** is how you run and extend it.

---

## Part A: steps taken

1. **Fixed the question first:** not "implement burn-rate alerts" but "where is the Workbook policy fast, slow or silent, against fair baselines". That decided the shape of the repo: a simulator, three policies, and a measurement layer.
2. **Wrote the math** (`slo.py`): SLO with availability and latency SLIs over per-minute counts, prefix sums so any trailing window is O(1), burn rate = error ratio / budget, rolling 30-day budget. A test derives 14.4 / 6 / 1 from "2% in 1h, 5% in 6h, 10% in 3d" so the numbers are not magic.
3. **Wrote the alert state machine** (`alerts.py`): fire when long AND short window are at or above the burn threshold, one fire per episode, resolve after a hold of calm minutes, no evaluation until the long window is full. Added a group-level `notifications()` dedupe after the first demo run showed one outage paging twice (fast and slow rule).
4. **Chose fair baselines:** a static 2% / 10 min error-ratio alert, and a single-window policy with the same long windows and thresholds but no short window (isolates what the short window buys).
5. **Wrote the simulator** (`sim.py`): seeded minute-level Poisson/normal traffic with a diurnal sine, nine incident shapes, a noisy-but-within-SLO profile, a 0.3 req/min profile. Incidents start after day 3 so every window is full.
6. **Wrote the measurement layer** (`measure.py`): time to detect, % of the 30-day budget burned by then, pages, tickets, false pages, medians over 12 seeds, plus sweeps for the guard and the resolve hold.
7. **First demo run** (20 s) before writing tests, to see whether the story was real. It was, with surprises: single-window detected exactly like multi-window, and the static threshold beat the policy on a moderate latency regression.
8. **Wrote 45 tests** in four files, including exact-threshold boundaries (288 errors in 20 minutes at 1000/min is exactly 14.4x), a naive reference implementation of the whole state machine compared on 8 random seeds, and measurement tests on the real scenarios.
9. **Mutation-checked:** 11 deliberate breaks on a fresh copy, one at a time, pattern-missed reporting. First run: 1 survivor (start-at-0). I replaced it with a realistic off-by-one (killed) and added a partial-window test; the original start-at-0 mutant stays alive because it is equivalent (negative-wrapped prefix sums give a negative total, which never fires).
10. **Wrote README and this file** from the real final demo output, then committed locally. Not pushed; CI has not run.

Problems and choices along the way:
- Per-rule pages overstated pages (2 per outage); fixed with group-level dedupe, but both counts are reported for flapping.
- A first boundary test used 14x and passed for the wrong reason (14x is below 14.4x anyway); changed to 30x.
- Test count was 61 after parametrising; folded seed loops into single tests to land at 45.
- The static baseline needed a choice (2% / 10 min); a different choice changes its false pages and speed.

---

## Part B: steps for you

1. Needs Python 3.11 or newer. No packages (pytest only for tests).
2. From the repo folder: `python -m slo_burn demo` (about 20 s). `--seeds 4` for a quick run.
3. Tests: `python -m pip install pytest`, then `python -m pytest`.
4. To try your own SLO: build `SLO("mine", 0.9995)`, a `Traffic(total, errors, slow)` from your per-minute counts, then `evaluate(multiwindow(), slo, Stats(traffic.total, slo.bad(traffic)))`.
5. To add an incident shape, add an entry to `SHAPES` in `slo_burn/sim.py` and a row to `SCENARIOS`.
6. After pushing, check the CI run on Python 3.11 and 3.13 before claiming anything about CI.
