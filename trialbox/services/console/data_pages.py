"""TB-PLAN-04 step 3: the Sources, Conflicts and Forms pages of a study's own data core (D-123), and their
``/api/v1`` routes (D-125, D-127).

* **Sources** (``/studies/{rs}/sources``): each source with its direction (REDCap and a spreadsheet two-way, a FHIR
  bundle or any hospital system one-way in), last sync and last result; attach or detach REDCap; Sync now; and which
  side owns each field.
* **Trial-record differences** (``/studies/{rs}/conflicts``; titled "Conflicts" before T-201, FIT-018: the clinical
  conflicts are ``console.conflicts_page``): the open conflicts, one row each (record = screening number or
  pseudonym, field, TrialBox's value, the source's value, the source, when) with two buttons: keep TrialBox's value
  or take the source's. A conflict is never forced and never resolved by the box; ``?all=1`` shows the trail.
* **Forms** (``/studies/{rs}/forms``): the study's FHIR Questionnaires with each field's type, label, choices and
  owner; import a REDCap data dictionary CSV.

Everything is read from and done by the orchestrator's data-core API (``orchestrator.datacore_api``) through
``backend.study_api``. Each action is one function shared by the page and ``/api/v1`` (as ``apply_mark`` in
``console.home``). Only a role that may change the study's set-up (``study_setup.can_change_setup``) attaches,
detaches, syncs, imports or resolves; everyone else on the study reads. Conflicts show trial values, so they are
shown only to roles that may read patient-level rows.
"""

from __future__ import annotations

import re
import time
from typing import Annotated, Any
from urllib.parse import quote

from datacore.forms import fields_of, titles_of
from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from console import s28
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.i18n import translate
from console.studies import known_study
from console.study_setup import can_change_setup, parse_map

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
TWO_WAY = ("redcap", "sheet")  # TB-PLAN-04 §3: REDCap and a PI's spreadsheet; every hospital system is one-way in
KEEP = ("trialbox", "theirs")  # orchestrator.datacore_api.ResolveBody.keep
MAX_DICTIONARY = 2 * 1024 * 1024


class ApiResolve(BaseModel):
    keep: str  # "trialbox" keeps TrialBox's value, "theirs" takes the source's


class ApiRedcap(BaseModel):
    token_ref: str = Field(min_length=1, max_length=32)
    field_map: dict[str, str]  # REDCap field -> TrialBox field
    owned: list[str] = Field(default_factory=list)  # TrialBox fields REDCap owns
    key_field: str = "tb_screening_no"
    event: str = ""
    dag: str = ""
    create: bool = False


class ApiDictionary(BaseModel):
    csv: str = Field(min_length=1, max_length=MAX_DICTIONARY)
    record_field: str = ""


def direction(name: str) -> str:
    return "two" if name in TWO_WAY else "in"


def kind_of(item: dict[str, Any]) -> str:
    """A Questionnaire item's field kind, as ``datacore.forms.fields_of`` reads it."""
    t = str(item.get("type") or "")
    if t == "choice":
        return "multi" if item.get("repeats") else "choice"
    if t == "string":
        return "calc" if item.get("readOnly") else "text"
    return "notes" if t == "text" else t


def err_of(exc: Exception) -> dict[str, str]:
    if isinstance(exc, Problem):
        return {"code": exc.code, "fields": ", ".join(exc.fields)}
    return {"code": "unavailable", "fields": ""}


