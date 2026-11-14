"""One readiness page (D-131): the three questions as green, amber or red, each with what is missing.

1. **Which trial?** Red: no criteria. Amber: criteria drafted and not yet approved by the investigator. Green: an
   approved version and nothing waiting.
2. **Which patients could fit?** Red: no input. Amber with what is missing: proposed facts to check, local codes not
   mapped, sheet rows without a chart number, other "please check" items, inputs that disagree, the share of
   diagnoses in a code system TrialBox cannot read, and "feasibility needs a bulk source" when there are only charts.
   For the hospital's own workspace also a held night of the feed (T-611): the box still serves the night before,
   and the item names the tables the completeness gate refused (T-112b, D-443: read from ``dataops.batch``, so a
   night a steward has accepted or rejected is no longer held; the audit chain when no batch row exists). Green:
   none of these. The answer also names the feed tier the box serves (``feed``, :func:`feed_loaded`).
3. **Where do trial records live?** Green: TrialBox's forms are added (or REDCap is linked). Amber otherwise.

:func:`patient_check` runs the approved criteria (the SQL engine with D-130's and D-135's rules) on the workspace's
patients: ready, needs information, or not eligible, with every criterion's answer and why: the trail the
assistant reads for "why is this patient on the list?". :func:`feasibility` gives the counts with how much rests on
coded, confirmed and proposed facts.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from matching.coverage import ICD10CM
from tb_common.db import ENV as DB_ENV
from tb_common.db import DatabaseError
from tb_common.http import ServiceError

from sitesetup import publish
from sitesetup.service import LAKE_DOWN, SiteSetup


class LakeUnread(RuntimeError):
    """NEW-SITE-2 (D-709): the lake named the snapshot it serves and a question about that snapshot failed (its
    client raises a plain error for a query that does not answer 200). Not "nothing there"."""


#: the error types a reader of the lake raises when the lake could not be read; :func:`is_unread` says whether one is
UNREAD = (*LAKE_DOWN, LakeUnread)


def is_unread(exc: BaseException) -> bool:
    """Is this the lake not read, and not a fault to show as one? (D-712; narrowed by NEW-SITE-5, D-715.)

    A reader's ``LakeUnread``, or the lake failing or not answering (``lake_down``). With D-675 the status of a
    failed query says who failed: **500 and above is the lake** (it cannot serve the snapshot, it met a limit, it
    broke), which ``lake_down`` reads for every error of the lake's service. Below 500 the lake answered and the
    question is at fault (400: the statement refused; 422: the engine's complaint), or the caller's set-up (401,
    403: the service-token check): those go on as errors, and so does another service's error."""
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return unread_of(type(exc), status, getattr(exc, "service", None))


def unread_of(kind: type[BaseException], status: int | None, service: str | None) -> bool:
    """:func:`is_unread` decided by the error's type, its HTTP status and the service that raised it, never by the
    error itself (train 15: a handler hands these three, so the decision is visibly not the error's text). The
    same rule as ``lake_down`` (D-715): a failed query (``LakeQueryFailed``, a ``ServiceError`` of the lake) is
    the lake not read at 500 and above, or with no answer (0)."""
    from lake.client import LakeBadAnswer, LakeUnhealthy

    if issubclass(kind, LakeUnread | LakeUnhealthy | LakeBadAnswer):
        return True  # D-712: a 200 that is not the lake's answer is the lake failing too, whatever its status
    if issubclass(kind, ServiceError):
        return service == "lake" and status is not None and (status >= 500 or status == 0)
    if issubclass(kind, httpx.HTTPStatusError):
        return status is not None and status >= 500
    return issubclass(kind, httpx.HTTPError)


def _query_failed(exc: Exception) -> LakeUnread | None:
    """For a reader whose query of a snapshot the lake named has failed: the ``LakeUnread`` to raise when the
    lake failed, None when the question is at fault (the error then goes on as it is). Through the lake's client
    the status decides (:func:`is_unread`); a library lake (a space other than the hospital's) raises the lake's
    own classes, and the lake's own rule decides the same way (``lake.store.query_failure_status``, D-675)."""
    from lake.store import query_failure_status

    if isinstance(exc, UNREAD):
        return LakeUnread(type(exc).__name__) if is_unread(exc) else None
    return LakeUnread(type(exc).__name__) if query_failure_status(exc) >= 500 else None


UNKNOWN_SQL = """
SELECT count(*) AS n, count(*) FILTER (WHERE coalesce(code, '') = '' OR coalesce(system, '') <> $1) AS unknown
FROM condition
"""


def _state(missing: list[dict[str, Any]], red: bool) -> str:
    return "red" if red else ("amber" if missing else "green")


def unknown_share(svc: SiteSetup, ws: str) -> tuple[int, int]:
    """``(diagnoses, in an unknown code system)`` in the workspace's lake (D-130's meaning: not ICD-10-CM)."""
    lake = svc.lake(ws)
    if not lake.snapshot():  # D-709: a lake that cannot be asked raises here; it is not a lake with no diagnosis
        return 0, 0
    try:
        row = lake.query(UNKNOWN_SQL, [ICD10CM]).to_pylist()[0]
    except Exception as exc:  # it serves a snapshot; did the lake fail, or is this question at fault (D-715)?
        unread = _query_failed(exc)
        if unread is None:
            raise
        raise unread from exc
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


def newest_batch() -> Any:
    """T-112b (D-443): the newest night in ``dataops.batch``, or ``None`` when the trial database or the schema cannot
    be read (no ``TB_DB_URL``, no night recorded with the schema yet): the caller then reads the audit chain."""
    if not os.environ.get(DB_ENV):
        return None
    from datacore.dataops import newest_night

    try:
        return newest_night()
    except DatabaseError:
        return None


def feed_held(svc: SiteSetup, batch: Any = None) -> dict[str, Any] | None:
    """T-611 (DATA-001): when the newest night of the hospital feed was held, what the readiness page says: the box
    still serves the snapshot before it, and the tables the gate named.

    T-112b (D-443): the light is read from ``dataops.batch`` (``batch``: the newest night, :func:`newest_batch`) when
    the trial database has one; a night a steward has since accepted or rejected is no longer held. Without a batch
    row it is read from the audit chain's newest ``ingest.*`` event, as before."""
    if batch is not None:
        if batch.state != "HELD":
            return None
        return _held_item(batch.snapshot, batch.detail)
    rec = last_feed_night(getattr(getattr(svc, "audit", None), "directory", None))
    if not rec or rec.get("event") != "ingest.held":
        return None
    return _held_item(str(rec.get("snapshot") or ""), rec.get("detail") or {})


def _held_item(snapshot: str, detail: dict[str, Any]) -> dict[str, Any]:
    problems = [str(p) for p in detail.get("incomplete") or []]
    names = sorted({p.split(":", 1)[0] for p in problems})
    return {
        "key": "patients.feed_held",
        "n": max(len(names), 1),
        "tables": ", ".join(names) or "-",
        "snapshot": snapshot,
        "problems": problems[:10],
        "link": "/data-ops",
    }


def scores_unverified(svc: SiteSetup) -> dict[str, Any] | None:
    """D-442: the readiness item when the snapshot the box serves has no finished derive batch (it never ran, or it
    crashed): the stored scores were not computed for it, and while the stored-score read is on every score
    criterion reads "needs information". None without a trial database, a feed or a store that can be read."""
    if not os.environ.get(DB_ENV):
        return None
    try:
        snap = svc.lake("main").snapshot()
        if not snap:
            return None
        from tb_common.derived_store import shared_store

        st = shared_store()
        if st is None or st.batch(str(snap)) is not None:
            return None
    except LAKE_DOWN:  # D-709: a lake that cannot be asked does not say the scores are verified
        raise
    except Exception:
        return None
    return {"key": "patients.scores_unverified", "n": 1, "tables": str(snap)}


DOCS_SQL = "SELECT count(*) AS n FROM document"


def feed_loaded(svc: SiteSetup, batch: Any = None) -> dict[str, Any] | None:
    """T-112b (D-443): which tier of the hospital feed the box serves (survey question 26: tier 1 structured data of
    the participating departments, tier 2 all departments, tier 3 notes and reports). Read from what is loaded:
    ``CURRENT`` with notes or reports is ``notes`` (tier 3); with structured records only it is ``structured`` (tier
    1 or 2: the records do not say whether every department is in). ``None`` when no feed is loaded. ``batch``: the
    newest night, named beside the tier with its state."""
    lake = svc.lake("main")
    snap = lake.snapshot()  # D-709: a lake that cannot be asked raises here; it is not "no feed is loaded"
    if not snap:
        return None
    try:
        docs = int(lake.query(DOCS_SQL, []).to_pylist()[0]["n"] or 0)
    except Exception as exc:  # it serves a snapshot; did the lake fail, or is this question at fault (D-715)?
        unread = _query_failed(exc)
        if unread is None:
            raise
        raise unread from exc
    out: dict[str, Any] = {"snapshot": str(snap), "tier": "notes" if docs else "structured", "documents": docs}
    if batch is not None:
        out["night"] = {"snapshot": batch.snapshot, "state": batch.state, "attempt": batch.attempt}
    return out


def _or_unread(read: Any, unread: list[bool]) -> Any:
    """What ``read`` answers; None, and ``unread`` marked, when the lake could not be read for it (the lake went
    away after the first question, or names its snapshot and fails the query)."""
    try:
        return read()
    except UNREAD as exc:
        status = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
        if not unread_of(type(exc), status, getattr(exc, "service", None)):
            raise
        unread.append(True)
        return None


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
    # NEW-SITE-2 (D-709): asked once. A lake that cannot be asked is said so ("could not be read"), never read as
    # "no feed", "no unknown codes" or "scores verified"; what the set-up's own store holds is still answered
    unread: list[bool] = []  # marked by whichever question of this answer could not read the lake
    served = _or_unread(lambda: svc.lake(ws).snapshot(), unread)
    feed = ws == "main" and bool(served) and not inputs
    patients: list[dict[str, Any]] = []
    night = newest_batch() if ws == "main" else None  # T-112b (D-443): the lights read dataops first
    held = feed_held(svc, night) if ws == "main" else None
    if held:
        patients.append(held)
    unverified = _or_unread(lambda: scores_unverified(svc) if feed else None, unread)  # D-442: the served batch
    if unverified:
        patients.append(unverified)
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
    n_dx, n_unknown = (0, 0) if unread else (_or_unread(lambda: unknown_share(svc, ws), unread) or (0, 0))
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
    # T-112b (D-443): the tier the box serves
    loaded = _or_unread(lambda: feed_loaded(svc, night), unread) if ws == "main" and not unread else None
    if unread:  # said first, and without a link: nothing on these pages fixes it
        patients.insert(0, {"key": "patients.lake_unread"})
    no_patients = not inputs and not feed and not unread  # not known is not "none"
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
    out = {"ws": ws, "study": study.get("id"), "overall": overall, "questions": q, "bulk": bulk, "feed": loaded}
    return {**out, "lake_unread": True} if unread else out


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
