"""Feasibility report profile (D-104): the extra facts a sponsor-grade feasibility report needs beyond the funnel.

Published next to the feasibility JSON as ``feasprofile_<stem>.json`` (tag ``aggregate``, stored in the box and
read by the console's report page; not mailed). Every patient count goes through the same controlled rounding as the
funnel (``round_count``: below the small-cell threshold → "<t", else the nearest multiple of t, D-86), so the file can
leave the hospital as it is.

Contents:

* ``demographics`` — the pool eligible now (patients passing every applied criterion at the latest month-end) by age
  band and sex, from the lake ``patient`` table;
* ``visits_90d`` — how many of them have a booked appointment in the next 90 days (appointments as the box holds
  them; the page says where they came from);
* ``projection`` — cumulative enrolment P10/P50/P90 at the end of each month, from the same Monte-Carlo draws as the
  headline (``feas_compute.simulate(path=True)``); the console applies the site's screen-failure rate to it;
* ``screen_fail_default`` — a literature default only when the ruleset's population is early Alzheimer's disease
  (Clarity AD screened 5,967 to randomise 1,795 ≈ 70 %; 60 % is used, labelled as a default); otherwise null, and the
  page shows consented patients only until the site enters a rate;
* ``data`` — facts for the "data quality and limitations" section (appointment rows and note chunks in the lake).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from typing import Any

import numpy as np
from tb_common.ruleset import Ruleset
from tb_common.smallcell import round_count

from orchestrator.scenarios.feas_compute import FeasParams, FeasRaw, _months_shown, simulate

AGE_BANDS: tuple[tuple[str, int, int], ...] = (
    ("<50", 0, 49),
    ("50-59", 50, 59),
    ("60-69", 60, 69),
    ("70-79", 70, 79),
    ("80+", 80, 200),
)
AD_SCREEN_FAIL = 0.6
_AD = re.compile(r"alzheimer|\bAD\b|\bMCI\b|amyloid|アルツハイマー|認知症|阿茲海默|失智", re.IGNORECASE)

DEMO_SQL = """
SELECT pid, CAST(birth_date AS VARCHAR) AS birth_date, sex FROM patient
WHERE list_contains(CAST($1 AS VARCHAR[]), pid)
"""
VISIT_SQL = """
SELECT count(DISTINCT pid) AS n FROM appointment
WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND status = 'booked'
  AND CAST(start AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE)
"""
FACTS_SQL = "SELECT (SELECT count(*) FROM appointment) AS appts, (SELECT count(*) FROM document_chunk) AS chunks"


def is_early_ad(rs: Ruleset) -> bool:
    m = rs.manifest
    text = " ".join(
        str(x or "")
        for x in (
            m.title,
            m.trial_alias,
            m.population.disease_stage if m.population else None,
        )
    )
    return bool(_AD.search(text))


def age_band(birth: date, today: date) -> str:
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return next(lbl for lbl, lo, hi in AGE_BANDS if lo <= age <= hi)


def demographics(rows: list[tuple[str, str | None, str | None]], today: date, t: int) -> dict[str, Any]:
    """Age band × sex counts, rounded (pure; unit-tested)."""
    grid: dict[str, dict[str, int]] = {lbl: {"F": 0, "M": 0, "other": 0} for lbl, _, _ in AGE_BANDS}
    unknown_age = 0
    for _pid, birth, sex in rows:
        s = (sex or "").strip().lower()
        key = "F" if s in ("f", "female") else "M" if s in ("m", "male") else "other"
        try:
            band = age_band(date.fromisoformat(str(birth)[:10]), today)
        except (TypeError, ValueError):
            unknown_age += 1
            continue
        grid[band][key] += 1
    bands = [
        {
            "band": lbl,
            **{k: round_count(v, t) for k, v in grid[lbl].items()},
            "n": round_count(sum(grid[lbl].values()), t),
        }
        for lbl, _, _ in AGE_BANDS
    ]
    tot = {k: round_count(sum(grid[b][k] for b in grid), t) for k in ("F", "M", "other")}
    return {"bands": bands, "sex": tot, "age_unknown": round_count(unknown_age, t)}


def _scalar(table: Any, col: str) -> int:
    vals = table.to_pydict().get(col) or [0]
    return int(vals[0] or 0)


def build(lake: Any, rs: Ruleset, p: FeasParams, raw: FeasRaw, today: date) -> dict[str, Any]:
    t = p.small_cell
    pool = sorted(raw.prevalent_pids)
    out: dict[str, Any] = {
        "schema": "feasprofile/1",
        "ruleset": rs.id,
        "version": rs.version,
        "snapshot": p.snapshot,
        "small_cell": t,
        "pool_now": round_count(len(pool), t),
        "potential": round_count(raw.variants.get("unknown_as_pass", 0), t),
        "screen_fail_default": AD_SCREEN_FAIL if is_early_ad(rs) else None,
        "screen_fail_source": "Clarity AD (5,967 screened, 1,795 randomised); early-AD default"
        if is_early_ad(rs)
        else None,
    }
    if pool:
        rows = lake.query(DEMO_SQL, [pool], p.snapshot).to_pydict()
        triples = list(zip(rows.get("pid") or [], rows.get("birth_date") or [], rows.get("sex") or [], strict=False))
        out["demographics"] = demographics(triples, today, t)
        visits = lake.query(VISIT_SQL, [pool, today.isoformat(), (today + timedelta(days=90)).isoformat()], p.snapshot)
        out["visits_90d"] = round_count(_scalar(visits, "n"), t)
    else:
        out["demographics"] = demographics([], today, t)
        out["visits_90d"] = 0
    try:
        facts = lake.query(FACTS_SQL, [], p.snapshot)
        out["data"] = {"appointment_rows": _scalar(facts, "appts"), "note_chunks": _scalar(facts, "chunks")}
    except Exception:  # a lake without one of the tables: say so rather than fail the report
        out["data"] = {"appointment_rows": None, "note_chunks": None}
    shown = _months_shown(raw.index_dates)
    recent = [raw.first_eligible.get(m, 0) for m in shown[-12:]]
    lam = float(np.mean(recent)) if recent else 0.0
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
        path=True,
    )
    out["projection"] = {
        "months": p.months,
        "path": sim["path"],
        "low": sim["low"],
        "mid": sim["mid"],
        "high": sim["high"],
    }
    return out


def to_bytes(profile: dict[str, Any]) -> bytes:
    return (json.dumps(profile, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
