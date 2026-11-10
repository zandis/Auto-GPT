"""One readiness page (D-131): the three questions as green, amber or red, each with what is missing.

1. **Which trial?** Red: no criteria. Amber: criteria drafted and not yet approved by the investigator. Green: an
   approved version and nothing waiting.
2. **Which patients could fit?** Red: no input. Amber with what is missing: proposed facts to check, local codes not
   mapped, sheet rows without a chart number, other "please check" items, inputs that disagree, the share of
   diagnoses in a code system TrialBox cannot read, and "feasibility needs a bulk source" when there are only charts.
   For the hospital's own workspace also a held night of the feed (T-611): the box still serves the night before,
   and the item names the tables the completeness gate refused. Green: none of these.
3. **Where do trial records live?** Green: TrialBox's forms are added (or REDCap is linked). Amber otherwise.

:func:`patient_check` runs the approved criteria (the SQL engine with D-130's and D-135's rules) on the workspace's
patients: ready, needs information, or not eligible, with every criterion's answer and why: the trail the
assistant reads for "why is this patient on the list?". :func:`feasibility` gives the counts with how much rests on
coded, confirmed and proposed facts.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from matching.coverage import ICD10CM

from sitesetup import publish
from sitesetup.service import SiteSetup

UNKNOWN_SQL = """
SELECT count(*) AS n, count(*) FILTER (WHERE coalesce(code, '') = '' OR coalesce(system, '') <> $1) AS unknown
FROM condition
"""


def _state(missing: list[dict[str, Any]], red: bool) -> str:
    return "red" if red else ("amber" if missing else "green")


def unknown_share(svc: SiteSetup, ws: str) -> tuple[int, int]:
    """``(diagnoses, in an unknown code system)`` in the workspace's lake (D-130's meaning: not ICD-10-CM)."""
    lake = svc.lake(ws)
    try:
        if not lake.snapshot():
            return 0, 0
        row = lake.query(UNKNOWN_SQL, [ICD10CM]).to_pylist()[0]
    except Exception:
        return 0, 0
    return int(row["n"] or 0), int(row["unknown"] or 0)


def last_feed_night(audit_dir: Path | None, days: int = 7) -> dict[str, Any] | None:
    """T-611: the newest ``ingest.*`` record of the audit chain's last ``days`` day files, or None. Read only."""
    if audit_dir is None or not audit_dir.is_dir():
        return None
    for f in sorted(audit_dir.glob("*.jsonl"), reverse=True)[:days]:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if '"ingest.' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if str(rec.get("event", "")).startswith("ingest."):
                return dict(rec)
    return None


def feed_held(svc: SiteSetup) -> dict[str, Any] | None:
    """T-611 (DATA-001): when the newest night of the hospital feed was held, what the readiness page says: the box
    still serves the snapshot before it, and the tables the gate named."""
    rec = last_feed_night(getattr(getattr(svc, "audit", None), "directory", None))
    if not rec or rec.get("event") != "ingest.held":
        return None
    detail = rec.get("detail") or {}
    problems = [str(p) for p in detail.get("incomplete") or []]
    names = sorted({p.split(":", 1)[0] for p in problems})
    return {
        "key": "patients.feed_held",
        "n": max(len(names), 1),
        "tables": ", ".join(names) or "-",
        "snapshot": str(rec.get("snapshot") or ""),
        "problems": problems[:10],
        "link": "/admin?tab=sources",
    }


