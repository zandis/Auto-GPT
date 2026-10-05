"""FEAS computation (SPEC §8.1): funnel, sensitivity variants, monthly new-eligible and the enrolment simulation.

Everything is computed inside the lake in one query: the ruleset's approved SQL (and, for threshold variants, SQL
rendered by the same deterministic template generator from modified IR copies) is evaluated at every month-end of
the lookback and reduced per patient. Semantics (DECISIONS D-18, D-40, D-41):

* step *k* passes at an index date when every applied criterion up to *k* passes there: inclusion ``C IS TRUE``,
  exclusion ``C IS NOT TRUE`` (unknown inclusion drops, unknown exclusion keeps);
* a patient *remains* after step *k* when the steps pass at **some** month-end of the lookback;
* ``monthly_new``: patients whose first eligible month-end falls in that month, after a 12-month wash-out;
* the simulation uses the patients eligible at the latest month-end (prevalent) plus the monthly incidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from lake.client import LakeAPI
from tb_common.ruleset import Ruleset
from tb_common.smallcell import round_count
from tb_common.timeutil import add_months, month_ends
from tb_contracts import (
    CriterionIR,
    FeasibilityResult,
    FunnelStep,
    MonthlyCount,
    SensitivityRow,
    Simulation,
)

UNKNOWN_AS_PASS = "unknown_as_pass"
WASHOUT_MONTHS = 12
CHART_MONTHS = 24


class FeasError(RuntimeError):
    pass


@dataclass(frozen=True)
class Step:
    criterion: CriterionIR
    applied: bool
    reason: str = ""  # why not applied

    @property
    def id(self) -> str:
        return self.criterion.id

    @property
    def inclusion(self) -> bool:
        return self.criterion.kind == "inclusion"

    @property
    def col(self) -> str:
        return f'"C_{self.criterion.id}"'


@dataclass(frozen=True)
class Variant:
    name: str  # e.g. "bmi=24"
    criterion_id: str
    column_id: str  # criterion id of the modified copy in the variant SQL
    ir: CriterionIR | None = None  # None for unknown_as_pass


@dataclass
class FeasParams:
    run_date: date
    snapshot: str
    lookback_months: int = 36
    departments: list[str] = field(default_factory=list)
    variants: dict[str, str] = field(default_factory=dict)  # key -> "v1,v2"
    small_cell: int = 5
    reach_rate: float = 0.6
    accept_rate: float = 0.35
    rate_source: str = "default"
    concentration: float = 20.0
    capacity_per_month: float | None = None
    months: int = 12
    iterations: int = 1000


@dataclass
class FeasRaw:
    """Unsuppressed counts (never leave the box; used for the simulation and the funnel-compare harness)."""

    start_n: int
    remaining: dict[str, int]
    unknown: dict[str, int]
    variants: dict[str, int]
    first_eligible: dict[str, int]  # YYYY-MM -> n
    prevalent: int
    index_dates: list[date]


# ---------------------------------------------------------------------------------------------- steps & variants
def steps(rs: Ruleset) -> list[Step]:
    """Funnel rows in manifest order; only structured criteria present in the approved SQL are applied."""
    out: list[Step] = []
    for c in rs.active():
        if c.kind not in ("inclusion", "exclusion"):
            continue
        if c.class_ != "structured":
            out.append(Step(c, False, f"{c.class_} criterion — not applied in counts"))
        elif f'"C_{c.id}"' not in rs.sql:
            out.append(Step(c, False, "not compiled"))
        else:
            out.append(Step(c, True))
    return out


def _walk_atoms(node: dict[str, Any]) -> list[dict[str, Any]]:
    if "args" in node:
        return [a for arg in node["args"] for a in _walk_atoms(arg)]
    return [node]


def _numbers(spec: str) -> list[float]:
    vals: list[float] = []
    for tok in spec.split(","):
        tok = tok.strip()
        if tok:
            try:
                vals.append(float(tok))
            except ValueError as exc:
                raise FeasError(f"variant value {tok!r} is not a number") from exc
    return vals


def parse_variant_option(value: str) -> dict[str, str]:
    """``bmi:24,25,27`` -> ``{"bmi": "24,25,27"}``."""
    key, sep, vals = value.partition(":")
    if not sep or not key or not vals:
        raise FeasError(f"variant must look like key:v1,v2 (got {value!r})")
    return {key.lower() if "-" not in key else key.upper(): vals}


def build_variants(rs: Ruleset, spec: dict[str, str], applied: list[Step]) -> list[Variant]:
    """Threshold variants: ``<derived>:<values>`` (every applied atom with that derived value) or
    ``<criterion-id or INC-03>:<values>`` (the criterion's single numeric threshold)."""
    out: list[Variant] = []
    by_id = {s.id: s for s in applied if s.applied}
    n = 0
    for key, values in sorted(spec.items()):
        nums = _numbers(values)
        targets: list[Step] = []
        if "-" in key:
            cid = key if key.startswith(f"{rs.id}-") else f"{rs.id}-{key}"
            if cid not in by_id:
                raise FeasError(f"variant {key}: no applied structured criterion {cid}")
            targets = [by_id[cid]]
        else:
            targets = [
                s
                for s in by_id.values()
                if any(
                    a.get("derived") == key and (a.get("value") or {}).get("num") is not None
                    for a in _walk_atoms(s.criterion.logic.model_dump(mode="json", by_alias=True, exclude_none=True))
                )
            ]
            if not targets:
                raise FeasError(f"variant {key}: no applied criterion uses derived value {key!r}")
        for st in sorted(targets, key=lambda s: s.id):
            for num in nums:
                logic = st.criterion.logic.model_dump(mode="json", by_alias=True, exclude_none=True)
                hits = [
                    a
                    for a in _walk_atoms(logic)
                    if (a.get("value") or {}).get("num") is not None and ("-" in key or a.get("derived") == key)
                ]
                if "-" in key and len(hits) != 1:
                    raise FeasError(f"variant {key}: criterion needs exactly one numeric threshold (has {len(hits)})")
                for a in hits:
                    a["value"]["num"] = num
                n += 1
                ir = CriterionIR.model_validate(
                    {
                        **st.criterion.model_dump(mode="json", by_alias=True, exclude_none=True),
                        "id": f"V{n}-{st.id}",
                        "logic": logic,
                    }
                )
                label = key if "-" not in key else st.id.split("-", 1)[1]
                out.append(Variant(f"{label}={num:g}", st.id, ir.id, ir))
    return out


def variant_sql(rs: Ruleset, variants: list[Variant]) -> str:
    """Template-rendered SQL for the modified criterion copies (same generator as the approved SQL)."""
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets

    irs = [v.ir for v in variants if v.ir is not None]
    if not irs:
        return ""
    return SqlGenerator(rs.id, rs.version, ValueSets(rs.id, rs.valuesets, Terminology())).render(irs)


# ---------------------------------------------------------------------------------------------- SQL
def _pass(step: Step, col: str | None = None, unknown_as_pass: bool = False) -> str:
    c = col or step.col
    if step.inclusion:
        return f"({c} IS NOT FALSE)" if unknown_as_pass else f"({c} IS TRUE)"
    return f"({c} IS NOT TRUE)"


def funnel_query(rs: Ruleset, st: list[Step], variants: list[Variant], departments: list[str]) -> str:
    applied = [s for s in st if s.applied]
    if not applied:
        raise FeasError(f"ruleset {rs.id} has no structured criteria to count")
    vsql = variant_sql(rs, variants)
    cum: list[str] = []
    sel: list[str] = []
    agg: list[str] = []
    for i, s in enumerate(applied):
        cum.append(_pass(s))
        prev = " AND ".join(cum[:-1]) or "TRUE"
        sel.append(f"({' AND '.join(cum)}) AS f{i}")
        # reached the step / had a known FALSE value there (unknown attribution, DECISIONS D-18)
        sel.append(f"({prev}) AS r{i}")
        sel.append(f"(({prev}) AND {s.col} IS FALSE) AS u{i}")
        agg.append(f"bool_or(f{i}) AS f{i}")
        agg.append(f"bool_or(r{i}) AS r{i}")
        agg.append(f"bool_or(u{i}) AS u{i}")
    last = len(applied) - 1
    for j, v in enumerate(variants):
        parts = []
        for s in applied:
            if s.id == v.criterion_id:
                parts.append(_pass(s, f'"C_{v.column_id}"'))
            else:
                parts.append(_pass(s))
        sel.append(f"({' AND '.join(parts)}) AS w{j}")
        agg.append(f"bool_or(w{j}) AS w{j}")
    uap = len(variants)
    sel.append(f"({' AND '.join(_pass(s, unknown_as_pass=True) for s in applied)}) AS w{uap}")
    agg.append(f"bool_or(w{uap}) AS w{uap}")
    agg.append(f"min(index_date) FILTER (WHERE f{last}) AS first_eligible")
    agg.append(f"bool_or(f{last} AND index_date = CAST($4 AS DATE)) AS prevalent")
    dept = " AND list_contains(CAST($5 AS VARCHAR[]), e.dept)" if departments else ""
    vcols = ""
    vjoin = ""
    vcte = ""
    if vsql:
        vcols = ", " + ", ".join(f'v."C_{v.column_id}"' for v in variants if v.ir is not None)
        vjoin = "\nLEFT JOIN v ON v.pid = r.pid AND v.index_date = r.index_date"
        vcte = f"v AS (SELECT * FROM (\n{vsql}\n)),\n"
    return (
        "-- FEAS funnel (orchestrator/scenarios/feas_compute.py): template SQL only; $3/$4 lookback, $5 departments\n"
        f"WITH\nr AS (SELECT * FROM (\n{rs.sql}\n)),\n{vcte}"
        "pop AS (SELECT DISTINCT e.pid FROM encounter e\n"
        f"  WHERE CAST(e.start AS DATE) BETWEEN CAST($3 AS DATE) AND CAST($4 AS DATE){dept}),\n"
        f"x AS (SELECT r.*{vcols} FROM r JOIN pop ON pop.pid = r.pid{vjoin}),\n"
        "s AS (SELECT pid, index_date,\n  " + ",\n  ".join(sel) + "\n  FROM x)\n"
        "SELECT pid,\n  " + ",\n  ".join(agg) + "\nFROM s GROUP BY pid ORDER BY pid"
    )


# ---------------------------------------------------------------------------------------------- compute
def compute(lake: LakeAPI, rs: Ruleset, p: FeasParams) -> tuple[FeasibilityResult, FeasRaw]:
    idx = month_ends(p.run_date, p.lookback_months)
    if not idx:
        raise FeasError("lookback must be at least one month")
    st = steps(rs)
    spec = dict(rs.manifest.variants or {})
    spec.update(p.variants)
    variants = build_variants(rs, spec, st)
    sql = funnel_query(rs, st, variants, p.departments)
    pop_from = add_months(idx[0], -1)
    params: list[Any] = [[d.isoformat() for d in idx], None, pop_from.isoformat(), idx[-1].isoformat()]
    if p.departments:
        params.append(list(p.departments))
    table = lake.query(sql, params, p.snapshot)
    cols = table.to_pydict()
    n = table.num_rows
    applied = [s for s in st if s.applied]
    remaining = {s.id: sum(1 for x in cols[f"f{i}"] if x) for i, s in enumerate(applied)}
    # inclusion: reached the step, never passed and never had a known value there -> dropped for lack of data;
    # exclusion: kept, and never had a known (FALSE) value -> kept for lack of data
    unknown: dict[str, int] = {}
    for i, s in enumerate(applied):
        rows = zip(cols[f"r{i}"], cols[f"f{i}"], cols[f"u{i}"], strict=True)
        unknown[s.id] = sum(1 for r, f, u in rows if ((r and not f and not u) if s.inclusion else (f and not u)))
    var_counts = {v.name: sum(1 for x in cols[f"w{j}"] if x) for j, v in enumerate(variants)}
    var_counts[UNKNOWN_AS_PASS] = sum(1 for x in cols[f"w{len(variants)}"] if x)
    first: dict[str, int] = {}
    for d in cols["first_eligible"]:
        if d is not None:
            key = d.strftime("%Y-%m")
            first[key] = first.get(key, 0) + 1
    prevalent = sum(1 for x in cols["prevalent"] if x)
    raw = FeasRaw(n, remaining, unknown, var_counts, first, prevalent, idx)
    return _result(rs, p, st, variants, raw), raw


def _months_shown(idx: list[date]) -> list[str]:
    months = [d.strftime("%Y-%m") for d in idx]
    washout = min(WASHOUT_MONTHS, max(len(months) - 1, 0))
    return months[washout:][-CHART_MONTHS:]


def _result(rs: Ruleset, p: FeasParams, st: list[Step], variants: list[Variant], raw: FeasRaw) -> FeasibilityResult:
    """Published (aggregate) feasibility: every count goes through controlled rounding (``round_count``: <t, else
    the nearest multiple of t) and dropped / % / deltas are derived from the published counts, so no small cell can
    be recomputed from neighbouring rows (DECISIONS D-86). The exact counts stay in the box (raw JSON)."""
    t = p.small_cell

    def pub(n: int) -> int | str:
        return round_count(n, t)

    def diff(a: int | str, b: int | str, exact: int) -> int | str:
        return a - b if isinstance(a, int) and isinstance(b, int) else pub(exact)

    start_pub = pub(raw.start_n)
    funnel: list[FunnelStep] = []
    prev, prev_pub = raw.start_n, start_pub
    for s in st:
        label = s.criterion.label or s.criterion.text[:60]
        if not s.applied:
            funnel.append(
                FunnelStep(
                    criterion_id=s.id,
                    label=label,
                    remaining=prev_pub,
                    dropped=0,
                    pct=_pct(prev_pub, start_pub),
                    applied=False,
                )
            )
            continue
        rem = raw.remaining[s.id]
        rem_pub = pub(rem)
        funnel.append(
            FunnelStep(
                criterion_id=s.id,
                label=label,
                remaining=rem_pub,
                dropped=diff(prev_pub, rem_pub, prev - rem),
                pct=_pct(rem_pub, start_pub),
                unknown=pub(raw.unknown[s.id]),
                applied=True,
            )
        )
        prev, prev_pub = rem, rem_pub
    final_pub = prev_pub
    sens: list[SensitivityRow] = []
    for v in variants:
        r_pub = pub(raw.variants[v.name])
        sens.append(
            SensitivityRow(criterion_id=v.criterion_id, variant=v.name, remaining=r_pub, delta=_delta(r_pub, final_pub))
        )
    r_pub = pub(raw.variants[UNKNOWN_AS_PASS])
    sens.append(
        SensitivityRow(criterion_id="*", variant=UNKNOWN_AS_PASS, remaining=r_pub, delta=_delta(r_pub, final_pub))
    )
    shown = _months_shown(raw.index_dates)
    monthly = [MonthlyCount(month=m, n=pub(raw.first_eligible.get(m, 0))) for m in shown]
    recent = [raw.first_eligible.get(m, 0) for m in shown[-12:]]
    lam = float(np.mean(recent)) if recent else 0.0  # exact: drives the simulation inside the box
    recent_pub = [x for x in (pub(n) for n in recent) if isinstance(x, int)]
    lam_pub = (  # published mean from published counts only (an exact mean of small counts reveals their sum)
        round(sum(recent_pub) / len(recent), 1) if recent and len(recent_pub) == len(recent) else None
    )
    seed_src = f"{rs.id}|{rs.version}|{p.snapshot}|{p.run_date.isoformat()}|{p.lookback_months}"
    sim = simulate(
        prevalent=raw.prevalent,
        monthly_rate=lam,
        reach=p.reach_rate,
        accept=p.accept_rate,
        capacity=p.capacity_per_month,
        months=p.months,
        iterations=p.iterations,
        concentration=p.concentration,
        seed=int(hashlib.sha256(seed_src.encode()).hexdigest()[:16], 16),
    )
    simulation = Simulation(
        reach_rate=p.reach_rate,
        accept_rate=p.accept_rate,
        capacity_per_month=p.capacity_per_month,
        months=p.months,
        low=sim["low"],
        mid=sim["mid"],
        high=sim["high"],
        source="calibrated" if p.rate_source == "calibrated" else "default",
        iterations=p.iterations,
        monthly_eligible_mean=lam_pub,
    )
    notes = [
        f"Counts are distinct patients eligible at one or more of {len(raw.index_dates)} month-ends "
        f"({raw.index_dates[0].isoformat()} … {raw.index_dates[-1].isoformat()}); cells 1–{t - 1} are shown as '<{t}' "
        f"and all other counts are rounded to the nearest {t}, so that no small cell can be derived from the others.",
        "Unknown inclusion values (no data in the window) do not count as eligible; unknown exclusions do not exclude "
        f"(variant '{UNKNOWN_AS_PASS}' counts unknown inclusions as met).",
        f"Eligible at the latest month-end: {pub(raw.prevalent)}; mean new eligible per month (last 12 "
        f"months): {lam_pub if lam_pub is not None else f'<{t}'}.",
        f"Monthly new-eligible counts use a {WASHOUT_MONTHS}-month wash-out at the start of the lookback.",
    ]
    for s in st:
        if s.applied and raw.unknown[s.id]:
            what = (
                "dropped with no value at any month-end"
                if s.inclusion
                else "not excluded only because no value was recorded"
            )
            notes.append(f"{s.id}: {pub(raw.unknown[s.id])} patients {what}.")
    not_applied = [s.id for s in st if not s.applied]
    if not_applied:
        notes.append(
            "Not applied in counts (note/human criteria, checked at screening): " + ", ".join(not_applied) + "."
        )
    return FeasibilityResult(
        ruleset=rs.id,
        version=rs.version,
        snapshot=date.fromisoformat(p.snapshot),
        population=population_label(p),
        lookback_months=p.lookback_months,
        run_date=p.run_date,
        start_n=start_pub,
        funnel=funnel,
        sensitivity=sens,
        monthly_new=monthly,
        simulation=simulation,
        notes=notes,
    )


def population_label(p: FeasParams) -> str:
    where = "departments " + ",".join(p.departments) if p.departments else "hospital"
    return f"{where}: patients with ≥1 encounter in the last {p.lookback_months} months"


def _pct(n: int | str, start: int | str) -> float | None:
    """% of start from published counts only (a 0.1 % precision on exact counts would pin the exact count)."""
    if not isinstance(n, int) or not isinstance(start, int) or start <= 0:
        return None
    return round(100.0 * n / start, 1)


def _delta(n: int | str, base: int | str) -> int | None:
    return n - base if isinstance(n, int) and isinstance(base, int) else None


# ---------------------------------------------------------------------------------------------- simulation
def simulate(
    *,
    prevalent: int,
    monthly_rate: float,
    reach: float,
    accept: float,
    capacity: float | None,
    months: int = 12,
    iterations: int = 1000,
    concentration: float = 20.0,
    seed: int = 0,
) -> dict[str, float]:
    """Monte-Carlo enrolment over ``months`` (DECISIONS D-41).

    Per iteration: reach ~ Beta(reach·κ, (1−reach)·κ), accept ~ Beta(accept·κ, (1−accept)·κ); prevalent eligible
    patients present uniformly over the months (multinomial), new eligible patients arrive Poisson(monthly_rate);
    each presenting patient enrols with probability reach·accept; enrolment per month is capped at ``capacity``
    (waiting patients carry over). Returns P10 / P50 / P90 of the total.
    """
    rng = np.random.default_rng(seed)
    k = max(concentration, 1e-6)
    eps = 1e-6
    r = rng.beta(max(reach * k, eps), max((1 - reach) * k, eps), iterations)
    a = rng.beta(max(accept * k, eps), max((1 - accept) * k, eps), iterations)
    totals = np.zeros(iterations)
    for it in range(iterations):
        present = rng.multinomial(prevalent, [1.0 / months] * months) if prevalent > 0 else np.zeros(months, int)
        arrivals = present + rng.poisson(max(monthly_rate, 0.0), months)
        willing = rng.binomial(arrivals, r[it] * a[it])
        backlog = 0.0
        total = 0.0
        for m in range(months):
            backlog += willing[m]
            take = backlog if capacity is None else min(backlog, capacity)
            total += take
            backlog -= take
        totals[it] = total
    lo, mid, hi = np.percentile(totals, [10, 50, 90])
    return {"low": round(float(lo), 1), "mid": round(float(mid), 1), "high": round(float(hi), 1)}


def raw_json(raw: FeasRaw) -> bytes:
    """Unsuppressed counts for the internal funnel-compare harness (never mailed)."""
    body = {
        "start_n": raw.start_n,
        "remaining": raw.remaining,
        "unknown": raw.unknown,
        "variants": raw.variants,
        "first_eligible": dict(sorted(raw.first_eligible.items())),
        "prevalent": raw.prevalent,
        "index_dates": [d.isoformat() for d in raw.index_dates],
    }
    return (json.dumps(body, indent=1, sort_keys=True) + "\n").encode()
