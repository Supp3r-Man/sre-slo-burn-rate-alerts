"""Run policies over scenarios and measure detection time, budget burned, pages and false pages."""
from dataclasses import dataclass
from statistics import median

from .alerts import evaluate, multiwindow, notifications, single_window, static_threshold
from .sim import AVAIL, SCENARIOS, WARMUP, build
from .slo import Stats


@dataclass
class Run:
    detected: bool
    ttd: int               # minutes from incident start to first alert (None if silent)
    first_severity: str
    budget_pct: float      # % of 30-day budget burned by detection (or by incident end if silent)
    pages: int             # page fires at or after incident start
    tickets: int
    pre_pages: int         # page fires after warm-up but before the incident (false pages)
    pre_tickets: int
    rule_pages: int        # page fires per rule, before group-level dedupe (from incident start)


def active_at(events, t):
    """Rules whose last event strictly before t was a fire (still firing at t)."""
    last = {}
    for e in events:
        if e.t < t:
            last[e.rule] = e
    return [e for e in last.values() if e.kind == "fire"]


def measure(scn, events):
    fires = [e for e in notifications(events) if e.t >= WARMUP]
    pages = lambda es: sum(e.severity == "page" for e in es)
    rule_pages = lambda lo: sum(e.kind == "fire" and e.severity == "page" and e.t >= lo for e in events)
    if scn.start is None:
        return Run(False, None, None, 0.0, 0, 0, pages(fires), len(fires) - pages(fires), rule_pages(WARMUP))
    pre = [e for e in fires if e.t < scn.start]
    post = [e for e in fires if e.t >= scn.start]
    bad = scn.slo.bad(scn.traffic)
    carried = active_at(events, scn.start)
    first_t, sev = None, None
    if carried:
        first_t, sev = scn.start, carried[0].severity
    if post and (first_t is None or post[0].t < first_t):
        first_t, sev = post[0].t, post[0].severity
    upto = first_t + 1 if first_t is not None else scn.end
    pct = 100 * sum(bad[scn.start:upto]) / scn.budget_bad
    return Run(first_t is not None, None if first_t is None else first_t - scn.start, sev, pct,
               pages(post), len(post) - pages(post), pages(pre), len(pre) - pages(pre), rule_pages(scn.start))


def policies(slo, min_bad=3, hold=10):
    return [static_threshold(slo), single_window(resolve_hold=hold), multiwindow(resolve_hold=hold),
            multiwindow("multiwindow+guard", min_bad, hold)]


def run_scenario(scn, pols):
    stats = Stats(scn.traffic.total, scn.slo.bad(scn.traffic))
    return {p.name: measure(scn, evaluate(p, scn.slo, stats)) for p in pols}


def aggregate(runs):
    det = [r for r in runs if r.detected]
    n = len(runs)
    return {
        "detect_pct": 100 * len(det) / n,
        "ttd": median(r.ttd for r in det) if det else None,
        "budget_pct": median(r.budget_pct for r in runs),
        "pages": sum(r.pages for r in runs) / n,
        "tickets": sum(r.tickets for r in runs) / n,
        "rule_pages": sum(r.rule_pages for r in runs) / n,
        "false_pages": sum(r.pre_pages for r in runs) / n,
        "false_tickets": sum(r.pre_tickets for r in runs) / n,
        "page_first_pct": 100 * sum(r.first_severity == "page" for r in det) / n,
    }


def study(seeds, names=None, pols_for=None, min_bad=3, hold=10):
    """{scenario: {policy: aggregate}} over `seeds` (an iterable of ints)."""
    out = {}
    for name, _, _, slo in SCENARIOS:
        if names and name not in names:
            continue
        per = {}
        for seed in seeds:
            for pn, r in run_scenario(build(name, seed), (pols_for or policies)(slo, min_bad, hold)).items():
                per.setdefault(pn, []).append(r)
        out[name] = {pn: aggregate(rs) for pn, rs in per.items()}
    return out


def sweep(seeds, scenario, make_policy, values):
    """Aggregate for one scenario while varying one policy parameter; {value: aggregate}."""
    out = {}
    for v in values:
        pol = make_policy(v)
        out[v] = aggregate([run_scenario(build(scenario, s), [pol])[pol.name] for s in seeds])
    return out
