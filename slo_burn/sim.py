"""Seeded minute-level traffic simulator with diurnal load and incident shapes. All data synthetic."""
import math
import random
from dataclasses import dataclass

from .slo import MIN_PER_DAY, SLO, WINDOW_30D, Traffic

WARMUP = 3 * MIN_PER_DAY      # incidents start after day 3 so every alert window is full
DAYS = 10

AVAIL = SLO("checkout-availability", 0.999)
LATENCY = SLO("checkout-latency-300ms", 0.99, "latency", 300.0)


@dataclass(frozen=True)
class Profile:
    name: str
    base_rpm: float
    amp: float = 0.5           # diurnal amplitude: load swings base*(1 +- amp), peak at 12:00
    err: float = 0.0001        # healthy failure ratio
    slow: float = 0.002        # healthy slow-request ratio
    blip_rate: float = 0.0     # per-minute chance a 3-minute 20% error blip starts


PROFILES = {
    "normal": Profile("normal", 200.0),
    "noisy": Profile("noisy", 200.0, err=0.0003, blip_rate=1 / 2160),
    "tiny": Profile("tiny", 0.3, err=0.0008),
}


@dataclass(frozen=True)
class Shape:
    duration: int
    fn: object                 # (dt_minutes, profile) -> (error_ratio, slow_ratio, traffic_multiplier)


SHAPES = {
    "hard_outage": Shape(120, lambda dt, p: (1.0, p.slow, 1.0)),
    "short_outage": Shape(10, lambda dt, p: (1.0, p.slow, 1.0)),
    "ramp": Shape(360, lambda dt, p: (0.05 * min(dt / 180, 1.0), p.slow, 1.0)),
    "flapping": Shape(360, lambda dt, p: (1.0 if dt % 30 < 5 else p.err, p.slow, 1.0)),
    "slow_burn_2x": Shape(5 * MIN_PER_DAY, lambda dt, p: (0.002, p.slow, 1.0)),
    "slow_burn_0.9x": Shape(5 * MIN_PER_DAY, lambda dt, p: (0.0009, p.slow, 1.0)),
    "blip": Shape(3, lambda dt, p: (0.2, p.slow, 1.0)),
    "retry_storm": Shape(120, lambda dt, p: (0.5, p.slow, 3.0)),
    "latency_regression": Shape(360, lambda dt, p: (p.err, 0.08, 1.0)),
}


def poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam < 30:
        limit, k, prod = math.exp(-lam), 0, 1.0
        while True:
            prod *= rng.random()
            if prod <= limit:
                return k
            k += 1
    return max(0, round(rng.gauss(lam, lam ** 0.5)))


def binomial(rng, n, p):
    """Poisson/normal approximation of Binomial(n, p); exact at p<=0 and p>=1, always in [0, n]."""
    if n <= 0 or p <= 0:
        return 0
    if p >= 1:
        return n
    if p > 0.5:
        return n - binomial(rng, n, 1 - p)
    lam = n * p
    if lam < 30:
        return min(n, poisson(rng, lam))
    return min(n, max(0, round(rng.gauss(lam, (lam * (1 - p)) ** 0.5))))


@dataclass
class Scenario:
    name: str
    slo: SLO
    traffic: Traffic
    start: int                 # incident start minute, None for healthy scenarios
    end: int
    budget_bad: float          # bad events that exhaust the 30-day budget at nominal volume


def generate(profile, shape, seed, slo=AVAIL, days=DAYS, name=None):
    rng = random.Random(seed)
    sh = SHAPES[shape] if shape else None
    start = WARMUP + rng.randrange(MIN_PER_DAY) if sh else None
    end = start + sh.duration if sh else None
    total, errors, slow = [], [], []
    blip_left = 0
    for m in range(days * MIN_PER_DAY):
        lam = profile.base_rpm * (1 + profile.amp * math.sin(2 * math.pi * (m % MIN_PER_DAY - 360) / MIN_PER_DAY))
        err, slw, mult = profile.err, profile.slow, 1.0
        if sh and start <= m < end:
            err, slw, mult = sh.fn(m - start, profile)
        if blip_left == 0 and profile.blip_rate and rng.random() < profile.blip_rate:
            blip_left = 3
        if blip_left:
            err, blip_left = max(err, 0.2), blip_left - 1
        t = poisson(rng, lam * mult)
        e = binomial(rng, t, err)
        s = binomial(rng, t - e, slw)
        total.append(t), errors.append(e), slow.append(s)
    budget = slo.error_budget * profile.base_rpm * WINDOW_30D
    return Scenario(name or shape or profile.name, slo, Traffic(total, errors, slow), start, end, budget)


# (scenario name, profile, shape, slo)
SCENARIOS = [
    ("hard_outage", "normal", "hard_outage", AVAIL),
    ("ramp", "normal", "ramp", AVAIL),
    ("flapping", "normal", "flapping", AVAIL),
    ("slow_burn_2x", "normal", "slow_burn_2x", AVAIL),
    ("slow_burn_0.9x", "normal", "slow_burn_0.9x", AVAIL),
    ("blip", "normal", "blip", AVAIL),
    ("retry_storm", "normal", "retry_storm", AVAIL),
    ("latency_regression", "normal", "latency_regression", LATENCY),
    ("healthy", "normal", None, AVAIL),
    ("noisy_but_fine", "noisy", None, AVAIL),
    ("tiny_healthy", "tiny", None, AVAIL),
    ("tiny_outage_120m", "tiny", "hard_outage", AVAIL),
    ("tiny_outage_10m", "tiny", "short_outage", AVAIL),
]


def build(name, seed):
    for n, prof, shape, slo in SCENARIOS:
        if n == name:
            return generate(PROFILES[prof], shape, seed, slo, name=n)
    raise KeyError(name)
