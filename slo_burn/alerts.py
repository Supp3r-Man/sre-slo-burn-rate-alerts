"""Alert policies (multi-window multi-burn-rate and baselines) with dedupe/resolve semantics."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str          # "page" or "ticket"
    long_min: int
    short_min: int         # None = single-window rule
    burn: float


@dataclass(frozen=True)
class Policy:
    name: str
    rules: tuple
    min_bad: int = 0       # low-traffic guard: need >= min_bad bad events in the long window
    resolve_hold: int = 10  # condition must be false this many consecutive minutes to resolve


@dataclass(frozen=True)
class Event:
    t: int
    rule: str
    severity: str
    kind: str              # "fire" or "resolve"


def _ge(bad, total, burn, eb):
    """True when bad/total >= burn * eb (relative tolerance absorbs float error at exact thresholds)."""
    return total > 0 and bad >= burn * eb * total * (1 - 1e-9)


def evaluate(policy, slo, stats):
    """Run every rule minute by minute. One `fire` per episode (dedupe), `resolve` after the hold."""
    eb, pb, pt = slo.error_budget, stats.pb, stats.pt
    hold = max(1, policy.resolve_hold)
    events = []
    for rule in policy.rules:
        firing, calm = False, 0
        lw, sw = rule.long_min, rule.short_min
        for t in range(lw - 1, len(stats)):
            bl, tl = pb[t + 1] - pb[t + 1 - lw], pt[t + 1] - pt[t + 1 - lw]
            on = _ge(bl, tl, rule.burn, eb) and bl >= policy.min_bad
            if on and sw:
                on = _ge(pb[t + 1] - pb[t + 1 - sw], pt[t + 1] - pt[t + 1 - sw], rule.burn, eb)
            if on:
                calm = 0
                if not firing:
                    firing = True
                    events.append(Event(t, rule.name, rule.severity, "fire"))
            elif firing:
                calm += 1
                if calm >= hold:
                    firing, calm = False, 0
                    events.append(Event(t, rule.name, rule.severity, "resolve"))
    return sorted(events, key=lambda e: (e.t, e.rule))


def notifications(events):
    """Group-level dedupe: a fire notifies only if no other rule of the same severity is firing.

    At the same minute fires are processed before resolves, so a hand-over between rules stays one incident.
    """
    active = {"page": set(), "ticket": set()}
    out = []
    for e in sorted(events, key=lambda e: (e.t, e.kind == "resolve", e.rule)):
        group = active[e.severity]
        if e.kind == "fire":
            if not group:
                out.append(e)
            group.add(e.rule)
        else:
            group.discard(e.rule)
    return out


# Google SRE Workbook, "Alerting on SLOs": 2% of budget in 1h, 5% in 6h, 10% in 3d.
WORKBOOK = (("page-fast", "page", 60, 5, 14.4), ("page-slow", "page", 360, 30, 6.0),
            ("ticket", "ticket", 4320, 360, 1.0))


def multiwindow(name="multiwindow", min_bad=0, resolve_hold=10):
    return Policy(name, tuple(Rule(*r) for r in WORKBOOK), min_bad, resolve_hold)


def single_window(name="single-window", resolve_hold=10):
    """Same long windows and thresholds, no short window: isolates what the short window buys."""
    return Policy(name, tuple(Rule(n, s, lw, None, b) for n, s, lw, _, b in WORKBOOK), 0, resolve_hold)


def static_threshold(slo, ratio=0.02, window=10, name="static-2%/10m"):
    """Classic fixed error-ratio alert, ignoring the SLO target."""
    return Policy(name, (Rule("static", "page", window, None, ratio / slo.error_budget),), 0, 10)
