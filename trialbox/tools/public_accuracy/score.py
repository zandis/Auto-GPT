"""The scorer: the box's answers (``answers.json`` of :mod:`.box`, or the same shape collected from an installed box)
joined to the gold (``gold/`` of :mod:`.site`) by ids only, after the run.

Pair level (TREC, SIGIR, TCGA): a pair is the gold label of one patient for one trial and the box's answer for that
patient in that trial's SCREEN. The box's answer is one of

* ``excluded``  the patient's tier is ``excluded`` (some criterion blocked, the pair agreeing where a model decided);
* ``listed``    on the candidate list and no criterion left open;
* ``open``      on the list with a criterion left to a person or not answered (``pending_human``, ``unknown``,
  ``not evaluated``);
* ``unanswered`` the patient is not in that trial's SCREEN (the screen failed, or scope missed the patient).

Reported per language and stratum: **eligible lost** (eligible, excluded), **excluded caught** (excluded,
excluded), **wrong exclusions** (of the box's exclusions, the share whose gold is eligible), **unanswered**, and the
open share. SIGIR's "would consider" and "would not refer" are their own strata and never enter eligible or excluded.

Criterion level (the TrialGPT physician labels, TCGA cancer type, JMED-Personas): the gold criterion is matched to the
compiled criterion by its text (the box numbers criteria in protocol order); the box's verdict ``fail`` is a block.
A block on a criterion the gold says is met or not applicable is a wrong exclusion; a block on one the gold says is not
met is a catch. With SIGIR's evidence sentence ids, the judge's quote is checked against the deciding sentences.

Compile level: the same trial in two languages (TFDA zh-Hant and its NCT record; jRCT ja and its NCT record):
criteria count, class split and the age limit, per pair and in all; Chia: per line, whether the compiler's class and
domain agree with the entity kinds the annotators marked.

Protocol level (D-1107, card H-3): per set, the protocols of the set, those screened, those cut by the time budget
(not a failure, and not attempted), and those that failed before SCREEN (FEAS, APPROVE) or in it, each by a stable
class read from the stored state and error (``feas_equivalence``, ``approve_failed``, ``screen_reporting`` ...). A
failed protocol stays in the denominator of the failure share; the target "fewer than one protocol in ten" is a named
boolean. Pair and criterion rows on a protocol that never screened are counted by that protocol's status, never
dropped from sight.

Attempts (D-1129, card H-14): a set that ended on its own budget and was taken up again by a resume is one record:
``answers.json`` holds each protocol once (the attempt that answered it in ``attempt``), so every denominator counts
a protocol once and a protocol cut in attempt 1 and screened in attempt 2 is screened. The ``protocols`` block says
``attempts`` (how many, the protocols finished in each, those still cut) and its line.

Pathology (TCGA, the PoC-1 figure): over the protocols screened, ineligible reports excluded (n of N), wrong
exclusions (of the box's exclusions), eligible reports lost (n of N). A set with nothing screened or no verdict is
"not scored", by name (D-1108).

Every rate carries an exact (Clopper-Pearson) 95 % interval. A gold row of an audited or actively sampled set may
carry ``inclusion_probability``, the probability that row was drawn. A rate with any such row is the
inverse-probability weighted (Horvitz–Thompson) estimate of the frame mean, over the frame size named in
``ids.json`` under ``sampling.frames`` (the rate's own name, an integer, or one integer per language). Its
interval is a Korn–Graubard interval on the Kish effective sample size, widened, when the draw is not a fixed-size
equal-probability sample, by the normal interval of the Poisson-sampling variance, so one rare draw is not given a
bound that leaves out the rest of the frame. A frame included in full (every probability is 1 and the sample is
the whole frame) has no sampling uncertainty and the interval is the point. A declared frame that drew no rows
still counts in the denominator. A rate conditional on this run's answers (eligible lost, excluded caught) uses
the answered count when the gold lists the whole declared frame, so a rescreen does not keep a stale frame.
A set that records no probability is scored as before, byte for byte. Nothing here reads a model.
"""

from __future__ import annotations

import difflib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools import gold_kind
from tools.public_accuracy import key as answer_keys

#: the report's layout: 2 adds ``protocols``, ``pathology``, ``unjudged_exclusions`` and the denominators (card H-3);
#: 3 adds ``pairs.conflicted`` and, per language, ``eligible_lost_without_conflicted`` (D-1064, card H-6); 4 adds
#: ``protocols.attempts`` (D-1129, card H-14); 5 adds ``ladder`` (card 10A-3: cells by rung, criterion kind, note
#: language and site, and the decided share printed beside every figure); a report with no such field is layout 1.
#: A rate whose rows carry inclusion probabilities also carries the weighted fields (card 10G-37). Those fields are
#: absent when no probability is recorded, so an unweighted report stays this layout and the version stays 5.
#: Keys are only ever added.
SCHEMA_VERSION = 5

OPEN_VERDICTS = ("pending_human", "unknown", "not_evaluated", "not evaluated", "data_gap", "uncertain")


# ---------------------------------------------------------------- exact intervals
def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Bin(n, p), summed in log space."""
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(
        1.0,
        sum(
            math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
            for i in range(k + 1)
        ),
    )


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided interval for k successes in n (bisection on the binomial tail; no SciPy)."""
    if n == 0:
        return (0.0, 1.0)

    def solve(f: Any) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - _binom_cdf(k - 1, n, p) < alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: _binom_cdf(k, n, p) > alpha / 2)
    return (round(lower, 4), round(upper, 4))


def rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = clopper_pearson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": [lo, hi]}


def _ht_total(outcomes: Sequence[int], inclusion: Sequence[float], population: int) -> float:
    """``Σ y_i / π_i`` over the included units. :func:`ht_mean` divides it by the frame."""
    if isinstance(population, bool) or not isinstance(population, int) or population <= 0:
        raise ValueError(f"population must be a positive integer, got {population!r}")
    if len(outcomes) != len(inclusion):
        raise ValueError("one inclusion probability per outcome")
    if len(outcomes) > population:
        raise ValueError(f"the sample ({len(outcomes)}) is larger than the frame ({population})")
    terms: list[float] = []
    for y, pi in zip(outcomes, inclusion, strict=True):
        if isinstance(y, bool) or y not in (0, 1):
            raise ValueError(f"an outcome is 0 or 1, got {y!r}")
        if isinstance(pi, bool) or not isinstance(pi, (int, float)) or not 0 < float(pi) <= 1:
            raise ValueError(f"an inclusion probability is in (0, 1], got {pi!r}")
        terms.append(float(y) / float(pi))
    return math.fsum(terms)


def ht_mean(outcomes: Sequence[int], inclusion: Sequence[float], population: int) -> float:
    """Horvitz–Thompson mean of a 0/1 outcome: ``(1/N) Σ y_i / π_i``.

    Unbiased for the mean over a frame of ``population`` units when unit ``i`` is included with probability
    ``π_i``, including a sample that happens to be empty (the estimate is then 0). ``outcomes`` and ``inclusion``
    are the units that were included, in the same order. Each unit keeps its own probability: the largest
    probability in the draw is not reused for the others."""
    return _ht_total(outcomes, inclusion, population) / population


def _kish(inclusion: Sequence[float]) -> float:
    """Effective sample size ``(Σ w)² / Σ w²`` with ``w = 1/π``. Equal probabilities give the sample size.

    Log-weights, scaled by the largest, so a very small accepted probability does not square to infinity."""
    if not inclusion:
        return 0.0
    logs: list[float] = []
    for p in inclusion:
        if not math.isfinite(p) or p <= 0.0:
            return 0.0
        logs.append(-math.log(p))
    pivot = max(logs)
    if not math.isfinite(pivot):
        return float(len(inclusion))
    scaled = [math.exp(lw - pivot) for lw in logs]
    total = math.fsum(scaled)
    squares = math.fsum(w * w for w in scaled)
    if not math.isfinite(total) or not math.isfinite(squares) or squares == 0.0:
        return float(len(inclusion))
    return (total * total) / squares


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Lentz), as Numerical Recipes ``betacf``."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1.0e-300:
        d = 1.0e-300
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1.0e-300:
            d = 1.0e-300
        c = 1.0 + aa / c
        if abs(c) < 1.0e-300:
            c = 1.0e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1.0e-300:
            d = 1.0e-300
        c = 1.0 + aa / c
        if abs(c) < 1.0e-300:
            c = 1.0e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3.0e-14:
            return h
    raise ValueError("the incomplete-beta fraction did not converge")


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta ``I_x(a, b)``."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    if x < (a + 1.0) / (a + b + 2.0):
        front = math.exp(a * math.log(x) + b * math.log1p(-x) - log_beta) / a
        return front * _betacf(a, b, x)
    front = math.exp(b * math.log1p(-x) + a * math.log(x) - log_beta) / b
    return 1.0 - front * _betacf(b, a, 1.0 - x)


