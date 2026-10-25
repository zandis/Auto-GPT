"""DL-1 feasibility pack: the typed, disclosed, frozen data object (spec v4 §12.4; RPT-03, RPT-05, RPT-06, RPT-16,
RPT-21, RPT-22, RPT-32, RPT-33, RPT-35; CAS-8, CAS-10; FR-M3-2, FR-M3-11).

:func:`build_pack` turns one cascade run (plus the v1 FEAS month-end series for incidence and threshold variants,
the snapshot's data-fitness rows and the recall certificate or its refusal) into the pack object:

1. exact aggregates from one state matrix (:mod:`deliverables.analytics`);
2. primary suppression and independent controlled rounding per the recipient's profile (:mod:`.disclosure`);
   differences come from exact values; percentages from unrounded values only when ``rate_publishable``;
3. sections §1–§11 and §13–§15 in order (§12 on request); a table or figure that cannot be produced is replaced by a
   fixed ``not available: {reason}`` panel;
4. the object is frozen: canonical JSON, sha256, complete ``disclosure_trace``. Renderers accept only that.

Exact values never enter the released object. With ``include_exact`` (synthetic or open data only, never a
sponsor release) a separate ``internal_exact`` block carries them for the Test Bench comparison.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from matching.cascade.engine import CascadeResult
from tb_common.ruleset import Ruleset

from deliverables import analytics as an
from deliverables import figures as fg
from deliverables.disclosure import (
    DisclosureError,
    DisclosureTrace,
    Profile,
    ceil_base,
    complementary,
    floor_base,
    funnel_recovery,
    pct,
    release,
    require_complete,
    round_base,
    sha256,
)

SCHEMA = "deliverable_feasibility_pack@0.1.0"
SECTIONS: tuple[tuple[str, str], ...] = (
    ("1", "Cover and executive summary"),
    ("2", "Study, scope and data fitness"),
    ("3", "Criteria mapping and computability"),
    ("4", "Attrition and the estimate by tier"),
    ("5", "Incidence (24 months) and the prevalent pool"),
    ("6", "Population characteristics and representativeness"),
    ("7", "Clinical profile"),
    ("8", "Treatment patterns and standard of care"),
    ("9", "Pool by department and investigator (bands only)"),
    ("10", "Competing trials and allocation"),
    ("11", "Recruitability and projection, with the calibration record"),
    ("12", "Criterion impact and relaxation (on request)"),
    ("13", "Site profile and start-up"),
    ("14", "Data, methods and limitations"),
    ("15", "Provenance, disclosures and approval"),
)
SECTION_CONTENT: dict[str, tuple[list[str], list[str]]] = {
    "1": (["F-T1"], []),
    "2": (["F-T2", "F-T3"], []),
    "3": (["F-T4"], ["F-F3"]),
    "4": (["F-T5", "F-T6", "F-T7", "F-T8"], ["F-F1", "F-F2"]),
    "5": (["F-T9"], ["F-F4"]),
    "6": (["F-T10"], ["F-F5", "F-F6"]),
    "7": (["F-T11"], ["F-F7"]),
    "8": (["F-T12", "F-T13"], ["F-F8"]),
    "9": (["F-T14"], ["F-F9"]),
    "10": (["F-T15"], []),
    "11": (["F-T16", "F-T17"], ["F-F10", "F-F11"]),
    "12": (["F-T18"], ["F-F12", "F-F13"]),
    "13": (["F-T19"], []),
    "14": (["F-T20"], []),
    "15": ([], []),
}
DISCLAIMERS = {
    "disc.emr_counts": "Counts derive from routinely collected medical records at {site} and reflect documentation, "
    "not clinical eligibility. Criteria marked partially or not computable need chart review.",
    "disc.accuracy": "Record-derived counts can differ from manual estimates in either direction; prefer the "
    "chart-review-adjusted estimate and its interval.",
    "disc.forecast": "Forecasts are probabilistic: P10–P90 means a 10 % chance of fewer and a 10 % chance of more. "
    "Past forecasts are scored in the calibration record.",
    "disc.ai": "AI-assisted pre-screening is used at the site: compiled rules filter structured data first and a "
    "language model reads notes only for the residue. Eligibility is decided by the investigator.",
}
METHODS = [
    ("attrition", "deliverables.analytics.sequential", "1.0.0", "CONSORT 2010 flow; one state matrix (RPT-21)"),
    ("tier estimate", "deliverables.analytics.tier_estimates", "1.0.0", "stratified estimator with FPC (CAS-8)"),
    ("Wilson interval", "deliverables.analytics.wilson", "1.0.0", "Wilson 1927; Newcombe 1998"),
    ("adjusted estimate", "deliverables.analytics.adjusted_estimate", "1.0.0", "§10.3 Beta(2,3) prior on w"),
    ("projection", "deliverables.analytics.projection", "1.0.0", "Poisson–Gamma (Anisimov & Fedorov 2007)"),
    ("incidence", "orchestrator.scenarios.feas_compute.compute", "v1", "first eligible month-end, 12-month wash-out"),
    ("recall certificate", "orchestrator.recall.ledger.render_certificate", "S1-12", "WSR 2024 betting CS"),
    ("disclosure", "deliverables.disclosure", "1.0.0", "§12.2.3 order of operations; CMS cell-size policy"),
]


@dataclass
class PackInputs:
    cascade: CascadeResult
    ruleset: Ruleset
    profile: Profile
    site_id: str
    site_name: str
    snapshot_id: str
    snapshot: str
    data_cut: str
    run_date: date
    recipient_class: str
    feas_raw: Any | None = None  # orchestrator.scenarios.feas_compute.FeasRaw (month-end series, variants)
    data_fitness: list[dict[str, Any]] = field(default_factory=list)
    certificate: dict[str, Any] | None = None  # RecallCertificate JSON, or {"refused": True, "reasons": [...]}
    locked: frozenset[str] = frozenset()  # safety_critical criteria (RPT-28)
    reach_rate: float = 0.6
    accept_rate: float = 0.35
    target: int | None = None
    include_exact: bool = False
    on_request: bool = True  # §12 included


def _na(reason: str) -> dict[str, Any]:
    return {"not_available": reason}


def _logic_summary(c: Any) -> str:
    logic = c.logic.model_dump(mode="json", by_alias=True, exclude_none=True)
    parts = []
    for a in an_atoms(logic):
        bits = [str(a.get("domain", "")), str(a.get("quantifier", ""))]
        if a.get("valueset") and a.get("valueset") != "NONE":
            bits.append(str(a["valueset"]))
        if a.get("value"):
            v = a["value"]
            bits.append(f"{v.get('op', '')} {v.get('num', v.get('code', ''))} {v.get('unit', '') or ''}".strip())
        if a.get("age"):
            bits.append(f"age {a['age']}")
        w = a.get("window")
        if w:
            bits.append(f"window {w.get('from_days')}…{w.get('to_days')} d")
        parts.append(" ".join(b for b in bits if b))
    op = logic.get("op", "")
    return f" {op} ".join(parts)[:240] if op else (parts[0] if parts else "")


def an_atoms(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if "args" in node:
        return [a for arg in node["args"] for a in an_atoms(arg)]
    return [node]


def build_pack(inp: PackInputs) -> dict[str, Any]:
    """Build, disclose and freeze the DL-1 object."""
    res, rs, p = inp.cascade, inp.ruleset, inp.profile
    trace = DisclosureTrace(p.name, p.version)
    labels = {c.id: (c.label or c.text[:60]) for c in rs.active()}
    crit = {c.id: c for c in rs.active()}

    # ------------------------------------------------------------------------------------------- 1 exact
    sm = an.state_matrix(res)
    seq = an.sequential(sm, res, labels)
    marg = an.marginal(sm, res)
    loo = an.loo(sm, res, set(inp.locked))
    tiers = an.tier_estimates(res)
    adj = an.adjusted_estimate(tiers)
    final_exact = len(an.final_pool(sm, res))
    strong_exact = next(t.n_computable for t in tiers if t.tier == "strong")
    raw = inp.feas_raw
    trace.add(
        "exact_aggregates",
        state_matrix={"patients": len(sm.pids), "criteria": len(sm.criteria)},
        source="matching.cascade one run",
    )

    # ------------------------------------------------------------------------------------------- 2–3 release
    def r(n: int) -> int | str:
        return release(int(n), p)

    trace.add("primary_suppression", k=p.k, label=p.suppressed_label, zero_shown=True)
    exact_tables: dict[str, list[dict[str, Any]]] = {}

    t5: list[dict[str, Any]] = []
    t5x: list[dict[str, Any]] = []
    for row in seq:
        t5.append(
            {
                "step": row.step,
                "criterion_id": row.criterion_id,
                "label": row.label,
                "n_remaining": r(row.n_remaining),
                "n_excluded": r(row.n_excluded),  # difference from exact values, then rounded (step 3)
                "pct_excluded_of_prev": pct(row.n_excluded, row.n_prev, p) if row.step else None,
                "n_unknown_data_gap": r(row.n_unknown_data_gap),
                "n_unknown_uncertain": r(row.n_unknown_uncertain),
                "stage": row.stage,
                "applied": row.applied,
            }
        )
        t5x.append(row.__dict__.copy())
    exact_tables["F-T5"] = t5x

    t6 = [
        {
            "criterion_id": m["criterion_id"],
            "n_fail_alone": r(m["n_fail_alone"]),
            "pct_of_base": pct(m["n_fail_alone"], m["base"], p),
            "n_unknown": r(m["n_unknown"]),
            "pct_unknown": pct(m["n_unknown"], m["base"], p),
        }
        for m in marg
    ]
    exact_tables["F-T6"] = marg
    t7 = [
        {
            "criterion_id": x["criterion_id"],
            "n_eligible_without": r(x["n_eligible_without"]),
            "delta_n": r(x["delta_n"]),
            "delta_pct": pct(x["delta_n"], x["n_eligible_without"], p) if x["n_eligible_without"] else None,
            "locked": x["locked"],
        }
        for x in loo
    ]
    exact_tables["F-T7"] = loo

    def ci_release(est: float, lo: float, hi: float) -> tuple[int | str, int, int]:
        """CAS-8: estimate control-rounded (and suppressed); endpoints floored and ceiled to base 5."""
        e = round(est)
        return r(e) if e < p.k else round_base(e, p.base), floor_base(lo, p.base), ceil_base(hi, p.base)

    t8 = []
    for t in tiers:
        est, lo, hi = ci_release(t.est, t.ci_low, t.ci_high)
        t8.append(
            {
                "tier": t.tier,
                "n_computable": r(t.n_computable),
                "est": est,
                "ci95_low": lo,
                "ci95_high": hi,
                "n_sampled": r(t.n_sampled),
                "method": t.method,
            }
        )
    exact_tables["F-T8"] = [t.__dict__ | {"strata": len(t.strata)} for t in tiers]
    adj_est, adj_lo, adj_hi = ci_release(adj[0], adj[1], adj[2])

    # incidence (v1 month-end series) and projection
    t9: list[dict[str, Any]] = []
    t9x: list[dict[str, Any]] = []
    monthly_mean_pub: float | str | None = None
    prevalent = 0
    lam = 0.0
    if raw is not None:
        from orchestrator.scenarios.feas_compute import _months_shown

        shown = _months_shown(raw.index_dates)
        series = [raw.first_eligible.get(m, 0) for m in shown]
        for i, m in enumerate(shown):
            window = series[max(0, i - 11) : i + 1]
            ma = sum(window) / len(window) if i >= 11 else None
            t9.append(
                {
                    "month": m,
                    "n_new_meeting": r(series[i]),
                    "ma12": None if ma is None or not all(v == 0 or v >= p.k for v in window) else round(ma, 1),
                }
            )
            t9x.append({"month": m, "n_new_meeting": series[i], "ma12": ma})
        recent = series[-12:]
        rel = [release(v, p) for v in recent]
        monthly_mean_pub = (
            round(sum(v for v in rel if isinstance(v, int)) / len(rel), 1)
            if rel and all(isinstance(v, int) for v in rel)
            else p.suppressed_label
        )
        prevalent = raw.prevalent
        lam = sum(recent) / len(recent) if recent else 0.0
    exact_tables["F-T9"] = t9x
    seed = int(sha256([rs.id, rs.version, inp.snapshot, inp.run_date.isoformat()])[7:23], 16)
    proj = an.projection(
        float(min(prevalent, final_exact) if raw is not None else final_exact),
        lam,
        reach=inp.reach_rate,
        accept=inp.accept_rate,
        seed=seed,
    )
    m12 = proj[-1]
    trace.add("independent_rounding", base=p.base, method="Decimal half-up per count; differences from exact")

    # complementary suppression: every member of the funnel is rounded (none exact), so the linear check is the
    # interval propagation of RPT-07; it must find no recoverable suppressed cell
    new_r, new_d, added = complementary([x["n_remaining"] for x in t5], [x["n_excluded"] for x in t5], p)
    for t5row, rr, dd in zip(t5, new_r, new_d, strict=True):
        t5row["n_remaining"], t5row["n_excluded"] = rr, dd
    rec = funnel_recovery(new_r, new_d, p)
    if rec:
        seq_r = [(x["n_remaining"], x["n_excluded"]) for x in t5]
        raise DisclosureError(f"suppressed funnel cells recoverable at steps {rec}: {seq_r}")
    trace.add("complementary_suppression", structures=["funnel F-T5"], exact_members=0, added=added, recoverable=rec)
    trace.add("rates_from_unrounded", rule=f"rate_publishable(k={p.k})")
    trace.add("no_reason_by_demographic_below_k", crossed_tables=[])
    trace.add("differencing_check", prior_releases=0, note="no earlier release to this requester for this snapshot")

    # ------------------------------------------------------------------------------------------- tables
    tables: dict[str, Any] = {}
    top3 = [x.criterion_id for x in sorted(seq[1:], key=lambda x: (-x.n_excluded, x.step))[:3] if x.n_excluded]
    cert = inp.certificate or {"refused": True, "reasons": ["no certificate computed"]}
    recall_sentence = (
        cert.get("statement", {}).get("en", "")
        if not cert.get("refused")
        else "Recall certificate refused: " + "; ".join(cert.get("reasons", []))
    )
    tables["F-T1"] = [
        {
            "metric": "computable_count",
            "value": r(strong_exact),
            "interval_low": None,
            "interval_high": None,
            "interval_def": "computable: every criterion decided by records (tier strong)",
            "source_path": "F-T8.strong",
            "flag": "computable count",
        },
        {
            "metric": "adjusted_estimate",
            "value": adj_est,
            "interval_low": adj_lo,
            "interval_high": adj_hi,
            "interval_def": "95 % interval; " + adj[3],
            "source_path": "F-T8",
            "flag": "",
        },
        {
            "metric": "monthly_new_meeting_criteria",
            "value": monthly_mean_pub,
            "interval_low": None,
            "interval_high": None,
            "interval_def": "mean of the last 12 released monthly counts",
            "source_path": "F-T9",
            "flag": "",
        },
        {
            "metric": "projection_12m_p10_p50_p90",
            "value": round(m12["cum_p50"]),
            "interval_low": round(m12["cum_p10"]),
            "interval_high": round(m12["cum_p90"]),
            "interval_def": "P10–P90 of 10,000 seeded paths",
            "source_path": "F-T17.month12",
            "flag": "model output",
        },
    ]
    exact_tables["F-T1"] = [
        {"metric": "computable_count", "value": strong_exact},
        {"metric": "adjusted_estimate", "value": adj[0], "interval_low": adj[1], "interval_high": adj[2]},
        {"metric": "final_pool_structured_and_note", "value": final_exact},
    ]
    stage_counts = {s.stage: s.patients_out for s in res.stages}
    tables["F-T2"] = [
        {"item": "study", "value": f"{rs.id} {rs.manifest.title}"},
        {"item": "registry_id", "value": getattr(rs.manifest, "nct_id", None) or "—"},
        {"item": "ruleset", "value": f"{rs.id} v{rs.version} ({res.semantics} semantics, CAS-19)"},
        {"item": "snapshot", "value": f"{inp.snapshot_id} (data cut {inp.data_cut[:7]})"},
        {"item": "population", "value": res.stages[0].detail.get("population", "")},
        {"item": "population_n", "value": r(stage_counts.get("S0", 0))},
        {"item": "disclosure_profile", "value": f"{p.name} v{p.version} (recipient {inp.recipient_class})"},
    ]
    tables["F-T3"] = inp.data_fitness or _na("no data-fitness rows from the publish cycle")
    t4 = []
    for c in rs.active():
        stages = "S1" if c.id in res.applied else ("S2–S4" if c.class_ == "note" else "S5")
        comp = "full" if c.id in res.applied else ("partial" if c.class_ == "note" else "none")
        t4.append(
            {
                "criterion_id": c.id,
                "kind": c.kind,
                "protocol_text": c.text,
                "text_lang": rs.manifest.language or "en",
                "computability": comp,
                "stages": stages,
                "logic_summary": _logic_summary(c),
                "valueset_refs": ", ".join(
                    sorted(
                        {
                            str(a.get("valueset"))
                            for a in an_atoms(c.logic.model_dump(mode="json", by_alias=True, exclude_none=True))
                            if a.get("valueset")
                        }
                        - {"NONE"}
                    )
                ),
                "window": "",
                "completeness_pct": None,
                "llm_involved": c.class_ == "note",
                "lexicon_recall": "not certified (CAS-13)" if c.class_ == "note" else None,
                "library_match": res.criterion_hashes.get(c.id, "")[:19],
                "safety_critical": c.id in inp.locked,
            }
        )
    tables["F-T4"] = t4
    tables["F-T5"], tables["F-T6"], tables["F-T7"], tables["F-T8"] = t5, t6, t7, t8
    tables["F-T9"] = t9 or _na("no month-end series (incidence needs the v1 FEAS run)")
    tables["F-T10"] = _na("no reference population configured for the site (RPT-29)")
    tables["F-T11"] = _na("lab cut-off profile not implemented in the MS1 slice")
    tables["F-T12"] = _na("lines of therapy need the IR v3 macro (RPT-30, MS4)")
    tables["F-T13"] = _na("pathway intervals not implemented in the MS1 slice")
    dept: dict[str, int] = {}
    for pid in an.final_pool(sm, res):
        d = res.traces[pid].department or "unknown"
        dept[d] = dept.get(d, 0) + 1
    tables["F-T14"] = [
        {
            "department": d,
            "investigator_code": "—",
            "cohort_band": "≥10" if n >= 10 else ("5–9" if n >= 5 else "<5"),
            "upcoming_visits_14d_band": "—",
            "active_competing_studies": "—",
        }
        for d, n in sorted(dept.items())
    ] or _na("no patients in the final pool")
    tables["F-T15"] = _na("competing-trial overlap needs the registry mirror (M5)")
    tables["F-T16"] = [
        {
            "parameter": "reach_rate",
            "value": inp.reach_rate,
            "low": None,
            "high": None,
            "distribution": "Beta(κ=20)",
            "source": "default",
            "n_behind": 0,
        },
        {
            "parameter": "accept_rate",
            "value": inp.accept_rate,
            "low": None,
            "high": None,
            "distribution": "Beta(κ=20)",
            "source": "default",
            "n_behind": 0,
        },
        {
            "parameter": "w_potential",
            "value": 0.4,
            "low": None,
            "high": None,
            "distribution": "Beta(2, 3)",
            "source": "default",
            "n_behind": 0,
        },
        {
            "parameter": "monthly_rate",
            "value": monthly_mean_pub,
            "low": None,
            "high": None,
            "distribution": "Gamma(shape 4)",
            "source": "EMR",
            "n_behind": None,
        },
    ]
    tables["F-T17"] = [{"month": x["month"], **{k: round(v, 1) for k, v in x.items() if k != "month"}} for x in proj]
    sens: list[dict[str, Any]] = [
        {
            "criterion_id": "*",
            "variant": "as computed (structured + note)",
            "n_eligible": r(final_exact),
            "delta_n": 0,
            "locked": False,
        },
        {
            "criterion_id": "*",
            "variant": "structured criteria only (after S1)",
            "n_eligible": r(stage_counts.get("S1", 0)),
            "delta_n": r(max(stage_counts.get("S1", 0) - final_exact, 0)),
            "locked": False,
        },
        {
            "criterion_id": "*",
            "variant": "unknown inclusion counted as met",
            "n_eligible": r(an.unknown_as_pass(sm, res)),
            "delta_n": r(max(an.unknown_as_pass(sm, res) - final_exact, 0)),
            "locked": False,
        },
    ]
    sens_x = [
        {"variant": "as computed", "n": final_exact},
        {"variant": "structured only", "n": stage_counts.get("S1", 0)},
        {"variant": "unknown inclusion counted as met", "n": an.unknown_as_pass(sm, res)},
    ]
    if raw is not None:
        for name, n in sorted(raw.variants.items()):
            cid = next((c for c in crit if name.split("=")[0] in c), "*")
            sens.append(
                {
                    "criterion_id": cid,
                    "variant": f"{name} (month-end FEAS, structured)",
                    "n_eligible": r(n),
                    "delta_n": r(abs(n - raw.remaining[next(reversed(raw.remaining))])) if raw.remaining else None,
                    "locked": cid in inp.locked,
                }
            )
            sens_x.append({"variant": name, "n": n})
    tables["F-T18"] = sens if inp.on_request else _na("on request")
    exact_tables["F-T18"] = sens_x
    tables["F-T19"] = [
        {
            "field": "site_id",
            "value": inp.site_id,
            "source": "site profile",
            "as_of": inp.run_date.isoformat()[:7],
            "answer_memory_ref": None,
        },
        {
            "field": "site_name",
            "value": inp.site_name,
            "source": "site profile",
            "as_of": inp.run_date.isoformat()[:7],
            "answer_memory_ref": None,
        },
    ]
    tables["F-T20"] = [
        {"analysis": a, "function": f, "version": v, "reference": ref, "parameters": ""} for a, f, v, ref in METHODS
    ]

    # ------------------------------------------------------------------------------------------- figures
    figs: dict[str, Any] = {}
    applied_rows = [x for x in t5[1:] if x["applied"]]
    final_rel = r(final_exact)
    figs["F-F2"] = fg.waterfall(
        [{**x, "n_prev": t5[0]["n_remaining"]} for x in applied_rows] if applied_rows else [], final_rel, p.k
    )
    s1_exc = [x for x in t5[1:] if x["stage"] == "S1"]
    note_exc = [x for x in t5[1:] if x["stage"] == "S2–S4"]
    after = {s.stage: s.patients_out for s in res.stages}
    boxes: list[dict[str, Any]] = [
        {"stage": "S0", "label": "population of scope", "n": r(after.get("S0", 0))},
        {
            "stage": "S1",
            "label": "structured criteria pass",
            "n": r(after.get("S1", 0)),
            "excluded": r(after.get("S0", 0) - after.get("S1", 0)),
            "reasons": [
                (x["criterion_id"], x["n_excluded"])
                for x in sorted(s1_exc, key=lambda x: -(x["n_excluded"] if isinstance(x["n_excluded"], int) else 0))
            ],
        },
        {
            "stage": "S2–S4",
            "label": "note criteria not failing",
            "n": r(after.get("S4", 0)),
            "excluded": r(after.get("S1", 0) - after.get("S4", 0)),
            "reasons": [(x["criterion_id"], x["n_excluded"]) for x in note_exc],
        },
        {"stage": "Final", "label": f"computable {_s(r(strong_exact))}; adjusted {_s(adj_est)}", "n": final_rel},
    ]
    figs["F-F1"] = fg.flow(boxes, p.k)
    f3 = []
    for cid in [*res.applied, *res.note_criteria]:
        cells = [sm.get(x, cid) for x in sm.pids if sm.get(x, cid)]
        f3.append(
            {
                "criterion_id": cid,
                "badge": "●" if cid in res.applied else "◐",
                "pass": r(sum(1 for c in cells if c == "pass")),
                "fail": r(sum(1 for c in cells if c == "fail")),
                "unknown_data_gap": r(sum(1 for c in cells if c in ("unknown:data_gap", "pass:unknown_kept"))),
                "unknown_uncertain": r(sum(1 for c in cells if c == "unknown:uncertain")),
            }
        )
    figs["F-F3"] = fg.stacked(f3, p.k)
    figs["F-F4"] = fg.incidence(t9, p.k) if t9 else _na("no month-end series")
    figs["F-F10"] = fg.fan(proj, inp.target)
    figs["F-F12"] = fg.tornado(t7, p.k) if inp.on_request else _na("on request")
    for fid, reason in (
        ("F-F5", "population pyramid needs a reference population"),
        ("F-F6", "representativeness needs a reference population"),
        ("F-F7", "lab ECDFs not implemented in the MS1 slice"),
        ("F-F8", "treatment Sankey needs lines of therapy (MS4)"),
        ("F-F9", "department heat map needs monthly department series"),
        ("F-F11", "insufficient history (fewer than 3 scored studies, RPT-27)"),
        ("F-F13", "optional figure not produced"),
    ):
        figs[fid] = _na(reason)

    # ------------------------------------------------------------------------------------------- sections
    sections = []
    for sid, title in SECTIONS:
        if sid == "12" and not inp.on_request:
            continue
        tids, fids = SECTION_CONTENT[sid]
        sections.append({"id": sid, "title": title, "tables": tids, "figures": fids})
    figure_index = {
        fid: (
            f
            if isinstance(f, dict)
            else {"fid": f.fid, "title": f.title, "alt": f.alt, "data": f.data, "png_sha256": sha256(f.png.hex())}
        )
        for fid, f in figs.items()
    }
    obj: dict[str, Any] = {
        "schema": SCHEMA,
        "deliverable": "DL-1",
        "data_class": "D1",
        "study_id": res.study_id,
        "ruleset": {"id": rs.id, "version": rs.version, "ir_hash": res.ir_hash, "semantics": res.semantics},
        "site": {"id": inp.site_id, "name": inp.site_name},
        "snapshot": {"id": inp.snapshot_id, "date": inp.snapshot, "data_cut_month": inp.data_cut[:7]},
        "generated_month": inp.run_date.isoformat()[:7],
        "recipient_class": inp.recipient_class,
        "profile": {"name": p.name, "version": p.version, "k": p.k, "base": p.base},
        "headline": {
            "computable_count": r(strong_exact),
            "adjusted_estimate": {"est": adj_est, "ci95_low": adj_lo, "ci95_high": adj_hi},
            "monthly_new_meeting_criteria": monthly_mean_pub,
            "projection_12m": {
                "p10": round(m12["cum_p10"]),
                "p50": round(m12["cum_p50"]),
                "p90": round(m12["cum_p90"]),
            },
            "top_limiting_criteria": top3,
            "recall_sentence": recall_sentence,
        },
        "sections": sections,
        "tables": tables,
        "figures": figure_index,
        "recall_certificate": cert,
        "cascade": {k: v for k, v in res.manifest_block().items() if k != "stages"}
        | {
            "stages": [
                {"stage": s.stage, "patients_out": r(s.patients_out), "data_class": "D1", "ir_hash": s.ir_hash}
                for s in res.stages
            ]
        },
        "annex_b_logic_hashes": res.criterion_hashes,
        "disclaimers": {k: v.format(site=inp.site_name) for k, v in DISCLAIMERS.items()},
        "logic_text_released": False,  # RPT-35: CQL/SQL text is never released by default
    }
    _scrub_cascade(obj["cascade"], r)
    trace.add("freeze_hash", fields=sorted(obj))
    obj["disclosure_trace"] = trace.to_dict()
    frozen = {
        "object": obj,
        "sha256": sha256(obj),
        "pngs": {fid: f.png for fid, f in figs.items() if not isinstance(f, dict)},
    }
    if inp.include_exact:
        frozen["internal_exact"] = {"note": "INTERNAL: synthetic or open data only; never released", **exact_tables}
    return frozen


def _s(v: int | str) -> str:
    return f"{v:,}" if isinstance(v, int) else str(v)


def _scrub_cascade(block: dict[str, Any], r: Any) -> None:
    """The manifest metrics in a released pack are counts too: release them through the profile."""
    block["n_scope"] = r(block.get("n_scope", 0))
    block["n_after"] = {k: r(v) for k, v in block.get("n_after", {}).items()}
    for k in (
        "pairs_S2_zero_hit",
        "pairs_S2b_above",
        "pairs_S2b_below",
        "unprocessed",
        "rescue_yield",
        "sampled_patients",
        "cache_hits",
    ):
        if k in block:
            block[k] = r(block[k])
    block["pairs_judged"] = {k: r(v) for k, v in block.get("pairs_judged", {}).items()}
    block["data_class"] = "D1"


def verify_frozen(frozen: Mapping[str, Any]) -> dict[str, Any]:
    """RPT-03/RPT-06: renderers accept only a frozen object whose hash matches and whose trace is complete."""
    obj = frozen.get("object")
    if not isinstance(obj, dict) or sha256(obj) != frozen.get("sha256"):
        raise DisclosureError("pack object is not frozen or its hash does not match")
    require_complete(obj.get("disclosure_trace", {}))
    return obj


def all_released_counts(obj: Mapping[str, Any]) -> Sequence[Any]:
    """Every count cell of the released tables (for the small-cell invariant)."""
    keys = {
        "n_remaining",
        "n_excluded",
        "n_unknown_data_gap",
        "n_unknown_uncertain",
        "n_fail_alone",
        "n_unknown",
        "n_eligible_without",
        "n_computable",
        "n_sampled",
        "n_new_meeting",
        "n_eligible",
    }
    out: list[Any] = []
    for rows in obj["tables"].values():
        if isinstance(rows, list):
            for row in rows:
                out.extend(v for k, v in row.items() if k in keys and v is not None)
    return out


__all__ = ["SCHEMA", "SECTIONS", "PackInputs", "all_released_counts", "build_pack", "verify_frozen"]
