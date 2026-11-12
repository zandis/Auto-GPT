"""Copy-assist pages and their ``/api/v1`` routes (T-302c, D-434).

A study without the sponsor's written acknowledgement of the REDCap send runs its switch in ``copy``: TrialBox drafts,
the coordinator reviews and signs, and a person types the signed values into the sponsor's EDC by hand.

* ``GET /studies/{rs}/edc/copy/{record}``: per visit, then per form in the sponsor's form order (the data
  dictionary's), each signed value with its label, its value and word, its source and who signed it; a "copied"
  tick per value or per form with who and when. A value that is not signed is never shown: the page counts it and
  links to the review. Every view is audited (the orchestrator's ``edc.copy_view`` and the console's
  ``console.edc_copy``).
* ``POST /studies/{rs}/edc/copy/{record}/tick``: tick values copied (one value, or every value of a form), or undo a
  tick with a reason. Audited.
* ``GET /studies/{rs}/edc/copy.csv``: the same sheet as a plain file (one subject with ``?record=``, else the
  study), with a ``flow.export`` row (D-149) before the bytes leave.
* ``GET /api/v1/studies/{rs}/edc/copy`` and ``POST /api/v1/studies/{rs}/edc/copy/{record}/tick``: the same, for a
  script. The session and the right are checked before the body is read (``console.api_first``, T-657).

Who: the matrix rows ``edc.copy`` (the sheet and the file) and ``edc.copy_tick`` (the ticks), read through the
study's delegation log (``Helpers.permit``); the orchestrator checks the person's role again. No chart number is
shown or written: the record key is the screening number. An opted-out patient is refused by name and left out of
the study file.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common.flowledger import record_export
from tb_common.service_auth import actor_header

from console import i18n_copyassist, s28
from console.api_first import before_body
from console.auth import Session
from console.backend import Problem, Unavailable
from console.edc_pages import err_of, item_words
from console.home import Helpers
from console.i18n import CATALOGUES, translate
from console.studies import known_study

for _lang, _cat in (("en", i18n_copyassist.EN), ("ja", i18n_copyassist.JA), ("zh-TW", i18n_copyassist.ZH)):
    CATALOGUES[_lang].update(_cat)

VIEW = "edc.copy"
TICK = "edc.copy_tick"
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_FORM = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_VISIT = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
ACTIONS = ("copied", "undone")
CSV_COLUMNS = ("record", "visit", "visit_date", "form", "item", "label", "value", "word", "source", "signed_by",
               "signed_at", "copied_by", "copied_at")  # fmt: skip


class ApiTick(BaseModel):
    drafts: list[int] = Field(min_length=1, max_length=2000)
    action: str = Field(default="copied", pattern=r"^(copied|undone)$")
    reason: str = Field(default="", max_length=300)


def source_line(c: Mapping[str, Any] | None, words: Mapping[str, Any], lang: str) -> str:
    """One line for a value's citation: what kind of source, the readable source (or the person's own words), the
    day, a quoted passage, and for an imported file its name and the value's place in it."""
    if not c:
        return ""
    kind = str(c.get("kind") or "")
    head = translate(lang, f"edc.cite.{kind}")
    head = "" if head == f"edc.cite.{kind}" else head
    if kind == "odm":
        body = " ".join(x for x in (str(c.get("name") or ""), str(c.get("path") or "")) if x)
    else:
        body = str(words.get("source") or "") or " ".join(
            x for x in (str(c.get("text") or ""), str(c.get("day") or "")) if x)  # fmt: skip
    quote = str(c.get("quote") or "")
    return " · ".join(x for x in (head, body, f"“{quote}”" if quote else "") if x)


def decorate(sheet: Mapping[str, Any], fields: Mapping[str, Any], maps: Mapping[str, Any],
             lang: str) -> dict[str, Any]:  # fmt: skip
    """The orchestrator's sheet with each value's label, word and source line in the reader's language."""
    out: dict[str, Any] = json.loads(json.dumps(sheet))
    for rec in out.get("records") or []:
        for vis in rec["visits"]:
            for form in vis["forms"]:
                for v in form["values"]:
                    d = {"item": v["item"], "cdash": v.get("cdash"), "test": v.get("test"), "value": v["value"],
                         "final_citation": v.get("citation")}  # fmt: skip
                    w = item_words(d, fields.get(v["item"]), maps.get(v["item"]), lang)
                    v["label"] = w["label"]
                    v["given"] = w["given"]
                    v["word"] = w["options"].get(str(v["value"]), "") if w["options"] else ""
                    v["source"] = source_line(v.get("citation"), w, lang)
    return out


