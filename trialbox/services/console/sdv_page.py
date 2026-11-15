"""The monitor's source-data verification pages and their ``/api/v1`` twins (T-303, D-436; FIT-002, ROLE-012, LIFE-026).

The owner's rule: SDV access to *enrolled subjects only*, limited to *the cited record items*. A CRO account reads a
study only under a monitor grant (D-380: a ``monitor`` entry of the delegation log for the visit dates, naming the
monitoring visit; ``console.team``):

* ``/studies/{rs}/monitor``: the study's enrolled subjects (``tb_common.authz.monitor_may_see``) by screening number,
  and the study's monitoring-visit records. The PI the log names and the steward (``monitor.grant``) see the visit
  records only.
* ``/studies/{rs}/monitor/{record}``: one enrolled subject's source-reference sheet: its lifecycle facts (never the
  pseudonym), then per CRF value a person decided (confirmed or changed) the citation its EDC draft holds (the
  source item the value was taken from), and the value's decisions and signatures. Nothing else of the patient's
  record: no open draft, no patient twin, no narrative, no chart number. It prints as the per-subject sheet.
  NEW-JRN-8 (D-772): below them, the subject's values in TrialBox's built-in forms, who entered each and when, and
  every change to them (``form_values``; the data core's record read takes the monitor's row for this).
* ``POST /studies/{rs}/monitor/visits``: the monitoring-visit record (date, the CRA = the signed-in account, the visit
  id of the grant, the subjects verified, findings), row ``monitor.visit``.

The data core answers ``GET /studies/{rs}/subjects/{record}`` with the subject nested under ``subject`` beside its
steps, visits and AEs; only that dict is the subject (D-436: reading the whole reply refused every enrolled subject).
Every read is audited with the monitoring-visit id (``console.monitor_view``); every refusal too (``console.denied``).
An enrolled subject who opted out is listed and opens with the day of the opt-out (D-762: still a trial subject,
D-441); a record keyed by the pseudonym is never listed or opened (D-772). Rights are matrix rows (``h.permit``);
the CRO scope check in ``console.app`` lets a CRO account reach these paths and nothing else patient-level.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from datacore.builtin import RECORD_FIELD, TITLES
from datacore.lifecycle import live_steps
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common.authz import monitor_may_see

from console import s28
from console.api_first import before_body
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.studies import known_study
from console.teamstore import FINDINGS_MAX, Entry, TeamError

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")  # a screening number (record id), as on the lifecycle pages
#: NEW-JRN-8 review (D-772): a record keyed by the pseudonym itself (the data core takes either key); never listed,
#: never opened, never read by the monitor
_PID = re.compile(r"^[0-9a-fA-F]{32}$")
#: the lifecycle facts the sheet shows; the pseudonym and who changed the state are not among them
SUBJECT_KEYS = ("record", "state", "since", "reason", "consented", "icf_version", "enrolled")
#: what a decided CRF value shows besides its value and citation
ITEM_KEYS = ("id", "visit", "visit_date", "item", "form", "cdash", "fate", "decided_by", "decided_at", "sent_at")
CITE_KEYS = ("kind", "table", "row", "snapshot", "day", "text", "quote", "name", "sha256", "path")
SIG_KEYS = ("printed_name", "role", "meaning", "at", "method")
#: NEW-JRN-8 (D-772): TrialBox's own forms, whose values the sheet shows with their trail (the screening number is the
#: record's key, not a value)
BUILTIN_FORMS = tuple(TITLES)
NOT_A_VALUE = (RECORD_FIELD,)
#: the review of D-772: coded, date and number fields only; free text (a note, a reason, a name, the AE term) can
#: carry a chart number or a narrative, which the sheet never shows (D-436)
SHOWN_KINDS = ("choice", "multi", "date", "dateTime", "integer", "decimal")
DECIDED = ("confirmed", "edited")


class ApiVisit(BaseModel):
    """The monitoring-visit record through ``/api/v1`` (the CRA and the visit id come from the session's grant)."""

    visit_day: str = Field(default="", max_length=10)
    subjects: list[str] = Field(default_factory=list, max_length=500)
    findings: str = Field(default="", max_length=FINDINGS_MAX + 1)


def _cite(raw: Any) -> dict[str, str] | None:
    """The citation an EDC draft holds, as plain text fields (a manual citation keeps the one it replaced)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, Mapping):
        return None
    out = {k: str(raw[k])[:300] for k in CITE_KEYS if raw.get(k) not in (None, "")}
    rep = _cite(raw.get("replaces")) if raw.get("replaces") is not None else None
    if rep:
        out["replaces"] = " · ".join(v for k, v in rep.items() if k in ("text", "day", "quote"))
    return out or None


def cited_items(drafts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per CRF value a person decided: the value, whether it is signed, and its citation. Open, rejected and
    superseded drafts are not values and are not shown; nor is any field a draft row holds beyond these (its
    pseudonym, the model's reason, the run)."""
    out = []
    for d in drafts:
        if d.get("fate") not in DECIDED:
            continue
        row: dict[str, Any] = {k: d.get(k) for k in ITEM_KEYS}
        row["value"] = d.get("final")
        row["redcap_now"] = d.get("redcap_now")  # NEW-EDC-5c (D-801): REDCap holds another value since (D-686)
        row["citation"] = _cite(d.get("final_citation")) or _cite(d.get("citation"))
        sig = d.get("signature")
        row["signature"] = {k: str(sig.get(k) or "") for k in SIG_KEYS} if isinstance(sig, Mapping) else None
        out.append(row)
    return out


def item_trail(trail: Mapping[str, Any], ids: set[int]) -> dict[str, list[dict[str, Any]]]:
    """The decisions about the values shown and the signatures over them; nothing about other drafts."""
    decisions = [
        {"at": str(x.get("at") or ""), "by": str(x.get("by_user") or ""), "visit": str(x.get("visit") or ""),
         "item": str(x.get("item") or ""), "action": str(x.get("action") or ""), "old": x.get("old"),
         "new": x.get("new"), "reason": str(x.get("reason") or ""), "citation": _cite(x.get("citation"))}
        for x in trail.get("decisions") or [] if int(x.get("draft_id") or 0) in ids
    ]  # fmt: skip
    shown = {str(x["item"]) for x in decisions}
    signatures = [
        {**{k: str(s.get(k) or "") for k in SIG_KEYS}, "visit": str(s.get("visit") or ""),
         "intact": bool(s.get("intact")), "items": [i for i in s.get("items") or [] if i in shown]}
        for s in trail.get("signatures") or []
    ]  # fmt: skip
    return {"decisions": decisions, "signatures": [s for s in signatures if s["items"]]}


def form_values(record: Mapping[str, Any], fields: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """NEW-JRN-8 (D-772): one subject's values in TrialBox's built-in forms (who entered each and when) and every change
    to them, in the forms' order. A field of any other form (a REDCap dictionary's, the EDC's) is not shown: the
    monitor sees those as cited items only."""
    known = {str(f.get("name")): (BUILTIN_FORMS.index(str(f.get("form"))), n, f) for n, f in enumerate(fields)
             if f.get("form") in BUILTIN_FORMS and f.get("name") not in NOT_A_VALUE
             and f.get("kind") in SHOWN_KINDS and (f.get("owner") or "trialbox") == "trialbox"}  # fmt: skip
    rows = []
    for event, vals in (record.get("values") or {}).items():
        for name, v in (vals or {}).items():
            if name in known:
                f = known[name][2]
                rows.append({"event": str(event), "field": name, "form": str(f.get("form")),
                             "form_titles": TITLES[str(f.get("form"))],
                             "label": str(f.get("label") or name), "labels": dict(f.get("labels") or {}),
                             "options": dict(f.get("options") or {}),
                             "option_labels": dict(f.get("option_labels") or {}), "value": v.get("value"),
                             "by": str(v.get("by") or ""), "at": str(v.get("at") or "")})  # fmt: skip
    rows.sort(key=lambda r: (known[r["field"]][0], r["event"], known[r["field"]][1]))
    trail = [{"at": str(x.get("at") or ""), "by": str(x.get("by") or ""), "event": str(x.get("event") or ""),
              "field": str(x.get("field")), "old": x.get("old"), "new": x.get("new")}
             for x in record.get("history") or [] if x.get("field") in known]  # fmt: skip
    return {"forms": rows, "form_trail": trail}


def register(app: FastAPI, h: Helpers) -> None:
    bk, au = h.bk, h.au

    def api(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)

    def deny(sess: Session, path: str, rid: str = "", **detail: str) -> Exception:
        where = {"ruleset": rid} if rid else {}
        au.append("console.denied", **where, actor=h.actor(sess), detail={"action": path[:80], **detail})
        return h.problem(403, "forbidden")

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        return rid

    def grant_of(sess: Session, rid: str) -> Entry | None:
        """The account's monitor grant in the study today, when ``monitor.read`` holds through it."""
        if h.stand is None or not h.permit(sess.user, "monitor.read", rid).allowed:
            return None
        return h.stand(sess.user, rid).monitor  # type: ignore[no-any-return]

    def need_grant(sess: Session, path: str, rid: str) -> Entry:
        g = grant_of(sess, rid)
        if g is None:
            raise deny(sess, path, rid)
        return g

    def core(path: str) -> Any:
        try:
            return s28.call(bk, "GET", path)
        except Problem as exc:
            if exc.status == 404:
                raise h.problem(404, "notfound") from exc
            raise h.problem(409, "request.refused", reason="the data core refused the request") from exc
        except Unavailable as exc:
            raise h.problem(503, "request.refused", reason="the data core did not answer") from exc

    def edc(path: str) -> Any:
        """An EDC read; a study without EDC prefill (404) has no cited values."""
        try:
            return s28.call(bk, "GET", path)
        except Problem as exc:
            if exc.status == 404:
                return None
            raise h.problem(409, "request.refused", reason="the EDC refused the request") from exc
        except Unavailable as exc:
            raise h.problem(503, "request.refused", reason="the EDC did not answer") from exc

    def opted(gone: Mapping[str, str], pid: str) -> str:
        """The day of the subject's opt-out ("yes" for a merged chart), "" when not opted out (D-762)."""
        return (gone[pid] or "yes") if pid and pid in gone else ""

    def pid_of(rid: str, one: Mapping[str, Any]) -> str:
        """The subject's pseudonym, for the day of an opt-out (D-762); "" when the box cannot tell."""
        pid = str(one.get("pid") or "")
        if pid:
            return pid
        if _PID.match(str(one.get("record") or "")):
            return str(one["record"]).lower()
        rec = str(one.get("record") or "").upper()
        return next((p for p, n in h.store.screening_nos(rid).items() if str(n).upper() == rec), "")

    def enrolled(rid: str) -> list[dict[str, Any]]:
        """The study's subjects a monitor may open: enrolled; the lifecycle facts only. NEW-LIFE-5 (D-762): an
        enrolled subject who opted out is a trial subject still (D-441): listed, with the day of the opt-out."""
        reply = core(f"/studies/{rid}/subjects?today={h.today().isoformat()}") or {}
        gone = h.opted_out_on()
        out = []
        for s in reply.get("subjects") or []:
            # D-762: an enrolled subject who opted out is listed with the day; D-772: a pseudonym-keyed record never
            if monitor_may_see(s) and not _PID.match(str(s.get("record") or "")):
                out.append({**{k: s.get(k) for k in SUBJECT_KEYS}, "opted_out": opted(gone, pid_of(rid, s))})
        return out

    def visits_of(sess: Session, rid: str, path: str, g: Entry | None) -> list[dict[str, Any]]:
        if g is None and not h.permit(sess.user, "monitor.grant", rid).allowed:
            raise deny(sess, path, rid)
        assert h.team is not None
        return [v.as_dict() for v in h.team.monitor_visits(rid)]

    def overview(sess: Session, path: str, rs: str) -> tuple[str, Entry | None, list[dict[str, Any]] | None, Any]:
        """(study, grant, enrolled subjects or None for a reader of the visit records only, visit records)."""
        rid = study_or_404(sess, rs)
        g = grant_of(sess, rid)
        visits = visits_of(sess, rid, path, g)
        subs = None
        if g is not None:
            subs = enrolled(rid)
            au.append("console.monitor_view", ruleset=rid, actor=h.actor(sess),
                      detail={"record": "*", "visit": g.training_ref or "", "subjects": len(subs)})  # fmt: skip
        return rid, g, subs, visits

    def sheet(sess: Session, path: str, rs: str, record: str) -> tuple[str, Entry, dict[str, Any]]:
        """One enrolled subject's source references. A candidate, a screen failure or a consented person who never
        enrolled is 403; each refusal and each view audited with the visit. An enrolled subject who opted out is
        shown with the day of the opt-out, never the pseudonym (NEW-LIFE-5, D-762)."""
        rid = study_or_404(sess, rs)
        g = need_grant(sess, path, rid)
        visit = g.training_ref or ""
        rec = record.strip()[:64]
        if not _REC.match(rec):
            raise h.problem(404, "notfound")
        if _PID.match(rec):  # the review of D-772: never read by a pseudonym, not even to refuse it
            au.append("console.denied", ruleset=rid, actor=h.actor(sess),
                      detail={"action": path[:80], "why": "pseudonym_key", "visit": visit})  # fmt: skip
            raise h.problem(404, "notfound")
        reply = core(f"/studies/{rid}/subjects/{quote(rec)}?today={h.today().isoformat()}") or {}
        one = dict(reply.get("subject") or {})  # the data core nests the subject (D-436)
        day = {str(s.get("new")): str(s.get("on_day") or "") for s in live_steps(list(reply.get("steps") or []))}
        one.setdefault("consented", day.get("consented", ""))
        one.setdefault("enrolled", day.get("enrolled", ""))
        if _PID.match(str(one.get("record") or "")):  # D-772: a pseudonym-keyed record is never opened
            au.append("console.denied", ruleset=rid, actor=h.actor(sess),
                      detail={"action": path[:80], "why": "pseudonym_key", "visit": visit})  # fmt: skip
            raise h.problem(404, "notfound")
        gone = opted(h.opted_out_on(), pid_of(rid, one))  # NEW-LIFE-5 (D-762): shown, never the pseudonym
        if not monitor_may_see(one):
            raise deny(sess, path, rid, why="not_enrolled", visit=visit)
        key = str(one.get("record") or rec).upper()
        drafts = edc(f"/studies/{rid}/edc/drafts?record={quote(key)}") or []
        items = cited_items(drafts)
        trail = edc(f"/studies/{rid}/edc/trail/{quote(key)}") or {}
        ids = {int(x["id"]) for x in items if x.get("id") is not None}
        typed = form_values(core(f"/studies/{rid}/records/{quote(key)}") or {},
                            list((core(f"/studies/{rid}/sources") or {}).get("fields") or []))  # fmt: skip
        au.append("console.monitor_view", ruleset=rid, actor=h.actor(sess),
                  detail={"record": rec, "visit": visit, "state": str(one.get("state") or ""),
                          "items": len(items), "forms": len(typed["forms"])})  # fmt: skip
        out = {"subject": {**{k: one.get(k) for k in SUBJECT_KEYS}, "opted_out": gone}, "items": items,
               **item_trail(trail, ids), **typed}  # fmt: skip
        return rid, g, out

    def record_visit(sess: Session, path: str, rs: str, body: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        """The monitoring-visit record: each subject named must be one the monitor may open now."""
        rid = study_or_404(sess, rs)
        if not h.permit(sess.user, "monitor.visit", rid).allowed:
            raise deny(sess, path, rid)
        g = need_grant(sess, path, rid)
        raw = body.get("subjects")
        named = [str(x).strip().upper()[:64] for x in (raw if isinstance(raw, list) else str(raw or "").split(","))]
        named = [x for x in named if x]
        allowed = {str(s["record"]).upper() for s in enrolled(rid)}
        stray = [x for x in named if x not in allowed]
        if stray:
            raise deny(sess, path, rid, why="not_enrolled", visit=g.training_ref or "")
        assert h.team is not None
        try:
            v = h.team.add_monitor_visit(
                rid, visit_ref=g.training_ref or "", visit_day=str(body.get("visit_day") or ""),
                cra=sess.user.username, subjects=named, findings=str(body.get("findings") or ""),
                at=h.clock().isoformat(),
            )  # fmt: skip
        except TeamError as exc:
            raise h.problem(400, "request.refused", reason=str(exc)) from exc
        au.append("console.monitor_visit", ruleset=rid, actor=h.actor(sess),
                  detail={"id": v.id, "visit": v.visit_ref, "day": v.visit_day,
                          "subjects": list(v.subjects)})  # fmt: skip
        return rid, v.as_dict()

    # ------------------------------------------------------------------ pages
    @app.get("/studies/{rs}/monitor")
    def monitor_list(request: Request, rs: str, done: str = "") -> Response:
        sess = h.need(request)
        rid, g, subs, visits = overview(sess, request.url.path, rs)
        return h.page(request, "sdv_list.html", sess, rs=rid, grant=g, subjects=subs, visits=visits,
                      done=done == "1", may_record=g is not None and h.permit(sess.user, "monitor.visit", rid).allowed,
                      findings_max=FINDINGS_MAX)  # fmt: skip

    @app.post("/studies/{rs}/monitor/visits")
    async def monitor_visit(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        body = {"visit_day": str(form.get("visit_day") or "")[:10],
                "subjects": [str(x) for x in form.getlist("subjects")],
                "findings": str(form.get("findings") or "")[: FINDINGS_MAX + 1]}  # fmt: skip
        rid, _ = record_visit(sess, request.url.path, rs, body)
        return RedirectResponse(f"/studies/{rid}/monitor?done=1", status_code=303)

    @app.get("/studies/{rs}/monitor/{record}")
    def monitor_page(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        rid, g, out = sheet(sess, request.url.path, rs, record)
        return h.page(request, "sdv_subject.html", sess, rs=rid, record=record[:64], grant=g, **out)

    # ------------------------------------------------------------------ /api/v1
    @app.get("/api/v1/studies/{rs}/monitor")
    def api_list(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid, g, subs, visits = overview(sess, request.url.path, rs)
        return {"study": rid, "visit": g.training_ref if g else None, "subjects": subs, "visits": visits}

    def first_visit(sess: Session, request: Request) -> None:
        """T-657 (D-444): the session and the ``monitor.visit`` row, before the body is read."""
        rid = study_or_404(sess, request.path_params["rs"])
        if not h.permit(sess.user, "monitor.visit", rid).allowed:
            raise deny(sess, request.url.path, rid)

    @app.post("/api/v1/studies/{rs}/monitor/visits")
    @before_body(first_visit)
    def api_visit(request: Request, rs: str, body: ApiVisit) -> dict[str, Any]:
        sess = api(request)
        rid, v = record_visit(sess, request.url.path, rs, body.model_dump())
        return {"study": rid, "visit": v}

    @app.get("/api/v1/studies/{rs}/monitor/{record}")
    def api_sheet(request: Request, rs: str, record: str) -> dict[str, Any]:
        sess = api(request)
        rid, g, out = sheet(sess, request.url.path, rs, record)
        return {"study": rid, "visit": g.training_ref or None, **out}
