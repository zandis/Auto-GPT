"""Report-level disclosure control for DL-1 (spec v4 §12.2.3 profiles and order of operations, §7.8; RPT-05/06/07).

Profiles (selected by the recipient class, RPT-05):

=================  ==================  ======================  ==================
profile            recipient class     primary suppression     rounding
=================  ==================  ======================  ==================
``dc.sponsor``     external_sponsor    1–10 → ``<11`` (k 11)   nearest 5
``dc.internal``    internal            1–4 → ``<5`` (k 5)      nearest 5
=================  ==================  ======================  ==================

Zero is shown. Every count is rounded independently; difference counts ("excluded at step i") are computed from the
exact values and then rounded, never by subtracting rounded values (step 3). Interval endpoints are floored and ceiled
to base 5 (CAS-8). Percentages derive from unrounded values and are published only when ``rate_publishable(k)``
holds (step 5). Arithmetic is Decimal (§17.2: no floats in reported counts).

:class:`DisclosureTrace` records the eight steps; :func:`require_complete` is what renderers call (RPT-06).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

Released = int | str

ORDER: tuple[str, ...] = (
    "exact_aggregates",
    "primary_suppression",
    "independent_rounding",
    "complementary_suppression",
    "rates_from_unrounded",
    "no_reason_by_demographic_below_k",
    "differencing_check",
    "freeze_hash",
)


class DisclosureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    version: str
    k: int  # small-cell threshold: 1..k-1 suppressed
    base: int  # controlled rounding base

    @property
    def suppressed_label(self) -> str:
        return f"<{self.k}"

    @property
    def complementary_label(self) -> str:
        """Marker of a complementary suppression (step 4): the value is withheld, whatever its size."""
        return "x"


SPONSOR = Profile("dc.sponsor", "1.0.0", 11, 5)
INTERNAL = Profile("dc.internal", "1.0.0", 5, 5)
PROFILES: dict[str, Profile] = {p.name: p for p in (SPONSOR, INTERNAL)}
RECIPIENT_PROFILE: dict[str, str] = {"external_sponsor": "dc.sponsor", "internal": "dc.internal"}


def profile_for(recipient_class: str) -> Profile:
    """RPT-05: the recipient class selects the profile; the author does not."""
    try:
        return PROFILES[RECIPIENT_PROFILE[recipient_class]]
    except KeyError as exc:
        raise DisclosureError(f"no disclosure profile for recipient class {recipient_class!r}") from exc


def round_base(n: int, base: int) -> int:
    """Nearest multiple of ``base`` (half up), Decimal arithmetic."""
    return int((Decimal(n) / Decimal(base)).quantize(Decimal(1), rounding=ROUND_HALF_UP) * base)


def release(n: int, p: Profile) -> Released:
    """Primary suppression then independent controlled rounding of one exact count."""
    if n < 0:
        raise DisclosureError("negative count")
    if n == 0:
        return 0
    if n < p.k:
        return p.suppressed_label
    return round_base(n, p.base)


def floor_base(x: float, base: int) -> int:
    return int((Decimal(str(x)) / base).to_integral_value(rounding=ROUND_FLOOR) * base)


def ceil_base(x: float, base: int) -> int:
    return int((Decimal(str(x)) / base).to_integral_value(rounding=ROUND_CEILING) * base)


def rate_publishable(numerator: int, denominator: int, k: int) -> bool:
    """Numerator, complement and denominator each 0 or ≥ k (§12.2.3 step 5)."""
    rest = denominator - numerator
    return all(v == 0 or v >= k for v in (numerator, rest, denominator)) and denominator > 0


def pct(numerator: int, denominator: int, p: Profile) -> float | None:
    """A percentage from unrounded values, or None when it would reveal a small cell."""
    if not rate_publishable(numerator, denominator, p.k):
        return None
    return float((Decimal(100 * numerator) / Decimal(denominator)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def released_ok(value: Released, p: Profile) -> bool:
    if isinstance(value, str):
        return value in (p.suppressed_label, p.complementary_label)
    return value == 0 or (value >= p.k - (p.base // 2) and value % p.base == 0)


def interval_of(value: Released, p: Profile) -> tuple[int, int]:
    """Exact values consistent with one released value (what an attacker knows about it)."""
    if value == p.complementary_label:
        return 0, 10**12
    if isinstance(value, str):
        return 1, p.k - 1
    if value == 0:
        return 0, 0
    lo, hi = value - p.base // 2, value + (p.base - 1) // 2
    if p.base % 2 == 0:
        lo = value - p.base // 2
        hi = value + p.base // 2 - 1
    return max(lo, p.k), hi


def funnel_recovery(released_remaining: list[Released], released_dropped: list[Released], p: Profile) -> list[int]:
    """Indices of suppressed cells of a released funnel that the neighbouring released cells pin to one exact value.

    For a funnel r_0 ≥ r_1 ≥ … with drops d_i = r_{i-1} − r_i, each released cell is an interval; propagating
    r_i = r_{i-1} − d_i in both directions narrows the intervals. A suppressed cell whose interval shrinks to a single
    value is recoverable (RPT-07)."""
    n = len(released_remaining)
    r = [interval_of(v, p) for v in released_remaining]
    d = [(0, 0)] + [interval_of(v, p) for v in released_dropped[1:]]
    for _ in range(4 * n):
        changed = False
        for i in range(1, n):
            lo = max(r[i][0], r[i - 1][0] - d[i][1])
            hi = min(r[i][1], r[i - 1][1] - d[i][0])
            plo = max(r[i - 1][0], r[i][0] + d[i][0])
            phi = min(r[i - 1][1], r[i][1] + d[i][1])
            dlo = max(d[i][0], r[i - 1][0] - r[i][1])
            dhi = min(d[i][1], r[i - 1][1] - r[i][0])
            if (lo, hi) != r[i] or (plo, phi) != r[i - 1] or (dlo, dhi) != d[i]:
                r[i], r[i - 1], d[i] = (lo, hi), (plo, phi), (dlo, dhi)
                changed = True
        if not changed:
            break
    out = []
    small = p.suppressed_label
    for i in range(n):
        if released_remaining[i] == small and r[i][0] == r[i][1]:
            out.append(i)
        if i and released_dropped[i] == small and d[i][0] == d[i][1]:
            out.append(i)
    return sorted(set(out))


def complementary(
    remaining: list[Released], dropped: list[Released], p: Profile, max_rounds: int = 200
) -> tuple[list[Released], list[Released], list[str]]:
    """Step 4 for a funnel: while a suppressed cell is recoverable from its neighbours, withhold (``x``) the
    neighbouring released cell whose withholding removes the most recoveries (greedy; smallest index on ties).
    Returns the new columns and the cells added, e.g. ``["n_remaining[9]", "n_excluded[10]"]``."""
    rem, drop = list(remaining), list(dropped)
    added: list[str] = []
    x = p.complementary_label
    for _ in range(max_rounds):
        rec = funnel_recovery(rem, drop, p)
        if not rec:
            return rem, drop, added
        cands: list[tuple[str, int]] = []
        for i in rec:
            for j in (i - 1, i, i + 1):
                if 0 < j < len(rem) and rem[j] != x and not (isinstance(rem[j], str)):
                    cands.append(("n_remaining", j))
                if 0 < j < len(drop) and drop[j] != x and not isinstance(drop[j], str):
                    cands.append(("n_excluded", j))
        if not cands:
            raise DisclosureError(f"cannot protect suppressed funnel cells {rec}")
        best: tuple[int, str, int] | None = None
        for col, j in sorted(set(cands), key=lambda c: (c[1], c[0])):
            trial_r, trial_d = list(rem), list(drop)
            (trial_r if col == "n_remaining" else trial_d)[j] = x
            left = len(funnel_recovery(trial_r, trial_d, p))
            if best is None or left < best[0]:
                best = (left, col, j)
        assert best is not None
        _, col, j = best
        (rem if col == "n_remaining" else drop)[j] = x
        added.append(f"{col}[{j}]")
    raise DisclosureError("complementary suppression did not converge")


@dataclass
class DisclosureTrace:
    """The ``disclosure_trace`` of a data object (§12.2.3): one entry per step, in order."""

    profile: str
    profile_version: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def add(self, step: str, **detail: Any) -> None:
        expected = ORDER[len(self.steps)] if len(self.steps) < len(ORDER) else None
        if step != expected:
            raise DisclosureError(f"disclosure step {step!r} out of order (expected {expected!r})")
        self.steps.append({"step": step, **detail})

    @property
    def complete(self) -> bool:
        return [s["step"] for s in self.steps] == list(ORDER)

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile, "profile_version": self.profile_version, "steps": self.steps}


def require_complete(trace: dict[str, Any]) -> None:
    """RPT-06: renderers refuse an object whose ``disclosure_trace`` is incomplete or out of order."""
    steps = [s.get("step") for s in trace.get("steps", [])]
    if steps != list(ORDER):
        raise DisclosureError(f"disclosure_trace incomplete or out of order: {steps}")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def sha256(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(obj)).hexdigest()


__all__ = [
    "INTERNAL",
    "ORDER",
    "PROFILES",
    "SPONSOR",
    "DisclosureError",
    "DisclosureTrace",
    "Profile",
    "Released",
    "canonical",
    "ceil_base",
    "complementary",
    "floor_base",
    "funnel_recovery",
    "interval_of",
    "pct",
    "profile_for",
    "rate_publishable",
    "release",
    "released_ok",
    "require_complete",
    "round_base",
    "sha256",
]
