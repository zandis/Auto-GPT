"""TB-PLAN-04 step 4 (D-129): built-in data capture in the console, and its ``/api/v1`` routes (D-125, D-127).

* **Entry** (``/studies/{rs}/entry``): choose a record (a screening number or pseudonym of the study, never a chart
  number), an event or visit and a form; the form is shown in the page's language with its branching applied in
  the browser where it is simple (a per-form stylesheet with ``:has()``, no script: the console's CSP forbids
  scripts) and always on the server. Save checks the whole form (required when shown, type, range, ownership) and is
  refused with every reason, per field, in the reader's language.
* **History** (``/studies/{rs}/history``): every change of a record: when, who, event, field, old and new, source.
* **Exports**: CDISC ODM 1.3.2, REDCap CSV and XLSX of every record, from the Entry and Forms pages.
* **Built-in forms**: one button on the Forms page (one call) adds TrialBox's seven forms.

Everything goes through the orchestrator's data-core API (``orchestrator.datacore_api``). Each action is one
function shared by the page and ``/api/v1``. Roles: the study's coordinator enters data and adds the forms (the
same rule as ``study_setup.can_change_setup``); the investigator and the admin read; a viewer or a CRA account sees
no record-level page (403), a CRO account and an account scoped to another study get 404.
"""

from __future__ import annotations

import base64
import contextlib
import re
from typing import Any
from urllib.parse import quote, urlencode