def source_rows(raw: list[dict[str, Any]], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in raw:
        body = s.get("body") or {}
        res = s.get("last_result") or None
        out.append({
            "name": s["name"],
            "direction": direction(s["name"]),
            "last_sync": s.get("last_sync"),
            "result": None if res is None else {
                "pulled": res.get("pulled", 0), "taken": res.get("taken", 0), "pushed": res.get("pushed", 0),
                "conflicts": len(res.get("conflicts") or []), "created": len(res.get("created") or {}),
                "waiting": len(res.get("waiting") or []),
            },
            "owned": [f["name"] for f in fields if f.get("owner") == s["name"]],
            "carried": len(body.get("field_map") or {}),
            "token_ref": body.get("token_ref", ""),
        })  # fmt: skip
    return out


def register(app: FastAPI, h: Helpers) -> None:
    bk, au = h.bk, h.au

    def study_or_404(sess: Session, rs: str, rows: bool = False) -> str:
        """A study this account sees (never a CRO account). ``rows``: the page shows trial values, so only roles
        that read patient-level rows see it."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.sponsor_form or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if rows and not sess.user.can_view_phi:
            au.append("console.denied", actor=h.actor(sess), detail={"action": f"conflicts {rid}"})
            raise h.problem(403, "forbidden")
        if rows:  # D-273: per-record trial values follow the delegation log, as the participants pages do
            h.delegated(sess, rid, f"conflicts {rid}", ("screen", "enter_data"))
        return rid

    def need_change(sess: Session, path: str) -> None:
        if not can_change_setup(sess.user):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")

    # ------------------------------------------------------------------ reads
    def read_sources(rid: str) -> dict[str, Any]:
        out = s28.call(bk, "GET", f"/studies/{rid}/sources")
        fields = list(out.get("fields") or [])
        return {"sources": source_rows(list(out.get("sources") or []), fields), "fields": fields}

    def read_conflicts(rid: str, everything: bool = False) -> list[dict[str, Any]]:
        return list(s28.call(bk, "GET", f"/studies/{rid}/conflicts" + ("?all=true" if everything else "")))

    def read_forms(rid: str) -> list[dict[str, Any]]:
        owners = {f["name"]: f.get("owner", "trialbox") for f in read_sources(rid)["fields"]}
        out = []
        for q in s28.call(bk, "GET", f"/studies/{rid}/forms"):
            items = [
                {
                    "name": f.name,
                    "kind": kind_of(it),
                    "label": f.label,
                    "labels": f.labels,  # TB-PLAN-04 step 4: per language (the built-in forms)
                    "required": f.required,
                    "branching": f.branching,
                    "vmin": f.vmin,
                    "vmax": f.vmax,
                    "choices": [
                        {"code": c, "label": d, "labels": {g: v[c] for g, v in f.option_labels.items() if c in v}}
                        for c, d in f.options.items()
                    ],
                    "owner": owners.get(f.name, "trialbox"),
                }
                for it, f in zip(q.get("item") or [], fields_of(q), strict=True)
            ]
            out.append({"name": q.get("name", ""), "title": q.get("title") or q.get("name", ""),
                        "titles": titles_of(q), "url": q.get("url", ""), "fields": items})  # fmt: skip
        return out

    def tokens() -> list[str]:
        try:
            conns = s28.call(bk, "GET", "/redcap/connections") or {}
        except (Problem, Unavailable):
            return []
        return [str(c["token_ref"]) for c in conns.get("connections") or []]

    # ------------------------------------------------------------------ actions (one per page and /api/v1)
    def apply_attach(sess: Session, path: str, rs: str, body: ApiRedcap) -> dict[str, Any]:
        """Attach REDCap: hand it the fields it owns; every other mapped field stays TrialBox's."""
        rid = study_or_404(sess, rs)
        need_change(sess, path)
        bad = [f for f in [*body.field_map, *body.field_map.values(), *body.owned] if not _FIELD.match(f)]
        if bad or not body.field_map or not _NAME.match(body.token_ref):
            raise Problem(400, "DATA-FIELD", "field names are lower-case letters, digits and _", bad)
        out = s28.call(bk, "PUT", f"/studies/{rid}/sources/redcap", {**body.model_dump(), "by": h.actor(sess)})
        au.append("console.data_source", ruleset=rid, actor=h.actor(sess),
                  detail={"source": "redcap", "action": "attach", "owned": len(body.owned)})  # fmt: skip
        return dict(out)

    # D-178 (review J-14): the connection a Detach removed, kept for the toast's Undo (this person, this study, 15
    # minutes, in memory: the token itself is never here, only its reference name)
    detached: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}

    def apply_detach(sess: Session, path: str, rs: str) -> dict[str, Any]:
        """Detach REDCap: every field is TrialBox's again; nothing is deleted."""
        rid = study_or_404(sess, rs)
        need_change(sess, path)
        with_body = [x for x in s28.call(bk, "GET", f"/studies/{rid}/sources").get("sources") or []
                     if x.get("name") == "redcap"]  # fmt: skip
        if with_body:
            cfg = {k: v for k, v in dict(with_body[0].get("body") or {}).items() if k in ApiRedcap.model_fields}
            detached[(sess.token_sha, rid)] = (cfg, time.monotonic())
        out = s28.call(bk, "DELETE", f"/studies/{rid}/sources/redcap?by={quote(h.actor(sess))}")
        au.append("console.data_source", ruleset=rid, actor=h.actor(sess),
                  detail={"source": "redcap", "action": "detach"})  # fmt: skip
        return dict(out)

    def apply_sync(sess: Session, path: str, rs: str, name: str) -> dict[str, Any]:
        """Sync now: the same two-way sync as the box's timer."""
        rid = study_or_404(sess, rs)
        need_change(sess, path)
        if not _NAME.match(name):
            raise h.problem(404, "notfound")
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/sync/{name}", {"by": h.actor(sess)}))
        au.append("console.data_sync", ruleset=rid, actor=h.actor(sess),
                  detail={"source": name, "conflicts": len(out.get("conflicts") or [])})  # fmt: skip
        return out

    def apply_resolve(sess: Session, path: str, rs: str, cid: int, keep: str) -> dict[str, Any]:
        """A person's choice for one conflict: keep TrialBox's value or take the source's."""
        rid = study_or_404(sess, rs, rows=True)
        need_change(sess, path)
        if keep not in KEEP:
            raise h.problem(400, "request.refused", reason="keep is trialbox or theirs")
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/conflicts/{cid}", {"keep": keep, "by": h.actor(sess)}))
        au.append("console.data_resolve", ruleset=rid, actor=h.actor(sess), detail={"conflict": cid, "keep": keep})
        return out

    def apply_dictionary(sess: Session, path: str, rs: str, text: str, record_field: str) -> dict[str, Any]:
        """Import a REDCap data dictionary: one Questionnaire per instrument, identifier fields dropped."""
        rid = study_or_404(sess, rs)
        need_change(sess, path)
        rec = record_field.strip()
        if rec and not _FIELD.match(rec):
            raise Problem(400, "FORM-NAME", "field names are lower-case letters, digits and _", [rec[:40]])
        out = dict(s28.call(bk, "POST", f"/studies/{rid}/forms/dictionary",
                            {"csv": text, "record_field": rec, "by": h.actor(sess)}))  # fmt: skip
        au.append("console.data_forms", ruleset=rid, actor=h.actor(sess),
                  detail={"forms": len(out.get("forms") or []), "dropped": len(out.get("dropped") or [])})  # fmt: skip
        return out

    # ------------------------------------------------------------------ pages
    def sources_page(request: Request, sess: Session, rid: str, **extra: Any) -> Response:
        try:
            data = read_sources(rid)
            open_n = len(read_conflicts(rid)) if sess.user.can_view_phi else None
            err = None
        except (Problem, Unavailable) as exc:
            data, open_n, err = {"sources": [], "fields": []}, None, err_of(exc)
        has_redcap = any(s["name"] == "redcap" for s in data["sources"])
        return h.page(
            request,
            "data_sources.html",
            sess,
            rs=rid,
            sources=data["sources"],
            fields=data["fields"],
            open_n=open_n,
            has_redcap=has_redcap,
            editable=can_change_setup(sess.user),
            tokens=tokens() if can_change_setup(sess.user) and not has_redcap else [],
            identity="\n".join(f"{f['name']}={f['name']}" for f in data["fields"]),
            can_undo_detach=not has_redcap and undo_of(sess, rid) is not None,  # D-178: the toast's Undo
            **{"err": err, **extra},
        )

    @app.get("/studies/{rs}/sources")
    def sources(request: Request, rs: str) -> Response:
        sess = h.need(request)
        return sources_page(request, sess, study_or_404(sess, rs))

    @app.post("/studies/{rs}/sources/redcap")
    async def attach(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        body = ApiRedcap(
            token_ref=str(form.get("token_ref") or "").strip()[:32] or "-",
            field_map={k.lower(): v.lower() for k, v in parse_map(str(form.get("field_map") or "")).items()},
            owned=[str(x) for x in form.getlist("owned")],
            key_field=str(form.get("key_field") or "").strip() or "tb_screening_no",
            event=str(form.get("event") or "").strip(),
            dag=str(form.get("dag") or "").strip(),
            create=bool(form.get("create")),
        )
        try:
            apply_attach(sess, request.url.path, rid, body)
        except (Problem, Unavailable) as exc:
            return sources_page(request, sess, rid, err=err_of(exc))
        return RedirectResponse(f"/studies/{rid}/sources?done=attach", status_code=303)

    @app.post("/studies/{rs}/sources/redcap/detach")
    def detach(request: Request, rs: str, csrf: str = Form(""), confirm: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        need_change(sess, request.url.path)
        if confirm != "yes" and h.confirm is not None:  # P-10 (D-143): the consequence first
            return h.confirm(request, sess, translate(sess.lang, "confirm.detach"), request.url.path, {},
                             f"/studies/{rid}/sources")  # fmt: skip
        try:
            apply_detach(sess, request.url.path, rid)
        except (Problem, Unavailable) as exc:
            return sources_page(request, sess, rid, err=err_of(exc))
        return RedirectResponse(f"/studies/{rid}/sources?done=detach", status_code=303)

    def undo_of(sess: Session, rid: str) -> dict[str, Any] | None:
        got = detached.get((sess.token_sha, rid))
        if got is None or time.monotonic() - got[1] > 900:
            return None
        return got[0]

    @app.post("/studies/{rs}/sources/redcap/undo")
    def detach_undo(request: Request, rs: str, csrf: str = Form("")) -> Response:
        """D-178 (review J-14): the toast's Undo after Detach: the same connection attached again."""
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        need_change(sess, request.url.path)
        cfg = undo_of(sess, rid)
        if cfg is None:
            raise h.problem(409, "dc.undo_none")
        now_on = [x for x in s28.call(bk, "GET", f"/studies/{rid}/sources").get("sources") or []
                  if x.get("name") == "redcap"]  # fmt: skip
        if now_on:  # someone attached a connection since the detach: the undo must not replace it
            detached.pop((sess.token_sha, rid), None)
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"source": "redcap", "action": "undo_detach", "reason": "attached since"})  # fmt: skip
            raise h.problem(409, "dc.undo_attached")
        try:
            apply_attach(sess, request.url.path, rid, ApiRedcap(**cfg))
        except (Problem, Unavailable) as exc:
            return sources_page(request, sess, rid, err=err_of(exc))
        detached.pop((sess.token_sha, rid), None)
        au.append("console.data_source", ruleset=rid, actor=h.actor(sess),
                  detail={"source": "redcap", "action": "undo_detach"})  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/sources?done=undo", status_code=303)

    @app.post("/studies/{rs}/sources/{name}/sync")
    def sync_now(request: Request, rs: str, name: str, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        try:
            apply_sync(sess, request.url.path, rid, name)
        except (Problem, Unavailable) as exc:
            return sources_page(request, sess, rid, err=err_of(exc))
        return RedirectResponse(f"/studies/{rid}/sources?done=sync", status_code=303)

    def conflicts_page(request: Request, sess: Session, rid: str, everything: bool, **extra: Any) -> Response:
        try:
            rows = read_conflicts(rid, everything)
            lang = sess.lang if sess.lang in ("ja", "zh-TW") else "en"
            labels = {f["name"]: (f.get("labels") or {}).get(lang) or f.get("label") or ""
                      for f in read_sources(rid)["fields"]}  # fmt: skip
            err = None
        except (Problem, Unavailable) as exc:
            rows, labels, err = [], {}, err_of(exc)
        return h.page(
            request,
            "data_conflicts.html",
            sess,
            rs=rid,
            open_rows=[c for c in rows if not c.get("resolved")],
            done_rows=[c for c in rows if c.get("resolved")],
            labels=labels,
            everything=everything,
            editable=can_change_setup(sess.user),
            **{"err": err, **extra},
        )

    @app.get("/studies/{rs}/conflicts")
    def conflicts(request: Request, rs: str, all: str = "") -> Response:
        sess = h.need(request)
        return conflicts_page(request, sess, study_or_404(sess, rs, rows=True), all == "1")

    @app.post("/studies/{rs}/conflicts/{cid}")
    def resolve(request: Request, rs: str, cid: int, csrf: str = Form(""), keep: str = Form(""),
                confirm: str = Form("")) -> Response:  # fmt: skip
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs, rows=True)
        need_change(sess, request.url.path)
        if keep not in KEEP:
            raise h.problem(400, "request.refused", reason="keep is trialbox or theirs")
        if confirm != "yes" and h.confirm is not None:  # P-10 (D-143): the consequence first
            lang = sess.lang
            try:
                src = next((str(c.get("source") or "") for c in read_conflicts(rid) if c.get("id") == cid), "")
            except (Problem, Unavailable):
                src = ""
            name = translate(lang, f"dc.source.{src}") if src and f"dc.source.{src}" != translate(
                lang, f"dc.source.{src}") else (src or "REDCap")  # fmt: skip
            key = "confirm.keep" if keep == "trialbox" else "confirm.take"
            return h.confirm(request, sess, translate(lang, key, source=name), request.url.path, {"keep": keep},
                             f"/studies/{rid}/conflicts")  # fmt: skip
        try:
            apply_resolve(sess, request.url.path, rid, cid, keep)
        except (Problem, Unavailable) as exc:
            return conflicts_page(request, sess, rid, False, err=err_of(exc))
        return RedirectResponse(f"/studies/{rid}/conflicts?done={cid}", status_code=303)

    def forms_page(request: Request, sess: Session, rid: str, **extra: Any) -> Response:
        try:
            qs, err = read_forms(rid), None
        except (Problem, Unavailable) as exc:
            qs, err = [], err_of(exc)
        return h.page(request, "data_forms.html", sess, rs=rid, forms=qs, editable=can_change_setup(sess.user),
                      **{"err": err, **extra})  # fmt: skip

    @app.get("/studies/{rs}/forms")
    def forms(request: Request, rs: str) -> Response:
        sess = h.need(request)
        return forms_page(request, sess, study_or_404(sess, rs))

    @app.post("/studies/{rs}/forms/dictionary")
    async def import_dictionary(
        request: Request,
        rs: str,
        csrf: Annotated[str, Form()] = "",
        record_field: Annotated[str, Form()] = "",
        dictionary: Annotated[UploadFile | None, File()] = None,
    ) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        need_change(sess, request.url.path)
        data = await dictionary.read(MAX_DICTIONARY + 1) if dictionary is not None else b""
        if not data.strip():
            return forms_page(request, sess, rid, err={"code": "FORM-EMPTY", "fields": ""})
        if len(data) > MAX_DICTIONARY:
            return forms_page(request, sess, rid, err={"code": "FORM-SIZE", "fields": ""})
        try:
            out = apply_dictionary(sess, request.url.path, rid, data.decode("utf-8-sig", errors="replace"),
                                   record_field)  # fmt: skip
        except (Problem, Unavailable) as exc:
            return forms_page(request, sess, rid, err=err_of(exc))
        q = f"forms={len(out.get('forms') or [])}&fields={out.get('fields', 0)}&dropped={len(out.get('dropped') or [])}"
        return RedirectResponse(f"/studies/{rid}/forms?{q}", status_code=303)

    # ------------------------------------------------------------------ /api/v1 (D-125, D-127)
    def api_session(request: Request) -> Session:
        assert h.api_session is not None, "console.home.register runs first"
        return h.api_session(request)

    def api_call(fn: Any, *args: Any) -> Any:
        """An orchestrator refusal as the API's JSON error (D-125), never a page."""
        try:
            return fn(*args)
        except Problem as exc:
            status = exc.status if 400 <= exc.status < 500 else 502
            raise h.problem(status, "request.refused", code=exc.code, reason=exc.message,
                            fields=", ".join(exc.fields)) from exc  # fmt: skip
        except Unavailable as exc:
            raise h.problem(503, "unavailable", detail=str(exc)[:200]) from exc

    @app.get("/api/v1/studies/{rs}/sources")
    def api_sources(request: Request, rs: str) -> dict[str, Any]:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        data = api_call(read_sources, rid)
        return {"study": rid, "may_change": can_change_setup(sess.user), **data}

    @app.put("/api/v1/studies/{rs}/sources/redcap")
    def api_attach(request: Request, rs: str, body: ApiRedcap) -> dict[str, Any]:
        sess = api_session(request)
        return {"study": rs.upper(), **api_call(apply_attach, sess, request.url.path, rs, body)}

    @app.delete("/api/v1/studies/{rs}/sources/redcap")
    def api_detach(request: Request, rs: str) -> dict[str, Any]:
        sess = api_session(request)
        return {"study": rs.upper(), **api_call(apply_detach, sess, request.url.path, rs)}

    @app.post("/api/v1/studies/{rs}/sources/{name}/sync")
    def api_sync(request: Request, rs: str, name: str) -> dict[str, Any]:
        sess = api_session(request)
        return {"study": rs.upper(), **api_call(apply_sync, sess, request.url.path, rs, name)}

    @app.get("/api/v1/studies/{rs}/conflicts")
    def api_conflicts(request: Request, rs: str, all: bool = False) -> dict[str, Any]:
        sess = api_session(request)
        rid = study_or_404(sess, rs, rows=True)
        return {"study": rid, "conflicts": api_call(read_conflicts, rid, all)}

    @app.post("/api/v1/studies/{rs}/conflicts/{cid}")
    def api_resolve(request: Request, rs: str, cid: int, body: ApiResolve) -> dict[str, Any]:
        sess = api_session(request)
        return {"study": rs.upper(), **api_call(apply_resolve, sess, request.url.path, rs, cid, body.keep)}

    @app.get("/api/v1/studies/{rs}/forms")
    def api_forms(request: Request, rs: str) -> dict[str, Any]:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        return {"study": rid, "forms": api_call(read_forms, rid)}

    @app.post("/api/v1/studies/{rs}/forms/dictionary")
    def api_dictionary(request: Request, rs: str, body: ApiDictionary) -> dict[str, Any]:
        sess = api_session(request)
        return {"study": rs.upper(),
                **api_call(apply_dictionary, sess, request.url.path, rs, body.csv, body.record_field)}  # fmt: skip