def to_csv(sheet: Mapping[str, Any]) -> bytes:
    """The decorated sheet as CSV: UTF-8 with a byte-order mark (spreadsheets read the three languages), one row per
    value. A cell that a spreadsheet would read as a formula is written with a leading quote (CWE-1236)."""

    def cell(x: Any) -> str:
        s = "" if x is None else str(x)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for rec in sheet.get("records") or []:
        for vis in rec["visits"]:
            for form in vis["forms"]:
                for v in form["values"]:
                    cp = v.get("copied") or {}
                    w.writerow([cell(x) for x in (rec["record"], vis["visit"], vis["visit_date"], form["form"],
                                                  v["item"], v.get("label"), v["value"], v.get("word"),
                                                  v.get("source"), v["signed_by"], v["signed_at"], cp.get("by"),
                                                  cp.get("at"))])  # fmt: skip
    return ("﻿" + buf.getvalue()).encode("utf-8")


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    def act(sess: Session, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """A call the orchestrator attributes to the signed-in person (their signed assertion and role, D-162)."""
        return s28.call(bk, method, path, body, headers=actor_header(sess.user.username, None, sess.user.role))

    def guard(sess: Session, rs: str, action: str, path: str) -> str:
        """The study (404 when the account does not see it), then the matrix row with the account's standing in it
        (403, audited)."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not h.permit(sess.user, action, rid).allowed:
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        return rid

    def record_of(rid: str, record: str) -> str:
        """The screening number of a subject of this study who has not opted out (409 when they have)."""
        rec = record.strip().upper()
        if not _REC.match(rec):
            raise h.problem(400, "edc.err.edc.record")
        pid = next((p for p, n in store.screening_nos(rid).items() if str(n).upper() == rec), None)
        if pid is None:
            raise h.problem(404, "notfound")
        if pid in h.gone():
            raise h.problem(409, "edc.err.edc.opted_out")
        return rec

    def lang_of(sess: Session) -> str:
        return sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"

    def read(sess: Session, rid: str, rec: str | None, fmt: str) -> dict[str, Any]:
        """The sheet from the orchestrator (audited there), decorated, and the console's own audit line."""
        q = f"?format={fmt}" + (f"&record={rec}" if rec else "")
        sheet = act(sess, "GET", f"/studies/{rid}/edc/copy{q}")
        fields = {f["name"]: f for f in (s28.call(bk, "GET", f"/studies/{rid}/sources").get("fields") or [])}
        maps = {str(m.get("item")): m for m in (s28.call(bk, "GET", f"/studies/{rid}/edc").get("map") or [])}
        gone = h.gone()
        nos = {str(n).upper() for p, n in store.screening_nos(rid).items() if p in gone}
        sheet = {**sheet, "records": [r for r in sheet.get("records") or [] if str(r["record"]).upper() not in nos]}
        au.append("console.edc_copy", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "view", "format": fmt, "record": rec or "*",
                          "values": int(sheet.get("values") or 0)})  # fmt: skip
        return decorate(sheet, fields, maps, lang_of(sess))

    def do_tick(sess: Session, rid: str, rec: str, ids: list[int], action: str, reason: str) -> dict[str, Any]:
        if action not in ACTIONS:
            raise h.problem(400, "edc.err.edc.tick_action")
        if not ids:
            raise h.problem(400, "edc.err.edc.tick_none")
        out = act(sess, "POST", f"/studies/{rid}/edc/copy/tick",
                  {"record": rec, "drafts": ids[:2000], "action": action, "reason": reason[:300]})  # fmt: skip
        au.append("console.edc_copy", ruleset=rid, actor=h.actor(sess),
                  detail={"action": action, "record": rec, "values": len(ids)})  # fmt: skip
        return dict(out)

    # ------------------------------------------------------------------ the page
    def sheet_page(request: Request, sess: Session, rid: str, rec: str, err: dict[str, Any] | None = None,
                   status: int = 200) -> Response:  # fmt: skip
        sheet = read(sess, rid, rec, "page")
        recs = sheet.get("records") or []
        resp = h.page(request, "edc_copy.html", sess, rs=rid, record=rec, sheet=sheet,
                      visits=recs[0]["visits"] if recs else [], err=err,
                      may_tick=h.permit(sess.user, TICK, rid).allowed,
                      may_review=h.permit(sess.user, "edc.review", rid).allowed)  # fmt: skip
        resp.status_code = status
        return resp

    @app.get("/studies/{rs}/edc/copy/{record}")
    def copy_page(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        rid = guard(sess, rs, VIEW, request.url.path)
        rec = record_of(rid, record)
        try:
            return sheet_page(request, sess, rid, rec)
        except (Problem, Unavailable) as exc:
            return h.page(request, "edc_copy.html", sess, rs=rid, record=rec, sheet=None, visits=[],
                          err=err_of(exc), may_tick=False, may_review=False)  # fmt: skip

    @app.post("/studies/{rs}/edc/copy/{record}/tick")
    async def copy_tick(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        rid = guard(sess, rs, TICK, request.url.path)  # who, before anything of the body is used
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rec = record_of(rid, record)
        ids = sorted({int(str(x)) for x in form.getlist("draft") if str(x).isdigit()})
        action, reason = str(form.get("action") or "copied"), str(form.get("reason") or "")
        anchor = str(form.get("anchor") or "")
        try:
            do_tick(sess, rid, rec, ids, action, reason)
        except (Problem, Unavailable) as exc:
            return sheet_page(request, sess, rid, rec, err_of(exc), 409)
        frag = f"#{anchor}" if re.fullmatch(r"[a-z0-9_-]{1,120}", anchor) else ""
        return RedirectResponse(f"/studies/{rid}/edc/copy/{rec}?done={action}{frag}", status_code=303)

    @app.get("/studies/{rs}/edc/copy.csv")
    def copy_csv(request: Request, rs: str, record: str = "") -> Response:
        sess = h.need(request)
        rid = guard(sess, rs, VIEW, request.url.path)  # the page's question (D-434)
        rec = record_of(rid, record) if record else None
        try:
            data = to_csv(read(sess, rid, rec, "csv"))
        except Problem as exc:
            raise h.problem(409, "request.refused", code=exc.code, reason=exc.message, fields="") from exc
        except Unavailable as exc:
            raise h.problem(503, "unavailable", detail=str(exc)[:200]) from exc
        name = f"{rid}-copy-assist{'-' + rec if rec else ''}.csv"
        record_export(au, channel="console_download", filename=name, data=data, identifier_level="pseudonymised",
                      approval=f"console role {sess.user.role}; {VIEW} of study {rid} (copy-assist, signed values)",
                      actor=h.actor(sess), ruleset=rid)  # fmt: skip
        return Response(data, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"',
                                 "X-Download-Options": "noopen"})  # fmt: skip

    # ------------------------------------------------------------------ /api/v1
    def api_call(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except Problem as exc:
            status = exc.status if 400 <= exc.status < 500 else 502
            raise h.problem(status, "request.refused", code=exc.code, reason=exc.message,
                            fields=", ".join(exc.fields)) from exc  # fmt: skip
        except Unavailable as exc:
            raise h.problem(503, "unavailable", detail=str(exc)[:200]) from exc

    def api_sess(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)  # the bearer token, and the page's role and scope rules (D-146)

    @app.get("/api/v1/studies/{rs}/edc/copy")
    def api_copy(request: Request, rs: str, record: str = "") -> dict[str, Any]:
        sess = api_sess(request)
        rid = guard(sess, rs, VIEW, request.url.path)
        rec = record_of(rid, record) if record else None
        return {"study": rid, **api_call(read, sess, rid, rec, "api")}

    def tick_first(sess: Session, request: Request) -> None:
        """T-657 (D-444): the session and the ``edc.copy_tick`` row, before the body is read."""
        guard(sess, request.path_params["rs"], TICK, request.url.path)

    @app.post("/api/v1/studies/{rs}/edc/copy/{record}/tick")
    @before_body(tick_first)
    def api_tick(request: Request, rs: str, record: str, body: ApiTick) -> dict[str, Any]:
        sess = api_sess(request)
        rid = guard(sess, rs, TICK, request.url.path)
        rec = record_of(rid, record)
        return {"study": rid, **api_call(do_tick, sess, rid, rec, sorted(set(body.drafts)), body.action, body.reason)}
