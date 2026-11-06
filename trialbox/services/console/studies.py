"""Report-first role pages (D-104): pure view-model builders for the study card, the feasibility report and the
weekly PI list. No I/O here; ``console.home`` fetches the job outputs and passes plain dicts in, so every rule
below (GO reading, status derivation, the "why this patient fits" facts) is unit-tested without a box.

Verdict semantics are the screening engine's: ``pass`` = fine for eligibility (an inclusion met, or an exclusion
not present), ``fail`` = not eligible on that criterion, ``unknown`` = the chart did not say, ``pending_human`` =
a person decides (CDR, study partner, …).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from tb_contracts import Job

from console.sitestore import Mark, SiteProfile

TERMINAL_REGISTRY = frozenset({"screen_fail", "declined", "withdrawn"})
STATUS_ORDER = ("new", "pending", "contacted", "screened", "enrolled", "not_eligible")


# ---------------------------------------------------------------------------------------------- jobs
def latest_job(jobs: Iterable[Job], ruleset: str, types: Sequence[str], state: str | None = "done") -> Job | None:
    """The most recently updated job of one of ``types`` for ``ruleset`` (and ``state``)."""
    best: Job | None = None
    for j in jobs:
        if (j.ruleset or "").upper() != ruleset.upper() or j.type not in types:
            continue
        if state is not None and j.state != state:
            continue
        if best is None or (j.updated_at, j.job_id) > (best.updated_at, best.job_id):
            best = j
    return best


def output(job: Job | None, prefix: str, suffix: str, tag: str | None = None) -> Any:
    if job is None:
        return None
    for o in job.outputs or []:
        if o.filename.startswith(prefix) and o.filename.endswith(suffix) and (tag is None or o.tag == tag):
            return o
    return None


# ---------------------------------------------------------------------------------------------- feasibility
def go_reading(low: float, mid: float, high: float, target: float | None) -> str | None:
    """GO when even the low case meets the sponsor's target; CONDITIONAL when the target lies inside the range;
    NO-GO when even the high case misses it; None without a target (projection only)."""
    if not target or target <= 0:
        return None
    if low >= target:
        return "go"
    if high >= target:
        return "conditional"
    return "nogo"


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.1f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v) if v not in (None, "") else "–"


@dataclass
class CriterionMeta:
    id: str
    kind: str  # inclusion / exclusion
    cls: str  # structured / note / human / mixed
    label: str
    text: str = ""


VERIFIED_BY = {"structured": "records", "note": "notes", "human": "person", "mixed": "records_notes"}


def feas_report(
    result: Mapping[str, Any],
    profile: Mapping[str, Any] | None,
    site: SiteProfile,
    crit: Mapping[str, CriterionMeta],
    *,
    sponsor: bool = False,
) -> dict[str, Any]:
    """The sections of the feasibility report, in order (D-104 §2). Counts are the published (rounded,
    small-cell-suppressed) counts of the feasibility JSON, so the same view is safe for the sponsor copy; the sponsor
    view only drops the site's free-text comment unless the coordinator ticked "include in sponsor copy"."""
    prof = dict(profile or {})
    sim = dict(result.get("simulation") or {})
    months = int(sim.get("months") or 12)
    sf_default = prof.get("screen_fail_default")
    sf = site.screen_fail if site.screen_fail is not None else sf_default
    sf_source = "site" if site.screen_fail is not None else ("default" if sf_default is not None else None)
    keep = 1.0 - float(sf) if sf is not None else 1.0

    def scaled(x: Any) -> float:
        return round(float(x or 0) * keep, 1)

    low, mid, high = scaled(sim.get("low")), scaled(sim.get("mid")), scaled(sim.get("high"))
    target_n = site.target_n
    target_m = site.target_months or months
    # compare at the sponsor's own deadline: the projection path's month when it is inside the horizon, otherwise
    # the horizon total against the pro-rated target (stated as an extrapolation in the assumptions)
    path_raw = (prof.get("projection") or {}).get("path") or []
    if target_n and target_m and 1 <= target_m <= len(path_raw):
        a, b, c = path_raw[int(target_m) - 1]
        reading = go_reading(scaled(a), scaled(b), scaled(c), float(target_n))
    else:
        target_at_horizon = (target_n * months / target_m) if target_n else None
        reading = go_reading(low, mid, high, target_at_horizon)

    funnel_rows = []
    start = result.get("start_n")
    start_i = _int(start)
    applied = [f for f in result.get("funnel") or [] if f.get("applied") is not False]
    pool_now = applied[-1].get("remaining") if applied else None
    for f in result.get("funnel") or []:
        cid = str(f.get("criterion_id") or "")
        meta = crit.get(cid)
        rem = f.get("remaining")
        width = None
        if f.get("applied") is not False and start_i and _int(rem) is not None:
            width = max(0.5, min(100.0, 100.0 * (_int(rem) or 0) / start_i))
        funnel_rows.append(
            {
                "id": cid,
                "label": f.get("label") or (meta.label if meta else cid),
                "kind": meta.kind if meta else "",
                "applied": f.get("applied") is not False,
                "remaining": _fmt(rem),
                "dropped": _fmt(f.get("dropped")),
                "unknown": _fmt(f.get("unknown")) if f.get("unknown") not in (None, 0) else "",
                "pct": f.get("pct"),
                "width": width,
                "verified": VERIFIED_BY.get(meta.cls, "records") if meta else "records",
            }
        )
    # barriers: the five criteria that lose most patients, split "value failed" vs "never recorded"
    bars = []
    for f in applied:
        d, u = _int(f.get("dropped")), _int(f.get("unknown")) or 0
        if d is None or d <= 0:
            continue
        meta = crit.get(str(f.get("criterion_id")))
        never = min(u, d) if meta is None or meta.kind != "exclusion" else 0
        bars.append(
            {
                "id": f.get("criterion_id"),
                "label": f.get("label") or (meta.label if meta else f.get("criterion_id")),
                "dropped": d,
                "never": never,
                "failed": d - never,
            }
        )
    bars.sort(key=lambda b: -b["dropped"])
    bars = bars[:5]
    not_applied = [r for r in funnel_rows if not r["applied"]]
    sens = [
        {
            "criterion": s.get("criterion_id"),
            "label": (crit[str(s.get("criterion_id"))].label if str(s.get("criterion_id")) in crit else "")
            or str(s.get("criterion_id")),
            "variant": s.get("variant"),
            "remaining": _fmt(s.get("remaining")),
            "delta": s.get("delta"),
        }
        for s in result.get("sensitivity") or []
    ]
    potential = next(
        (s.get("remaining") for s in result.get("sensitivity") or [] if s.get("variant") == "unknown_as_pass"), None
    )
    monthly = [{"month": m.get("month"), "n": m.get("n")} for m in result.get("monthly_new") or []]
    path = [[scaled(a), scaled(b), scaled(c)] for a, b, c in (prof.get("projection") or {}).get("path") or []]
    demo = prof.get("demographics") or None
    caps = [{"key": k, **v} for k, v in site.capabilities.items() if v.get("value")]
    facts = data_facts(result, prof, site)
    return {
        "sponsor": sponsor,
        "ruleset": result.get("ruleset"),
        "version": result.get("version"),
        "snapshot": result.get("snapshot"),
        "run_date": result.get("run_date"),
        "lookback": result.get("lookback_months"),
        "population": result.get("population"),
        "summary": {
            "per_month": [round(low / months, 2), round(mid / months, 2), round(high / months, 2)],
            "horizon": [low, mid, high],
            "months": months,
            "reading": reading,
            "target_n": target_n,
            "target_months": target_m if target_n else None,
            "pool_now": _fmt(pool_now if pool_now is not None else prof.get("pool_now")),
            # the latest-month-end pool the projection starts from (look-back counts above are cumulative)
            "pool_latest": _fmt(prof.get("pool_now")) if "pool_now" in prof else None,
            "potential": _fmt(potential if potential is not None else prof.get("potential")),
            "visits_90d": _fmt(prof.get("visits_90d")) if "visits_90d" in prof else None,
            "start": _fmt(start),
            "monthly_mean": sim.get("monthly_eligible_mean"),
            "screen_fail": sf,
            "screen_fail_source": sf_source,
            "screen_fail_ref": prof.get("screen_fail_source"),
            "consent_only": sf is None,
            "barriers": bars[:3],
            "n_not_applied": len(not_applied),
        },
        "funnel": funnel_rows,
        "barriers": bars,
        "not_applied": not_applied,
        "sensitivity": sens,
        "monthly": monthly,
        "projection": path,
        "demographics": demo,
        "capabilities": caps,
        "competing": list(site.competing),
        "comment": site.comment if (not sponsor or site.comment_to_sponsor) else "",
        "entered": {"by": site.entered_by, "at": site.entered_at[:10] if site.entered_at else ""},
        "facts": facts,
        "assumptions": [
            ("reach", sim.get("reach_rate"), sim.get("source") or "default"),
            ("accept", sim.get("accept_rate"), sim.get("source") or "default"),
            ("screen_fail", sf, sf_source or "none"),
            ("capacity", sim.get("capacity_per_month"), "settings"),
            ("horizon", months, "fixed"),
            ("iterations", sim.get("iterations") or 1000, "fixed"),
            ("target", f"{target_n} / {target_m}" if target_n else None, "site" if target_n else "none"),
        ],
        "notes": list(result.get("notes") or []),
    }