def _beta_ppf(p: float, a: float, b: float) -> float:
    """Inverse of :func:`_betai`, by bisection. ``a`` and ``b`` may be non-integral (effective counts)."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _betai(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


#: standard normal 97.5% point: the Poisson-sampling half of a weighted interval
_Z95 = 1.959963984540054


def _safe_korn_graubard(estimate: float, n_eff: float) -> tuple[float, float]:
    """Korn–Graubard, or the whole [0, 1] when the beta numbers are not finite. The report is still written."""
    if not math.isfinite(estimate) or not math.isfinite(n_eff) or n_eff < 0.0:
        return (0.0, 1.0)
    try:
        return _korn_graubard(estimate, n_eff)
    except (OverflowError, ValueError, ZeroDivisionError):
        return (0.0, 1.0)


def _fixed_size_equal(inclusion: Sequence[float], population: int) -> bool:
    """Every inclusion probability equal, and the sample the size that probability names.

    A fixed-size equal-probability sample. Its interval is Clopper–Pearson; the Poisson piece treats inclusions
    as independent and would only widen it."""
    if not inclusion:
        return False
    pi0 = inclusion[0]
    if any(p != pi0 for p in inclusion):
        return False
    return abs(len(inclusion) - pi0 * population) <= 1e-6


def _poisson_share_interval(
    estimate: float, outcomes: Sequence[int], inclusion: Sequence[float], population: int
) -> tuple[float, float]:
    """Normal interval for the HT mean under independent sampling, clipped to [0, 1].

    The variance of the mean is ``(1/N²) Σ (1-π_i) y_i² / π_i²``. A non-finite variance covers [0, 1]: that
    draw does not support a tighter bound. One event drawn at probability 0.02 from a frame of 100 is such a draw
    (it happens about 27% of the time when every row is an event); a beta interval on the point 0.5 stops short of 1."""
    if population <= 0:
        return (0.0, 1.0)
    acc = 0.0
    for y, pi in zip(outcomes, inclusion, strict=True):
        if y == 0 or pi >= 1.0:
            continue
        inv = 1.0 / pi
        acc += (1.0 - pi) * inv * inv
        if not math.isfinite(acc):
            return (0.0, 1.0)
    var = acc / (float(population) * float(population))
    if not math.isfinite(var) or var < 0.0:
        return (0.0, 1.0)
    se = math.sqrt(var)
    if se == 0.0:
        point = min(1.0, max(0.0, estimate))
        return (point, point)
    half = _Z95 * se
    return (max(0.0, estimate - half), min(1.0, estimate + half))


def _korn_graubard(estimate: float, n_eff: float, alpha: float = 0.05) -> tuple[float, float]:
    """Clopper–Pearson (beta) interval on an effective sample size. For an integer size and ``k = estimate * n``
    successes it is :func:`clopper_pearson`. A smaller effective size, from unequal weights, widens it. No event
    still has an upper bound above 0, so an empty audit is not reported as a certainty."""
    if n_eff <= 0:
        return (0.0, 1.0)
    p = min(1.0, max(0.0, estimate))
    k = p * n_eff
    lo = 0.0 if k <= 0.0 else _beta_ppf(alpha / 2, k, n_eff - k + 1.0)
    hi = 1.0 if k >= n_eff else _beta_ppf(1.0 - alpha / 2, k + 1.0, n_eff - k)
    return (round(lo, 4), round(hi, 4))


def weighted_rate(outcomes: Sequence[int], inclusion: Sequence[float], population: int) -> dict[str, Any]:
    """The inverse-probability weighted share, and an interval that uses the weights.

    ``k`` and ``n`` stay the counts in the sample (what was seen). ``rate`` is the Horvitz–Thompson estimate of
    the share in the frame, which is not ``k / n`` when the inclusion probabilities differ. ``estimated_events``
    is ``Σ y_i / π_i``, the total itself, not that share rounded and multiplied back by the frame.
    ``effective_n`` is the Kish size of the inverse-probability weights. The interval is Korn–Graubard on that
    size, widened by the normal interval of the Poisson-sampling variance unless the draw is a fixed-size
    equal-probability sample (that interval is already Clopper–Pearson). A frame included in full, every
    probability 1, has no sampling uncertainty and the interval is the point. A probability so small that the
    beta numbers overflow does not abort the report: the interval is then the whole [0, 1]."""
    total = _ht_total(outcomes, inclusion, population)
    est = total / population
    pis = [float(p) for p in inclusion]
    n_eff = _kish(pis)
    if not math.isfinite(n_eff):
        n_eff = 0.0
    if pis and len(pis) == population and all(p == 1.0 for p in pis):
        shown = round(est, 4)
        lo, hi = shown, shown
    else:
        lo, hi = _safe_korn_graubard(est, n_eff)
        if not _fixed_size_equal(pis, population):
            plo, phi = _poisson_share_interval(est, outcomes, pis, population)
            lo, hi = round(min(lo, plo), 4), round(max(hi, phi), 4)
    return {
        "k": sum(outcomes),
        "n": len(outcomes),
        "rate": round(est, 4) if math.isfinite(est) else None,
        "ci95": [lo, hi],
        "population": population,
        "estimated_events": total if math.isfinite(total) else None,
        "weighted": True,
        "effective_n": round(n_eff, 4),
        "method": "horvitz-thompson",
    }


def _frame_size(ids: Mapping[str, Any], name: str, lang: str | None, n_langs: int) -> int:
    """The frame a rate is a mean over. An integer is the whole rate; a per-language object is required when a
    pair-level rate is reported for more than one language. A pooled rate (``lang`` is None) sums a per-language
    object."""
    sampling = ids.get("sampling")
    frames = sampling.get("frames") if isinstance(sampling, dict) else None
    if not isinstance(frames, dict) or name not in frames:
        raise ValueError(
            f"{name}: inclusion probabilities need the frame size at sampling.frames.{name} "
            "(how many units the sample was drawn from)"
        )
    entry = frames[name]
    if isinstance(entry, int) and not isinstance(entry, bool):
        if entry <= 0:
            raise ValueError(f"sampling.frames.{name} must be a positive integer")
        if lang is not None and n_langs > 1:
            raise ValueError(f"{name}: {n_langs} languages need sampling.frames.{name} as a size per language")
        return entry
    if isinstance(entry, dict):
        if lang is None:
            vals = list(entry.values())
            if not vals or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in vals):
                raise ValueError(f"sampling.frames.{name} sizes must be positive integers")
            return sum(vals)
        if lang not in entry:
            raise ValueError(f"{name}: sampling.frames.{name} has no size for {lang}")
        n = entry[lang]
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise ValueError(f"sampling.frames.{name}.{lang} must be a positive integer")
        return n
    raise ValueError(f"sampling.frames.{name} must be a positive integer, or one per language")


#: rates whose denominator is the pairs this run answered, not every row the gold file lists
_ANSWER_CONDITIONAL = frozenset({"eligible_lost", "eligible_lost_without_conflicted", "excluded_caught"})


def _lookup_frame(ids: Mapping[str, Any], name: str, lang: str | None, n_langs: int) -> int | None:
    """The declared frame, or None when this rate names none. An integer is not copied onto each language."""
    sampling = ids.get("sampling")
    frames = sampling.get("frames") if isinstance(sampling, dict) else None
    if not isinstance(frames, dict) or name not in frames:
        return None
    entry = frames[name]
    if isinstance(entry, dict):
        if lang is not None and lang not in entry:
            return None
        return _frame_size(ids, name, lang, n_langs)
    if isinstance(entry, bool) or not isinstance(entry, int):
        return None
    if lang is not None and n_langs > 1:
        return None
    return _frame_size(ids, name, lang, n_langs)


def _domain_population(
    declared: int, listed: int | None, domain_n: int, answer_conditional: bool
) -> int | None:
    """The denominator this rate is a mean over.

    A conditional rate (eligible lost, excluded caught) whose gold file lists the whole declared frame is a mean
    over the pairs this run answered, not over a frame stored by an earlier run. No answered pair means there is
    no such mean (the caller keeps the empty rate). A file that lists only a sample of a larger frame keeps that
    frame: the rows in the file are not the population."""
    if answer_conditional and listed is not None and listed == declared and domain_n != declared:
        if domain_n == 0:
            return None
        return domain_n
    return declared


def _zero_over_frame(sample_n: int, population: int) -> dict[str, Any]:
    """No events to weight (an empty draw, or rows that are all non-events). The frame stays the denominator."""
    block = weighted_rate([], [], population)
    block["k"] = 0
    block["n"] = sample_n
    return block


def _proportion(
    units: Sequence[tuple[int, Mapping[str, Any]]],
    ids: Mapping[str, Any],
    name: str,
    lang: str | None,
    n_langs: int,
    *,
    listed: int | None = None,
    answer_conditional: bool = False,
) -> dict[str, Any]:
    """``rate(k, n)`` when the rows are a census of their frame. Otherwise the weighted rate.

    A probability on some units of the rate and not the others is refused. A probability is passed through as
    recorded: ``True`` is not the number 1. A domain with no probabilities and a larger declared frame contributes
    nothing when every row is a non-event (the weight would multiply zero), and is refused when a row is an event,
    because that event has no probability to invert. The rows themselves, when there are exactly as many as the
    frame, are that frame."""
    flags = ["inclusion_probability" in row for _, row in units]
    if any(flags) and not all(flags):
        raise ValueError(
            f"{name}: an inclusion probability on {sum(flags)} of {len(units)} units; "
            "record one on every unit of the rate, or on none"
        )
    if any(flags):
        declared = _frame_size(ids, name, lang, n_langs)
        population = _domain_population(declared, listed, len(units), answer_conditional)
        if population is None:
            return rate(sum(y for y, _ in units), len(units))
        outcomes = [y for y, _ in units]
        inclusion = [row["inclusion_probability"] for _, row in units]
        return weighted_rate(outcomes, inclusion, population)
    declared_missing = _lookup_frame(ids, name, lang, n_langs)
    if declared_missing is None:
        return rate(sum(y for y, _ in units), len(units))
    population = _domain_population(declared_missing, listed, len(units), answer_conditional)
    if population is None or len(units) == population:
        return rate(sum(y for y, _ in units), len(units))
    events = sum(y for y, _ in units)
    if events:
        raise ValueError(
            f"{name}: {events} event(s) among {len(units)} units have no inclusion probability; "
            f"a declared frame of {population} is not a census of those rows"
        )
    return _zero_over_frame(len(units), population)


def _same_counts(old: Mapping[str, Any], new: Mapping[str, Any], name: str) -> dict[str, Any]:
    """The weighted rate keeps the sample counts. A drift between the two readings is a scorer bug."""
    if (new["k"], new["n"]) != (old["k"], old["n"]):
        raise ValueError(f"{name}: the sampled rows do not match the unweighted counts")
    return dict(new)


_PAIR_RATES = (
    "eligible_lost",
    "excluded_caught",
    "wrong_exclusions",
    "unanswered",
    "left_open",
    "eligible_lost_without_conflicted",
)


def _frame_languages(ids: Mapping[str, Any]) -> set[str]:
    """Languages a per-language frame names. An integer frame is the whole rate and names none."""
    sampling = ids.get("sampling")
    frames = sampling.get("frames") if isinstance(sampling, dict) else None
    langs: set[str] = set()
    if not isinstance(frames, dict):
        return langs
    for entry in frames.values():
        if isinstance(entry, dict):
            langs.update(str(k) for k in entry)
    return langs


def _empty_language(ids: Mapping[str, Any], lang: str, n_langs: int, sibling: Mapping[str, Any]) -> dict[str, Any]:
    """A language the frame names and this run did not draw. Its declared sizes stay in the denominator."""
    block: dict[str, Any] = {
        "answered": 0,
        "other_strata": {},
        "pairs_in_gold": 0,
        "unanswered_by_protocol": {},
        "denominators": PAIR_DENOMINATORS,
    }
    if "conflicted_pairs" in sibling:
        block["conflicted_pairs"] = 0
    for name in _PAIR_RATES:
        if name not in sibling:
            continue
        declared = _lookup_frame(ids, name, lang, n_langs)
        block[name] = rate(0, 0) if declared is None else _zero_over_frame(0, declared)
    return block


def _reweight_pair_rates(
    summary: dict[str, dict[str, Any]],
    units: Mapping[str, Mapping[str, list[tuple[int, dict[str, Any]]]]],
    ids: Mapping[str, Any],
    listed: Mapping[str, Mapping[str, int]] | None = None,
) -> None:
    n_langs = sum(1 for by in units.values() if any(by.get(name) for name in _PAIR_RATES))
    for lang, block in summary.items():
        by = units.get(lang) or {}
        counts = (listed or {}).get(lang) or {}
        for name in _PAIR_RATES:
            if name not in block:
                continue
            listed_n = int(counts.get(name, 0)) if name in _ANSWER_CONDITIONAL else None
            block[name] = _same_counts(
                block[name],
                _proportion(
                    by.get(name) or [],
                    ids,
                    name,
                    lang,
                    n_langs,
                    listed=listed_n,
                    answer_conditional=name in _ANSWER_CONDITIONAL,
                ),
                name,
            )
    sibling = next(iter(summary.values()), None)
    if sibling is None:
        return
    for lang in sorted(_frame_languages(ids) - set(summary)):
        summary[lang] = _empty_language(ids, lang, n_langs, sibling)


# ---------------------------------------------------------------- joining
def load(built: Path, work: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    gold = built / "gold"
    ids = json.loads((gold / "ids.json").read_text(encoding="utf-8"))
    pairs = [json.loads(x) for x in (gold / "pairs.jsonl").read_text(encoding="utf-8").splitlines() if x]
    crits = [json.loads(x) for x in (gold / "criteria.jsonl").read_text(encoding="utf-8").splitlines() if x]
    answers = json.loads((work / "answers.json").read_text(encoding="utf-8"))
    return ids, pairs, crits, answers


def pid_of(mrn: str, key: bytes | None = None) -> str:
    """The box's pseudonym of a chart number (the site key of the run)."""
    from tb_common.crypto import pid_for_mrn

    if key is None:
        from tools import feas_demo as fd

        key = fd.KEY
    return str(pid_for_mrn(key, mrn))


