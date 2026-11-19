"""Sampling weights for an audited or actively sampled set (plan 10 card 10G-37, D-1334).

A set whose gold rows are a sample of a larger frame, not the whole frame, declares the draw in ``ids.json``::

    "sampling": {"unit": "pair",                         # or "criterion": the gold file the draw is over
                 "strata": {"rare": 10,                   # frame size of the stratum, a positive integer
                            "common": {"frame": 990, "lang": "en"}}}   # or with the stratum's one language

and every row of that gold file (``pairs.jsonl`` or ``criteria.jsonl``) names its stratum in ``sampling_stratum``.
The design read here is a stratified simple random sample without replacement: within a stratum every unit had the
same chance to be drawn. A Bernoulli draw with one probability per stratum is also such a sample once its drawn
count is known, so the method conditions on the drawn count ``n_h`` of each stratum and never needs a probability per
row. A draw whose probability differs row by row inside one stratum is not this design; write each probability as its
own stratum.

The estimate. A unit's weight is ``N_h / n_h``. A rate is a share of a domain (eligible lost: of the eligible pairs
the box answered), and the domain is read from this run's answers on the drawn rows, so a replay that answers or
excludes other rows gets its own domain and never a stored one. The estimated events ``Y = sum_h N_h e_h / n_h`` and
the estimated domain ``X = sum_h N_h d_h / n_h`` are unbiased for the frame's counts; the rate is ``Y / X`` (a ratio of
two unbiased totals: consistent, not exactly unbiased; when the domain is the whole frame it is ``Y / N`` and
unbiased). A stratum with frame units and no draw has no estimate: the rate and both totals are then None, with the
reason, and only the interval is reported.

The interval is conservative and holds for every frame, however rare the events. For each stratum that was sampled
but not in full, an exact two-sided hypergeometric interval for its count of domain events and one for its count of
domain non-events; a stratum drawn in full has its counts exactly, and a stratum with no draw has each count anywhere
from 0 to its frame size. With ``m`` strata sampled but not in full, each of the ``2m`` intervals has level
``1 - alpha / (2m)``, so all hold together with probability at least ``1 - alpha`` (Bonferroni). The rate's interval is
the rate's range over that box: ``[Y_lo / (Y_lo + Z_hi), Y_hi / (Y_hi + Z_lo)]``, rounded outward. It is wide where
the draw says little (an undrawn rare stratum), and it can be much wider than nominal with many strata; it is never
narrower than the draw supports. ``tests/unit/test_sampling_weights_10g37.py`` shows its coverage by a seeded
simulation; the limits are on the card's page (``docs/handover/sampling-weights-2026-11-19.md``).

A set with no ``sampling`` is scored exactly as before: this module writes nothing for it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from fractions import Fraction
from typing import Any

#: the largest frame size of one stratum: the hypergeometric tails are summed in log space with ``lgamma``, exact
#: enough to this size; a larger stratum is refused with that reason
MAX_FRAME = 10**7

ALPHA = 0.05

METHOD = (
    "stratified simple random sample (each stratum's drawn count known): weight N_h/n_h per row; the rate is the "
    "ratio of the weighted totals; the 95 % interval is conservative: exact hypergeometric bounds per stratum on the "
    "domain's events and non-events, Bonferroni over the strata sampled but not in full; an undrawn stratum spans 0 "
    "to its frame"
)

UNITS = ("pair", "criterion")


class Design:
    """A read and checked ``sampling`` declaration: per stratum its frame size, its drawn count and its language."""

    def __init__(self, unit: str, frames: dict[str, int], langs: dict[str, str], drawn: dict[str, int]) -> None:
        self.unit, self.frames, self.langs, self.drawn = unit, frames, langs, drawn

    def describe(self) -> dict[str, Any]:
        strata = {
            h: {"frame": n, "drawn": self.drawn.get(h, 0), **({"lang": self.langs[h]} if h in self.langs else {})}
            for h, n in sorted(self.frames.items())
        }
        return {
            "unit": self.unit,
            "strata": strata,
            "frame": sum(self.frames.values()),
            "drawn": sum(self.drawn.values()),
            "undrawn_strata": sorted(h for h in self.frames if not self.drawn.get(h)),
        }


def _positive_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def read_design(ids: Mapping[str, Any], rows_by_unit: Mapping[str, list[dict[str, Any]]]) -> Design | str | None:
    """The set's declared draw, or a reason it is refused (a string), or None when the set declares no draw.

    ``rows_by_unit``: the gold rows of each unit (``{"pair": pairs, "criterion": crits}``). A refusal is reported in
    place of every weighted figure; the unweighted figures are kept beside it, labelled as the sample."""
    s = ids.get("sampling")
    if s is None:
        return None
    if not isinstance(s, dict):
        return "sampling must be an object with unit and strata"
    unit = s.get("unit")
    if unit not in UNITS:
        return f"sampling.unit must be one of {', '.join(UNITS)}, got {unit!r}"
    strata = s.get("strata")
    if not isinstance(strata, dict) or not strata:
        return "sampling.strata must name at least one stratum and its frame size"
    frames: dict[str, int] = {}
    langs: dict[str, str] = {}
    for h, v in strata.items():
        size, lang = (v.get("frame"), v.get("lang")) if isinstance(v, dict) else (v, None)
        if not isinstance(size, int) or not _positive_int(size):
            return f"sampling.strata.{h}: the frame size must be a positive integer, got {size!r}"
        if size > MAX_FRAME:
            return f"sampling.strata.{h}: a frame of {size} is larger than this scorer computes exactly ({MAX_FRAME})"
        if lang is not None and not isinstance(lang, str):
            return f"sampling.strata.{h}: lang must be a language code, got {lang!r}"
        frames[str(h)] = size
        if lang:
            langs[str(h)] = lang
    rows = rows_by_unit.get(unit) or []
    drawn: dict[str, int] = {}
    seen: set[tuple[str, ...]] = set()
    for i, r in enumerate(rows):
        h = r.get("sampling_stratum")
        if not isinstance(h, str) or h not in frames:
            return (
                f"gold {unit} row {i + 1}: sampling_stratum {h!r} is not a declared stratum "
                f"({', '.join(sorted(frames))}); every row of a sampled set names its stratum"
            )
        ident = (str(r.get("mrn")), str(r.get("ruleset")), str(r.get("kind", "")), str(r.get("text", "")))
        if ident in seen:
            return f"gold {unit} row {i + 1}: the same unit twice in the sample; a unit is drawn at most once"
        seen.add(ident)
        drawn[h] = drawn.get(h, 0) + 1
    for h, n in drawn.items():
        if n > frames[h]:
            return f"sampling.strata.{h}: {n} rows drawn from a frame of {frames[h]}"
    return Design(unit, frames, langs, drawn)


# ---------------------------------------------------------------- exact hypergeometric bounds
def _log_pmf(x: int, n: int, m: int, total: int) -> float:
    """log P(X = x), X the successes in n draws without replacement from ``total`` units of which ``m`` succeed."""

    def lc(a: int, b: int) -> float:
        return math.lgamma(a + 1) - math.lgamma(b + 1) - math.lgamma(a - b + 1)

    return lc(m, x) + lc(total - m, n - x) - lc(total, n)


def _tail_le(k: int, n: int, m: int, total: int) -> float:
    lo, hi = max(0, n - (total - m)), min(n, m)
    if k < lo:
        return 0.0
    if k >= hi:
        return 1.0
    return min(1.0, math.fsum(math.exp(_log_pmf(x, n, m, total)) for x in range(lo, k + 1)))


def _tail_ge(k: int, n: int, m: int, total: int) -> float:
    lo, hi = max(0, n - (total - m)), min(n, m)
    if k <= lo:
        return 1.0
    if k > hi:
        return 0.0
    return min(1.0, math.fsum(math.exp(_log_pmf(x, n, m, total)) for x in range(k, hi + 1)))


def hypergeometric_bounds(k: int, n: int, total: int, tail: float) -> tuple[int, int]:
    """Exact bounds for the count ``M`` of successes in a frame of ``total`` units, from ``k`` successes in a simple
    random sample of ``n``: each side misses with probability at most ``tail``. ``n == 0`` gives ``[0, total]`` and
    ``n == total`` gives ``[k, k]``."""
    if n == 0:
        return 0, total
    if n == total:
        return k, k
    first, last = k, total - (n - k)
    # lower: the smallest M whose P(X >= k) exceeds the tail (that probability rises with M)
    lower = first
    if k > 0:
        a, b = first, last
        while a < b:
            mid = (a + b) // 2
            if _tail_ge(k, n, mid, total) > tail:
                b = mid
            else:
                a = mid + 1
        lower = a
    # upper: the largest M whose P(X <= k) exceeds the tail (that probability falls with M)
    upper = last
    if k < n:
        a, b = first, last
        while a < b:
            mid = (a + b + 1) // 2
            if _tail_le(k, n, mid, total) > tail:
                a = mid
            else:
                b = mid - 1
        upper = a
    return lower, upper


# ---------------------------------------------------------------- one weighted rate
def _floor4(x: Fraction) -> float:
    return math.floor(x * 10000) / 10000


def _ceil4(x: Fraction) -> float:
    return math.ceil(x * 10000) / 10000


def weighted_totals(units: Iterable[tuple[str, bool, bool]], design: Design) -> tuple[Fraction, Fraction] | None:
    """The exact weighted totals ``(events, domain)``, ``sum_h N_h c_h / n_h``; None when a stratum was not drawn."""
    if any(not design.drawn.get(h) for h in design.frames):
        return None
    y = x = Fraction(0)
    for h, dom, ev in units:
        if dom:
            w = Fraction(design.frames[h], design.drawn[h])
            x += w
            y += w if ev else 0
    return y, x


def estimate(
    units: Iterable[tuple[str, bool, bool]],
    design: Design,
    *,
    lang: str | None = None,
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """One weighted rate. ``units`` is every drawn row of the set, as ``(stratum, in the domain, an event)``; a row
    outside the rate's domain still counts as drawn. ``lang``: the rate is of one language, so a stratum declared for
    another language holds none of its domain.

    ``k`` and ``n`` are the sample's own counts (the events and the domain among the drawn rows)."""
    events: dict[str, int] = {}
    nonevents: dict[str, int] = {}
    for h, dom, ev in units:
        if dom:
            (events if ev else nonevents)[h] = (events if ev else nonevents).get(h, 0) + 1
    strata = [h for h in sorted(design.frames) if lang is None or design.langs.get(h) in (None, lang)]
    partial = [h for h in strata if 0 < design.drawn.get(h, 0) < design.frames[h]]
    tail = alpha / (4 * len(partial)) if partial else 0.0
    y_lo = y_hi = z_lo = z_hi = 0
    y_est = x_est = Fraction(0)
    undrawn: list[str] = []
    for h in strata:
        big, n = design.frames[h], design.drawn.get(h, 0)
        e, d = events.get(h, 0), nonevents.get(h, 0)
        if n == 0:
            undrawn.append(h)
        else:
            y_est += Fraction(big * e, n)
            x_est += Fraction(big * (e + d), n)
        e_lo, e_hi = hypergeometric_bounds(e, n, big, tail)
        d_lo, d_hi = hypergeometric_bounds(d, n, big, tail)
        y_lo, y_hi, z_lo, z_hi = y_lo + e_lo, y_hi + e_hi, z_lo + d_lo, z_hi + d_hi
    k, n_dom = sum(events.values()), sum(events.values()) + sum(nonevents.values())
    if y_hi + z_hi == 0:
        lo, hi = 0.0, 1.0  # the domain is empty in the whole frame: there is no share to bound
    else:
        lo = 0.0 if y_lo == 0 else _floor4(Fraction(y_lo, y_lo + z_hi))
        hi = 0.0 if y_hi == 0 else _ceil4(Fraction(y_hi, y_hi + z_lo))
    out: dict[str, Any] = {
        "k": k,
        "n": n_dom,
        "rate": None,
        "ci95": [lo, hi],
        "weighted": True,
        "estimated_events": None,
        "estimated_in_domain": None,
        "events_in_frame": [y_lo, y_hi],
        "non_events_in_frame": [z_lo, z_hi],
        "frame": sum(design.frames[h] for h in strata),
        "drawn": sum(design.drawn.get(h, 0) for h in strata),
        "undrawn_strata": undrawn,
    }
    if undrawn:
        out["rate_not_estimated_because"] = (
            f"no row was drawn from {', '.join(undrawn)} ({sum(design.frames[h] for h in undrawn)} frame units): "
            "the frame's share cannot be estimated, only bounded"
        )
        return out
    out["estimated_events"] = round(float(y_est), 4)
    out["estimated_in_domain"] = round(float(x_est), 4)
    if x_est == 0:
        out["rate_not_estimated_because"] = "no drawn row is in this rate's domain"
        return out
    out["rate"] = round(float(y_est / x_est), 4)
    return out