def data_facts(
    result: Mapping[str, Any], prof: Mapping[str, Any], site: SiteProfile
) -> list[tuple[str, dict[str, Any]]]:
    """(i18n key, values) for the data-quality section: what the counts stand on, said plainly."""
    out: list[tuple[str, dict[str, Any]]] = [("facts.snapshot", {"snapshot": result.get("snapshot") or "–"})]
    data = prof.get("data") or {}
    appts = data.get("appointment_rows")
    if appts is None:
        out.append(("facts.appts.unknown", {}))
    elif appts == 0:
        out.append(("facts.appts.none", {}))
    else:
        out.append(("facts.appts.box", {"n": f"{appts:,}"}))
    chunks = data.get("note_chunks")
    out.append(("facts.notes.none", {}) if not chunks else ("facts.notes", {"n": f"{chunks:,}"}))
    sim = result.get("simulation") or {}
    out.append(("facts.rates.measured", {}) if sim.get("source") == "calibrated" else ("facts.rates.default", {}))
    n_na = len([f for f in result.get("funnel") or [] if f.get("applied") is False])
    if n_na:
        out.append(("facts.not_applied", {"n": n_na}))
    out.append(("facts.rounded", {"k": prof.get("small_cell") or 5}))
    if not site.entered_at:
        out.append(("facts.site.missing", {}))
    return out