def readiness(svc: SiteSetup, ws: str, study: dict[str, Any], records: dict[str, Any]) -> dict[str, Any]:
    """``study``: ``{id, exists, approved (version or None), waiting (drafts to approve), criteria}``;
    ``records``: ``{forms, redcap}`` of the study's data core."""
    st = svc.store
    trial: list[dict[str, Any]] = []
    if not study.get("exists"):
        trial.append({"key": "trial.none", "link": "/pilot/protocol"})
    elif study.get("waiting"):
        trial.append({"key": "trial.not_approved", "n": int(study["waiting"]), "link": study.get("approval_link", "")})
    elif not study.get("approved"):
        trial.append({"key": "trial.not_approved", "n": 1, "link": study.get("approval_link", "")})
    inputs = st.inputs(ws)
    kinds = Counter(i["kind"] for i in inputs)
    feed = ws == "main" and bool(svc.lake(ws).snapshot()) and not inputs
    patients: list[dict[str, Any]] = []
    held = feed_held(svc) if ws == "main" else None
    if held:
        patients.append(held)
    facts = st.facts(ws)
    n_prop = sum(1 for f in facts if f["status"] == "proposed")
    if n_prop:
        patients.append({"key": "patients.proposed", "n": n_prop, "link": "facts"})
    unmapped = [c for c in st.locals(ws) if c["mapped_code"] is None]
    if unmapped:
        patients.append(
            {
                "key": "patients.unmapped",
                "n": len(unmapped),
                "rows": sum(int(c["n"]) for c in unmapped),
                "link": "codes",
            }
        )
    open_checks = st.checks(ws, open_only=True)
    nokey = [c for c in open_checks if c["kind"] == "no_key"]
    if nokey:
        patients.append({"key": "patients.nokey", "n": len(nokey), "link": "checks"})
    other = [c for c in open_checks if c["kind"] != "no_key"]
    if other:
        patients.append({"key": "patients.checks", "n": len(other), "link": "checks"})
    dis = publish.disagreements(facts)
    if dis:
        patients.append({"key": "patients.disagree", "n": len(dis), "link": "people"})
    n_dx, n_unknown = unknown_share(svc, ws)
    if n_unknown:
        patients.append(
            {
                "key": "patients.unknown_share",
                "n": n_unknown,
                "of": n_dx,
                "pct": round(100 * n_unknown / n_dx) if n_dx else 0,
                "link": "codes",
            }
        )
    bulk = feed or kinds["dump"] > 0 or kinds["sheet"] > 0
    if inputs and not bulk:
        patients.append({"key": "patients.bulk", "link": "sheets"})
    no_patients = not inputs and not feed
    rec: list[dict[str, Any]] = []
    if not (records.get("forms") or records.get("redcap")):
        rec.append({"key": "records.forms", "link": "forms"})
    q: dict[str, dict[str, Any]] = {
        "trial": {"state": _state(trial, not study.get("exists")), "missing": trial},
        "patients": {
            "state": _state(patients, no_patients),
            "missing": patients,
            "inputs": dict(kinds),
            "feed": feed,
            "patients": len({f["pid"] for f in facts}),
        },
        "records": {"state": _state(rec, False), "missing": rec},
    }
    states = [v["state"] for v in q.values()]
    overall = "red" if "red" in states else ("amber" if "amber" in states else "green")
    return {"ws": ws, "study": study.get("id"), "overall": overall, "questions": q, "bulk": bulk}


def patient_check(svc: SiteSetup, ws: str, rs: Any, today: date) -> list[dict[str, Any]]:
    """Every patient of the workspace against the approved criteria the SQL engine can read (structured ones;
    note criteria are read by the two models at screening)."""
    from orchestrator.scenarios.evaluate import SqlEngine

    pids = sorted(
        {f["pid"] for f in svc.store.facts(ws)} | {i["pid"] for i in svc.store.inputs(ws, "chart") if i["pid"]}
    )
    lake = svc.lake(ws)
    if not pids or not lake.snapshot():
        return []
    ids = [c.id for c in rs.active() if c.kind in ("inclusion", "exclusion") and f'"C_{c.id}"' in rs.sql]
    evals = SqlEngine(lake).evaluate(rs, pids, today, ids)
    by = {c.id: c for c in rs.active()}
    out = []
    for pid in pids:
        e = evals.get(pid)
        rows = []
        state = "ready"
        for cid in ids:
            c = by[cid]
            v = None if e is None else e.results.get(cid)
            reason = ((e.reasons or {}) if e else {}).get(cid) or ("coded" if v is not None else "data_gap")
            refs = ((e.evidence or {}) if e else {}).get(cid) or []
            if c.kind == "inclusion":
                verdict = "met" if v is True else ("not_met" if v is False else "unknown")
            else:
                verdict = "excluded" if v is True else ("clear" if v is False else "unknown")
            if verdict in ("not_met", "excluded"):
                state = "not_eligible"
            elif verdict == "unknown" and state == "ready":
                state = "needs"
            rows.append(
                {
                    "id": cid,
                    "kind": c.kind,
                    "label": c.label or c.text[:60],
                    "verdict": verdict,
                    "reason": reason,
                    "facts": [r.split("|")[0] for r in refs][:10],
                }
            )
        out.append({"pid": pid, "short": pid[:8], "state": state, "criteria": rows})
    return out


def feasibility(svc: SiteSetup, ws: str, rs: Any, today: date) -> dict[str, Any] | None:
    """Feasibility counts on the workspace's lake, each with how much rests on coded, confirmed and proposed facts
    (in the box only; the FEAS report rounds them)."""
    from orchestrator.scenarios.feas_compute import FeasError, FeasParams, compute

    lake = svc.lake(ws)
    snap = lake.snapshot()
    if not snap:
        return None
    try:
        _res, raw = compute(lake, rs, FeasParams(run_date=today, snapshot=snap, lookback_months=36))
    except FeasError:
        return None
    by = {c.id: c for c in rs.active()}
    steps = []
    for cid, n in raw.remaining.items():
        b = raw.basis.get(cid, {"coded": n, "confirmed": 0, "proposed": 0})
        c = by.get(cid)
        steps.append({"id": cid, "label": (c.label or c.text[:60]) if c else cid, "remaining": n, **b})
    return {"start": raw.start_n, "steps": steps, "snapshot": snap}
