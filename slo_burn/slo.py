"""SLI/SLO definitions, rolling error budget and burn rate over per-minute request counts."""
from dataclasses import dataclass

MIN_PER_DAY = 1440
WINDOW_30D = 30 * MIN_PER_DAY


@dataclass
class Traffic:
    """Per-minute counts. `errors` (failed) and `slow` (over latency threshold) are disjoint."""
    total: list
    errors: list
    slow: list

    def __post_init__(self):
        if not (len(self.total) == len(self.errors) == len(self.slow)):
            raise ValueError("series must have equal length")
        for t, e, s in zip(self.total, self.errors, self.slow):
            if e < 0 or s < 0 or e + s > t:
                raise ValueError("need 0 <= errors + slow <= total per minute")

    def __len__(self):
        return len(self.total)


@dataclass(frozen=True)
class SLO:
    name: str
    objective: float            # e.g. 0.999
    kind: str = "availability"  # "availability": bad = failed; "latency": bad = slower than threshold
    latency_ms: float = None

    def __post_init__(self):
        if not 0 < self.objective < 1:
            raise ValueError("objective must be strictly between 0 and 1")
        if self.kind not in ("availability", "latency"):
            raise ValueError("kind must be availability or latency")
        if self.kind == "latency" and not self.latency_ms:
            raise ValueError("latency SLO needs latency_ms")

    @property
    def error_budget(self):
        return round(1 - self.objective, 12)

    def bad(self, traffic):
        return traffic.errors if self.kind == "availability" else traffic.slow

    def sli(self, traffic, lo, hi):
        """Good-event ratio over minutes [lo, hi); 1.0 when there was no traffic."""
        tot = sum(traffic.total[lo:hi])
        return 1.0 if tot == 0 else 1 - sum(self.bad(traffic)[lo:hi]) / tot


class Stats:
    """Prefix sums over (bad, total) so any trailing window is O(1)."""

    def __init__(self, total, bad):
        self.pt, self.pb = [0], [0]
        for t, b in zip(total, bad):
            self.pt.append(self.pt[-1] + t)
            self.pb.append(self.pb[-1] + b)

    def __len__(self):
        return len(self.pt) - 1

    def window(self, t, w):
        """(bad, total) over minutes t-w+1 .. t inclusive; truncated at the series start."""
        lo = max(0, t + 1 - w)
        return self.pb[t + 1] - self.pb[lo], self.pt[t + 1] - self.pt[lo]


def burn_rate(bad, total, budget):
    """Error ratio divided by the error budget fraction; 0 when there was no traffic."""
    return 0.0 if total == 0 else (bad / total) / budget


def threshold_for(budget_fraction, window_min, period_min=WINDOW_30D):
    """Burn-rate threshold that consumes `budget_fraction` of the period budget in `window_min`."""
    return budget_fraction * period_min / window_min


def hours_to_exhaust(burn, period_min=WINDOW_30D):
    return float("inf") if burn <= 0 else period_min / burn / 60


class ErrorBudget:
    def __init__(self, slo, traffic):
        self.slo = slo
        self.stats = Stats(traffic.total, slo.bad(traffic))

    def burn_rate(self, t, window):
        bad, total = self.stats.window(t, window)
        return burn_rate(bad, total, self.slo.error_budget)

    def consumed(self, t, window=WINDOW_30D):
        """Fraction of the rolling-window budget used by minute t (1.0 = exhausted, >1 = overspent)."""
        bad, total = self.stats.window(t, window)
        return 0.0 if total == 0 else bad / (self.slo.error_budget * total)

    def remaining(self, t, window=WINDOW_30D):
        return 1.0 - self.consumed(t, window)