from datacore.branching import css_rules
from datacore.forms import fields_of, titles_of
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from console import s28
from console.auth import Session, User
from console.backend import Problem, Unavailable
from console.data_pages import err_of
from console.home import Helpers
from console.i18n import translate
from console.studies import known_study
from console.timefmt import local_today, site_zone

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PID = re.compile(r"^[0-9a-fA-F]{32}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
FORMATS = ("odm", "cdisc", "csv", "xlsx")
SUFFIX_FORMAT = {"odm.xml": "odm", "cdisc.odm.xml": "cdisc"}  # the download path's suffix -> format
BACKS = ("visits", "subject")  # D-134: where Save returns when the form was opened from the lifecycle pages
ENTERED = ("text", "notes", "date", "dateTime", "integer", "decimal", "choice", "multi")


class ApiSave(BaseModel):
    event: str = Field(default="", max_length=100)
    values: dict[str, str]


def can_enter(user: User) -> bool:
    """Who enters trial data and adds forms: the study's coordinator (as ``study_setup.can_change_setup``)."""
    return user.role == "coordinator"


def record_key(record: str) -> str:
    rec = record.strip()
    return rec.lower() if _PID.match(rec) else rec.upper()


def form_view(q: dict[str, Any]) -> dict[str, Any]:
    """A Questionnaire as the entry page shows it; labels in every language (the template picks the page's)."""
    fields = []
    for f in fields_of(q):
        fields.append({
            "name": f.name, "kind": f.kind, "label": f.label or f.name, "labels": f.labels,
            "options": [{"code": c, "label": d, "labels": {g: f.option_labels.get(g, {}).get(c, "")
                                                         for g in f.option_labels}} for c, d in f.options.items()],
            "required": f.required, "vmin": f.vmin, "vmax": f.vmax, "branching": f.branching,
            "entered": f.kind in ENTERED,
        })  # fmt: skip
    return {"name": q.get("name", ""), "titles": titles_of(q), "fields": fields}


def why(lang: str, p: dict[str, str], labels: dict[str, str]) -> str:
    """One refusal reason in the reader's language."""
    key = f"dc.why.{p.get('code', '')}"
    text = translate(lang, key, label=labels.get(p.get("field", ""), p.get("field", "")), min=p.get("min", ""),
                     max=p.get("max", ""), owner=p.get("owner", ""))  # fmt: skip
    return translate(lang, "dc.why.other") if text == key else text


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    def study_or_404(sess: Session, rs: str) -> str:
        """A study this account sees, and a role that reads record-level rows (the trial values)."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.role == "cro" or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not sess.user.can_view_phi:
            au.append("console.denied", actor=h.actor(sess), detail={"action": f"entry {rid}"})
            raise h.problem(403, "forbidden")
        # D-273 (PV-3): trial values and their exports as the participants page: an investigator as delegated only
        h.delegated(sess, rid, f"entry {rid}", ("screen", "enter_data"))
        return rid

    def enters(user: User, rid: str | None) -> bool:
        """The coordinator; D-147: also an investigator the study's PI ticked "enter data" for in the delegation log
        (trial values only: adding forms stays the coordinator's)."""
        if can_enter(user):
            return True
        return rid is not None and user.role == "investigator" and h.may is not None and h.may(user, rid, "enter_data")

    def need_enter(sess: Session, path: str, rid: str | None = None) -> None:
        if not enters(sess.user, rid):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")

    # ------------------------------------------------------------------ reads
    def read_forms(rid: str) -> list[dict[str, Any]]:
        return [form_view(q) for q in s28.call(bk, "GET", f"/studies/{rid}/forms")]

    def read_records(rid: str) -> list[dict[str, Any]]:
        return list(s28.call(bk, "GET", f"/studies/{rid}/records"))

    def issued(rid: str) -> dict[str, str]:
        """The study's screening numbers -> pseudonym (the console's site store issues them)."""
        try:
            return {no: pid for pid, no in store.screening_nos(rid).items()}
        except Exception:  # a store without the table answers no numbers
            return {}

    def check_record(rid: str, record: str) -> str:
        """A record is a screening number this study issued, its pseudonym, or a record the data core already
        holds; anything else (a chart number, a name) is refused, never stored."""
        rec = record_key(record)
        nos = issued(rid)
        known = {r["record"] for r in read_records(rid)}
        if not _REC.match(rec) or not (rec in nos or rec in nos.values() or rec in known):
            raise Problem(400, "DATA-RECORD", "not a screening number or pseudonym of this study", [rec[:40]])
        return rec

    def read_record(rid: str, record: str) -> dict[str, Any]:
        return dict(s28.call(bk, "GET", f"/studies/{rid}/records/{quote(record)}"))

    # ------------------------------------------------------------------ actions (one per page and /api/v1)
    def apply_builtin(sess: Session, path: str, rs: str, ctcae: str = "") -> dict[str, Any]:
        """Add TrialBox's seven forms (ja, zh-TW, en) to the study in one call; ``ctcae`` names an oncology study's
        CTCAE version (D-396)."""
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/forms/builtin", {"by": h.actor(sess), "ctcae": ctcae[:16]}))
        au.append("console.data_forms", ruleset=rid, actor=h.actor(sess),
                  detail={"forms": len(out.get("forms") or []), "origin": "builtin",
                          "ctcae": str(out.get("ctcae") or "")})  # fmt: skip
        return out

    def apply_save(sess: Session, path: str, rs: str, record: str, event: str, form: str,
                   values: dict[str, str]) -> dict[str, Any]:  # fmt: skip
        """Save one whole form for one record and event; refused whole, with every reason (DATA-FORM)."""
        rid = study_or_404(sess, rs)
        need_enter(sess, path, rid)
        ev = event.strip().lower()
        if not _NAME.match(form) or (ev and not _NAME.match(ev)):
            raise Problem(400, "DATA-EVENT", "event and form names are lower-case letters, digits and _", [ev[:40]])
        rec = check_record(rid, record)
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/entry/{quote(rec)}",
                            {"form": form, "event": ev, "values": values, "by": h.actor(sess)}))  # fmt: skip
        au.append("console.data_entry", ruleset=rid, actor=h.actor(sess),
                  detail={"form": form, "event": ev, "changed": out.get("changed", 0)})  # fmt: skip
        if form == "tb_adverse_event" and h.sae_sync is not None:
            h.sae_sync(rid)  # D-277 (CR-012): the SAE register is written on the write path, never on a page view
        if out.get("life"):  # T-516 (UX-011): a lifecycle form moved the participant; the screening log follows now,
            with contextlib.suppress(Problem, Unavailable):  # with the screening numbers the console issued
                s28.call(
                    bk, "POST", f"/studies/{rid}/subjects/refresh", {"screening": issued(rid), "by": h.actor(sess)}
                )
        return out

    def read_export(sess: Session, rs: str, fmt: str) -> tuple[str, str, bytes]:
        """An export of every record: (file name, media type, bytes). Who reads the records may download them."""
        rid = study_or_404(sess, rs)
        if fmt not in FORMATS:
            raise h.problem(404, "notfound")
        out = s28.call(bk, "GET", f"/studies/{rid}/export/{fmt}?by={quote(h.actor(sess))}")
        data = base64.b64decode(out["b64"]) if "b64" in out else str(out.get("text") or "").encode("utf-8")
        au.append("console.data_export", ruleset=rid, actor=h.actor(sess), detail={"format": fmt})
        return str(out["name"]), str(out["media_type"]), data

    # ------------------------------------------------------------------ pages
    def entry_page(request: Request, sess: Session, rid: str, record: str, event: str, form: str,
                   posted: dict[str, str] | None = None, problems: list[dict[str, str]] | None = None,
                   err: dict[str, str] | None = None, back: str = "", prefill: str = "",
                   win: str = "") -> Response:  # fmt: skip
        lang = sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"
        try:
            fms = read_forms(rid)
            recs = read_records(rid)
        except (Problem, Unavailable) as exc:
            fms, recs, err = [], [], err or err_of(exc)
        rec = record_key(record) if record else ""
        values: dict[str, str] = {}
        owners: dict[str, str] = {}
        events: list[str] = []
        if rec and err is None:
            try:
                rec = check_record(rid, rec)
                got = read_record(rid, rec)
                owners = dict(got.get("owners") or {})
                events = sorted(got.get("values") or {})
                values = {k: v["value"] for k, v in (got.get("values") or {}).get(event, {}).items()}
            except (Problem, Unavailable) as exc:
                err = err_of(exc)
        chosen = next((f for f in fms if f["name"] == form), None)
        labels = {f["name"]: (f["labels"].get(lang) or f["label"]) for fm in fms for f in fm["fields"]}
        per_field: dict[str, list[str]] = {}
        for p in problems or []:
            per_field.setdefault(p.get("field", ""), []).append(why(lang, p, labels))
        options = sorted({*issued(rid), *(r["record"] for r in recs)})
        ae: dict[str, Any] | None = None
        if form == "tb_adverse_event" and rec and event and err is None:  # P-03: the reporting clock on the AE form
            try:
                one = s28.call(bk, "GET", f"/studies/{rid}/subjects/{quote(rec)}")
                ae = next((a for a in one.get("aes") or [] if a.get("event") == event), None)
            except (Problem, Unavailable):
                ae = None
        if prefill == "done" and form == "tb_visit" and not values.get("vs_status") and posted is None:
            # D-134 "Done today" from the visit list: the visit filled in for today; the coordinator checks and saves
            posted = {"vs_status": "1", "vs_date": local_today(h.clock(), site_zone(bk)).isoformat(),
                      "vs_window": "1" if win == "1" else "0" if win == "0" else ""}  # fmt: skip
        return h.page(
            request,
            "data_entry.html",
            sess,
            rs=rid,
            forms=fms,
            form=chosen,
            record=rec,
            event=event,
            events=events,
            options=options,
            values={**values, **(posted or {})},
            owners=owners,
            problems=per_field,
            n_problems=len(problems or []),
            editable=enters(sess.user, rid),
            css=bool(chosen and any(f["branching"] for f in chosen["fields"])),
            exports=FORMATS,
            err=err,
            back=back if back in BACKS else "",
            ae=ae,
        )

    @app.get("/studies/{rs}/entry")
    def entry(request: Request, rs: str, record: str = "", event: str = "", form: str = "", back: str = "",
              prefill: str = "", win: str = "") -> Response:  # fmt: skip
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        ev = event.strip().lower()
        return entry_page(request, sess, rid, record[:64], ev if _NAME.match(ev) else "",
                          form if _NAME.match(form) else "", back=back, prefill=prefill, win=win)  # fmt: skip

    @app.post("/studies/{rs}/entry")
    async def save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        need_enter(sess, request.url.path, rid)
        record, event, form = (str(data.get(k) or "").strip()[:100] for k in ("record", "event", "form"))
        back = str(data.get("back") or "")
        try:
            fm = next((f for f in read_forms(rid) if f["name"] == form), None)
        except (Problem, Unavailable) as exc:
            return entry_page(request, sess, rid, record, event, form, err=err_of(exc))
        if fm is None:
            return entry_page(request, sess, rid, record, event, "", err={"code": "DATA-FORM", "fields": form[:40]})
        try:
            owners = dict(read_record(rid, record_key(record)).get("owners") or {}) if record else {}
        except (Problem, Unavailable):
            owners = {}
        values = {}
        for f in fm["fields"]:
            if not f["entered"] or owners.get(f["name"], "trialbox") != "trialbox":
                continue
            got = [str(v).strip() for v in data.getlist(f"f_{f['name']}") if str(v).strip()]
            values[f["name"]] = ",".join(got) if f["kind"] == "multi" else (got[0] if got else "")
        try:
            apply_save(sess, request.url.path, rid, record, event, form, values)
        except Problem as exc:
            return entry_page(request, sess, rid, record, event.lower(), form, posted=values,
                              problems=exc.problems, err=None if exc.problems else err_of(exc), back=back)  # fmt: skip
        except Unavailable as exc:
            return entry_page(request, sess, rid, record, event.lower(), form, posted=values, err=err_of(exc),
                              back=back)  # fmt: skip
        if back == "visits":
            q = urlencode({"saved": f"{record_key(record)} {event.lower()}".strip()})
            return RedirectResponse(f"/studies/{rid}/visits?{q}", status_code=303)
        if back == "subject":
            return RedirectResponse(f"/studies/{rid}/subjects/{quote(record_key(record))}?done=entry", status_code=303)
        q = urlencode({"record": record_key(record), "saved": form, "event": event.lower()})
        return RedirectResponse(f"/studies/{rid}/history?{q}", status_code=303)

    @app.get("/studies/{rs}/entry/{form}.css")
    def branching_css(request: Request, rs: str, form: str) -> Response:
        """The form's simple branching rules as a stylesheet (the browser hides a field whose rule is false)."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        try:
            fm = next((f for f in read_forms(rid) if f["name"] == form), None)
        except (Problem, Unavailable):
            fm = None
        css = ""
        if fm is not None:
            choice = {f["name"] for f in fm["fields"] if f["kind"] == "choice"}
            css = css_rules({f["name"]: f["branching"] for f in fm["fields"] if f["branching"]}, choice)
        return Response(css, media_type="text/css", headers={"Cache-Control": "no-store"})

    @app.get("/studies/{rs}/history")
    def history(request: Request, rs: str, record: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        lang = sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"
        rows: list[dict[str, Any]] = []
        err = None
        rec = record_key(record[:64]) if record else ""
        labels: dict[str, str] = {}
        try:
            recs = read_records(rid)
            labels = {f["name"]: (f["labels"].get(lang) or f["label"]) for fm in read_forms(rid)
                      for f in fm["fields"]}  # fmt: skip
            if rec:
                rec = check_record(rid, rec)
                rows = list(reversed(read_record(rid, rec).get("history") or []))
        except (Problem, Unavailable) as exc:
            recs, err = [], err_of(exc)
        return h.page(request, "data_history.html", sess, rs=rid, record=rec, rows=rows, labels=labels,
                      records=[r["record"] for r in recs], editable=enters(sess.user, rid), err=err)  # fmt: skip

    @app.get("/studies/{rs}/export.{fmt}")
    def download(request: Request, rs: str, fmt: str) -> Response:
        sess = h.need(request)
        try:
            name, media, data = read_export(sess, rs, SUFFIX_FORMAT.get(fmt, fmt))
        except (Problem, Unavailable) as exc:
            raise h.problem(503, "unavailable", detail=str(exc)[:200]) from exc
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/studies/{rs}/forms/builtin")
    async def add_builtin(request: Request, rs: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        try:
            out = apply_builtin(sess, request.url.path, rs, str(data.get("ctcae") or ""))
        except (Problem, Unavailable) as exc:
            q = urlencode({"err": exc.code if isinstance(exc, Problem) else "unavailable",
                           "fields": ", ".join(exc.fields) if isinstance(exc, Problem) else ""})  # fmt: skip
            return RedirectResponse(f"/studies/{rs.upper()}/forms?{q}", status_code=303)
        q = urlencode({"builtin": len(out.get("forms") or []), "ctcae": str(out.get("ctcae") or "")})
        return RedirectResponse(f"/studies/{rs.upper()}/forms?{q}", status_code=303)

    # ------------------------------------------------------------------ /api/v1 (D-125, D-127)
    def api_session(request: Request) -> Session:
        assert h.api_session is not None, "console.home.register runs first"
        return h.api_session(request)

    def refused(sess: Session, exc: Exception) -> Response:
        """An orchestrator refusal as the API's JSON error; per-field reasons in the account's language."""
        if isinstance(exc, Unavailable):
            return JSONResponse({"error": "unavailable", "detail": {"detail": str(exc)[:200]}}, status_code=503)
        assert isinstance(exc, Problem)
        lang = sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"
        status = exc.status if 400 <= exc.status < 500 else 502
        body: dict[str, Any] = {
            "error": "request.refused",
            "detail": {"code": exc.code, "reason": exc.message, "fields": ", ".join(exc.fields)},
        }
        if exc.problems:
            body["problems"] = [{**p, "message": why(lang, p, {})} for p in exc.problems]
        return JSONResponse(body, status_code=status)

    @app.post("/api/v1/studies/{rs}/forms/builtin", response_model=None)
    async def api_builtin(request: Request, rs: str) -> Any:
        sess = api_session(request)
        try:
            is_json = request.headers.get("content-type", "").startswith("application/json")
            body = await request.json() if is_json else {}
        except ValueError:
            body = {}
        ctcae = str(body.get("ctcae") or "") if isinstance(body, dict) else ""
        try:
            return {"study": rs.upper(), **apply_builtin(sess, request.url.path, rs, ctcae)}
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/records", response_model=None)
    def api_records(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        try:
            return {"study": rid, "records": read_records(rid), "may_enter": enters(sess.user, rid)}
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/records/{record}", response_model=None)
    def api_record(request: Request, rs: str, record: str) -> Any:
        """One record's values per event and its change history (who, when, old, new, source)."""
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        try:
            rec = check_record(rid, record)
            got = read_record(rid, rec)
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)
        return {"study": rid, "record": rec, "values": got.get("values") or {}, "history": got.get("history") or []}

    @app.put("/api/v1/studies/{rs}/records/{record}/forms/{form}", response_model=None)
    def api_save(request: Request, rs: str, record: str, form: str, body: ApiSave) -> Any:
        sess = api_session(request)
        try:
            out = apply_save(sess, request.url.path, rs, record, body.event, form, body.values)
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)
        return {"study": rs.upper(), **out}

    @app.get("/api/v1/studies/{rs}/export/{fmt}", response_model=None)
    def api_export(request: Request, rs: str, fmt: str) -> Any:
        sess = api_session(request)
        try:
            name, media, data = read_export(sess, rs, fmt)
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
