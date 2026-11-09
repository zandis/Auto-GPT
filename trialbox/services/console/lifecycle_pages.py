"""TB-PLAN-04 step 5 (D-134): the trial lifecycle in the console, and its ``/api/v1`` routes (D-125, D-127).

* **Participants** (``/studies/{rs}/subjects``): every screening number of the study and its state; one participant
  (``/studies/{rs}/subjects/{record}``) with the next legal steps, Undo, every step so far, the visits with their
  windows, the AEs (several, on events ``ae1``, ``ae2`` ...) and deviations (``dv1`` ...). An illegal step is refused
  with a plain reason, on the page and in ``/api/v1``.
* **Visits** (``/studies/{rs}/visits``): the coordinator's list, today, this week and overdue; "Done today" opens the
  visit form filled in for today (two taps: the button, Save), "Open the visit form" opens it as it is. The same
  list is on the coordinator's home page; serious AEs are on the investigator's (and the coordinator's) home page.
* **Visit schedule** (``/studies/{rs}/schedule``): typed in, or read from REDCap's arms and events.
* **Enrolment report** (``/studies/{rs}/enrolment``, ``.csv``, ``.xlsx``).

Everything goes through the orchestrator's lifecycle API (``orchestrator.lifecycle_api``); each page first asks it
to bring the participants up to date with the site store's screening numbers. "Today" is the site's local date
(``site.tz``: Asia/Tokyo, Asia/Taipei). Roles as on the Entry page: the study's coordinator records steps and the
schedule; the investigator and the admin read; viewer and CRA accounts get 403; CRO and other-study accounts 404.
"""

from __future__ import annotations

import base64
import contextlib
import re
from datetime import date
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from console import s28
from console.auth import Session
from console.backend import Problem, Unavailable
from console.data_pages import err_of
from console.entry_pages import can_enter, record_key
from console.home import Helpers
from console.i18n import translate
from console.studies import known_study
from console.timefmt import local_today, site_zone

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VISIT = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATES = ("candidate", "approached", "consented", "enrolled", "on_study", "completed", "withdrawn", "screen_fail")
SF_REASONS = ("not_eligible", "declined", "lost_contact", "other")
WD_REASONS = ("1", "2", "3", "4", "5", "6")
SCHEDULE_ROWS = 4  # empty rows on the schedule page for new visits


class ApiStep(BaseModel):
    to: str = Field(max_length=20)
    on_day: str = Field(default="", max_length=10)
    reason: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=300)


class ApiVisit(BaseModel):
    visit: str = Field(max_length=41)
    day: int
    before: int = 0
    after: int = 0
    anchor: str = "enrolment"
    labels: dict[str, str] = Field(default_factory=dict)


class ApiSchedule(BaseModel):
    visits: list[ApiVisit]