def proven_zero(block: Mapping[str, Any]) -> bool:
    """The sample shows no event in the whole frame (the interval's upper end is 0) and a domain was drawn."""
    ci = block.get("ci95") or [0.0, 1.0]
    return bool(block.get("n")) and ci[1] == 0.0


# ---------------------------------------------------------------- the rates of a set
Rule = Callable[[dict[str, Any]], tuple[bool, bool]]


def rates(
    rows: list[dict[str, Any]], design: Design, rules: Mapping[str, Rule], lang: str | None = None
) -> dict[str, dict[str, Any]]:
    """Each rule maps one drawn row (as the scorer read it) to (in the domain, an event)."""
    return {
        name: estimate(((r["sampling_stratum"], *rule(r)) for r in rows), design, lang=lang)
        for name, rule in rules.items()
    }


def pair_rules(lang: str | None, conflicted: bool) -> dict[str, Rule]:
    """The pair rates of :func:`tools.public_accuracy.score.summarise`, over the drawn rows. A row is
    ``{"lang", "label", "got", "marked", "keyed"}`` (``keyed``: it has an mrn and a ruleset)."""

    def mine(r: dict[str, Any]) -> bool:
        return bool(r["keyed"]) and (lang is None or r["lang"] == lang) and r["label"] in ("eligible", "excluded")

    def answered(r: dict[str, Any]) -> bool:
        return mine(r) and r["got"] != "unanswered"

    out: dict[str, Rule] = {
        "eligible_lost": lambda r: (answered(r) and r["label"] == "eligible", r["got"] == "excluded"),
        "excluded_caught": lambda r: (answered(r) and r["label"] == "excluded", r["got"] == "excluded"),
        "wrong_exclusions": lambda r: (mine(r) and r["got"] == "excluded", r["label"] == "eligible"),
        "unanswered": lambda r: (mine(r), r["got"] == "unanswered"),
        "left_open": lambda r: (mine(r), r["got"] == "open"),
    }
    if conflicted:
        out["eligible_lost_without_conflicted"] = lambda r: (
            answered(r) and r["label"] == "eligible" and not r["marked"],
            r["got"] == "excluded",
        )
    return out


