"""The weekly PI sample of "criteria not matched", the send-back to the PI list, and the site's check (T-310a, D-446).

URS-PI-05, CR-014, FIT-007, UX-032. Three things around the study's "criteria not matched" page (``console.home``,
D-143, D-351):

* **The weekly sample** (``/studies/{rs}/not-matched/sample``): ten of the latest screening run's not-matched patients
  a week, the same ten for everyone who opens it, drawn by the orchestrator's weekly job
  (:mod:`orchestrator.notmatched_sample`) or, when that has not run yet this week, by the first page view, from the
  run's stored list (its own snapshot) and never with an opted-out patient. The PI answers each one: "the records do
  not match, as the run said" (``agree``) or "send back to my list" (``send_back``). The page counts the answers of
  the week and the study's sample so far. Rows ``notmatched.sample`` and ``notmatched.send_back``: the study's PI,
  and a sub-investigator only with the "screen" tick.
* **Send-back re-enters the PI list.** A patient sent back from the sample or from the list ("This is wrong, send to
  review") is on the study's weekly list again (tier ``review``, marked "sent back"), until the PI marks them.
* **The site's check.** Where ``TB_NOT_MATCHED_GATE`` holds the list (``auto``: VALIDATION and PRODUCTION), the list
  and its sample show nobody until the data steward records, on ``/studies/{rs}/not-matched/check``, that the site's
  check (the dry run) passed, with the id of its record. Taking it back (with a note) holds the list again. Row
  ``notmatched.check``: the steward. Every record is audited (``console.notmatched_check``).

Every changing page route has its ``/api/v1`` twin; the API checks the session before it reads the body.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from tb_common.notmatched import ANSWERS, NotMatchedError, NotMatchedStore, gate_on, iso_week, sample_week
from tb_contracts import Job

from console import ai_confirm, i18n_notmatched
from console import studies as st
from console.auth import Session
from console.home import Helpers, json_body
from console.i18n import CATALOGUES

for _lang, _cat in (("en", i18n_notmatched.EN), ("ja", i18n_notmatched.JA), ("zh-TW", i18n_notmatched.ZH)):
    CATALOGUES[_lang].update(_cat)

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
EVIDENCE = ("quote", "quote_date", "reason", "resource_refs")


#: ERASE-C (D-868): the token an opted-out patient's sample row holds after the opt-out worker's clear
ERASED = "erased:"


class NotMatched:
    """What ``console.home`` asks (``Helpers.not_matched``): is a study's list open, the state the page shows, and the
    sent-back patients the weekly list takes back."""

    def __init__(self, h: Helpers, store: NotMatchedStore, gated: bool) -> None:
        self.h, self.store, self.gated = h, store, gated

    def shown(self, rid: str) -> bool:
        return self.store.shown(rid, self.gated)

    def state(self, rid: str) -> dict[str, Any]:
        return {"gated": self.gated, "shown": self.shown(rid), "check": self.store.check(rid)}

    def back_to_list(self, rs: str, cl: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """``cl`` with the sent-back patients of the latest not-matched list added as ``review`` rows, and
        {pid: the send-back} for them. A patient already on the list stays as the run listed them."""
        sent = self.h.store.excluded_reviews(rs)
        if not sent or self.h.excluded_bundle is None:
            return cl, {}
        _job, doc = self.h.excluded_bundle(rs)  # opted-out patients are already off it (D-273)
        if doc is None:
            return cl, {}
        rows = list((cl or {}).get("rows") or [])
        have = {str(r.get("pid")) for r in rows}
        back: dict[str, Any] = {}
        for r in doc.get("rows") or []:
            pid = str(r.get("pid") or "")
            if pid in sent and pid not in have and pid not in back:
                crits = [{"id": c.get("id"), "verdict": "fail", "evidence": {k: c[k] for k in EVIDENCE if k in c}}
                         for c in r.get("criteria") or [] if c.get("id")]  # fmt: skip
                rows.append({"pid": pid, "tier": "review", "criteria": crits, "actions": list(r.get("actions") or []),
                             "sent_back": True})  # fmt: skip
                back[pid] = sent[pid]
        if not back:
            return cl, {}
        return {**(cl or {}), "rows": rows}, back


def register(app: FastAPI, h: Helpers, env: Mapping[str, str], store: NotMatchedStore | None = None) -> NotMatched:
    nm = NotMatched(h, store if store is not None else NotMatchedStore(), gate_on(env))
    h.not_matched = nm
    au = h.au

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def api(request: Request) -> Session:
        """The bearer session of an ``/api/v1`` call (``console.home``), checked before anything else."""
        assert h.api_session is not None  # set by console.home.register, which runs first
        return h.api_session(request)

    def study(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not st.known_study(h.bk, rid):
            if _RS.match(rid):
                au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        return rid

    def need(sess: Session, rs: str, action: str, path: str) -> str:
        """The study, for an account the ``action`` row lets in there (with its standing in the delegation log)."""
        rid = study(sess, rs)
        if not h.permit(sess.user, action, rid):
            raise deny(sess, path)
        return rid

    def run_doc(job_id: str) -> tuple[Job | None, dict[str, Any] | None]:
        """The stored not-matched list of the run a sample was drawn from (its own snapshot, D-383)."""
        job = h.bk.get_job(job_id) if job_id else None
        out = st.output(job, "excluded_", ".json")
        if out is None:
            return job, None
        try:
            doc = json.loads(h.bk.get_object(out.minio_key))
        except (KeyError, ValueError, OSError):
            return job, None
        return job, doc if isinstance(doc, dict) else None

    def week_sample(sess: Session, rid: str) -> dict[str, Any]:
        """This week's sample of the study, drawn now if nobody has yet; the rows as the not-matched page shows them,
        without the patients on the opt-out register."""
        week = iso_week(h.today())
        got = nm.store.sample(rid, week)
        if not got and h.excluded_bundle is not None:
            job, doc = h.excluded_bundle(rid)
            if job is not None and doc is not None:
                snap = job.snapshot_date.isoformat() if job.snapshot_date else str(doc.get("snapshot") or "")
                got, drawn = sample_week(nm.store, rid, week, doc, job_id=job.job_id, snapshot=snap, gone=h.gone(),
                                         by=h.actor(sess), at=h.clock().isoformat())  # fmt: skip
                if drawn:
                    au.append("notmatched.sample", ruleset=rid, job_id=job.job_id, actor=h.actor(sess),
                              detail={"week": week, "n": len(got), "snapshot": snap, "by": "page"})  # fmt: skip
        gone = h.gone()
        shown = [t for t in got if t.pid not in gone and not t.pid.startswith(ERASED)]  # D-868: an erased row
        rows: dict[str, dict[str, Any]] = {}
        values_unread = False  # NEW-CAND-1 (D-713): a run of this sample could not read its coded values (D-652)
        for job_id in sorted({t.job_id for t in shown}):
            _job, doc = run_doc(job_id)
            values_unread = values_unread or (doc or {}).get("coded_values") == "not read"
            if doc is not None and h.excluded_rows is not None:
                pids = {t.pid for t in shown if t.job_id == job_id}
                part = {**doc, "rows": [r for r in doc.get("rows") or [] if str(r.get("pid")) in pids]}
                rows.update({r["pid"]: r for r in h.excluded_rows(rid, part, sess.lang)})
        items = [{"t": t, "short": t.pid[:8], "items": (rows.get(t.pid) or {}).get("items") or []} for t in shown]
        answered = sum(1 for t in shown if t.answer)
        return {"week": week, "rows": items, "n": len(shown), "answered": answered, "removed": len(got) - len(shown),
                "back": sum(1 for t in shown if t.answer == "send_back"), "totals": nm.store.counts(rid),
                "values_unread": values_unread,
                "snapshot": shown[0].snapshot if shown else "", "job_id": shown[0].job_id if shown else ""}  # fmt: skip

    def apply_answer(sess: Session, path: str, rs: str, pid: str, answer: str, note: str) -> tuple[str, str]:
        """The PI's answer for one patient of this week's sample, the same for the page and ``/api/v1``. Returns
        (study, answer)."""
        rid = need(sess, rs, "notmatched.sample", path)
        if answer == "send_back" and not h.permit(sess.user, "notmatched.send_back", rid):
            raise deny(sess, path)
        if not nm.shown(rid):
            raise h.problem(409, "nm.held")
        if answer not in ANSWERS:
            raise h.problem(400, "nm.err.answer")
        if not _PID.match(pid) or pid in h.gone():  # an opted-out patient is never sent back (D-147)
            raise h.problem(404, "notfound")
        week = iso_week(h.today())
        mine = next((t for t in nm.store.sample(rid, week) if t.pid == pid), None)
        if mine is None:
            raise h.problem(404, "notfound")
        now = h.clock().isoformat()

        def before_commit() -> None:
            au.append("console.notmatched_answer", ruleset=rid, job_id=mine.job_id, actor=h.actor(sess),
                      detail={"pid": pid, "week": week, "answer": answer, "role": sess.user.role})  # fmt: skip
            if answer == "send_back":  # CR-014: back on the PI's weekly list, as from the not-matched page
                crit = mine.criteria[0] if mine.criteria and mine.criteria[0] != "rule" else ""
                _job, doc = run_doc(mine.job_id)  # D-989 (D-1152): the review rejects the answers that excluded

                def decided() -> None:
                    ai_confirm.review(au, rid, mine.job_id, doc, pid, crit, sess.user.username, h.actor(sess))

                h.store.send_excluded_review(rid, pid, mine.job_id, crit, " ".join(note.split())[:300],
                                             h.actor(sess), now, before_commit=decided)  # fmt: skip

        try:
            nm.store.answer(rid, week, pid, answer, note, h.actor(sess), now, before_commit=before_commit)
        except NotMatchedError as exc:
            raise h.problem(409, str(exc)) from exc
        return rid, answer

    def apply_check(sess: Session, path: str, rs: str, passed: bool, record: str, note: str) -> str:
        rid = need(sess, rs, "notmatched.check", path)

        def before_commit() -> None:
            au.append("console.notmatched_check", ruleset=rid, actor=h.actor(sess),
                      detail={"passed": passed, "record": record.strip()[:80], "note": note.strip()[:300]})  # fmt: skip

        try:
            nm.store.record_check(rid, passed=passed, record=record, note=note, by=h.actor(sess),
                                  at=h.clock().isoformat(), before_commit=before_commit)  # fmt: skip
        except NotMatchedError as exc:
            raise h.problem(400, str(exc)) from exc
        return rid

    # ------------------------------------------------------------------ the weekly sample
    @app.get("/studies/{rs}/not-matched/sample")
    def sample_page(request: Request, rs: str, done: str = "") -> Response:
        sess = h.need(request)
        rid = need(sess, rs, "notmatched.sample", request.url.path)
        state = nm.state(rid)
        ws = week_sample(sess, rid) if state["shown"] else None
        au.append("console.view", ruleset=rid, actor=h.actor(sess),
                  detail={"page": "not_matched_sample", "rows": ws["n"] if ws else 0})  # fmt: skip
        return h.page(request, "not_matched_sample.html", sess, rs=rid, ws=ws, held=state, done=done in ANSWERS,
                      may_back=bool(h.permit(sess.user, "notmatched.send_back", rid)), answer_done=done)  # fmt: skip

    @app.post("/studies/{rs}/not-matched/sample/{pid}")
    def sample_answer(request: Request, rs: str, pid: str, csrf: str = Form(""), answer: str = Form(""),
                      note: str = Form("")) -> Response:  # fmt: skip
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid, got = apply_answer(sess, request.url.path, rs, pid, answer, note)
        return RedirectResponse(f"/studies/{rid}/not-matched/sample?done={got}#s-{pid[:8]}", status_code=303)

    @app.get("/api/v1/studies/{rs}/not-matched/sample")
    def api_sample(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = need(sess, rs, "notmatched.sample", request.url.path)
        state = nm.state(rid)
        if not state["shown"]:
            return {"study": rid, "shown": False, "week": iso_week(h.today()), "patients": []}
        ws = week_sample(sess, rid)
        return {"study": rid, "shown": True, "week": ws["week"], "job_id": ws["job_id"], "snapshot": ws["snapshot"],
                "answered": ws["answered"], "size": ws["n"], "totals": ws["totals"],
                "patients": [{"pid": r["t"].pid, "criteria": list(r["t"].criteria), "answer": r["t"].answer}
                             for r in ws["rows"]]}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/not-matched/sample/{pid}")
    async def api_sample_answer(request: Request, rs: str, pid: str) -> dict[str, Any]:
        sess = api(request)
        rid = need(sess, rs, "notmatched.sample", request.url.path)  # the role before the body
        body = await json_body(request)
        _rid, got = apply_answer(sess, request.url.path, rid, pid, str(body.get("answer") or ""),
                                 str(body.get("note") or ""))  # fmt: skip
        return {"study": rid, "pid": pid, "answer": got, "on_pi_list": got == "send_back"}

    # ------------------------------------------------------------------ the site's check
    @app.get("/studies/{rs}/not-matched/check")
    def check_page(request: Request, rs: str, done: str = "") -> Response:
        sess = h.need(request)
        rid = need(sess, rs, "notmatched.check", request.url.path)
        return h.page(request, "not_matched_check.html", sess, rs=rid, held=nm.state(rid), done=done == "1")

    @app.post("/studies/{rs}/not-matched/check")
    def check_record(request: Request, rs: str, csrf: str = Form(""), passed: str = Form(""), record: str = Form(""),
                     note: str = Form("")) -> Response:  # fmt: skip
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid = apply_check(sess, request.url.path, rs, passed == "yes", record, note)
        return RedirectResponse(f"/studies/{rid}/not-matched/check?done=1", status_code=303)

    @app.get("/api/v1/studies/{rs}/not-matched/check")
    def api_check(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = need(sess, rs, "notmatched.check", request.url.path)
        return check_json(rid)

    @app.post("/api/v1/studies/{rs}/not-matched/check")
    async def api_check_record(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = need(sess, rs, "notmatched.check", request.url.path)  # the role before the body
        body = await json_body(request)
        passed = body.get("passed") is True
        apply_check(sess, request.url.path, rid, passed, str(body.get("record") or ""), str(body.get("note") or ""))
        return check_json(rid)

    def check_json(rid: str) -> dict[str, Any]:
        s = nm.state(rid)
        c = s["check"]
        return {"study": rid, "gated": s["gated"], "shown": s["shown"],
                "check": None if c is None else {"passed": c.passed, "record": c.record, "note": c.note, "by": c.by,
                                                 "at": c.at}}  # fmt: skip

    return nm


__all__ = ["NotMatched", "register"]