# ---------------------------------------------------------------------------------------------- weekly list
def derive_status(tier: str | None, registry: str | None, mark: str | None, new: bool) -> str:
    """One status per listed patient (D-104 §3.4). Registry statuses are the coordinator's; the PI's mark only
    removes a patient when it is "not suitable"."""
    if tier == "excluded" or mark == "not_suitable" or registry in TERMINAL_REGISTRY:
        return "not_eligible"
    if registry == "enrolled":
        return "enrolled"
    if registry == "consented":
        return "screened"
    if registry == "contacted":
        return "contacted"
    return "new" if new else "pending"


@dataclass
class Fit:
    """The facts behind the one-line "why this patient fits" (rendered by an i18n template, never by a model)."""

    inc_met: int = 0
    inc_total: int = 0
    exc_clear: int = 0
    exc_total: int = 0
    key: list[dict[str, Any]] = field(default_factory=list)  # met inclusion facts: label, date, quote
    note_exclusion: list[dict[str, Any]] = field(default_factory=list)  # exclusions found in notes (review tier)
    open: list[str] = field(default_factory=list)  # unknown labels
    not_met: list[str] = field(default_factory=list)  # inclusion criteria a note or record says are not met
    person: list[str] = field(default_factory=list)  # pending_human labels


def fit_facts(criteria: Sequence[Mapping[str, Any]], crit: Mapping[str, CriterionMeta]) -> Fit:
    fit = Fit()
    for v in criteria:
        cid = str(v.get("id"))
        meta = crit.get(cid)
        kind = meta.kind if meta else ("exclusion" if cid.upper().startswith(("E", "X")) else "inclusion")
        label = meta.label if meta else cid
        verdict = v.get("verdict")
        ev = v.get("evidence") or {}
        if kind == "inclusion":
            fit.inc_total += 1
            if verdict == "pass":
                fit.inc_met += 1
                fit.key.append({"id": cid, "label": label, "date": ev.get("quote_date"), "quote": ev.get("quote")})
            elif verdict == "fail":
                fit.not_met.append(label)
        else:
            fit.exc_total += 1
            if verdict == "pass":
                fit.exc_clear += 1
            elif verdict == "fail" and ev.get("quote"):
                fit.note_exclusion.append(
                    {"id": cid, "label": label, "date": ev.get("quote_date"), "quote": ev.get("quote")}
                )
        if verdict == "unknown":
            fit.open.append(label)
        elif verdict == "pending_human":
            fit.person.append(label)
    # prefer facts with a date or a quote: they are what a PI can check
    fit.key.sort(key=lambda k: (not (k.get("date") or k.get("quote")),))
    return fit


