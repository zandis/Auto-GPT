"""Recall-certificate statistics (SPEC_v4 §6.14 SAFE-2/3; review round 3, R3-03).

Two kinds of bound on a binomial rate p, the share of excluded patients who were in fact candidates (the elusion
rate of one stratum):

* ``cp_upper``: one-sided Clopper–Pearson upper bound. Valid for **one** look at a fixed sample size.
* ``ConfidenceSequence``: an anytime-valid upper confidence sequence (Waudby-Smith & Ramdas, "Estimating means of
  bounded random variables by betting", JRSS-B 2024). It is valid simultaneously at every sample size, so the recall
  ledger may add samples month after month, print a bound every month and demote criteria on any month, without the
  optional-stopping error that repeated Clopper–Pearson looks would commit.

The sequence bets against each candidate rate m: capital K_t(m) = prod_i (1 + lambda_i (m - X_i)) with a predictable
lambda_i >= 0. If the true rate is below m the capital grows; by Ville's inequality, capital at the true rate ever
reaching 1/alpha has probability <= alpha. The upper bound at time t is the largest m whose capital has never reached
1/alpha.

``certificate`` combines per-stratum bounds (Bonferroni over strata) with a known-positive recall lower bound.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

GRID = 2001  # candidate rates m in [0, 1]


def _binom_cdf(x: int, n: int, p: float) -> float:
    return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(x + 1))


def cp_upper(x: int, n: int, alpha: float = 0.05) -> float:
    """One-sided Clopper–Pearson upper bound for x events in n draws."""
    if n <= 0 or x >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def cp_lower(successes: int, n: int, alpha: float = 0.05) -> float:
    """One-sided Clopper–Pearson lower bound for a proportion (e.g. recall on n known positives)."""
    if n <= 0 or successes <= 0:
        return 0.0
    return 1.0 - cp_upper(n - successes, n, alpha)


@dataclass
class ConfidenceSequence:
    """Anytime-valid upper confidence sequence for a Bernoulli rate, updated one observation at a time.

    Each observation is 1 (an excluded patient who was in fact a candidate) or 0. State is a few floats per grid
    point, so it can be stored in the recall ledger and resumed. ``upper`` never increases (running intersection)."""

    alpha: float = 0.05
    log_capital: list[float] = field(default_factory=lambda: [0.0] * GRID)
    rejected: list[bool] = field(default_factory=lambda: [False] * GRID)
    n: int = 0
    total: float = 0.0
    sq_dev: float = 0.25  # running variance estimate, starts at the Bernoulli maximum
    upper: float = 1.0

    @staticmethod
    def grid(i: int) -> float:
        return i / (GRID - 1)

    def _lambda(self, m: float) -> float:
        # predictable plug-in bet (WSR 2024, eq. 26), truncated to keep 1 + lambda (m - x) >= 0.5
        t = self.n + 1
        var = (0.25 + self.sq_dev) / t
        lam = math.sqrt(2 * math.log(1 / self.alpha) / (var * t * math.log(t + 1)))
        cap = 0.5 / (1 - m) if m < 1 else math.inf  # keeps 1 + lambda (m - x) >= 0.5 when x = 1
        return min(lam, cap)

    def update(self, x: int) -> float:
        if x not in (0, 1):
            raise ValueError("observations are 0 or 1")
        threshold = math.log(1 / self.alpha)
        for i in range(GRID):
            if self.rejected[i]:
                continue
            m = self.grid(i)
            lam = self._lambda(m)
            self.log_capital[i] += math.log1p(lam * (m - x))
            if self.log_capital[i] >= threshold:
                self.rejected[i] = True
        prev_mean = self.total / self.n if self.n else 0.5
        self.n += 1
        self.total += x
        self.sq_dev += (x - prev_mean) ** 2
        alive = [i for i in range(GRID) if not self.rejected[i]]
        bound = self.grid(max(alive)) if alive else 0.0
        self.upper = min(self.upper, bound)
        return self.upper

    def extend(self, xs: Sequence[int]) -> float:
        for x in xs:
            self.update(x)
        return self.upper


@dataclass(frozen=True)
class Stratum:
    stage: str
    excluded: int  # patients excluded at this stage for this study (population size)
    sampled: int  # audit samples in the ledger (pooled per canonical criterion)
    found: int  # samples that were in fact candidates


@dataclass(frozen=True)
class Certificate:
    per_stratum_upper: dict[str, float]
    missed_point: float
    missed_upper: float
    per_1000_upper: float
    recall_lower: float | None
    known_positives: int
    method: str


def certificate(
    strata: Sequence[Stratum],
    known_positive: tuple[int, int] | None = None,
    alpha: float = 0.05,
    anytime: bool = True,
    observations: Mapping[str, Sequence[int]] | None = None,
) -> Certificate:
    """Combine strata into a certificate. With ``anytime`` and the per-stratum 0/1 observation sequences, each stratum
    bound is a confidence sequence at alpha/K (Bonferroni over K strata); otherwise Clopper–Pearson at alpha/K, which
    is valid only for a single, pre-planned look. ``known_positive`` is (r, missed) for the recall lower bound."""
    k = max(1, len(strata))
    per: dict[str, float] = {}
    point = upper = 0.0
    for s in strata:
        if anytime:
            if observations is None or s.stage not in observations:
                raise ValueError(f"anytime bound needs the observation sequence of stratum {s.stage}")
            obs = observations[s.stage]
            if len(obs) != s.sampled or sum(obs) != s.found:
                raise ValueError(f"observations of {s.stage} do not match the stratum counts")
            u = ConfidenceSequence(alpha=alpha / k).extend(obs)
        else:
            u = cp_upper(s.found, s.sampled, alpha / k)
        per[s.stage] = u
        point += s.excluded * (s.found / s.sampled if s.sampled else 0.0)
        upper += s.excluded * u
    excluded = sum(s.excluded for s in strata)
    recall = None
    r = 0
    if known_positive is not None:
        r, missed = known_positive
        recall = cp_lower(r - missed, r, alpha)
    return Certificate(
        per_stratum_upper=per,
        missed_point=point,
        missed_upper=upper,
        per_1000_upper=1000 * upper / excluded if excluded else 0.0,
        recall_lower=recall,
        known_positives=r,
        method=("confidence sequence (WSR 2024 betting)" if anytime else "Clopper–Pearson")
        + f", alpha {alpha} split over {k} strata (Bonferroni)",
    )