def answer_of(answers: dict[str, Any], ruleset: str, pid: str) -> tuple[str, dict[str, Any] | None]:
    a = answers.get(ruleset) or {}
    p = (a.get("patients") or {}).get(pid)
    if p is None:
        return "unanswered", None
    if p.get("tier") == "excluded":
        return "excluded", p
    if any(str(v.get("verdict")) in OPEN_VERDICTS for v in p.get("verdicts") or []):
        return "open", p
    return "listed", p


# ---------------------------------------------------------------- protocol level (D-1107)
#: protocol status -> what it means in a denominator
STATUS_WHAT = {
    "screened": "screened",
    "compiled": "compiled (a compile-only set)",
    "failed_before_screen": "failed before SCREEN (FEAS or APPROVE)",
    "failed_in_screen": "failed in SCREEN",
    "not_run_time_budget": "not run: cut by the set's time budget (not a failure)",
    "unfinished": "in answers.json with no end the scorer knows",
    "not_in_answers": "not in answers.json (not run: filtered out, or the set stopped first)",
}


def _slug(x: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(x or "").lower()).strip("_")


def _step(err: Any) -> str:
    """The step a job failed at, from its stored error (``{"step": ...}``, or text ``"<step>: ..."``)."""
    s: Any = None
    if isinstance(err, dict):
        s = err.get("step")
    elif isinstance(err, str):
        m = re.match(r"\s*([A-Za-z_]+)\s*:", err)
        s = m.group(1) if m else None
    return _slug(s) or "no_step"


def _message(err: Any) -> str:
    if isinstance(err, dict):
        err = err.get("message") or err.get("detail") or ""
    return " ".join(str(err or "").split())[:200]


def protocol_status(a: dict[str, Any] | None) -> tuple[str, str]:
    """(status, class) of one protocol's stored answer: the status is a key of :data:`STATUS_WHAT`; the class names
    where and why a failed protocol stopped (``<stage>_<step>`` from the job's error, or the driver's outcome:
    ``feas_timeout``, ``approve_failed``, ``feas_refused_by_tripwire`` ...). Read from the fields the driver stores
    (``outcome``, ``feas``/``feas_error``, ``approve``/``approve_error``, ``screen``/``screen_error``); an answer of
    the in-process dry run (no ``outcome``) is read from the same fields."""
    if a is None:
        return "not_in_answers", "not_in_answers"
    o = str(a.get("outcome") or "")
    if o == "not_run_time_budget":
        return "not_run_time_budget", o
    if a.get("screen") == "done" or o == "screened":
        return "screened", "screened"
    if o == "compiled":
        return "compiled", "compiled"
    refused = o if o in ("refused_by_tripwire", "refused_by_gateway") else ""
    if a.get("screen") is not None or o.startswith("screen_"):
        if o == "screen_refused_at_intake":
            return "failed_in_screen", o
        if refused:
            return "failed_in_screen", f"screen_{refused}"
        if a.get("screen") not in (None, "failed") and not a.get("screen_error"):
            return "failed_in_screen", f"screen_ended_{_slug(a.get('screen'))}"
        return "failed_in_screen", f"screen_{_step(a.get('screen_error'))}"
    if (a.get("approve") not in (None, "done")) or o.startswith("approve_"):
        if o == "approve_refused_at_intake":
            return "failed_before_screen", o
        return "failed_before_screen", f"approve_{_slug(a.get('approve')) or 'failed'}"
    if a.get("approve") == "done":
        return "unfinished", "approved_not_screened"
    if o == "timeout_feas":
        return "failed_before_screen", "feas_timeout"
    if o == "refused_at_intake":
        return "failed_before_screen", "feas_refused_at_intake"
    if refused:
        return "failed_before_screen", f"feas_{refused}"
    feas = a.get("feas")
    if feas == "failed":
        return "failed_before_screen", f"feas_{_step(a.get('feas_error'))}"
    if feas not in (None, "awaiting_approval") and o:
        return "failed_before_screen", f"feas_ended_{_slug(feas)}"  # e.g. FEAS "done" with no review workbook
    return "unfinished", _slug(o) or (f"feas_{_slug(feas)}" if feas else "no_outcome")