def pathology_rules() -> dict[str, Rule]:
    """The PoC-1 figure of :func:`tools.public_accuracy.score.score_pathology`. A row is ``{"label", "got",
    "counted"}`` (``counted``: a screened protocol, a label of eligible or excluded, an mrn)."""

    def answered(r: dict[str, Any]) -> bool:
        return bool(r["counted"]) and r["got"] in ("excluded", "listed", "open")

    return {
        "ineligible_excluded": lambda r: (answered(r) and r["label"] == "excluded", r["got"] == "excluded"),
        "wrong_exclusions": lambda r: (answered(r) and r["got"] == "excluded", r["label"] == "eligible"),
        "eligible_lost": lambda r: (answered(r) and r["label"] == "eligible", r["got"] == "excluded"),
        "left_open": lambda r: (answered(r), r["got"] == "open"),
    }


def criterion_rules(block_wrong: set[tuple[str, str]], block_right: set[tuple[str, str]]) -> dict[str, Rule]:
    """The criterion rates of :func:`tools.public_accuracy.score.score_criteria`. A row is ``{"kind", "label",
    "got"}``; answered is a block, an open verdict or no block."""

    def answered(r: dict[str, Any]) -> bool:
        return r["got"] in ("block", "open", "no_block")

    return {
        "wrong_exclusion": lambda r: (answered(r) and (r["kind"], r["label"]) in block_wrong, r["got"] == "block"),
        "caught": lambda r: (answered(r) and (r["kind"], r["label"]) in block_right, r["got"] == "block"),
    }


def frame_phrase(block: Mapping[str, Any]) -> str:
    """'an estimated 4.0 of 20.0 in the frame (95 % 0.0-0.62)', or the bound alone when there is no estimate."""
    lo, hi = block["ci95"]
    if block.get("rate") is None:
        return f"not estimated ({block.get('rate_not_estimated_because')}); 95 % bound {lo}-{hi}"
    return (
        f"an estimated {block['estimated_events']} of {block['estimated_in_domain']} in the frame of "
        f"{block['frame']} (rate {block['rate']}, 95 % {lo}-{hi})"
    )
