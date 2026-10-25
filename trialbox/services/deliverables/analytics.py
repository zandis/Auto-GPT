"""Exact DL-1 quantities from one cascade run (spec v4 §12.4 F-T5 … F-T9, F-T16 … F-T18; §10.3; CAS-8; RPT-21).

Every view (sequential, marginal, leave-one-out, tiers, unknown shares) derives from **one state matrix per run**
(RPT-21): the cascade's per-patient outcome of every criterion. These numbers are exact and D3 until
:mod:`deliverables.pack` releases them through a disclosure profile.

Semantics follow the cascade: a structured inclusion passes on ``pass``; ``unknown`` does not count as eligible and
is reported in the ``n_unknown_*`` columns; an unknown exclusion does not exclude (v1, CAS-19).
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from matching.cascade.engine import UNKNOWN_KEPT, CascadeResult
from matching.cascade.model import TIERS, PatientTrace

#: §10.3: w = P(potential resolves eligible), prior Beta(2, 3) until ≥ 30 are resolved (mean 0.4)
POTENTIAL_PRIOR = (2.0, 3.0)
Z95 = 1.959964


@dataclass
class StateMatrix:
    """pid × criterion → status ("pass" | "fail" | "unknown:data_gap" | "unknown:uncertain" | "pending_human" | "")."""

    pids: list[str]
    criteria: list[str]
    stage_of: dict[str, str]
    cells: dict[tuple[str, str], str]
    traces: dict[str, PatientTrace]

    def get(self, pid: str, cid: str) -> str:
        return self.cells.get((pid, cid), "")


def state_matrix(res: CascadeResult) -> StateMatrix:
    order = [*res.applied, *res.note_criteria, *res.human_criteria]
    stage = {c: "S1" for c in res.applied} | {c: "S2–S4" for c in res.note_criteria}
    stage |= {c: "S5" for c in res.human_criteria}
    cells: dict[tuple[str, str], str] = {}
    pids = sorted(t.pid for t in res.in_scope())
    for pid in pids:
        t = res.traces[pid]
        for cid in order:
            o = t.outcomes.get(cid)
            if o is None:
                continue
            if o.status == "unknown":
                cells[(pid, cid)] = f"unknown:{o.unknown_kind or 'uncertain'}"
            elif o.status == "pass" and o.reason == UNKNOWN_KEPT:
                cells[(pid, cid)] = "pass:unknown_kept"
            else:
                cells[(pid, cid)] = o.status
    return StateMatrix(pids, order, stage, cells, {p: res.traces[p] for p in pids})


def _passes(cell: str) -> bool:
    return cell.startswith("pass")


@dataclass
class AttritionRow:
    step: int
    criterion_id: str
    label: str
    stage: str
    n_remaining: int
    n_excluded: int
    n_prev: int
    n_unknown_data_gap: int
    n_unknown_uncertain: int
    applied: bool


def sequential(sm: StateMatrix, res: CascadeResult, labels: dict[str, str]) -> list[AttritionRow]:
    """F-T5: structured criteria in protocol order (S1), then note criteria (S2–S4); human criteria are listed but not
    applied (S5). A patient remains after step k when every applied step up to k passes."""
    rows = [AttritionRow(0, "", "Population of scope (S0)", "S0", len(sm.pids), 0, len(sm.pids), 0, 0, True)]
    alive = list(sm.pids)
    for i, cid in enumerate(sm.criteria, start=1):
        applied = cid not in res.human_criteria
        cells = [sm.get(p, cid) for p in alive]
        gap = sum(1 for c in cells if c in ("unknown:data_gap", "pass:unknown_kept"))
        unc = sum(1 for c in cells if c == "unknown:uncertain")
        if not applied:
            rows.append(
                AttritionRow(i, cid, labels.get(cid, cid), sm.stage_of[cid], len(alive), 0, len(alive), 0, 0, False)
            )
            continue
        if cid in res.applied:
            keep = [p for p in alive if _passes(sm.get(p, cid))]
        else:  # note criteria: only a fail removes (unknowns stay as potential)
            keep = [p for p in alive if sm.get(p, cid) != "fail"]
        rows.append(
            AttritionRow(
                i,
                cid,
                labels.get(cid, cid),
                sm.stage_of[cid],
                len(keep),
                len(alive) - len(keep),
                len(alive),
                gap,
                unc,
                True,
            )
        )
        alive = keep
    return rows


def final_pool(sm: StateMatrix, res: CascadeResult, skip: str | None = None) -> list[str]:
    """Patients passing every applied criterion (structured strictly, note criteria not failing), optionally
    leaving one criterion out (F-T7)."""
    out = []
    for p in sm.pids:
        ok = True
        for cid in [*res.applied, *res.note_criteria]:
            if cid == skip:
                continue
            c = sm.get(p, cid)
            if (cid in res.applied and not _passes(c)) or (cid in res.note_criteria and c == "fail"):
                ok = False
                break
        if ok:
            out.append(p)
    return out


def marginal(sm: StateMatrix, res: CascadeResult) -> list[dict[str, Any]]:
    """F-T6: per criterion, patients of the base failing it (whatever the others say) and with it unknown. Note
    criteria are evaluated only for patients that reached S2, so their base is the S1 survivors."""
    out = []
    base_all = len(sm.pids)
    for cid in [*res.applied, *res.note_criteria]:
        cells = [sm.get(p, cid) for p in sm.pids if sm.get(p, cid)]
        base = base_all if cid in res.applied else len(cells)
        out.append(
            {
                "criterion_id": cid,
                "base": base,
                "n_fail_alone": sum(1 for c in cells if c == "fail"),
                "n_unknown": sum(1 for c in cells if c.startswith("unknown") or c == "pass:unknown_kept"),
            }
        )
    return out


def loo(sm: StateMatrix, res: CascadeResult, locked: set[str]) -> list[dict[str, Any]]:
    """F-T7: eligible without each criterion (leave one out)."""
    final = len(final_pool(sm, res))
    rows = []
    for cid in [*res.applied, *res.note_criteria]:
        n = len(final_pool(sm, res, skip=cid))
        rows.append({"criterion_id": cid, "n_eligible_without": n, "delta_n": n - final, "locked": cid in locked})
    return rows


def unknown_as_pass(sm: StateMatrix, res: CascadeResult) -> int:
    """Sensitivity: structured inclusion unknowns counted as met."""
    n = 0
    for p in sm.pids:
        ok = all(sm.get(p, c) != "fail" for c in [*res.applied, *res.note_criteria])
        n += ok
    return n


# ------------------------------------------------------------------------------------------------ CAS-8 estimate
@dataclass
class TierEstimate:
    tier: str
    n_computable: int  # observed in the tier (exact)
    est: float
    ci_low: float
    ci_high: float
    n_sampled: int
    method: str
    strata: list[dict[str, Any]] = field(default_factory=list)


def wilson(x: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = x / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def tier_estimates(res: CascadeResult) -> list[TierEstimate]:
    """F-T8 / CAS-8: Σ_h N_h p̂_h over the S2/S2b-outcome × department strata, normal interval on the total with the
    finite-population correction, Wilson interval per stratum. Patients excluded before S3 are certain and enter
    with their known tier."""
    alive = [t for t in res.in_scope()]
    strata: dict[str, list[PatientTrace]] = {}
    for t in alive:
        if t.exit_stage in ("S1", "S2", "S2b"):
            continue
        strata.setdefault(t.sample_stratum or "-", []).append(t)
    out: list[TierEstimate] = []
    for tier in TIERS[:4]:
        est = var = 0.0
        n_sampled = 0
        detail = []
        certain = sum(1 for t in alive if t.tier == tier and t.exit_stage in ("S1", "S2", "S2b"))
        for key in sorted(strata):
            members = strata[key]
            big_n = len(members)
            sample = [t for t in members if t.sampled]
            n = len(sample)
            x = sum(1 for t in sample if t.tier == tier)
            n_sampled += n
            if n == 0:
                continue
            p = x / n
            est += big_n * p
            fpc = (big_n - n) / big_n if big_n else 0.0
            var += big_n * big_n * fpc * p * (1 - p) / max(n - 1, 1)
            lo, hi = wilson(x, n)
            detail.append({"stratum": key, "N": big_n, "n": n, "x": x, "wilson_low": lo, "wilson_high": hi})
        half = Z95 * math.sqrt(var)
        observed = sum(1 for t in alive if t.tier == tier)
        out.append(
            TierEstimate(
                tier=tier,
                n_computable=observed,
                est=certain + est,
                ci_low=max(0.0, certain + est - half),
                ci_high=certain + est + half,
                n_sampled=n_sampled,
                method="stratified Σ N_h p̂_h, normal CI with FPC (CAS-8)",
                strata=detail,
            )
        )
    return out


def adjusted_estimate(tiers: Sequence[TierEstimate]) -> tuple[float, float, float, str]:
    """§10.3 eligible = strong + w × potential, w ~ Beta(2, 3) until ≥ 30 potentials are resolved. The interval
    combines the tier sampling variance and the Beta variance of w (delta method)."""
    a, b = POTENTIAL_PRIOR
    w = a / (a + b)
    var_w = a * b / ((a + b) ** 2 * (a + b + 1))
    by = {t.tier: t for t in tiers}
    strong = by["strong"]
    pot = [by["potential:data_gap"], by["potential:uncertain"]]
    est_pot = sum(t.est for t in pot)
    est = strong.est + w * est_pot

    def sd(t: TierEstimate) -> float:
        return (t.ci_high - t.est) / Z95

    var = sd(strong) ** 2 + (w**2) * sum(sd(t) ** 2 for t in pot) + (est_pot**2) * var_w
    half = Z95 * math.sqrt(var)
    return est, max(0.0, est - half), est + half, f"strong + w·potential, w ~ Beta({a:g}, {b:g}) (prior, §10.3)"


# ------------------------------------------------------------------------------------------------ projection
def projection(
    prevalent: float, monthly: float, *, reach: float, accept: float, months: int = 12, paths: int = 10_000, seed: int
) -> list[dict[str, float]]:
    """F-T17 / F-F10: cumulative enrolment percentiles per month (Poisson–Gamma flow, Beta rates; seeded)."""
    rng = random.Random(seed)
    k = 20.0
    cum: list[list[float]] = [[] for _ in range(months)]
    for _ in range(paths):
        r = rng.betavariate(max(reach * k, 1e-6), max((1 - reach) * k, 1e-6))
        a = rng.betavariate(max(accept * k, 1e-6), max((1 - accept) * k, 1e-6))
        lam = rng.gammavariate(4.0, max(monthly, 1e-9) / 4.0) if monthly > 0 else 0.0
        total = 0.0
        for m in range(months):
            arrivals = prevalent / months + _poisson(rng, lam)
            total += _binomial(rng, round(arrivals), r * a)
            cum[m].append(total)
    out = []
    for m in range(months):
        xs = sorted(cum[m])

        def q(p: float, xs: list[float] = xs) -> float:
            return xs[min(len(xs) - 1, int(p * len(xs)))]

        out.append(
            {
                "month": m + 1,
                "cum_p5": q(0.05),
                "cum_p10": q(0.10),
                "cum_p50": q(0.50),
                "cum_p90": q(0.90),
                "cum_p95": q(0.95),
            }
        )
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 50:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _binomial(rng: random.Random, n: int, p: float) -> int:
    return sum(1 for _ in range(n) if rng.random() < p)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


__all__ = [
    "AttritionRow",
    "StateMatrix",
    "TierEstimate",
    "adjusted_estimate",
    "final_pool",
    "loo",
    "marginal",
    "projection",
    "sequential",
    "state_matrix",
    "tier_estimates",
    "unknown_as_pass",
    "wilson",
]