def _decided(p: dict[str, Any]) -> bool:
    """A patient the SCREEN said something of: a verdict on a criterion, or the tier ``excluded``."""
    return bool(p.get("verdicts")) or p.get("tier") == "excluded"


def _error_of(a: dict[str, Any], cls: str) -> Any:
    stage = cls.split("_", 1)[0]
    return a.get(f"{stage}_error") if stage in ("feas", "approve", "screen") else None


def statuses(ids: dict[str, Any], answers: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """ruleset -> (status, class), for every protocol of the set and every ruleset in the answers."""
    rss = set((ids.get("rulesets") or {}).values()) | set(answers)
    return {rs: protocol_status(answers.get(rs)) for rs in sorted(rss)}


def attempts(answers: dict[str, Any], clock: dict[str, Any] | None = None) -> dict[str, Any]:
    """D-1129: the set's attempts read as one: how many (the set's clock, ``set-clock.json``, or the highest
    ``attempt`` an answer carries), the protocols finished in each (an answer with no ``attempt``: attempt 1), and
    those still cut by a budget. The line is the one the set's report prints."""
    done = [a for a in answers.values() if protocol_status(a)[0] != "not_run_time_budget"]
    n = max([int((clock or {}).get("attempt") or 1)] + [int(a.get("attempt") or 1) for a in done])
    fin = {str(i): 0 for i in range(1, n + 1)}
    cut = 0
    for a in answers.values():
        if protocol_status(a)[0] == "not_run_time_budget":
            cut += 1
        else:
            k = str(int(a.get("attempt") or 1))
            fin[k] = fin.get(k, 0) + 1
    said = "; ".join(f"in attempt {k}: {v}" if i else f"protocols finished in attempt {k}: {v}"
                     for i, (k, v) in enumerate(sorted(fin.items(), key=lambda kv: int(kv[0]))))  # fmt: skip
    return {"attempts": n, "finished_in": fin, "still_cut": cut, "line": f"attempts: {n}; {said}; still cut: {cut}"}


def score_protocols(
    ids: dict[str, Any], answers: dict[str, Any], clock: dict[str, Any] | None = None
) -> dict[str, Any]:
    """D-1107 (card H-3): what became of each protocol of the set. A protocol that failed before or in SCREEN is its
    own line, by class, and stays in the denominator of the failure share; a budget cut is said apart and is not
    attempted. The target is "fewer than one protocol in ten of those attempted fails" (before or in SCREEN).
    ``clock``: the set's ``set-clock.json`` (D-1129: its attempts)."""
    in_set = sorted(set((ids.get("rulesets") or {}).values()))
    st = statuses(ids, answers)
    by: Counter[str] = Counter(s for s, _ in st.values())
    classes: dict[str, dict[str, Any]] = {}
    for rs, (s, cls) in st.items():
        if s not in ("failed_before_screen", "failed_in_screen", "unfinished"):
            continue
        row = classes.setdefault(cls, {"status": s, "protocols": 0, "rulesets": [], "example": ""})
        row["protocols"] += 1
        row["rulesets"].append(rs)
        row["example"] = row["example"] or _message(_error_of(answers.get(rs) or {}, cls))
    failed = by["failed_before_screen"] + by["failed_in_screen"]
    attempted = by["screened"] + by["compiled"] + failed + by["unfinished"]
    share = rate(failed, attempted)
    return {
        "what": "each protocol of the set by what became of it; a failure is counted by class and stays in the "
        "denominator; a budget cut is not a failure and not attempted",
        "in_set": len(in_set),
        "in_answers": sum(1 for rs in in_set if rs in answers),
        "answers_not_in_the_set": sorted(rs for rs in answers if in_set and rs not in in_set),
        **{s: by[s] for s in STATUS_WHAT},
        "attempted": attempted,
        "failed": failed,
        "patients_answered": sum(len(a.get("patients") or {}) for a in answers.values()),
        "verdicts": sum(
            len(p.get("verdicts") or []) for a in answers.values() for p in (a.get("patients") or {}).values()
        ),
        "patients_decided": sum(_decided(p) for a in answers.values() for p in (a.get("patients") or {}).values()),
        "failed_by_class": {cls: r["protocols"] for cls, r in sorted(classes.items()) if r["status"] != "unfinished"},
        "classes": dict(sorted(classes.items(), key=lambda kv: (kv[1]["status"], -kv[1]["protocols"], kv[0]))),
        "failed_share": share,
        "failed_before_screen_share": rate(by["failed_before_screen"], attempted),
        "fewer_than_one_in_ten_failed": None if not attempted else failed * 10 < attempted,
        "target": "fewer than one protocol in ten of those attempted fails (before or in SCREEN; the target reads "
        "this wider share, and the share failed before SCREEN is printed beside it); attempted = "
        "screened + compiled + failed + unfinished (budget cuts and protocols not in answers.json are not)",
        "statuses": STATUS_WHAT,
        "attempts": attempts(answers, clock),  # D-1129: the attempts of a set taken up again after its budget
    }


def criterion_says_excluded(crits: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(mrn, ruleset) of every pair whose own criterion labels exclude the patient: an inclusion "not included" or an
    exclusion "excluded" (the physicians' criterion-level reading). The one definition is the key's
    (:func:`tools.public_accuracy.key.criterion_says_excluded`), which D-1064's conflicted marks use too."""
    return answer_keys.criterion_says_excluded(crits)


def score_pairs(
    ids: dict[str, Any],
    pairs: list[dict[str, Any]],
    answers: dict[str, Any],
    key: bytes | None = None,
    crits: list[dict[str, Any]] | None = None,
    conflicted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pair-level table per (language, stratum, gold label).

    D-1064 (card H-6): ``conflicted`` is the key's marks (:func:`tools.public_accuracy.key.conflicted_of`). When the
    key marks them, the target's figure is read without them (``eligible_lost_without_conflicted``), ``eligible_lost``
    stays the figure on the key as published, and ``conflicted`` lists each marked pair with the criterion labels that
    exclude, what the box answered and on which criterion. A marked pair the box excluded on a line its criterion
    labels do not exclude on is a finding to trace (``conflicted_excluded_on_another_line``), never set aside silently.

    S1 (P1b review): a pair whose label is ``eligible`` while its own criterion labels exclude the patient (an
    inclusion not met, an exclusion met) is a conflict inside the gold. Those pairs are counted on their own
    (``label_conflicts``), with what the box answered, and the box's exclusions of them are said apart from
    ``eligible_lost`` (2 of sigir's 4 "eligible lost" in P1b agreed with the physicians' criterion labels)."""
    lang_of = ids.get("lang") or {}
    cells: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    by_crit = criterion_says_excluded(crits or [])
    conflicts: dict[str, Counter[str]] = defaultdict(Counter)
    on_the_line: Counter[str] = Counter()
    conflict_exclusions: list[dict[str, Any]] = []
    st = statuses(ids, answers)
    not_answered: dict[str, Counter[str]] = defaultdict(Counter)
    in_gold: Counter[str] = Counter()
    marks = (conflicted or {}).get("marks")
    marked = {(str(r["mrn"]), str(r["ruleset"])): r for r in marks or []}
    without: dict[str, Counter[str]] = defaultdict(Counter)
    marked_rows: list[dict[str, Any]] = []
    # card 10G-37: only a set that records inclusion probabilities takes this path; the counts above are unchanged
    weighted_set = any("inclusion_probability" in g for g in pairs)
    units: dict[str, dict[str, list[tuple[int, dict[str, Any]]]]] = defaultdict(
        lambda: {name: [] for name in _PAIR_RATES}
    )
    listed: dict[str, Counter[str]] = defaultdict(Counter)
    for g in pairs:
        if not g.get("mrn") or not g.get("ruleset"):
            continue
        lang = lang_of.get(g["ruleset"], "?")
        got, p = answer_of(answers, g["ruleset"], pid_of(g["mrn"], key))
        cells[(lang, g.get("stratum") or "", g["label"])][got] += 1
        if g["label"] in ("eligible", "excluded"):
            in_gold[lang] += 1
            if got == "unanswered":
                s = st.get(g["ruleset"], ("not_in_answers", ""))[0]
                not_answered[lang]["screened, the patient not in its SCREEN" if s == "screened" else s] += 1
            if weighted_set:
                pair_key = (str(g["mrn"]), str(g["ruleset"]))
                if g["label"] == "eligible":
                    # every eligible row the file lists, answered or not: the stored frame is that count when
                    # the file is the whole frame, and the rate below is only over the rows this run answered
                    listed[lang]["eligible_lost"] += 1
                    if pair_key not in marked:
                        listed[lang]["eligible_lost_without_conflicted"] += 1
                    if got != "unanswered":
                        units[lang]["eligible_lost"].append((int(got == "excluded"), g))
                        if pair_key not in marked:
                            units[lang]["eligible_lost_without_conflicted"].append((int(got == "excluded"), g))
                if g["label"] == "excluded":
                    listed[lang]["excluded_caught"] += 1
                    if got != "unanswered":
                        units[lang]["excluded_caught"].append((int(got == "excluded"), g))
                if got == "excluded":
                    units[lang]["wrong_exclusions"].append((int(g["label"] == "eligible"), g))
                units[lang]["unanswered"].append((int(got == "unanswered"), g))
                units[lang]["left_open"].append((int(got == "open"), g))
        mk = marked.get((str(g["mrn"]), str(g["ruleset"])))
        if mk is not None:
            marked_rows.append(_conflicted_row(g, mk, lang, got, p, answers, crits or []))
        elif g["label"] == "eligible" and got != "unanswered":
            without[lang]["n"] += 1
            without[lang]["k"] += int(got == "excluded")
        if g["label"] == "eligible" and (str(g["mrn"]), str(g["ruleset"])) in by_crit:
            conflicts[lang][got] += 1
            if got == "excluded" and p is not None:
                why = _blocked_on(g, p, (answers.get(g["ruleset"]) or {}).get("draft") or [], crits or [])
                on_the_line[lang] += int(why["agrees_on_the_line"])
                conflict_exclusions.append({"ruleset": g["ruleset"], "patient": g.get("patient"), "lang": lang, **why})
    rows = []
    for (lang, stratum, label), c in sorted(cells.items()):
        n = sum(c.values())
        rows.append(
            {
                "lang": lang,
                "stratum": stratum,
                "gold": label,
                "n": n,
                **{k: c[k] for k in ("excluded", "listed", "open", "unanswered")},
            }
        )
    summary = summarise(rows)
    for lang, c in conflicts.items():
        if lang in summary:
            summary[lang]["eligible_lost_where_the_criterion_labels_exclude"] = c["excluded"]
            # S1, the finer reading: the box blocked on the very line the physicians label as excluding (same text,
            # or an age line where that label is on an age statement)
            summary[lang]["eligible_lost_on_the_line_the_criterion_labels_exclude"] = on_the_line[lang]
    if marks is not None:
        for lang, s in summary.items():
            s["eligible_lost_without_conflicted"] = rate(without[lang]["k"], without[lang]["n"])
            s["conflicted_pairs"] = sum(1 for r in marked_rows if r["lang"] == lang)
    for lang, s in summary.items():
        # D-1107: the rates count only pairs the box answered; every pair of the gold is accounted for here, by the
        # status of its protocol, so pairs on a protocol that never screened are not silently dropped
        s["pairs_in_gold"] = in_gold[lang]
        s["unanswered_by_protocol"] = dict(sorted(not_answered[lang].items()))
        s["denominators"] = PAIR_DENOMINATORS
    if weighted_set:
        _reweight_pair_rates(summary, units, ids, listed)
    return {
        "rows": rows,
        "summary": summary,
        "label_conflicts": {
            "what": "pairs labelled eligible whose own criterion labels exclude the patient (inclusion not included, "
            "or exclusion excluded): a conflict inside the gold, with the box's answer",
            "by_lang": {lang: {"pairs": sum(c.values()), **dict(c)} for lang, c in sorted(conflicts.items())},
            "pairs": sum(sum(c.values()) for c in conflicts.values()),
            "excluded": conflict_exclusions,
        },
        **(
            {}
            if marks is None
            else {
                "conflicted": {
                    "what": "D-1064: pairs the key marks conflicted (a pair label of eligible while the same "
                    "physicians' criterion labels exclude the patient); set aside from the target, never relabelled",
                    "from": (conflicted or {}).get("from"),
                    "pairs": marked_rows,
                },
                "conflicted_excluded_on_another_line": [r for r in marked_rows if r["on_another_line"]],
            }
        ),
    }


#: the box's answer of a pair, in the words of a report
BOX_SAID = {"excluded": "excluded", "open": "review", "listed": "included", "unanswered": "not answered"}


def _conflicted_row(
    g: dict[str, Any],
    mk: dict[str, Any],
    lang: str,
    got: str,
    p: dict[str, Any] | None,
    answers: dict[str, Any],
    crits: list[dict[str, Any]],
) -> dict[str, Any]:
    """One conflicted pair: the criterion labels that exclude, what the box answered and on which criterion; whether
    an exclusion was on a line those labels exclude on (``on_another_line``: it was not, a finding to trace)."""
    draft = (answers.get(g["ruleset"]) or {}).get("draft") or []
    by_id = {c.get("id"): c for c in draft}
    row: dict[str, Any] = {
        "patient": g.get("patient"), "trial": g.get("trial"), "ruleset": g["ruleset"], "lang": lang,
        "label": g["label"], "why": mk.get("why") or "D-1064",
        "excluding": [f"{e['kind']} {e['label']}: {e['text']}" for e in mk.get("excluding") or []],
        "box": BOX_SAID[got], "tier": (p or {}).get("tier"), "blocked_on": [], "left_open_on": [],
        "left_open_on_an_excluding_line": [], "left_open_elsewhere": 0,
        "on_an_excluding_line": None, "on_another_line": False,
    }  # fmt: skip
    if p is None:
        return row
    row["left_open_on"] = [
        str((by_id.get(v.get("id")) or {}).get("text") or v.get("id"))
        for v in p.get("verdicts") or []
        if str(v.get("verdict")) in OPEN_VERDICTS
    ]
    excluding_ids = {
        hit.get("id")
        for e in mk.get("excluding") or []
        if (hit := match_criterion(e.get("text") or "", draft, e.get("kind") or "")) is not None
    }
    on = [
        str((by_id.get(v.get("id")) or {}).get("text") or v.get("id"))
        for v in p.get("verdicts") or []
        if str(v.get("verdict")) in OPEN_VERDICTS and v.get("id") in excluding_ids
    ]
    row["left_open_on_an_excluding_line"] = on
    row["left_open_elsewhere"] = len(row["left_open_on"]) - len(on)
    if got == "excluded":
        why = _blocked_on(g, p, draft, crits)
        row["blocked_on"] = why["blocked_on"]
        row["on_an_excluding_line"] = why["agrees_on_the_line"]
        row["on_another_line"] = not why["agrees_on_the_line"]
    return row


PAIR_DENOMINATORS = {
    "eligible_lost": "gold-eligible pairs the box answered (protocol screened and the patient in its SCREEN): the "
    "figure on the key as published",
    "eligible_lost_without_conflicted": "the same, without the pairs the key marks conflicted (D-1064): the figure "
    "the target reads, on a key that marks them",
    "excluded_caught": "gold-excluded pairs the box answered",
    "wrong_exclusions": "the box's exclusions of gold-eligible or gold-excluded pairs",
    "unanswered": "every gold-eligible and gold-excluded pair (pairs_in_gold); unanswered_by_protocol splits it by "
    "the status of the pair's protocol",
    "left_open": "every gold-eligible and gold-excluded pair (pairs_in_gold)",
}
CRITERION_DENOMINATORS = {
    "wrong_exclusion": "gold rows met or not applicable whose criterion compiled and whose patient the box answered "
    "with a verdict (block, open or no block)",
    "caught": "gold rows not met whose criterion compiled and whose patient the box answered with a verdict",
    "not_answered_by_protocol": "every other gold row, by the status of its protocol (and on a screened protocol, "
    "why: criterion not compiled, patient not in the SCREEN, no verdict)",
}

AGE_TEXT = re.compile(r"\bage[ds]?\b|\byears?[ -]old\b|\bmonths?[ -]old\b|歳|年齡|年龄", re.IGNORECASE)


def _is_age_line(c: dict[str, Any]) -> bool:
    lg = c.get("logic") or {}
    return bool(lg.get("age")) or bool(AGE_TEXT.search(str(c.get("text") or "")))


def _blocked_on(
    g: dict[str, Any], p: dict[str, Any], draft: list[dict[str, Any]], crits: list[dict[str, Any]]
) -> dict[str, Any]:
    """S1: the lines the box excluded a pair on, and whether one of them is a line the pair's own criterion labels
    exclude on (the gold row's text matches it, or both are about age)."""
    by_id = {c.get("id"): c for c in draft}
    fails = [
        by_id.get(v.get("id")) or {"id": v.get("id")} for v in p.get("verdicts") or [] if v.get("verdict") == "fail"
    ]
    rows = [
        c
        for c in crits
        if str(c.get("mrn")) == str(g["mrn"])
        and str(c.get("ruleset")) == str(g["ruleset"])
        and (c.get("kind"), c.get("label")) in BLOCK_RIGHT
    ]
    agree = any(
        match_criterion(r.get("text") or "", [f], r.get("kind") or "") is not None
        or (_is_age_line(f) and AGE_TEXT.search(str(r.get("text") or "")))
        for f in fails
        for r in rows
    )
    return {"blocked_on": [str(f.get("text") or f.get("id")) for f in fails], "agrees_on_the_line": bool(agree)}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_lang[r["lang"]].append(r)
    for lang, rs in by_lang.items():
        el = [r for r in rs if r["gold"] == "eligible"]
        ex = [r for r in rs if r["gold"] == "excluded"]
        # over the pairs the box answered (2026-11-15, Gate C): an unanswered pair is not a pair the box kept, so it
        # never enters eligible lost or excluded caught; the unanswered share is its own line
        n_el, n_ex = sum(r["n"] - r["unanswered"] for r in el), sum(r["n"] - r["unanswered"] for r in ex)
        lost, caught = sum(r["excluded"] for r in el), sum(r["excluded"] for r in ex)
        boxed = lost + caught
        answered = [r for r in rs if r["gold"] in ("eligible", "excluded")]
        n_all = sum(r["n"] for r in answered)
        out[lang] = {
            "answered": n_el + n_ex,
            "eligible_lost": rate(lost, n_el),
            "excluded_caught": rate(caught, n_ex),
            "wrong_exclusions": rate(lost, boxed),
            "unanswered": rate(sum(r["unanswered"] for r in answered), n_all),
            "left_open": rate(sum(r["open"] for r in answered), n_all),
            "other_strata": {
                f"{r['stratum']}:{r['gold']}": {k: r[k] for k in ("n", "excluded", "listed", "open", "unanswered")}
                for r in rs
                if r["gold"] not in ("eligible", "excluded")
            },
        }
    return out


# ---------------------------------------------------------------- criterion level
def match_criterion(text: str, draft: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    """The compiled criterion whose text is the gold criterion's (exact, contained, or a ratio of at least 0.6)."""
    t = " ".join(str(text).split()).lower()
    best, score = None, 0.0
    for c in draft:
        if c.get("kind") and kind and c["kind"] != kind:
            continue
        cc = " ".join(str(c.get("text") or "").split()).lower()
        s = 1.0 if t == cc or (len(t) > 20 and (t in cc or cc in t)) else difflib.SequenceMatcher(None, t, cc).ratio()
        if s > score:
            best, score = c, s
    return best if score >= 0.6 else None


BLOCK_RIGHT = set(answer_keys.EXCLUDING)
BLOCK_WRONG = {
    ("inclusion", "included"),
    ("exclusion", "not excluded"),
    ("inclusion", "not enough information"),
    ("exclusion", "not enough information"),
    ("inclusion", "not applicable"),
    ("exclusion", "not applicable"),
}


def evidence_hit(quote: str | None, sentences: list[str], evidence: list[int]) -> bool | None:
    """Whether the judge's quote lies in one of the gold's deciding sentences (None: no quote or no evidence ids)."""
    if not quote or not evidence or not sentences:
        return None
    q = " ".join(quote.split()).lower()[:120]
    for i in evidence:
        if 0 <= i < len(sentences):
            s = " ".join(sentences[i].split()).lower()
            if q[:60] in s or s[:60] in q:
                return True
    return False


def score_criteria(
    ids: dict[str, Any],
    crits: list[dict[str, Any]],
    answers: dict[str, Any],
    sentences: dict[str, list[str]] | None = None,
    key: bytes | None = None,
) -> dict[str, Any]:
    lang_of = ids.get("lang") or {}
    cells: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    evid: Counter[str] = Counter()
    st = statuses(ids, answers)
    not_answered: Counter[str] = Counter()
    weighted_set = any("inclusion_probability" in g for g in crits)
    wrong_units: list[tuple[int, dict[str, Any]]] = []
    caught_units: list[tuple[int, dict[str, Any]]] = []
    for g in crits:
        rs, mrn = g.get("ruleset"), g.get("mrn")
        if not rs or not mrn:
            continue
        a = answers.get(rs) or {}
        c = match_criterion(g["text"], a.get("draft") or [], g["kind"])
        pid = pid_of(mrn, key)
        p = (a.get("patients") or {}).get(pid)
        if c is None:
            got = "not_compiled"
        elif p is None:
            got = "unanswered"
        else:
            v = next((x for x in p.get("verdicts") or [] if x.get("id") == c["id"]), None)
            verdict = str((v or {}).get("verdict") or "")
            # S2 (P1b review): a matched row with no verdict is "no verdict", never a "no block"
            got = (
                "no_verdict"
                if not verdict
                else "block"
                if verdict == "fail"
                else "open"
                if verdict in OPEN_VERDICTS
                else "no_block"
            )
            if v is not None and sentences is not None:
                hit = evidence_hit(v.get("quote"), sentences.get(g["patient"]) or [], g.get("evidence") or [])
                evid["no quote or no ids" if hit is None else "in a deciding sentence" if hit else "elsewhere"] += 1
        if got in ("not_compiled", "unanswered", "no_verdict"):
            s = st.get(rs, ("not_in_answers", ""))[0]
            not_answered[f"screened: {got}" if s == "screened" else s] += 1
        elif weighted_set:
            if (g["kind"], g["label"]) in BLOCK_WRONG:
                wrong_units.append((int(got == "block"), g))
            elif (g["kind"], g["label"]) in BLOCK_RIGHT:
                caught_units.append((int(got == "block"), g))
        cells[(lang_of.get(rs, "?"), g.get("stratum") or "", g["kind"], g["label"])][got] += 1
    rows = []
    for (lang, stratum, kind, label), c in sorted(cells.items()):
        right = (kind, label) in BLOCK_RIGHT
        wrong = (kind, label) in BLOCK_WRONG
        rows.append(
            {
                "lang": lang,
                "stratum": stratum,
                "kind": kind,
                "gold": label,
                "n": sum(c.values()),
                **dict(c),
                "block_is": "catch" if right else "wrong exclusion" if wrong else "-",
            }
        )

    # over the criteria the box answered (2026-11-15, Gate C): a criterion not compiled or a patient unanswered is
    # counted on its own line, never as a "no block" in a rate's denominator
    def answered(r: dict[str, Any]) -> int:
        return sum(int(r.get(k, 0)) for k in ("block", "open", "no_block"))

    blocks_wrong = sum(int(r.get("block", 0)) for r in rows if r["block_is"] == "wrong exclusion")
    n_wrongable = sum(answered(r) for r in rows if r["block_is"] == "wrong exclusion")
    caught = sum(int(r.get("block", 0)) for r in rows if r["block_is"] == "catch")
    n_catchable = sum(answered(r) for r in rows if r["block_is"] == "catch")
    wrong_rate = rate(blocks_wrong, n_wrongable)
    caught_rate = rate(caught, n_catchable)
    if weighted_set:  # card 10G-37: the same counts, the inverse-probability estimate
        wrong_rate = _same_counts(
            wrong_rate, _proportion(wrong_units, ids, "wrong_exclusion", None, 1), "wrong_exclusion"
        )
        caught_rate = _same_counts(caught_rate, _proportion(caught_units, ids, "caught", None, 1), "caught")
    return {
        "answered": sum(answered(r) for r in rows),
        "unanswered": sum(int(r.get("unanswered", 0)) for r in rows),
        "rows": rows,
        "wrong_exclusion": wrong_rate,
        "caught": caught_rate,
        "not_compiled": sum(r.get("not_compiled", 0) for r in rows),
        "no_verdict": sum(int(r.get("no_verdict", 0)) for r in rows),
        "evidence": dict(evid),
        # D-1107: every gold row not in a rate's denominator, by the status of its protocol
        "rows_in_gold": sum(r["n"] for r in rows),
        "not_answered_by_protocol": dict(sorted(not_answered.items())),
        "denominators": CRITERION_DENOMINATORS,
    }


# ---------------------------------------------------------------- lines the benchmark wrote (S3, S4)
def _fails(p: dict[str, Any], cid: Any) -> bool:
    return any(v.get("id") == cid and v.get("verdict") == "fail" for v in p.get("verdicts") or [])


def score_written(
    ids: dict[str, Any], written: dict[str, list[str]], answers: dict[str, Any], crits: list[dict[str, Any]]
) -> dict[str, Any]:
    """S3, S4 (P1b review): the lines the benchmark wrote into a protocol that no gold row judges (the placed age and
    sex lines; JMED's coded "20歳以上") are invisible at criterion level, yet the box excludes patients by them. Per
    line matched to its compiled criterion: the patients the box answered, those it blocked on that line, and of
    those the excluded ones; a line not compiled is said. Patients are counted once per protocol and in all."""
    lang_of = ids.get("lang") or {}
    judged = {(str(c.get("ruleset")), " ".join(str(c.get("text") or "").split()).lower()) for c in crits}
    rows: list[dict[str, Any]] = []
    excluded_by_written: set[tuple[str, str]] = set()
    for rs, lines in sorted(written.items()):
        a = answers.get(rs) or {}
        draft = a.get("draft") or []
        pats = a.get("patients") or {}
        for line in lines:
            if (rs, " ".join(line.split()).lower()) in judged:
                continue  # a gold row judges it: the criterion table has it
            c = match_criterion(line, draft, "inclusion")
            row: dict[str, Any] = {"ruleset": rs, "lang": lang_of.get(rs, "?"), "line": line}
            if c is None:
                rows.append({**row, "compiled": False})
                continue
            cid = c["id"]
            blocked = [pid for pid, p in pats.items() if _fails(p, cid)]
            excl = [pid for pid in blocked if (pats[pid] or {}).get("tier") == "excluded"]
            excluded_by_written |= {(rs, pid) for pid in excl}
            rows.append({**row, "compiled": True, "class": c.get("class"), "answered": len(pats),
                         "blocked": len(blocked), "excluded": len(excl)})  # fmt: skip
    by_lang: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        by_lang[r["lang"]]["lines"] += 1
        by_lang[r["lang"]]["blocked"] += int(r.get("blocked", 0))
        by_lang[r["lang"]]["excluded"] += int(r.get("excluded", 0))
        by_lang[r["lang"]]["not_compiled"] += 0 if r["compiled"] else 1
    return {
        "what": "patients the box excluded on a line the benchmark wrote (no gold row judges it): placed age and sex "
        "lines, JMED's coded age line",
        "rows": rows,
        "summary": {lang: dict(c) for lang, c in sorted(by_lang.items())},
        "patients_excluded": len(excluded_by_written),
    }


def score_unjudged(
    ids: dict[str, Any],
    pairs: list[dict[str, Any]],
    crits: list[dict[str, Any]],
    answers: dict[str, Any],
    written: dict[str, list[str]] | None = None,
    key: bytes | None = None,
) -> dict[str, Any]:
    """S3, S4 read from the answers alone (so also for a set built before ``written.json``, as launch P1b's): on a
    protocol with pair or criterion gold, a gold patient the box excluded only on compiled criteria that no gold row of
    that protocol matches (a placed age line, JMED's coded "20歳以上", a protocol line the gold does not judge): such
    an exclusion is invisible at criterion level. Per line: the patients so excluded, and their pair label (else their
    criterion labels on that protocol). A patient is counted once in the summary."""
    lang_of = ids.get("lang") or {}
    by_rs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in crits:
        if c.get("ruleset") and c.get("mrn"):
            by_rs[str(c["ruleset"])].append(c)
    label = {(str(g["ruleset"]), str(g["mrn"])): g["label"] for g in pairs if g.get("ruleset") and g.get("mrn")}
    for rs_, _m in label:
        by_rs.setdefault(rs_, [])  # a protocol with pair gold only: none of its lines has a gold row
    crit_label: dict[tuple[str, str], list[str]] = defaultdict(list)
    for c in crits:
        crit_label[(str(c.get("ruleset")), str(c.get("mrn")))].append(f"{c.get('kind')} {c.get('label')}")
    benchmark = {(rs, " ".join(x.split()).lower()) for rs, xs in (written or {}).items() for x in xs}
    lines: dict[tuple[str, str], dict[str, Any]] = {}
    per_lang: dict[str, Counter[str]] = defaultdict(Counter)
    for rs, rows in sorted(by_rs.items()):
        a = answers.get(rs) or {}
        draft, pats = a.get("draft") or [], a.get("patients") or {}
        if not pats:
            continue
        judged = {
            hit["id"]
            for t, k in {(str(r.get("text") or ""), str(r.get("kind") or "")) for r in rows}
            if (hit := match_criterion(t, draft, k)) is not None
        }
        by_id = {c.get("id"): c for c in draft}
        lang = lang_of.get(rs, "?")
        for mrn in sorted({str(r["mrn"]) for r in rows} | {m for (r_, m) in label if r_ == rs}):
            p = pats.get(pid_of(mrn, key))
            if not p or p.get("tier") != "excluded":
                continue
            fails = [v.get("id") for v in p.get("verdicts") or [] if v.get("verdict") == "fail"]
            if not fails or set(fails) & judged:
                continue
            gl = label.get((rs, mrn)) or "criterion " + "; ".join(sorted(crit_label.get((rs, mrn)) or ["none"]))
            per_lang[lang]["patients_excluded"] += 1
            per_lang[lang][f"gold {gl}"] += 1
            per_lang[lang]["on an age line"] += int(any(_is_age_line(by_id.get(cid) or {}) for cid in fails))
            for cid in fails:
                c = by_id.get(cid) or {"id": cid}
                text = str(c.get("text") or cid)
                row = lines.setdefault((rs, str(cid)), {
                    "ruleset": rs, "lang": lang, "id": cid, "kind": c.get("kind"), "class": c.get("class"),
                    "line": text, "age_line": _is_age_line(c),
                    "written_by_the_benchmark": (rs, " ".join(text.split()).lower()) in benchmark if written else None,
                    "excluded": 0, "by_gold": Counter()})  # fmt: skip
                row["excluded"] += 1
                row["by_gold"][gl] += 1
    out_rows = [{**r, "by_gold": dict(r["by_gold"])} for _, r in sorted(lines.items())]
    return {
        "what": "gold patients the box excluded only on lines no gold row judges (placed age and sex lines, JMED's "
        "coded age line, protocol lines without a gold row), read from the answers",
        "rows": out_rows,
        "summary": {lang: dict(c) for lang, c in sorted(per_lang.items())},
        "patients_excluded": sum(c["patients_excluded"] for c in per_lang.values()),
    }


# ---------------------------------------------------------------- the pathology figure (TCGA)
def score_pathology(
    ids: dict[str, Any], pairs: list[dict[str, Any]], answers: dict[str, Any] | None, key: bytes | None = None
) -> dict[str, Any]:
    """The PoC-1 pathology figure (b266f9b7: "on 500 public pathology reports the pair excluded 384 of 450, with 0
    wrong exclusions, and lost 0 of 50 eligible patients"), over the protocols screened: reports answered, ineligible
    pairs excluded n of N, wrong exclusions k of the box's exclusions, eligible pairs lost n of N. D-1108: nothing
    screened, no pair answered or no verdict is "not scored", with the reason."""
    rss = sorted(set((ids.get("rulesets") or {}).values()))
    head: dict[str, Any] = {"protocols_in_set": len(rss)}
    if answers is None:
        return {**head, "scored": False, "not_scored_because": "no answers.json: the set did not run"}
    st = statuses(ids, answers)
    screened = [rs for rs in rss if st[rs][0] == "screened"]
    head["protocols_screened"] = screened
    if not screened:
        by = Counter(st[rs][0] for rs in rss)
        stray = sorted(rs for rs in answers if rs not in rss)
        why = f"0 of {len(rss)} protocols screened (" + ", ".join(f"{k}: {n}" for k, n in sorted(by.items())) + ")"
        if stray:
            why += f"; answers for rulesets not in the set: {', '.join(stray[:5])} (a wrong ruleset prefix or tag?)"
        return {**head, "scored": False, "not_scored_because": why}
    c: Counter[str] = Counter()
    reports: set[str] = set()
    decided = 0
    weighted_set = any("inclusion_probability" in g for g in pairs)
    el_u: list[tuple[int, dict[str, Any]]] = []
    ex_u: list[tuple[int, dict[str, Any]]] = []
    wrong_u: list[tuple[int, dict[str, Any]]] = []
    open_u: list[tuple[int, dict[str, Any]]] = []
    for g in pairs:
        if g.get("ruleset") not in screened or g.get("label") not in ("eligible", "excluded") or not g.get("mrn"):
            continue
        got, p = answer_of(answers, g["ruleset"], pid_of(g["mrn"], key))
        c[f"{g['label']}:{got}"] += 1
        if p is not None:
            reports.add(str(g["mrn"]))
            decided += _decided(p)
        if weighted_set and got in ("excluded", "listed", "open"):
            (el_u if g["label"] == "eligible" else ex_u).append((int(got == "excluded"), g))
            if got == "excluded":
                wrong_u.append((int(g["label"] == "eligible"), g))
            open_u.append((int(got == "open"), g))
    n_el = sum(c[f"eligible:{x}"] for x in ("excluded", "listed", "open"))
    n_ex = sum(c[f"excluded:{x}"] for x in ("excluded", "listed", "open"))
    lost, caught = c["eligible:excluded"], c["excluded:excluded"]
    head |= {"reports": len(reports), "pairs_answered": n_el + n_ex,
             "pairs_unanswered": c["eligible:unanswered"] + c["excluded:unanswered"]}  # fmt: skip
    if n_el + n_ex == 0:
        return {**head, "scored": False, "not_scored_because": "the screened protocols answered none of the gold pairs"}
    if decided == 0:
        return {**head, "scored": False,
                "not_scored_because": "SCREEN gave no verdict for any answered pair and excluded none"}  # fmt: skip
    fig = {
        "ineligible_excluded": rate(caught, n_ex),
        "wrong_exclusions": rate(lost, lost + caught),
        "eligible_lost": rate(lost, n_el),
        "left_open": rate(c["eligible:open"] + c["excluded:open"], n_el + n_ex),
    }
    if weighted_set:  # card 10G-37: same counts; the estimate is inverse-probability weighted
        fig = {
            "ineligible_excluded": _same_counts(
                fig["ineligible_excluded"],
                _proportion(ex_u, ids, "ineligible_excluded", None, 1),
                "ineligible_excluded",
            ),
            "wrong_exclusions": _same_counts(
                fig["wrong_exclusions"], _proportion(wrong_u, ids, "wrong_exclusions", None, 1), "wrong_exclusions"
            ),
            "eligible_lost": _same_counts(
                fig["eligible_lost"], _proportion(el_u, ids, "eligible_lost", None, 1), "eligible_lost"
            ),
            "left_open": _same_counts(fig["left_open"], _proportion(open_u, ids, "left_open", None, 1), "left_open"),
        }
    return {
        **head,
        "scored": True,
        **fig,
        "figure": f"on {len(reports)} public pathology reports ({len(screened)} of {len(rss)} protocols screened) "
        f"the pair excluded {caught} of {n_ex}, with {lost} wrong exclusions, and lost {lost} of {n_el} eligible "
        "patients",
    }


# ---------------------------------------------------------------- compile level
def class_split(draft: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(c.get("class")) for c in draft))


def _age(draft: list[dict[str, Any]]) -> list[Any]:
    return sorted(
        json.dumps((c.get("logic") or {}).get("age"), sort_keys=True)
        for c in draft
        if (c.get("logic") or {}).get("domain") == "demographic" and (c.get("logic") or {}).get("age")
    )


def score_compile_pairs(ids: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """The same trial in two languages: criteria counts, class split, age limits, per pair and summed."""
    rows = []
    done: set[str] = set()
    for rs, other in sorted((ids.get("pair_of") or {}).items()):
        if rs in done or ids["lang"].get(rs) == "en":
            continue
        done |= {rs, other}
        a, b = (answers.get(rs) or {}).get("draft") or [], (answers.get(other) or {}).get("draft") or []
        sa, sb = class_split(a), class_split(b)
        rows.append(
            {
                "local": rs,
                "lang": ids["lang"].get(rs),
                "en": other,
                "n_local": len(a),
                "n_en": len(b),
                "class_local": sa,
                "class_en": sb,
                "age_local": _age(a),
                "age_en": _age(b),
                "age_agree": _age(a) == _age(b),
                "structured_share_gap": round(
                    abs(sa.get("structured", 0) / (len(a) or 1) - sb.get("structured", 0) / (len(b) or 1)), 3
                ),
            }
        )
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_lang[str(r["lang"])].append(r)
    summary = {
        lang: {
            "pairs": len(rs),
            "both_compiled": sum(1 for r in rs if r["n_local"] and r["n_en"]),
            "age_agree": rate(sum(r["age_agree"] for r in rs), len(rs)),
            "mean_structured_share_gap": round(sum(r["structured_share_gap"] for r in rs) / len(rs), 3),
        }
        for lang, rs in by_lang.items()
    }
    return {"rows": rows, "summary": summary}


STRUCTURABLE = {"measurement", "value", "person"}


def score_chia(built: Path, answers: dict[str, Any]) -> dict[str, Any]:
    """Per Chia line matched to a compiled criterion: does the class agree with the annotation? A line with a
    measurement, a value or a person (age, sex) is structurable; one with only a condition, drug or procedure is a
    coded or note criterion. Reported as agreement of "structured" with "structurable"."""
    gold = json.loads((built / "gold" / "compile_gold.json").read_text(encoding="utf-8"))
    agree, n, unmatched = 0, 0, 0
    for rs, kinds in gold.items():
        draft = (answers.get(rs) or {}).get("draft") or []
        for kind, lines in kinds.items():
            for ln in lines:
                c = match_criterion(ln["text"], draft, "inclusion" if kind == "inc" else "exclusion")
                if c is None:
                    unmatched += 1
                    continue
                n += 1
                structurable = bool(set(ln["features"]) & STRUCTURABLE)
                agree += structurable == (c.get("class") in ("structured", "mixed"))
    return {"class_agreement": rate(agree, n), "unmatched_lines": unmatched}


def score(built: Path, work: Path, key: bytes | None = None) -> dict[str, Any]:
    if not (work / "answers.json").exists():  # D-1108: a set that did not run is "not scored", by name
        ids = json.loads((built / "gold" / "ids.json").read_text(encoding="utf-8"))
        miss: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "set": ids.get("set"),
                                "gold_kind": gold_kind.of_set(ids.get("set")),  # 10G-38, D-1326
                                "not_scored_because": "no answers.json: the set did not run",
                                "protocols": score_protocols(ids, {})}  # fmt: skip
        miss["answer_key"] = answer_keys.describe(built)
        if ids.get("set") == "tcga":
            miss["pathology"] = score_pathology(ids, [], None, key)
        return miss
    ids, pairs, crits, answers = load(built, work)
    clock: dict[str, Any] | None = None
    if (work / "set-clock.json").exists():  # D-1129: the set's attempts (the clock of the run's own folder)
        try:
            clock = json.loads((work / "set-clock.json").read_text(encoding="utf-8"))
        except ValueError:
            clock = None
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "set": ids.get("set"),
        "gold_kind": gold_kind.of_set(ids.get("set")),  # 10G-38 (D-1326): what the gold is; None: not stated
        "what": "joined by ids after the run; the gold was not in the box",
        "answer_key": answer_keys.describe(built),  # D-1104: every score names the key it was scored on
    }
    out["protocols"] = score_protocols(ids, answers, clock if isinstance(clock, dict) else None)
    if ids.get("set") == "tcga":
        out["pathology"] = score_pathology(ids, pairs, answers, key)
    if pairs:
        out["pairs"] = score_pairs(ids, pairs, answers, key, crits, answer_keys.conflicted_of(built))
    if crits:
        sents = None
        if ids.get("set") == "sigir":
            from tools.public_accuracy.sets import CRITERION_ML

            sents = json.loads((CRITERION_ML / "notes_en.json").read_text(encoding="utf-8"))
        out["criteria"] = score_criteria(ids, crits, answers, sents, key)
    wf = built / "gold" / "written.json"
    if wf.exists():  # S3, S4 (a set built before the file existed has no such row)
        written = json.loads(wf.read_text(encoding="utf-8"))
        if written:
            out["written_lines"] = score_written(ids, written, answers, crits)
    if crits:
        out["unjudged_exclusions"] = score_unjudged(
            ids, pairs, crits, answers, json.loads(wf.read_text(encoding="utf-8")) if wf.exists() else None, key
        )
    if ids.get("pair_of"):
        out["compile_pairs"] = score_compile_pairs(ids, answers)
    if (built / "gold" / "compile_gold.json").exists() and json.loads(
        (built / "gold" / "compile_gold.json").read_text(encoding="utf-8")
    ):
        out["chia"] = score_chia(built, answers)
    from tools.public_accuracy.ladder import ladder  # card 10A-3: the decided share beside every figure

    out["ladder"] = ladder(ids, answers, work=work, key=key)
    drafts = [c for a in answers.values() for c in a.get("draft") or []]
    out["compiled"] = {
        "protocols": len(answers),
        "criteria": len(drafts),
        "class_split": class_split(drafts),
        "screened": sum(1 for a in answers.values() if a.get("screen") == "done"),
    }
    # a set with gold rows the box answered none of has no figure (Gate C: "not scored, because"), never a 0 %
    why = not_scored_because(out)
    if why:
        out["not_scored_because"] = why
    return out


def not_scored_because(out: dict[str, Any]) -> str | None:
    """Why a scored folder has no figure, or None. Pair and criterion sets need a protocol screened (D-1108) and
    answered rows; compile sets need compiled criteria; the pathology set needs its figure."""
    if "pairs" in out or "criteria" in out:
        pr = out.get("protocols") or {}
        if pr and not pr.get("screened"):
            return (
                f"0 of {pr.get('in_set')} protocols screened (failed before SCREEN {pr.get('failed_before_screen')}, "
                f"in SCREEN {pr.get('failed_in_screen')}, time budget {pr.get('not_run_time_budget')}, not in "
                f"answers.json {pr.get('not_in_answers')})"
            )
        if pr and pr.get("patients_answered") and not pr.get("patients_decided"):
            return (
                f"{pr.get('screened')} protocols screened, but SCREEN gave no verdict for any patient and excluded none"
            )
        if (out.get("pathology") or {}).get("scored") is False:
            return str(out["pathology"]["not_scored_because"])
        n = int((out.get("criteria") or {}).get("answered") or 0)
        n += sum(int(v.get("answered") or 0) for v in ((out.get("pairs") or {}).get("summary") or {}).values())
        if n == 0:
            return "the box answered none of the set's gold rows (no SCREEN finished for them)"
        return None
    if not (out.get("compiled") or {}).get("criteria"):
        return "the box compiled no criteria"
    return None
