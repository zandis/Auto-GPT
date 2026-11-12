"""Report-first role pages (D-104): pure view-model builders for the study card, the feasibility report and the
weekly PI list. No I/O here; ``console.home`` fetches the job outputs and passes plain dicts in, so every rule
below (GO reading, status derivation, the "why this patient fits" facts) is unit-tested without a box.

Verdict semantics are the screening engine's: ``pass`` = fine for eligibility (an inclusion met, or an exclusion
not present), ``fail`` = not eligible on that criterion, ``unknown`` = the chart did not say, ``pending_human`` =
a person decides (CDR, study partner, …).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from tb_common.config import environment_name
from tb_contracts import Job

from console import coded_view
from console.recorded_opinions import view
from console.sitestore import DEFAULT_REASONS, Mark, SiteProfile, StudySettings

TERMINAL_REGISTRY = frozenset({"screen_fail", "declined", "withdrawn"})
STATUS_ORDER = ("new", "pending", "contacted", "screened", "enrolled", "set_aside", "closed")


# ---------------------------------------------------------------------------------------------- jobs
def waiting_studies(bk: Any) -> list[str]:
    """NEW-JRN-1 (JRN-001, D-540): the studies with criteria waiting for approval, in the order their jobs are
    listed. A new study has no ruleset folder until its first approval; this job is what makes it a study. The
    orchestrator is asked for the jobs of that state, so a job that waits behind newer ones is still found."""
    seen: list[str] = []
    for j in bk.list_jobs(limit=500, state="awaiting_approval"):
        rid = (j.ruleset or "").upper()
        if j.state == "awaiting_approval" and rid and rid not in seen:
            seen.append(rid)
    return seen


def known_study(bk: Any, rid: str) -> bool:
    """D-133 (review F-37): a study page answers only for a study TrialBox has (a ruleset of any status, so a study
    whose protocol was read but not yet approved can be set up). A mistyped code gets the 404 page, never an empty
    set-up form for a study that does not exist."""
    try:
        return any(r.id == rid for r in bk.rulesets())
    except Exception:
        return True


def log_study(bk: Any, rid: str) -> bool:
    """D-540: the delegation log, and only it, also opens for a study whose first criteria wait for approval, so
    that the steward can name the PI who approves (D-380). When the jobs cannot be read the answer is no: an
    unknown study stays unknown while the orchestrator is down."""
    if known_study(bk, rid):
        return True
    try:
        return rid in waiting_studies(bk)
    except Exception:
        return False


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
    original: str = ""  # the label as the study wrote it, when ``label`` is the site's translation (D-120)
    text_original: str = ""  # the text as the study wrote it, when ``text`` is the ruleset's translation (D-309)
    todo: str = ""  # the criterion's to-do in the page language (D-309)
    todo_original: str = ""  # the to-do as the run writes it, which ``todo`` replaces on the page


def criterion_meta(row: Mapping[str, Any], lang: str, site_label: str = "") -> CriterionMeta:
    """One approved criterion for a page in ``lang`` (T-507, D-309): the label the site gave at approval (D-120), else
    the label the ruleset ships for this text, else the study's own label; the shipped text and to-do in ``lang``
    when the ruleset has them. Whatever replaces the study's words keeps them beside it (``original``,
    ``text_original``)."""
    written = str(row.get("label") or row["id"])
    text = str(row.get("text") or "")
    tr = (row.get("i18n") or {}).get(lang) or {}
    local = site_label or str(tr.get("label") or "")
    local_text = str(tr.get("text") or "")
    todo = str(tr.get("todo") or "")
    return CriterionMeta(
        str(row["id"]),
        str(row["kind"]),
        str(row.get("class") or "structured"),
        local or written,
        local_text or text,
        written if local else "",
        text if local_text and local_text != text else "",
        todo,
        str(row.get("action") or "") if todo else "",
    )


def test_model_in_use(environ: Mapping[str, str] | None = None) -> bool:
    """T-507 (D-309, LLM-045): the box's note answers come from the test model with fixed answers. True with
    ``TB_LLM_MODE=stub``; with no ``TB_LLM_MODE`` on a DEV or TEST box, whose demo and tests run the in-process stub.
    A page marks every answer read from notes as "test model" then (DEV pages label the test model)."""
    env = os.environ if environ is None else environ
    mode = (env.get("TB_LLM_MODE") or "").strip().lower()
    if mode:
        return mode == "stub"
    return environment_name(env) in ("DEV", "TEST")


VERIFIED_BY = {"structured": "records", "note": "notes", "human": "person", "mixed": "records_notes"}


def site_or_written(written: object, meta: CriterionMeta | None, cid: str) -> tuple[str, bool]:
    """(label, is the site's own label): the label the site gave at approval wins over the words a run wrote down
    (D-146, review J-22 / R-72); otherwise the study's own words, which a page shows as written (``data-authored``)."""
    if meta is not None and meta.original:
        return meta.label, True
    return str(written or (meta.label if meta else "") or cid), False


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
        label, site_label = site_or_written(f.get("label"), meta, cid)
        funnel_rows.append(
            {
                "id": cid,
                "label": label,
                "site_label": site_label,
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
                "label": site_or_written(f.get("label"), meta, str(f.get("criterion_id") or ""))[0],
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
    """One status per listed patient (D-104 §3.4, D-108). Registry statuses are the coordinator's. A PI's "Not
    suitable now" or "Not now" only sets the patient aside for this study: it is never shown as "not eligible" or
    "screen fail" (FR-SCR-07f). ``closed`` = excluded by the records or a terminal registry status."""
    if tier == "excluded" or registry in TERMINAL_REGISTRY:
        return "closed"
    if mark in ("not_suitable", "not_now") and registry in (None, "candidate"):
        return "set_aside"
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
    todo_words: dict[str, str] = field(default_factory=dict)  # a run's to-do -> its words in the page language (D-309)


def fit_facts(criteria: Sequence[Mapping[str, Any]], crit: Mapping[str, CriterionMeta]) -> Fit:
    fit = Fit(todo_words={m.todo_original: m.todo for m in crit.values() if m.todo and m.todo_original})
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
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Rows of the weekly PI list from a SCREEN / MICROBATCH candidate list: high and review tiers, not enrolled,
    closed or set aside, sorted by next visit (none last), then tier, then pseudonym. A "Not now, re-check on <date>"
    mark hides the patient until that date (``today``); from then on the patient is back with the mark shown."""
    names = dict(practitioners or {})
    rows = []
    for r in (cl or {}).get("rows") or []:
        tier = r.get("tier")
        if tier not in ("high", "review"):
            continue
        pid = str(r.get("pid") or "")
        mk = marks.get(pid)
        mval = mk.mark if mk else None
        if mval == "not_now" and today is not None and recheck_due(mk, today):
            mval = None  # the re-check date has come: back on the list
        status = derive_status(tier, registry.get(pid), mval, seen.get(pid) == job_id)
        if not include_closed and status in ("closed", "enrolled", "set_aside"):
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
                "practitioner_id": prac,
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


# ---------------------------------------------------------------------------------------------- amendment re-screen
RESCREEN_GROUPS = ("returns", "no_longer", "in_screening")  # D-364 (LIFE-010), in the order the page shows them
SET_ASIDE_MARKS = ("not_suitable", "not_now")
LISTED = ("high", "review")


def semver(v: str | None) -> tuple[int, ...]:
    """``1.2.0`` -> (1, 2, 0); no version (a mark made before D-364) sorts before every version."""
    try:
        return tuple(int(x) for x in str(v or "").split("."))
    except ValueError:
        return ()


def rescreen_list(
    cl: Mapping[str, Any] | None,
    marks: Mapping[str, Mark],
    registry: Mapping[str, str],
    crit: Mapping[str, CriterionMeta] | None = None,
    old: Mapping[str, Any] | None = None,
    changed: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The amendment re-screen list (D-364, LIFE-010): who the investigator looks at again once a new criteria
    version screens. ``cl`` is the latest candidate list (run on the new version); ``old`` the latest list of an
    earlier version, when one is stored; ``changed`` the criterion ids the amendment added or changed.

    * ``returns``: set aside ("Not suitable", "Not now") under an earlier version, or a screen failure in the
      screening log, and on the new list with a better answer: off the old list, or a criterion that did not pass
      under the old version passes now (a relaxed criterion).
    * ``no_longer``: approached or waiting for information under an earlier version, or in the log as a candidate or
      contacted, and excluded by the new version.
    * ``in_screening``: consented and not yet enrolled: the investigator confirms them against the new version.

    A patient leaves the list once the investigator marks them on a list of the new version. Each row names the
    criteria behind it, as labels: those whose answer changed between the two lists, else the amendment's changes."""
    version = str((cl or {}).get("version") or "")
    if not version or old is None or semver(str(old.get("version") or "")) >= semver(version):
        return []  # no list of an earlier version: no amendment has screened yet
    crit = crit or {}
    label = {cid: (m.label or cid) for cid, m in crit.items()}
    rows = {str(r.get("pid") or ""): r for r in (cl or {}).get("rows") or []}
    before = {str(r.get("pid") or ""): r for r in old.get("rows") or []}

    def verdicts(r: Mapping[str, Any] | None) -> dict[str, str]:
        return {str(v.get("id")): str(v.get("verdict") or "") for v in (r or {}).get("criteria") or []}

    def why(pid: str, want: str) -> list[str]:
        now, then = verdicts(rows.get(pid)), verdicts(before.get(pid))
        ids = [c for c, v in now.items() if then and then.get(c) not in (None, v) and v == want]
        if not ids:
            ids = [c for c in changed if c in now] or list(changed)
        return [label.get(c, c) for c in ids]

    def improved(pid: str) -> bool:
        """The new version answers better: the patient was off the old list, or a criterion that did not pass
        passes now."""
        then = before.get(pid)
        if then is None or str(then.get("tier") or "") not in LISTED:
            return True
        now, was = verdicts(rows.get(pid)), verdicts(then)
        return any(v == "pass" and was.get(c) not in (None, "pass") for c, v in now.items())

    def earlier(mk: Mark | None) -> bool:
        return mk is not None and semver(mk.version) < semver(version)

    out: list[dict[str, Any]] = []
    pids = sorted(set(rows) | {p for p, st in registry.items() if st == "consented"})
    for pid in pids:
        if not pid:
            continue
        mk, reg, row = marks.get(pid), registry.get(pid), rows.get(pid)
        if mk is not None and not earlier(mk):
            continue  # the investigator already looked at this patient on a list of the new version
        tier = str((row or {}).get("tier") or "")
        group = ""
        was = ""
        if reg == "consented":
            group, was = "in_screening", "consented"
        elif tier in LISTED and improved(pid):
            if mk is not None and mk.mark in SET_ASIDE_MARKS and reg in (None, "candidate"):
                group, was = "returns", mk.mark
            elif reg == "screen_fail":
                group, was = "returns", "screen_fail"
        elif tier == "excluded" and (
            (mk is not None and mk.mark in ("approach", "need_info")) or reg in ("candidate", "contacted")
        ):
            group, was = "no_longer", (mk.mark if mk is not None else str(reg))
        if not group:
            continue
        out.append(
            {
                "pid": pid,
                "short": pid[:8],
                "group": group,
                "was": was,
                "was_version": (mk.version or "") if mk is not None else "",
                "version": version,
                "criteria": why(pid, "fail" if group == "no_longer" else "pass") if group != "in_screening" else [],
                "tier": tier,
            }
        )
    order = {g: i for i, g in enumerate(RESCREEN_GROUPS)}
    out.sort(key=lambda r: (order[r["group"]], r["pid"]))
    return out


def list_bridge(rep: Mapping[str, Any] | None, rows: Sequence[Mapping[str, Any]] | None, today: date) -> dict[str, Any]:
    """S3 (D-120): why the screening list is longer than the feasibility count. The count leaves out unknown
    inclusions and keeps unknown exclusions; the list keeps every patient whose answer is unknown (needs information)
    and every coded patient whose code is in the criterion's family but outside its list (D-113)."""
    funnel = (rep or {}).get("funnel") or []
    kept = [
        {"label": f["label"], "n": f["unknown"]}
        for f in funnel
        if f["applied"] and f["unknown"] and f["kind"] == "exclusion"
    ]
    gaps = [
        {"label": f["label"], "n": f["unknown"]}
        for f in funnel
        if f["applied"] and f["unknown"] and f["kind"] != "exclusion"
    ]
    out: dict[str, Any] = {"eligible": ((rep or {}).get("summary") or {}).get("pool_now"), "kept": kept, "gaps": gaps}
    if rows is not None:
        live = list(rows)
        out["listed"] = len(live)
        out["ready"] = sum(1 for r in live if in_worklist(r, "ready", today))
        out["needs"] = sum(1 for r in live if in_worklist(r, "needs", today))
        out["outside"] = sum(
            1
            for r in live
            if any(((v.get("evidence") or {}).get("reason") == "code_outside_list") for v in r.get("criteria") or [])
        )
        # D-130 (review F-10): a record in a code system nobody can read made a coded inclusion unknown
        out["unknown_system"] = sum(
            1
            for r in live
            if any(((v.get("evidence") or {}).get("reason") == "unknown_code_system") for v in r.get("criteria") or [])
        )
    return out


def recheck_due(mk: Any, today: date) -> bool:
    """A "Not now" mark keeps its re-check date in ``reason`` (ISO date)."""
    try:
        return date.fromisoformat(str(getattr(mk, "reason", "") or "")[:10]) <= today
    except ValueError:
        return True


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
                "original": meta.original if meta else "",
                "text": meta.text if meta else "",
                "text_original": meta.text_original if meta else "",
                "test_model": bool(meta and meta.cls in ("note", "mixed") and v.get("verdict") != "pending_human")
                and test_model_in_use(),
                "verdict": v.get("verdict"),
                "quote": ev.get("quote"),
                "date": ev.get("quote_date"),
                "reason": ev.get("reason"),
                # both quotes (D-120); each says where it came from: the test model, a recorded run or a synthetic
                # example (T-515)
                "opinions": [view(o, test_model_in_use()) for o in ev.get("opinions") or [] if o.get("quote")],
                "source": VERIFIED_BY.get(meta.cls, "records") if meta else "records",
                # T-514 (D-362): the coded records' value, unit, date and code
                "coded": coded_view.view(ev, v.get("verdict")),
            }
        )
        verdicts = {o.get("verdict") for o in ev.get("opinions") or [] if o.get("quote")}
        out[-1]["disagree"] = len(verdicts) > 1  # the two checks differ (T-515)
    return out


# ---------------------------------------------------------------------------------------------- workbench (D-105)
WORKLISTS: tuple[str, ...] = ("clinic", "ready", "needs", "review", "info", "approached", "all")
# D-120: ready = every criterion has an answer (nothing unknown, nothing not met); needs = at least one unknown
PAGE_SIZE = 25


def n_open(row: Mapping[str, Any]) -> int:
    """How many criteria of the row are still unknown (the information a person has to find)."""
    fit = row.get("fit")
    return len(getattr(fit, "open", []) or [])


def worklist_sorted(rows: Sequence[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """The clinic list stays in visit order; every other list puts the fewest unknowns first (the patients closest
    to a decision), then the visit (none last), then the pseudonym (D-120)."""
    if key == "clinic":
        return list(rows)
    return sorted(rows, key=lambda r: (n_open(r), r["visit"] is None, r["visit_text"] or "9", r["pid"]))


def paged(rows: Sequence[dict[str, Any]], page: int, size: int = PAGE_SIZE) -> tuple[list[dict[str, Any]], int, int]:
    """One page of a list: (rows, page, pages); ``page`` is clamped to 1..pages."""
    pages = max(1, -(-len(rows) // size))
    page = min(max(1, page), pages)
    return list(rows[(page - 1) * size : page * size]), page, pages


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
    if key == "ready":
        fit = row.get("fit")
        return n_open(row) == 0 and not getattr(fit, "not_met", None) and status not in ("contacted", "screened")
    if key == "needs":
        return n_open(row) > 0 and status not in ("contacted", "screened")
    if key == "review":
        return (mark is None or mark == "not_now") and status in ("new", "pending")
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


# ---------------------------------------------------------------------------------------------- build step 2 (D-108)
REGISTRY_KINDS = frozenset({"cohort", "nhi"})  # registry / observational: a cohort list, no contact step


def study_defaults(ruleset: str, kind: str) -> StudySettings:
    """The settings a study has until S21 (step 3) lets the site change them: study type from the ruleset kind, the
    FR-STUDY-09 "Not suitable" reasons by disease (AD, RA, other), the screening number as ``<STUDY>-0001``."""
    rid = ruleset.upper()
    disease = "ad" if rid.startswith(("AD", "ALZ")) else "ra" if rid.startswith("RA") else "other"
    registry = kind in REGISTRY_KINDS
    return StudySettings(
        study_type="registry" if registry else "trial",
        cohort_kind="dynamic" if kind == "nhi" else "enrolled",
        reasons=DEFAULT_REASONS[disease],
    )


def amber(row: Mapping[str, Any], changed: set[str]) -> list[str]:
    """Why an approval row needs the investigator's eyes (FR-FEAS-12a): compiler flags, CQL and SQL not fully
    equivalent, left to a person at screening, or new / changed since the approved version."""
    why = []
    if row.get("flags"):
        why.append("flags")
    eq = row.get("equivalence_pct")
    if isinstance(eq, (int, float)) and eq < 100:
        why.append("equivalence")
    if row.get("class") == "human":
        why.append("person")
    if row.get("id") in changed:
        why.append("changed")
    return why


def diff_since(draft: Sequence[Mapping[str, Any]], approved: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Changes since vN (FR-FEAS-12e): criteria added, with new text or a new check class, and removed, by id."""
    old = {str(r["id"]): r for r in approved}
    new = {str(r["id"]): r for r in draft}
    return {
        "added": [i for i in new if i not in old],
        "text": [i for i in new if i in old and (new[i].get("text") or "") != (old[i].get("text") or "")],
        "class": [i for i in new if i in old and (new[i].get("class") or "") != (old[i].get("class") or "")],
        "removed": [i for i in old if i not in new],
    }