def weekly_rows(
    cl: Mapping[str, Any] | None,
    crit: Mapping[str, CriterionMeta],
    registry: Mapping[str, str],
    marks: Mapping[str, Mark],
    seen: Mapping[str, str],
    job_id: str,
    practitioners: Mapping[str, str] | None = None,
    *,
    include_closed: bool = False,
) -> list[dict[str, Any]]:
    """Rows of the weekly PI list from a SCREEN / MICROBATCH candidate list: high and review tiers, not enrolled or
    closed, sorted by next visit (none last), then tier, then pseudonym."""
    names = dict(practitioners or {})
    rows = []
    for r in (cl or {}).get("rows") or []:
        tier = r.get("tier")
        if tier not in ("high", "review"):
            continue
        pid = str(r.get("pid") or "")
        mk = marks.get(pid)
        status = derive_status(tier, registry.get(pid), mk.mark if mk else None, seen.get(pid) == job_id)
        if not include_closed and status in ("not_eligible", "enrolled"):
            continue
        crits = list(r.get("criteria") or [])
        fit = fit_facts(crits, crit)
        nxt = r.get("next_appointment") or ""
        when = None
        if nxt:
            try:
                when = datetime.fromisoformat(str(nxt).replace("Z", "+00:00"))
            except ValueError:
                when = None
        prac = r.get("practitioner_id") or ""
        rows.append(
            {
                "pid": pid,
                "short": pid[:8],
                "tier": tier,
                "status": status,
                "visit": when,
                "visit_text": (str(nxt)[:16].replace("T", " ") if nxt else ""),
                "practitioner": names.get(prac, prac),
                "department": r.get("department") or "",
                "fit": fit,
                "actions": list(r.get("actions") or []),
                "changed": list(r.get("changed") or []),
                "mark": mk,
                "criteria": crits,
            }
        )
    order = {"high": 0, "review": 1}
    rows.sort(key=lambda x: (x["visit"] is None, x["visit_text"] or "9", order.get(str(x["tier"]), 2), x["pid"]))
    return rows


def week_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out = {s: 0 for s in STATUS_ORDER}
    for r in rows:
        out[str(r["status"])] = out.get(str(r["status"]), 0) + 1
    out["total"] = len(rows)
    out["marked"] = sum(1 for r in rows if r.get("mark") is not None)
    return out


