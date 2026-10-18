"""python -m slo_burn demo [--seeds N]: print the measured comparison tables."""
import sys

from .alerts import multiwindow
from .measure import study, sweep

INCIDENTS = ["hard_outage", "ramp", "flapping", "retry_storm", "latency_regression", "blip",
             "slow_burn_2x", "slow_burn_0.9x"]
QUIET = ["healthy", "noisy_but_fine", "tiny_healthy"]


def fmt(v, spec=".0f"):
    return "silent" if v is None else format(v, spec)


def render(res, seeds):
    L = [f"# {seeds} seeds per cell; 10 simulated days; incident starts after day 3 (synthetic data)", "",
         "## Incidents (ttd = minutes to first alert, any severity; budget% = % of the 30-day budget burned",
         "## by then, or by incident end if silent; pages/tickets = mean fires per run from incident start)",
         f"{'scenario':<19}{'policy':<19}{'detect%':>8}{'ttd_min':>9}{'page1st%':>9}{'budget%':>9}"
         f"{'pages':>7}{'tickets':>8}{'preFP':>7}"]
    for s in INCIDENTS:
        for p, a in res[s].items():
            L.append(f"{s:<19}{p:<19}{a['detect_pct']:>8.0f}{fmt(a['ttd']):>9}{a['page_first_pct']:>9.0f}"
                     f"{a['budget_pct']:>9.1f}{a['pages']:>7.2f}{a['tickets']:>8.2f}{a['false_pages']:>7.2f}")
    L += ["", "## Healthy / noisy-but-within-SLO / very low traffic: false alerts per 7 post-warm-up days",
          f"{'scenario':<19}{'policy':<19}{'false_pages':>12}{'false_tickets':>14}"]
    for s in QUIET:
        for p, a in res[s].items():
            L.append(f"{s:<19}{p:<19}{a['false_pages']:>12.2f}{a['false_tickets']:>14.2f}")
    return L


def guard_table(seeds):
    cols = {}
    for k in (0, 2, 3, 5):
        mk = lambda v: multiwindow("mw", v)
        h = sweep(range(seeds), "tiny_healthy", mk, [k])[k]
        s = sweep(range(seeds), "tiny_outage_10m", mk, [k])[k]
        o = sweep(range(seeds), "tiny_outage_120m", mk, [k])[k]
        cols[k] = (h, s, o)
    L = ["", "## Low-traffic guard (0.3 req/min; min_bad = bad events needed in the long window)",
         f"{'min_bad':<8}{'healthyFP/7d':>13} | {'10m outage:':<12}{'detect%':>8}{'ttd':>6}{'budget%':>9}"
         f" | {'120m outage:':<13}{'detect%':>8}{'ttd':>6}{'budget%':>9}"]
    for k, (h, s, o) in cols.items():
        L.append(f"{k:<8}{h['false_pages']:>13.2f} | {'':<12}{s['detect_pct']:>8.0f}{fmt(s['ttd']):>6}"
                 f"{s['budget_pct']:>9.1f} | {'':<13}{o['detect_pct']:>8.0f}{fmt(o['ttd']):>6}{o['budget_pct']:>9.1f}")
    return L


def hold_table(seeds):
    res = sweep(range(seeds), "flapping", lambda h: multiwindow("mw", 0, h), [1, 10, 30, 60])
    L = ["", "## Flapping (5 min down / 25 min up for 6h): resolve hold vs pages (multiwindow)",
         f"{'hold_min':<10}{'rule_fires':>11}{'notified':>9}{'ttd_min':>9}"]
    for h, a in res.items():
        L.append(f"{h:<10}{a['rule_pages']:>11.2f}{a['pages']:>9.2f}{fmt(a['ttd']):>9}")
    return L


def main(argv):
    if not argv or argv[0] != "demo":
        print("usage: python -m slo_burn demo [--seeds N]")
        return 2
    seeds = int(argv[argv.index("--seeds") + 1]) if "--seeds" in argv else 12
    res = study(range(seeds))
    print("\n".join(render(res, seeds) + guard_table(seeds) + hold_table(seeds)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
