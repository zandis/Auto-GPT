"""EDC prefill pages and their ``/api/v1`` routes (D-160).

* ``/studies/{rs}/edc``: the switch (on only with the sponsor's written acknowledgement and the blind re-entry result;
  off by default), the REDCap target, the map's state, each subject and visit with its counts, "draft a subject",
  "send signed values to REDCap" and the ODM file.
* ``/studies/{rs}/edc/map``: read the data dictionary from REDCap, then per item its CDASH tag and where its value may
  come from. A suggestion fills the rows; nothing is drafted from a diagnosis or medicine code nobody typed.
* ``/studies/{rs}/edc/review/{record}``: the coordinator's review. Per value: the value and its citation; confirm,
  change with a reason, or reject. A value without a citation has no confirm button and is refused anyway. Then the
  electronic signature: the person types their password again, sees the meaning of the signature and their printed
  name, and signs every confirmed value of that subject and visit. Then send.
* ``/studies/{rs}/edc/trail/{record}``: every draft, decision, signature and send of one subject.

Who may do what is ``tb_common.authz.edc_allowed`` (``enter_data`` for the work, the PI alone to switch on, the PI or
an admin to switch off; never a viewer or a CRO account), read through the delegation log (``console.team``). The
orchestrator checks the switch and every review rule again (``edc.service``). Each action is one function used by the
page and by ``/api/v1``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common.authz import edc_allowed

from console import s28
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.i18n import translate
from console.studies import known_study

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VISIT = re.compile(r"^([a-z][a-z0-9_]{0,99})?$")
_ITEM = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
SOURCES = ("none", "patient", "observation", "condition", "medication", "note")
WHAT = {"none": ("",), "patient": ("birth_date", "sex"), "observation": ("value", "date"),
        "condition": ("presence", "date"), "medication": ("presence", "term", "start"), "note": ("value",)}  # fmt: skip
ACK_KINDS = ("sponsor_letter", "iit_pi_sponsor")


class ApiSwitch(BaseModel):
    on: bool
    kind: str = ""
    reference: str = Field(default="", max_length=120)
    ack_date: str = Field(default="", max_length=10)
    reentry_pages: int = Field(default=0, ge=0, le=100000)
    reentry_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=300)


class ApiEdcDictionary(BaseModel):
    token_ref: str = Field(min_length=1, max_length=32)
    record_field: str = Field(default="", max_length=100)


class ApiTarget(BaseModel):
    token_ref: str = Field(min_length=1, max_length=32)
    key_field: str = "tb_screening_no"
    id_field: str = "record_id"


class ApiMap(BaseModel):
    items: list[dict[str, Any]] = Field(max_length=2000)
    target: ApiTarget


class ApiDraft(BaseModel):
    record: str = Field(max_length=64)
    visit: str = Field(default="", max_length=100)
    visit_date: str = Field(max_length=10)


class ApiDecide(BaseModel):
    action: str
    value: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=300)
    source: str = Field(default="", max_length=300)  # where a typed value comes from (a manual citation)
    source_day: str = Field(default="", max_length=10)


class ApiSign(BaseModel):
    record: str = Field(max_length=64)
    visit: str = Field(default="", max_length=100)
    password: str = Field(min_length=1, max_length=200)
    meaning_ack: bool = False  # the signer read the meaning of the signature


class ApiSend(BaseModel):
    record: str | None = Field(default=None, max_length=64)


def err_of(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, Problem):
        return {"code": exc.code, "fields": ", ".join(exc.fields), "problems": exc.problems or
                list((exc.detail or {}).get("problems") or [])}  # fmt: skip
    return {"code": "unavailable", "fields": "", "problems": []}


def percent(text: str) -> float:
    """The re-entry accuracy as typed on the page: ``98.5``, ``98.5 %`` or ``0.985`` -> 0.985."""
    t = text.replace("%", "").strip()
    if not t:
        return 0.0
    x = float(t)
    return min(x / 100 if x > 1 else x, 1.0)


def parse_rows(form: Mapping[str, Any], items: list[str]) -> list[dict[str, Any]]:
    """The map page's rows (``<field>-<item>`` inputs) as map items."""
    out = []
    for it in items:

        def g(k: str, it: str = it) -> str:
            return str(form.get(f"{k}-{it}") or "").strip()

        sex = {}
        for part in g("sex_codes").split(","):
            key, _, val = part.partition("=")
            if key.strip() and val.strip():
                sex[key.strip()] = val.strip()
        try:
            window = int(g("window_days") or "30")
        except ValueError:
            window = -1
        out.append({"item": it, "cdash": g("cdash").upper(), "test": g("test").upper(), "source": g("source") or "none",
                    "what": g("what"), "codes": [c.strip() for c in g("codes").split(",") if c.strip()],
                    "system": g("system"), "unit": g("unit"), "pick": g("pick") or "latest_before",
                    "window_days": window, "yes_code": g("yes_code") or "1", "sex_codes": sex,
                    "question": g("question")})  # fmt: skip
    return out


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        return s28.call(bk, method, path, body)

    def stand(sess: Session, rid: str) -> tuple[frozenset[str], bool, Any]:
        from console.team import standing

        if h.team is None:
            return frozenset(), False, None
        s = standing(h.team, sess.user, rid, h.clock().date())
        return s.tasks, s.pi, s.entry

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def study_or_404(sess: Session, rs: str, action: str, path: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        tasks, pi, _ = stand(sess, rid)
        if not edc_allowed(sess.user.role, action, tasks=tasks, is_pi=pi):
            raise deny(sess, path)
        return rid

    def may(sess: Session, rid: str) -> dict[str, bool]:
        tasks, pi, _ = stand(sess, rid)
        return {a: edc_allowed(sess.user.role, a, tasks=tasks, is_pi=pi) for a in
                ("map", "draft", "review", "sign", "send", "export", "switch_on", "switch_off")}  # fmt: skip

    def pid_of(rid: str, record: str) -> str:
        """The subject's pseudonymous id from its screening number (the record key in the EDC); never a chart no."""
        rec = record.strip().upper()
        if not _REC.match(rec):
            raise h.problem(400, "edc.err.edc.record")
        pid = next((p for p, n in store.screening_nos(rid).items() if str(n).upper() == rec), None)
        if pid is None:
            raise h.problem(404, "notfound")
        if h.optout is not None and pid in h.optout.active():
            raise h.problem(409, "edc.err.edc.opted_out")
        return pid

    def by(sess: Session) -> str:
        return sess.user.username

    # ------------------------------------------------------------------ the actions (page and /api/v1)
    def do_switch(sess: Session, path: str, rs: str, body: ApiSwitch) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "switch_on" if body.on else "switch_off", path)
        out = call("POST", f"/studies/{rid}/edc/switch", {**body.model_dump(), "by": by(sess), "role": sess.user.role})
        au.append("console.edc", ruleset=rid, actor=h.actor(sess), detail={"action": "switch", "on": body.on})
        return dict(out)

    def do_dictionary(sess: Session, path: str, rs: str, body: ApiEdcDictionary) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "map", path)
        return dict(call("POST", f"/studies/{rid}/edc/dictionary", {**body.model_dump(), "by": by(sess)}))

    def do_map(sess: Session, path: str, rs: str, body: ApiMap) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "map", path)
        return dict(call("PUT", f"/studies/{rid}/edc/map", {**body.model_dump(), "by": by(sess)}))

    def do_draft(sess: Session, path: str, rs: str, body: ApiDraft) -> list[dict[str, Any]]:
        rid = study_or_404(sess, rs, "draft", path)
        if not _VISIT.match(body.visit):
            raise h.problem(400, "edc.err.edc.visit")
        pid = pid_of(rid, body.record)
        return list(call("POST", f"/studies/{rid}/edc/drafts", {"record": body.record.strip().upper(), "pid": pid,
                                                                "visit": body.visit, "visit_date": body.visit_date,
                                                                "by": by(sess)}))  # fmt: skip

    def do_decide(sess: Session, path: str, rs: str, draft_id: int, body: ApiDecide) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "review", path)
        cit = {"text": body.source, "day": body.source_day} if body.source.strip() else None
        return dict(call("POST", f"/studies/{rid}/edc/drafts/{draft_id}/decide",
                         {"action": body.action, "value": body.value, "reason": body.reason, "citation": cit,
                          "by": by(sess)}))  # fmt: skip

    def do_sign(sess: Session, path: str, rs: str, body: ApiSign) -> dict[str, Any]:
        """The electronic signature: the signer types their password again (each failure counts toward the lockout)
        and acknowledges the meaning; the printed name is the one on the delegation log."""
        rid = study_or_404(sess, rs, "sign", path)
        if not _VISIT.match(body.visit):
            raise h.problem(400, "edc.err.edc.visit")
        if h.users.is_sso(sess.user.username):
            raise h.problem(409, "edc.err.edc.sign_sso")
        if not body.meaning_ack:
            raise h.problem(400, "edc.err.edc.meaning_ack")
        if h.users.authenticate(sess.user.username, body.password) is None:
            au.append("console.edc_reauth_failed", ruleset=rid, actor=h.actor(sess),
                      detail={"record": body.record.upper()[:64]})  # fmt: skip
            raise h.problem(401, "edc.err.edc.reauth")
        _, _, entry = stand(sess, rid)
        name = (entry.name if entry is not None and entry.name else "") or sess.user.username
        out = call("POST", f"/studies/{rid}/edc/sign", {
            "record": body.record.strip().upper(), "visit": body.visit, "signer": by(sess), "printed_name": name,
            "role": sess.user.role, "meaning": "transcribed", "lang": sess.lang,
            "meaning_text": translate(sess.lang, "edc.sign.meaning")})  # fmt: skip
        return dict(out)

    def do_send(sess: Session, path: str, rs: str, record: str | None) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "send", path)
        rec = record.strip().upper() if record else None
        if rec is not None and not _REC.match(rec):
            raise h.problem(400, "edc.err.edc.record")
        return dict(call("POST", f"/studies/{rid}/edc/send/redcap", {"record": rec, "by": by(sess)}))

    def do_export(sess: Session, path: str, rs: str) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "export", path)
        return dict(call("GET", f"/studies/{rid}/edc/export/odm?by={by(sess)}"))

    # ------------------------------------------------------------------ pages
    def status_page(request: Request, sess: Session, rid: str, err: dict[str, Any] | None = None,
                    status: int = 200) -> Response:  # fmt: skip
        st = call("GET", f"/studies/{rid}/edc")
        nos = {str(n).upper(): p for p, n in store.screening_nos(rid).items()}
        try:
            conns = [c["token_ref"] for c in (call("GET", "/redcap/connections").get("connections") or [])]
        except (Problem, Unavailable):
            conns = []
        resp = h.page(request, "edc.html", sess, rs=rid, st=st, may=may(sess, rid), subjects=sorted(nos),
                      connections=conns, kinds=ACK_KINDS, err=err)  # fmt: skip
        resp.status_code = status
        return resp

    @app.get("/studies/{rs}/edc")
    def edc_home(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        try:
            return status_page(request, sess, rid)
        except (Problem, Unavailable) as exc:
            return h.page(request, "edc.html", sess, rs=rid, st=None, may=may(sess, rid), subjects=[],
                          connections=[], kinds=ACK_KINDS, err=err_of(exc))  # fmt: skip

    async def form_of(request: Request, sess: Session) -> Any:
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        return form

    def back(rid: str, sess: Session, request: Request, exc: Exception) -> Response:
        return status_page(request, sess, rid, err_of(exc), 409)

    @app.post("/studies/{rs}/edc/switch")
    async def edc_switch(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        on = str(form.get("on") or "") == "1"
        rid = study_or_404(sess, rs, "switch_on" if on else "switch_off", request.url.path)
        try:
            pages = int(str(form.get("reentry_pages") or "0") or 0)
            acc = percent(str(form.get("reentry_accuracy") or ""))
            body = ApiSwitch(on=on, kind=str(form.get("kind") or ""), reference=str(form.get("reference") or ""),
                             ack_date=str(form.get("ack_date") or ""), reentry_pages=pages,
                             reentry_accuracy=min(acc, 1.0), reason=str(form.get("reason") or ""))  # fmt: skip
        except ValueError:
            return status_page(request, sess, rid, {"code": "edc.reentry", "fields": "", "problems": []}, 400)
        try:
            do_switch(sess, request.url.path, rid, body)
        except (Problem, Unavailable) as exc:
            return back(rid, sess, request, exc)
        return RedirectResponse(f"/studies/{rid}/edc?done=switch", status_code=303)

    @app.post("/studies/{rs}/edc/drafts")
    async def edc_draft(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "draft", request.url.path)
        rec, visit = str(form.get("record") or "").strip().upper(), str(form.get("visit") or "").strip()
        try:
            do_draft(sess, request.url.path, rid, ApiDraft(record=rec, visit=visit,
                                                         visit_date=str(form.get("visit_date") or "")))  # fmt: skip
        except (Problem, Unavailable) as exc:
            return back(rid, sess, request, exc)
        return RedirectResponse(f"/studies/{rid}/edc/review/{rec}?visit={visit}", status_code=303)

    @app.post("/studies/{rs}/edc/send")
    async def edc_send(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "send", request.url.path)
        rec = str(form.get("record") or "").strip() or None
        try:
            out = do_send(sess, request.url.path, rid, rec)
        except (Problem, Unavailable) as exc:
            if rec:
                return review_page(request, sess, rid, rec, str(form.get("visit") or ""), err_of(exc), 409)
            return back(rid, sess, request, exc)
        q = "&".join(f"{k}={len(out.get(k) or [])}" for k in ("sent", "already_there", "conflict", "no_record",
                                                             "readback"))  # fmt: skip
        if rec:
            return RedirectResponse(f"/studies/{rid}/edc/review/{rec.upper()}?visit={form.get('visit') or ''}&{q}",
                                    status_code=303)  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/edc?{q}", status_code=303)

    @app.get("/studies/{rs}/edc/export.odm.xml")
    def edc_odm(request: Request, rs: str) -> Response:
        sess = h.need(request)
        try:
            out = do_export(sess, request.url.path, rs)
        except (Problem, Unavailable) as exc:
            return back(rs.strip().upper(), sess, request, exc)
        return Response(str(out["text"]), media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{out["name"]}"'})  # fmt: skip

    # ------------------------------------------------------------------ the map
    def map_page(request: Request, sess: Session, rid: str, err: dict[str, Any] | None = None, status: int = 200,
                 rows: list[dict[str, Any]] | None = None) -> Response:  # fmt: skip
        st = call("GET", f"/studies/{rid}/edc")
        fields = {f["name"]: f for f in (call("GET", f"/studies/{rid}/sources").get("fields") or [])}
        saved = {m["item"]: m for m in st.get("map") or []}
        if rows is None:
            rows = st.get("map") or []
            if request.query_params.get("suggest") or not rows:
                sug = {m["item"]: m for m in call("GET", f"/studies/{rid}/edc/map/suggest")}
                rows = [saved.get(i) or sug[i] for i in sug] if not request.query_params.get("suggest") else list(
                    sug.values())  # fmt: skip
        try:
            conns = [c["token_ref"] for c in (call("GET", "/redcap/connections").get("connections") or [])]
        except (Problem, Unavailable):
            conns = []
        bad: dict[str, list[str]] = {}
        for p in (err or {}).get("problems") or []:
            bad.setdefault(str(p.get("item")), []).append(str(p.get("code")))
        resp = h.page(request, "edc_map.html", sess, rs=rid, rows=rows, fields=fields, st=st, sources=SOURCES,
                      what=WHAT, connections=conns, err=err, bad=bad, may=may(sess, rid))  # fmt: skip
        resp.status_code = status
        return resp

    @app.get("/studies/{rs}/edc/map")
    def edc_map(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "map", request.url.path)
        return map_page(request, sess, rid)

    @app.post("/studies/{rs}/edc/dictionary")
    async def edc_dictionary(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "map", request.url.path)
        try:
            out = do_dictionary(
                sess,
                request.url.path,
                rid,
                ApiEdcDictionary(
                    token_ref=str(form.get("token_ref") or "x")[:32], record_field=str(form.get("record_field") or "")
                ),
            )
        except (Problem, Unavailable) as exc:
            return map_page(request, sess, rid, err_of(exc), 409)
        return RedirectResponse(f"/studies/{rid}/edc/map?suggest=1&fields={out.get('fields', 0)}", status_code=303)

    @app.post("/studies/{rs}/edc/map")
    async def edc_map_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "map", request.url.path)
        items = [str(i) for i in form.getlist("item") if _ITEM.match(str(i))]
        rows = parse_rows(form, items)
        target = ApiTarget(token_ref=str(form.get("token_ref") or "x")[:32] or "x",
                           key_field=str(form.get("key_field") or "tb_screening_no"),
                           id_field=str(form.get("id_field") or "record_id"))  # fmt: skip
        try:
            do_map(sess, request.url.path, rid, ApiMap(items=rows, target=target))
        except (Problem, Unavailable) as exc:
            return map_page(request, sess, rid, err_of(exc), 409, rows)
        return RedirectResponse(f"/studies/{rid}/edc?done=map", status_code=303)

    # ------------------------------------------------------------------ review and sign
    def review_page(request: Request, sess: Session, rid: str, record: str, visit: str,
                    err: dict[str, Any] | None = None, status: int = 200) -> Response:  # fmt: skip
        rec = record.strip().upper()
        if not _REC.match(rec) or not _VISIT.match(visit):
            raise h.problem(404, "notfound")
        pid_of(rid, rec)  # a subject of this study (and not opted out)
        q = f"?record={rec}" + (f"&visit={visit}" if visit else "")
        drafts = list(call("GET", f"/studies/{rid}/edc/drafts{q}"))
        fields = {f["name"]: f for f in (call("GET", f"/studies/{rid}/sources").get("fields") or [])}
        st = call("GET", f"/studies/{rid}/edc")
        _, _, entry = stand(sess, rid)
        name = (entry.name if entry is not None and entry.name else "") or sess.user.username
        visits = sorted({str(d["visit"]) for d in drafts})
        unsigned = [d for d in drafts if d["fate"] in ("confirmed", "edited") and d["signature_id"] is None]
        resp = h.page(request, "edc_review.html", sess, rs=rid, record=rec, visit=visit, visits=visits, drafts=drafts,
                      fields=fields, st=st, unsigned=unsigned, printed_name=name, err=err, may=may(sess, rid),
                      sso=h.users.is_sso(sess.user.username))  # fmt: skip
        resp.status_code = status
        return resp

    @app.get("/studies/{rs}/edc/review/{record}")
    def edc_review(request: Request, rs: str, record: str, visit: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "review", request.url.path)
        try:
            return review_page(request, sess, rid, record, visit)
        except (Problem, Unavailable) as exc:
            return back(rid, sess, request, exc)

    @app.post("/studies/{rs}/edc/decide/{draft_id}")
    async def edc_decide(request: Request, rs: str, draft_id: int) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "review", request.url.path)
        rec, visit = str(form.get("record") or ""), str(form.get("visit") or "")
        body = ApiDecide(action=str(form.get("action") or ""), value=str(form.get("value") or "")[:2000],
                         reason=str(form.get("reason") or "")[:300], source=str(form.get("source") or "")[:300],
                         source_day=str(form.get("source_day") or "")[:10])  # fmt: skip
        try:
            do_decide(sess, request.url.path, rid, draft_id, body)
        except (Problem, Unavailable) as exc:
            return review_page(request, sess, rid, rec, visit, {**err_of(exc), "draft": draft_id}, 409)
        return RedirectResponse(f"/studies/{rid}/edc/review/{rec.upper()}?visit={visit}#d{draft_id}", status_code=303)

    @app.post("/studies/{rs}/edc/sign")
    async def edc_sign(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "sign", request.url.path)
        rec, visit = str(form.get("record") or ""), str(form.get("visit") or "")
        try:
            do_sign(
                sess,
                request.url.path,
                rid,
                ApiSign(
                    record=rec[:64] or "x",
                    visit=visit[:100],
                    password=str(form.get("password") or "")[:200] or " ",
                    meaning_ack=str(form.get("meaning_ack") or "") == "1",
                ),
            )
        except (Problem, Unavailable) as exc:
            return review_page(request, sess, rid, rec, visit, err_of(exc), 409)
        return RedirectResponse(f"/studies/{rid}/edc/review/{rec.upper()}?visit={visit}&signed=1", status_code=303)

    @app.get("/studies/{rs}/edc/trail/{record}")
    def edc_trail(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        rec = record.strip().upper()
        pid_of(rid, rec)
        trail = call("GET", f"/studies/{rid}/edc/trail/{rec}")
        return h.page(request, "edc_trail.html", sess, rs=rid, record=rec, trail=trail)

    # ------------------------------------------------------------------ /api/v1
    def api(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)

    def api_call(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except Problem as exc:
            status = exc.status if 400 <= exc.status < 500 else 502
            raise h.problem(status, "request.refused", code=exc.code, reason=exc.message,
                            fields=", ".join(exc.fields)) from exc  # fmt: skip
        except Unavailable as exc:
            raise h.problem(503, "unavailable", detail=str(exc)[:200]) from exc

    @app.get("/api/v1/studies/{rs}/edc")
    def api_status(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        return {"study": rid, "may": may(sess, rid), **api_call(call, "GET", f"/studies/{rid}/edc")}

    @app.post("/api/v1/studies/{rs}/edc/switch")
    def api_switch(request: Request, rs: str, body: ApiSwitch) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), "switch": api_call(do_switch, sess, request.url.path, rs, body)}

    @app.post("/api/v1/studies/{rs}/edc/dictionary")
    def api_dictionary(request: Request, rs: str, body: ApiEdcDictionary) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_dictionary, sess, request.url.path, rs, body)}

    @app.get("/api/v1/studies/{rs}/edc/map")
    def api_map(request: Request, rs: str, suggest: bool = False) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "map", request.url.path)
        if suggest:
            return {"study": rid, "items": api_call(call, "GET", f"/studies/{rid}/edc/map/suggest")}
        st = api_call(call, "GET", f"/studies/{rid}/edc")
        return {"study": rid, "items": st.get("map") or [], "target": st.get("target")}

    @app.put("/api/v1/studies/{rs}/edc/map")
    def api_put_map(request: Request, rs: str, body: ApiMap) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_map, sess, request.url.path, rs, body)}

    @app.post("/api/v1/studies/{rs}/edc/drafts")
    def api_draft(request: Request, rs: str, body: ApiDraft) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), "drafts": api_call(do_draft, sess, request.url.path, rs, body)}

    @app.get("/api/v1/studies/{rs}/edc/drafts")
    def api_drafts(request: Request, rs: str, record: str, visit: str = "") -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "review", request.url.path)
        rec = record.strip().upper()
        pid_of(rid, rec)
        if not _VISIT.match(visit):
            raise h.problem(400, "edc.err.edc.visit")
        q = f"?record={rec}" + (f"&visit={visit}" if visit else "")
        return {"study": rid, "record": rec, "drafts": api_call(call, "GET", f"/studies/{rid}/edc/drafts{q}")}

    @app.post("/api/v1/studies/{rs}/edc/drafts/{draft_id}/decide")
    def api_decide(request: Request, rs: str, draft_id: int, body: ApiDecide) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), "draft": api_call(do_decide, sess, request.url.path, rs, draft_id, body)}

    @app.post("/api/v1/studies/{rs}/edc/sign")
    def api_sign(request: Request, rs: str, body: ApiSign) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), "signature": api_call(do_sign, sess, request.url.path, rs, body)}

    @app.post("/api/v1/studies/{rs}/edc/send")
    def api_send(request: Request, rs: str, body: ApiSend) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_send, sess, request.url.path, rs, body.record)}

    @app.get("/api/v1/studies/{rs}/edc/export/odm")
    def api_export(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_export, sess, request.url.path, rs)}

    @app.get("/api/v1/studies/{rs}/edc/trail/{record}")
    def api_trail(request: Request, rs: str, record: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        rec = record.strip().upper()
        pid_of(rid, rec)
        return {"study": rid, "record": rec, **api_call(call, "GET", f"/studies/{rid}/edc/trail/{rec}")}
