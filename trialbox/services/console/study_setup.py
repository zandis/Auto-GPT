"""S21 Study set-up (three sections in build step 3) and S36 REDCap connection (D-109).

S21 sections: (1) Study: type, cohort kind, consent; (2) REDCap link: the per-study field map (ICD-04 §4.1a), Test
link, and the read-back (last read, Run now, duplicates, unmatched records, conflicts); (3) Screening log: the
screening-number prefix and next number, and the "Not suitable" reason list. Everything is saved in the orchestrator's
S-28 study store through its API; the coordinator edits, everyone on the study reads.

S36 (administrators): the REDCap base URL and the API tokens, entered once and shown masked, with Test connection.

The nightly read-back is ``python -m console.rc_read`` (cron on the box), the same call as Run now.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse

from console import s28
from console import studies as st
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.sitestore import ALL_REASONS, COHORT_KINDS, STUDY_TYPES, StudySettings

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
CONSENT_SCOPES = ("opt-in", "opt-out", "waiver")
LINK_TEXT = (
    "dag",
    "link_field",
    "consent_field",
    "consent_event",
    "enrol_field",
    "enrol_value",
    "screenfail_field",
    "withdraw_field",
    "withdraw_value",
    "subject_no_field",
    "write_mode",
    "write_form",
    "write_event",
)


def parse_map(text: str) -> dict[str, str]:
    """``"1=inclusion, 2=exclusion"`` (commas, semicolons or new lines) -> ``{"1": "inclusion", ...}``."""
    out: dict[str, str] = {}
    for part in re.split(r"[,;\n]", text or ""):
        code, sep, cat = part.partition("=")
        if sep and code.strip():
            out[code.strip()] = cat.strip()
    return out


def show_map(m: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in m.items())


def screening_map(store: Any, rs: str) -> dict[str, str]:
    """Screening number -> pid for the read-back join (the console's site store issues the numbers)."""
    return {no: pid for pid, no in store.screening_nos(rs).items()}


def read_now(h: Helpers, rs: str, by: str) -> dict[str, Any]:
    """Run now and the nightly job: the orchestrator reads REDCap through the study's link and updates the log."""
    issued = {no: at for _pid, no, at in h.store.screening_rows(rs)}
    body = {"screening": screening_map(h.store, rs), "issued": issued, "by": by}
    out = s28.call(h.bk, "POST", f"/studies/{rs}/redcap-read", body)
    return dict(out)


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.role == "cro":
            raise h.problem(404, "notfound")
        return rid

    def can_edit(sess: Session) -> bool:
        return sess.user.role == "coordinator"

    def need_edit(request: Request, sess: Session, csrf: str) -> None:
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not can_edit(sess):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

    def err_of(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, Problem):
            return {"code": exc.code, "msg": exc.message, "fields": ", ".join(exc.fields)}
        return {"code": "unavailable", "msg": "", "fields": ""}

    def get_or_none(path: str) -> Any:
        try:
            return s28.call(bk, "GET", path)
        except (Problem, Unavailable):
            return None

    def defaults(rid: str) -> StudySettings:
        kind = next((r.kind for r in bk.rulesets() if r.id == rid), "trial")
        return st.study_defaults(rid, kind)

    def setup_page(request: Request, sess: Session, rid: str, **extra: Any) -> Response:
        conf = s28.load(bk, store, rid, defaults(rid))
        row = s28.remote(bk, rid) if s28.has_api(bk) else None
        link = get_or_none(f"/studies/{rid}/redcap-link")
        conns = get_or_none("/redcap/connections") or {}
        reads = (link or {}).get("reads") or []
        lk = (link or {}).get("link") or {}
        return h.page(
            request,
            "setup.html",
            sess,
            rs=rid,
            conf=conf,
            row=row,
            api=s28.has_api(bk),
            editable=can_edit(sess),
            link=link,
            lk=lk,
            sf_map=show_map(lk.get("screenfail_choice_map") or {}),
            tokens=[c["token_ref"] for c in conns.get("connections") or []],
            last=reads[0] if reads else None,
            all_reasons=ALL_REASONS,
            study_types=STUDY_TYPES,
            cohort_kinds=COHORT_KINDS,
            scopes=CONSENT_SCOPES,
            example=f"{conf.screening_prefix or rid + '-'}{max(conf.first_no, 1):04d}",
            **{"saved": request.query_params.get("saved", ""), "err": None, "test": None, "read": None, **extra},
        )

    @app.get("/studies/{rs}/setup")
    def setup(request: Request, rs: str) -> Response:
        sess = h.need(request)
        return setup_page(request, sess, study_or_404(sess, rs))

    def save_settings(request: Request, sess: Session, rid: str, s: StudySettings, extra: dict[str, Any],
                      section: str) -> Response:  # fmt: skip
        try:
            s28.save(bk, rid, s, h.actor(sess), extra)
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc))
        au.append("console.study_setup", ruleset=rid, actor=h.actor(sess), detail={"section": section})
        return RedirectResponse(f"/studies/{rid}/setup?saved={section}#{section}", status_code=303)

    @app.post("/studies/{rs}/setup/study")
    def save_study(
        request: Request,
        rs: str,
        csrf: str = Form(""),
        study_type: str = Form("trial"),
        cohort_kind: str = Form("enrolled"),
        consent_scope: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_edit(request, sess, csrf)
        if study_type not in STUDY_TYPES or cohort_kind not in COHORT_KINDS:
            raise h.problem(400, "request.refused", reason="unknown study type or cohort kind")
        conf = s28.load(bk, store, rid, defaults(rid))
        row = s28.remote(bk, rid) or {}
        s = StudySettings(study_type, cohort_kind, conf.reasons, conf.screening_prefix, conf.first_no)
        scope = consent_scope if consent_scope in CONSENT_SCOPES else None
        return save_settings(request, sess, rid, s, {"consent_scope": scope,
                             "introduce_rule": row.get("introduce_rule")}, "study")  # fmt: skip

    @app.post("/studies/{rs}/setup/log")
    async def save_log(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        need_edit(request, sess, str(form.get("csrf") or ""))
        reasons = tuple(r for r in ALL_REASONS if r in form.getlist("reasons"))
        prefix = str(form.get("screening_prefix") or "").strip()[:16]
        try:
            first = max(1, min(999999, int(str(form.get("first_no") or "1"))))
        except ValueError:
            first = 1
        if not reasons:
            return setup_page(
                request, sess, rid, err={"code": "STUDY-FIELD", "msg": "at least one reason", "fields": ""}
            )
        conf = s28.load(bk, store, rid, defaults(rid))
        row = s28.remote(bk, rid) or {}
        s = StudySettings(conf.study_type, conf.cohort_kind, reasons, prefix, first)
        return save_settings(request, sess, rid, s, {"consent_scope": row.get("consent_scope"),
                             "introduce_rule": row.get("introduce_rule")}, "log")  # fmt: skip

    def link_from_form(rid: str, form: Any) -> dict[str, Any]:
        body: dict[str, Any] = {k: str(form.get(k) or "").strip() for k in LINK_TEXT}
        body["ruleset"] = rid
        body["link_mode"] = "tb_screening_no"
        body["token_ref"] = str(form.get("token_ref") or "").strip()
        try:
            body["project_id"] = int(str(form.get("project_id") or "0").strip() or 0)
        except ValueError:
            body["project_id"] = 0
        body["screenfail_choice_map"] = parse_map(str(form.get("screenfail_choice_map") or ""))
        body["link_field"] = body["link_field"] or "tb_screening_no"
        body["enrol_value"] = body["enrol_value"] or "1"
        body["withdraw_value"] = body["withdraw_value"] or "1"
        body["write_mode"] = body["write_mode"] if body["write_mode"] in ("off", "existing", "create") else "off"
        body["write_form"] = body["write_form"] or "trialbox_screening"
        return body

    @app.post("/studies/{rs}/setup/redcap")
    async def save_link(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        need_edit(request, sess, str(form.get("csrf") or ""))
        body = link_from_form(rid, form)
        try:
            s28.call(bk, "PUT", f"/studies/{rid}/redcap-link", {"link": body, "by": h.actor(sess)})
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc), lk_form=body)
        au.append("console.study_setup", ruleset=rid, actor=h.actor(sess), detail={"section": "redcap"})
        return RedirectResponse(f"/studies/{rid}/setup?saved=redcap#redcap", status_code=303)

    @app.post("/studies/{rs}/setup/redcap/test")
    def test_link(request: Request, rs: str, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_request:
            raise h.problem(403, "forbidden")
        try:
            out = s28.call(bk, "POST", f"/studies/{rid}/redcap-link/test", {"screening": screening_map(store, rid)})
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc))
        nos = {pid: no for no, pid in screening_map(store, rid).items()}
        for j in out.get("sample") or []:
            j["no"] = nos.get(j.get("pid") or "", j.get("link_value"))
        return setup_page(request, sess, rid, test=out)

    @app.post("/studies/{rs}/redcap-read")
    def run_now(request: Request, rs: str, csrf: str = Form(""), back: str = Form("setup")) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_request:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        target = f"/studies/{rid}/screening-log" if back == "log" else f"/studies/{rid}/setup"
        try:
            out = read_now(h, rid, h.actor(sess))
        except (Problem, Unavailable) as exc:
            e = err_of(exc)
            return RedirectResponse(f"{target}?rc_err={quote(e['code'])}#redcap", status_code=303)
        au.append("console.redcap_read", ruleset=rid, actor=h.actor(sess), detail={"changes": len(out["changes"])})
        return RedirectResponse(f"{target}?read={len(out['changes'])}#redcap", status_code=303)

    # ------------------------------------------------------------------ S36
    def need_admin_view(sess: Session) -> None:
        if sess.user.role not in ("admin", "viewer"):
            raise h.problem(403, "forbidden")

    def s36_page(request: Request, sess: Session, **extra: Any) -> Response:
        conns = get_or_none("/redcap/connections")
        return h.page(
            request,
            "redcap.html",
            sess,
            conns=(conns or {}).get("connections") or [],
            api=conns is not None,
            **{"saved": request.query_params.get("saved", ""), "err": None, "tested": None, **extra},
        )

    @app.get("/admin/redcap")
    def s36(request: Request) -> Response:
        sess = h.need(request)
        need_admin_view(sess)
        return s36_page(request, sess)

    @app.post("/admin/redcap")
    def s36_save(
        request: Request,
        csrf: str = Form(""),
        token_ref: str = Form("main"),
        url: str = Form(""),
        token: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        ref = token_ref.strip().lower()
        if not _REF.match(ref):
            return s36_page(
                request, sess, err={"code": "RC-FIELD", "msg": "token name: a-z, 0-9, - and _", "fields": ""}
            )
        body = {"url": url.strip(), "token": token.strip() or None, "by": h.actor(sess)}
        try:
            s28.call(bk, "PUT", f"/redcap/connections/{ref}", body)
        except (Problem, Unavailable) as exc:
            return s36_page(request, sess, err=err_of(exc))
        au.append("console.redcap_connection", actor=h.actor(sess), detail={"token_ref": ref})
        return RedirectResponse("/admin/redcap?saved=1", status_code=303)

    @app.post("/admin/redcap/{ref}/test")
    def s36_test(request: Request, ref: str, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            raise h.problem(403, "forbidden")
        if not _REF.match(ref):
            raise h.problem(404, "notfound")
        try:
            out = s28.call(bk, "POST", f"/redcap/connections/{ref}/test")
        except (Problem, Unavailable) as exc:
            return s36_page(request, sess, err=err_of(exc), tested=ref)
        return s36_page(request, sess, tested=ref, result=out)