def why_text(lang: str, exc: Problem) -> str:
    """A lifecycle refusal in the reader's language: the reason, with the states named in that language."""
    d = exc.detail
    key = f"life.why.{d.get('why') or 'other'}"

    def st(s: str) -> str:
        return translate(lang, f"life.state.{s}") if s in STATES else s

    allowed = ", ".join(st(x.strip()) for x in str(d.get("allowed") or "").split(",") if x.strip()) or "–"
    text = translate(lang, key, state=st(str(d.get("state") or "")), to=st(str(d.get("to") or "")), allowed=allowed)
    return translate(lang, "life.why.other") if text == key else text


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store
    tz = site_zone(bk)

    def today() -> date:
        return local_today(h.clock(), tz)

    def lang_of(sess: Session) -> str:
        return sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.role == "cro" or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not sess.user.can_view_phi:
            au.append("console.denied", actor=h.actor(sess), detail={"action": f"participants {rid}"})
            raise h.problem(403, "forbidden")
        return rid

    def need_enter(sess: Session, path: str) -> None:
        if not can_enter(sess.user):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")

    def screening(rid: str) -> dict[str, str]:
        try:
            return {no: pid for pid, no in store.screening_nos(rid).items()}
        except Exception:  # a store without the table answers no numbers
            return {}

    def refresh(rid: str, by: str, sess: Session | None = None) -> None:
        """Bring the participants up to date with the screening numbers and the screening log (idempotent). On a
        page this is the coordinator's (who records); an investigator, an administrator or a reader only reads."""
        if sess is not None and not can_enter(sess.user):
            return
        with contextlib.suppress(Problem, Unavailable):
            s28.call(bk, "POST", f"/studies/{rid}/subjects/refresh", {"screening": screening(rid), "by": by})

    def get(path: str) -> Any:
        return s28.call(bk, "GET", path)

    def short_of(sub: dict[str, Any]) -> str:
        pid = str(sub.get("pid") or "")
        return pid[:8] if pid else ""

    # ------------------------------------------------------------------ actions (one per page and /api/v1)
    def apply_step(sess: Session, path: str, rs: str, record: str, to: str, on_day: str, reason: str,
                   note: str) -> dict[str, Any]:  # fmt: skip
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        rec = record_key(record)
        if not _REC.match(rec) or (on_day and not _DAY.match(on_day)):
            raise Problem(400, "LIFE-STEP", "bad record or day", ["day"], detail={"why": "day"})
        body = {"to": to, "on_day": on_day, "reason": reason, "note": note[:300], "by": h.actor(sess),
                "today": today().isoformat()}  # fmt: skip
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/subjects/{quote(rec)}/step", body))
        au.append("console.life_step", ruleset=rid, actor=h.actor(sess), detail={"record": rec, "to": to})
        return out

    def apply_undo(sess: Session, path: str, rs: str, record: str) -> dict[str, Any]:
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        rec = record_key(record)
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/subjects/{quote(rec)}/undo", {"by": h.actor(sess)}))
        au.append("console.life_step", ruleset=rid, actor=h.actor(sess), detail={"record": rec, "to": "undo"})
        return out

    def apply_schedule(sess: Session, path: str, rs: str, visits: list[dict[str, Any]]) -> dict[str, Any]:
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        out = dict(s28.call(bk, "PUT", f"/studies/{rid}/schedule", {"visits": visits, "by": h.actor(sess)}))
        au.append("console.life_schedule", ruleset=rid, actor=h.actor(sess), detail={"visits": len(visits)})
        return out

    def apply_schedule_redcap(sess: Session, path: str, rs: str, token_ref: str) -> dict[str, Any]:
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/schedule/redcap", {"token_ref": token_ref,
                                                                             "by": h.actor(sess)}))  # fmt: skip
        au.append("console.life_schedule", ruleset=rid, actor=h.actor(sess), detail={"origin": "redcap"})
        return out

    def read_report_file(sess: Session, rs: str, fmt: str) -> tuple[str, str, bytes]:
        rid = study_or_404(sess, rs)
        if fmt not in ("csv", "xlsx"):
            raise h.problem(404, "notfound")
        out = s28.call(bk, "GET", f"/studies/{rid}/report/{fmt}?by={quote(h.actor(sess))}")
        data = base64.b64decode(out["b64"]) if "b64" in out else str(out.get("text") or "").encode("utf-8")
        au.append("console.export", ruleset=rid, actor=h.actor(sess), detail={"filename": str(out["name"])})
        return str(out["name"]), str(out["media_type"]), data

    # ------------------------------------------------------------------ what other pages show (home, mail)
    def visits_of(rid: str, day: date) -> dict[str, Any] | None:
        try:
            out = get(f"/studies/{rid}/visits?today={day.isoformat()}")
            subs = {s["record"]: s for s in get(f"/studies/{rid}/subjects?today={day.isoformat()}")["subjects"]}
        except (Problem, Unavailable):
            return None
        for r in [*out["rows"], *(x for rows in out["list"].values() for x in rows)]:
            r["short"] = short_of(subs.get(r["record"], {}))
            r["pid"] = str(subs.get(r["record"], {}).get("pid") or "")
        return dict(out)

    def aes(rid: str) -> dict[str, Any]:
        try:
            return dict(get(f"/studies/{rid}/aes?today={today().isoformat()}"))
        except (Problem, Unavailable):
            return {"unacked": [], "overdue": []}

    def serious(rid: str) -> list[dict[str, Any]]:
        """Serious AEs the investigator has not acknowledged, whatever their outcome (review 2026-11-09 P-02: a fatal
        SAE used to leave the banner and N1 the moment it was saved, as "not ongoing")."""
        return list(aes(rid).get("unacked") or [])

    def reports_due(rid: str) -> list[dict[str, Any]]:
        """One row per overdue report of a serious AE (P-03): participant, party, due date."""
        return [{**a, "party": c["party"], "due": c["due"]} for a in aes(rid).get("overdue") or []
                for c in a["clock"] if c["overdue"]]  # fmt: skip

    def life_home(sess: Session) -> dict[str, Any]:
        """The home page's visit block and serious-AE alert, across the studies this account sees."""
        if not sess.user.can_view_phi or h.trials is None:
            return {"studies": [], "sae": [], "reports": []}
        day = today()
        studies, sae, reports = [], [], []
        for r in h.trials(sess):  # read only: the lifecycle pages and the mail bring the participants up to date
            v = visits_of(r.id, day)
            if v is not None and v["rows"]:
                lst = v["list"]
                studies.append({"rs": r.id, "today": lst["today"], "week": lst["week"], "overdue": lst["overdue"]})
            sae += [{**a, "rs": r.id} for a in serious(r.id)]
            reports += [{**a, "rs": r.id} for a in reports_due(r.id)]
        return {"studies": studies, "sae": sae, "reports": reports, "today": day.isoformat()}

    def life_mail(rid: str, day: date) -> dict[str, Any]:
        """N1/N2 (D-134): the study's visits on ``day`` and its serious AEs, by pseudonym (the mail adds the screening
        number beside it, D-136; never a chart number in mail)."""
        refresh(rid, "console:notify")
        v = visits_of(rid, day)
        nos = store.screening_nos(rid)

        def short(pid: str) -> str:  # the screening number beside the pseudonym (D-136); never a chart number
            return f"{pid[:8]} ({nos[pid]})" if pid in nos else pid[:8] or "–"

        reports = [{"short": short(str(a.get("pid") or "")), "party": a["party"], "due": a["due"]}
                   for a in reports_due(rid)]  # fmt: skip
        if v is None:
            return {"today": [], "week": [], "overdue": [], "sae": len(serious(rid)), "reports": reports}
        lst = v["list"]
        keep = ("short", "visit", "due", "start", "end")

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {x: r[x] for x in keep} | {"short": short(str(r.get("pid") or ""))}

        return {k: [row(r) for r in lst[k]] for k in ("today", "week", "overdue")} | {
            "sae": len(serious(rid)), "reports": reports}  # fmt: skip

    h.life_home = life_home
    h.life_mail = life_mail
    h.life_sae = serious
    h.life_reports = reports_due

    def apply_ack(sess: Session, path: str, rs: str, record: str, event: str) -> dict[str, Any]:
        """The investigator acknowledges a serious AE (P-02, D-143): one tap, the study's investigator only."""
        rid = study_or_404(sess, rs)
        if sess.user.role != "investigator":
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        rec, ev = record_key(record[:64]), event.strip().lower()
        if not _REC.match(rec) or not re.fullmatch(r"ae\d{1,3}", ev):
            raise h.problem(404, "notfound")
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/aes/{quote(rec)}/{ev}/ack", {"by": h.actor(sess)}))
        au.append("console.sae_ack", ruleset=rid, actor=h.actor(sess),
                  detail={"record": rec, "event": ev, "at": out.get("ack_at")})  # fmt: skip
        return out

    # ------------------------------------------------------------------ pages
    @app.get("/studies/{rs}/subjects")
    def subjects_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        err = None
        subs: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        try:
            out = get(f"/studies/{rid}/subjects?today={today().isoformat()}")
            subs, counts = out["subjects"], out["counts"]
        except (Problem, Unavailable) as exc:
            err = err_of(exc)
        return h.page(request, "life_subjects.html", sess, rs=rid, subjects=subs, counts=counts, states=STATES,
                      err=err)  # fmt: skip

    def subject_page(request: Request, sess: Session, rid: str, rec: str, status: int = 200,
                     refused: str = "", done: str = "") -> Response:  # fmt: skip
        err = None
        one: dict[str, Any] = {}
        try:
            one = dict(get(f"/studies/{rid}/subjects/{quote(rec)}?today={today().isoformat()}"))
        except (Problem, Unavailable) as exc:
            if isinstance(exc, Problem) and exc.status == 404:
                raise h.problem(404, "notfound") from exc
            err = err_of(exc)
        return h.page(request, "life_subject.html", sess, status=status, rs=rid, record=rec, one=one, err=err,
                      editable=can_enter(sess.user), refused=refused, done=done, sf_reasons=SF_REASONS,
                      wd_reasons=WD_REASONS, today=today().isoformat())  # fmt: skip

    @app.get("/studies/{rs}/subjects/{record}")
    def subject(request: Request, rs: str, record: str, done: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        rec = record_key(record[:64])
        if not _REC.match(rec):
            raise h.problem(404, "notfound")
        refresh(rid, h.actor(sess), sess)
        return subject_page(request, sess, rid, rec, done=done if done in ("step", "undo", "entry", "ack") else "")

    @app.post("/studies/{rs}/subjects/{record}/step")
    async def subject_step(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        rec = record_key(record[:64])
        to, on_day, reason, note = (str(data.get(k) or "").strip()[:300] for k in ("to", "on_day", "reason", "note"))
        try:
            apply_step(sess, request.url.path, rid, rec, to, on_day, reason, note)
        except Problem as exc:
            return subject_page(request, sess, rid, rec, status=409, refused=why_text(lang_of(sess), exc))
        except Unavailable as exc:
            return subject_page(request, sess, rid, rec, status=503, refused=str(exc)[:120])
        return RedirectResponse(f"/studies/{rid}/subjects/{quote(rec)}?done=step", status_code=303)

    @app.post("/studies/{rs}/subjects/{record}/undo")
    async def subject_undo(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        rec = record_key(record[:64])
        try:
            apply_undo(sess, request.url.path, rid, rec)
        except Problem as exc:
            return subject_page(request, sess, rid, rec, status=409, refused=why_text(lang_of(sess), exc))
        return RedirectResponse(f"/studies/{rid}/subjects/{quote(rec)}?done=undo", status_code=303)

    @app.post("/studies/{rs}/subjects/{record}/aes/{event}/ack")
    async def sae_ack(request: Request, rs: str, record: str, event: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        try:
            apply_ack(sess, request.url.path, rs, record, event)
        except Problem as exc:
            raise h.problem(404 if exc.status == 404 else 409, "notfound" if exc.status == 404 else "request.refused",
                            reason=exc.message) from exc  # fmt: skip
        rid, rec = rs.strip().upper(), record_key(record[:64])
        back = str(data.get("back") or "")
        if back == "home":
            return RedirectResponse("/home?sae=acked", status_code=303)
        if back == "week":
            return RedirectResponse(f"/studies/{rid}/week?sae=acked", status_code=303)
        return RedirectResponse(f"/studies/{rid}/subjects/{quote(rec)}?done=ack", status_code=303)

    @app.get("/studies/{rs}/visits")
    def visits_page(request: Request, rs: str, saved: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        day = today()
        v = visits_of(rid, day)
        sched: list[Any] = []
        with contextlib.suppress(Problem, Unavailable):
            sched = list(get(f"/studies/{rid}/schedule")["visits"])
        return h.page(request, "life_visits.html", sess, rs=rid, v=v, schedule=sched, today=day.isoformat(),
                      editable=can_enter(sess.user), saved=saved[:80],
                      err=None if v is not None else {"code": "unavailable", "fields": ""})  # fmt: skip

    @app.get("/studies/{rs}/schedule")
    def schedule_page(request: Request, rs: str, saved: str = "", err: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        sched: list[Any] = []
        conns: list[str] = []
        try:
            sched = list(get(f"/studies/{rid}/schedule")["visits"])
            conns = [c["token_ref"] for c in (get("/redcap/connections") or {}).get("connections", [])]
        except (Problem, Unavailable):
            pass
        return h.page(request, "life_schedule.html", sess, rs=rid, schedule=sched, blank=SCHEDULE_ROWS, conns=conns,
                      editable=can_enter(sess.user), saved=saved[:10], refused=err[:300])  # fmt: skip

    @app.post("/studies/{rs}/schedule")
    async def schedule_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        try:
            if str(data.get("action") or "") == "redcap":
                out = apply_schedule_redcap(sess, request.url.path, rid, str(data.get("token_ref") or "")[:40])
            else:
                visits = []
                names, labels = data.getlist("visit"), data.getlist("label")
                days, before, after = data.getlist("day"), data.getlist("before"), data.getlist("after")
                anchors = data.getlist("anchor")
                lang = lang_of(sess)
                for i, raw in enumerate(names):
                    name = str(raw).strip().lower()
                    if not name:
                        continue

                    def num(xs: list[Any], i: int = i) -> int:
                        try:
                            return int(str(xs[i]).strip() or 0)
                        except (ValueError, IndexError):
                            return 99999  # refused by the orchestrator with the window's plain reason

                    label = str(labels[i]).strip()[:80] if i < len(labels) else ""
                    visits.append({"visit": name[:41], "day": num(days), "before": num(before), "after": num(after),
                                   "anchor": str(anchors[i]) if i < len(anchors) else "enrolment",
                                   "labels": {lang: label} if label else {}})  # fmt: skip
                out = apply_schedule(sess, request.url.path, rid, visits)
        except Problem as exc:
            q = urlencode({"err": why_text(lang_of(sess), exc) if exc.code == "LIFE-STEP" else exc.code})
            return RedirectResponse(f"/studies/{rid}/schedule?{q}", status_code=303)
        except Unavailable:
            return RedirectResponse(f"/studies/{rid}/schedule?err=unavailable", status_code=303)
        return RedirectResponse(f"/studies/{rid}/schedule?saved={len(out.get('visits') or [])}", status_code=303)

    @app.get("/studies/{rs}/enrolment")
    def enrolment(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        rep: dict[str, Any] | None = None
        err = None
        try:
            rep = dict(get(f"/studies/{rid}/report"))
        except (Problem, Unavailable) as exc:
            err = err_of(exc)
        return h.page(request, "life_report.html", sess, rs=rid, rep=rep, states=STATES, err=err)

    @app.get("/studies/{rs}/enrolment.{fmt}")
    def enrolment_file(request: Request, rs: str, fmt: str) -> Response:
        sess = h.need(request)
        try:
            name, media, data = read_report_file(sess, rs, fmt)
        except (Problem, Unavailable) as exc:
            raise h.problem(503, "unavailable", detail=str(exc)[:200]) from exc
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------------ /api/v1 (D-125, D-127)
    def api_session(request: Request) -> Session:
        assert h.api_session is not None, "console.home.register runs first"
        return h.api_session(request)

    def refused(sess: Session, exc: Exception) -> Response:
        if isinstance(exc, Unavailable):
            return JSONResponse({"error": "unavailable", "detail": {"detail": str(exc)[:200]}}, status_code=503)
        assert isinstance(exc, Problem)
        status = exc.status if 400 <= exc.status < 500 else 502
        detail = {"code": exc.code, "reason": exc.message, "fields": ", ".join(exc.fields)}
        if exc.code == "LIFE-STEP":
            detail.update({"why": str(exc.detail.get("why") or ""), "message": why_text(lang_of(sess), exc),
                           "allowed": str(exc.detail.get("allowed") or "")})  # fmt: skip
        return JSONResponse({"error": "request.refused", "detail": detail}, status_code=status)

    @app.get("/api/v1/studies/{rs}/subjects", response_model=None)
    def api_subjects(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        try:
            return {**get(f"/studies/{rid}/subjects?today={today().isoformat()}"), "may_step": can_enter(sess.user)}
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/subjects/{record}", response_model=None)
    def api_subject(request: Request, rs: str, record: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        try:
            return get(f"/studies/{rid}/subjects/{quote(record_key(record[:64]))}?today={today().isoformat()}")
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.post("/api/v1/studies/{rs}/subjects/{record}/step", response_model=None)
    def api_step(request: Request, rs: str, record: str, body: ApiStep) -> Any:
        sess = api_session(request)
        try:
            return {"study": rs.upper(), **apply_step(sess, request.url.path, rs, record, body.to, body.on_day,
                                                      body.reason, body.note)}  # fmt: skip
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.post("/api/v1/studies/{rs}/aes/{record}/{event}/ack", response_model=None)
    def api_sae_ack(request: Request, rs: str, record: str, event: str) -> Any:
        sess = api_session(request)
        try:
            return apply_ack(sess, request.url.path, rs, record, event)
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/visits", response_model=None)
    def api_visits(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        v = visits_of(rid, today())
        if v is None:
            return refused(sess, Unavailable("the lifecycle does not answer"))
        return v

    @app.get("/api/v1/studies/{rs}/schedule", response_model=None)
    def api_schedule(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        try:
            return get(f"/studies/{rid}/schedule")
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.put("/api/v1/studies/{rs}/schedule", response_model=None)
    def api_schedule_put(request: Request, rs: str, body: ApiSchedule) -> Any:
        sess = api_session(request)
        try:
            return apply_schedule(sess, request.url.path, rs, [v.model_dump() for v in body.visits])
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/enrolment", response_model=None)
    def api_enrolment(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        try:
            return get(f"/studies/{rid}/report")
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/enrolment/{fmt}", response_model=None)
    def api_enrolment_file(request: Request, rs: str, fmt: str) -> Any:
        sess = api_session(request)
        try:
            name, media, data = read_report_file(sess, rs, fmt)
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