def patient_rows(criteria: Sequence[Mapping[str, Any]], crit: Mapping[str, CriterionMeta]) -> list[dict[str, Any]]:
    """Every criterion of one patient for the patient page: protocol text, result, verbatim dated evidence, source."""
    out = []
    order = {c: i for i, c in enumerate(crit)}
    for v in sorted(criteria, key=lambda v: order.get(str(v.get("id")), 10_000)):
        cid = str(v.get("id"))
        meta = crit.get(cid)
        ev = v.get("evidence") or {}
        out.append(
            {
                "id": cid,
                "kind": meta.kind if meta else "",
                "label": meta.label if meta else cid,
                "text": meta.text if meta else "",
                "verdict": v.get("verdict"),
                "quote": ev.get("quote"),
                "date": ev.get("quote_date"),
                "confidence": ev.get("confidence"),
                "reason": ev.get("reason"),
                "source": VERIFIED_BY.get(meta.cls, "records") if meta else "records",
            }
        )
    return out


# ---------------------------------------------------------------------------------------------- workbench (D-105)
WORKLISTS: tuple[str, ...] = ("clinic", "review", "info", "approached", "all")
PIPELINE: tuple[str, ...] = ("found", "reviewed", "contacted", "consented", "enrolled")
STEPS: tuple[str, ...] = ("protocol", "criteria", "feasibility", "weekly", "contact", "enrolled")


def in_worklist(row: Mapping[str, Any], key: str, today: date, days: int = 14) -> bool:
    """The PI's worklists (D-105): clinic visits in the next two weeks, still to review, waiting for information,
    approved and contacted, all. A patient can sit on more than one list (a clinic visit that still needs review)."""
    mk = row.get("mark")
    mark = getattr(mk, "mark", None)
    status = row.get("status")
    if key == "clinic":
        when = row.get("visit")
        return when is not None and today <= when.date() <= today + timedelta(days=days)
    if key == "review":
        return mark is None and status in ("new", "pending")
    if key == "info":
        return mark == "need_info"
    if key == "approached":
        return mark == "approach" or status in ("contacted", "screened")
    return True


def worklist_counts(rows: Sequence[Mapping[str, Any]], today: date) -> dict[str, int]:
    return {k: sum(1 for r in rows if in_worklist(r, k, today)) for k in WORKLISTS}


def met_score(fit: Fit) -> tuple[int, int]:
    """Criteria met out of the criteria counted: inclusions met plus exclusions cleared."""
    return fit.inc_met + fit.exc_clear, fit.inc_total + fit.exc_total


def pipeline_counts(rows: Sequence[Mapping[str, Any]], registry: Mapping[str, str]) -> dict[str, int]:
    """Found → PI reviewed → contacted → consented → enrolled, cumulative: a consented patient was also contacted."""
    found = {str(r["pid"]) for r in rows} | set(registry)
    reviewed = {str(r["pid"]) for r in rows if r.get("mark") is not None}
    rank = {"contacted": 1, "consented": 2, "screen_fail": 2, "enrolled": 3}
    contacted = {p for p, s in registry.items() if rank.get(s, 0) >= 1}
    consented = {p for p, s in registry.items() if rank.get(s, 0) >= 2}
    enrolled = {p for p, s in registry.items() if s == "enrolled"}
    reviewed |= contacted
    return {
        "found": len(found),
        "reviewed": len(reviewed),
        "contacted": len(contacted),
        "consented": len(consented),
        "enrolled": len(enrolled),
    }


def procedure_step(
    *, approved: bool, feas_done: bool, screen_done: bool, contacted: int, enrolled: int, waiting: bool
) -> int:
    """Where a study stands on the six-step procedure (index into STEPS): the first step not yet done."""
    if waiting or not approved:
        return 1
    if not feas_done:
        return 2
    if not screen_done:
        return 3
    if enrolled:
        return 5
    if contacted:
        return 4
    return 3
