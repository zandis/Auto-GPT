"""TB-PLAN-04 step 5b (D-131, D-132, D-135): site set-up in the console, and its ``/api/v1`` routes (D-125, D-127).

* **Readiness** (``/site``): the three questions (which trial, which patients, where trial records live) as green,
  amber or red, each with what is missing and a link to fix it; the feasibility counts with how much rests on coded,
  confirmed and proposed facts, or a plain "feasibility needs a bulk source" when there are only charts.
* **Set-up wizard** (``/site/start``): one question per screen, with examples, what each answer means and progress
  to "ready". The shortest path is a protocol and charts pasted one by one.
* **Charts** (``/site/charts``): paste the EMR screen's text or upload .txt, Word, PDF or a scan (OCR on the box).
* **To check** (``/site/facts``): each proposed fact beside its quote, Confirm / Correct / Reject in one tap.
* **Local codes** (``/site/codes``), **Please check** (``/site/checks``, with the fixes made), **Sheets**
  (``/site/sheets``), **Patients** (``/site/people``: joined by pseudonym, disagreements listed; ``/site/patients``:
  the criteria on each patient, the trail), **Help** (``/site/help``: templates, the practice site, remote help).
* **Ask TrialBox** (``/ask``, linked from every page's header): explains and links, never changes anything. It reads
  the readiness and the screening trail and asks the local model to phrase the answer.

D-179 (review J-06): these pages are site-wide (the steward's work, every patient). A study-scoped account opens only
its own studies' readiness and the help; every other site page and API answers 404.

Everything goes through the orchestrator's set-up API (``orchestrator.setup_api``). Roles: the coordinator and the
administrator change things; the investigator reads; viewer and CRA accounts get 403, CRO accounts 404.
"""

from __future__ import annotations

import base64
import contextlib
import re
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from console import s28
from console.auth import Session, User
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.i18n import translate

_WS = re.compile(r"^[a-z][a-z0-9]{0,15}$")
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_PID = re.compile(r"^[0-9a-f]{32}$")
LANGS = ("ja", "zh-TW", "en")
WIZARD = ("trial", "charts", "bulk", "check", "records")
MAX_UPLOAD = 20 * 1024 * 1024
ROLES = (
    "chart_no",
    "birth_date",
    "sex",
    "diagnosis",
    "diagnosis_code",
    "lab",
    "lab_code",
    "lab_unit",
    "date",
    "drug_code",
    "drug_name",
    "ignore",
)
_WHY = re.compile(r"(?i)why|なぜ|どうして|理由|為什麼|為何|原因|リスト")
_NEXT = re.compile(r"(?i)next|what (do|should) i do|次|何を|どうすれば|下一步|該做|怎麼做")


# D-179 (review J-06): the site set-up pages hold every patient of the site (charts and their quotes, proposed facts,
# the hospital's codes, lists, the patients against a study's criteria): the steward's work, site-wide, for accounts
# that see every study. A study-scoped account (an SMO or CRO coordinator, D-104) opens only what is per study: its own
# studies' readiness and the help. Every other site page and API answers 404, as another study's pages do.
PER_STUDY = frozenset({"/site", "/site/help", "/api/v1/site/readiness"})
ASK_PER_HOUR = 60  # D-273 (PV-7): one patient's "why" answers per person and hour (the candidate pages' default)


def site_wide(user: User) -> bool:
    """May open the site-wide set-up pages (D-179): an account not limited to some studies."""
    return not user.studies


def can_setup(user: User) -> bool:
    """Who changes the site's set-up: the coordinator and the administrator (D-131: "a CRC or admin confirms")."""
    return user.role in ("coordinator", "admin")


class ApiChart(BaseModel):
    chart_no: str = Field(max_length=40)
    text: str = Field(default="", max_length=60_000)
    b64: str = ""
    name: str = Field(default="pasted.txt", max_length=200)


class ApiDecide(BaseModel):
    action: str = Field(pattern=r"^(confirm|correct|reject|undo)$")  # undo: D-178 (review J-14)
    changes: dict[str, str] = Field(default_factory=dict)


class ApiMap(BaseModel):
    domain: str
    system: str
    code: str
    target_code: str = ""


class ApiAnswer(BaseModel):
    answer: str = Field(max_length=40)


def register(app: FastAPI, h: Helpers) -> None:
    bk, au = h.bk, h.au

    def lang_of(sess: Session) -> str:
        return sess.lang if sess.lang in LANGS else "en"

    def need_view(sess: Session, path: str) -> None:
        if sess.user.role == "cro":
            raise h.problem(404, "notfound")
        if not sess.user.can_view_phi:
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        if not site_wide(sess.user) and path not in PER_STUDY:  # D-179: site-wide data, not a study's
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80], "reason": "study scope"})
            raise h.problem(404, "notfound")

    def need_change(sess: Session, path: str) -> None:
        need_view(sess, path)
        if not can_setup(sess.user):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")

    def ws_of(raw: str | None) -> str:
        w = (raw or "main").strip().lower()
        return w if _WS.match(w) else "main"

    def studies(sess: Session) -> list[str]:
        try:
            return sorted(r.id for r in bk.rulesets() if sess.user.sees_study(r.id))
        except Exception:
            return []

    def study_of(sess: Session, raw: str | None) -> str:
        rid = (raw or "").strip().upper()
        mine = studies(sess)
        if rid and _RS.match(rid) and sess.user.sees_study(rid):
            return rid  # a study whose protocol is being read may not be in the list yet: question 1 says so
        return mine[0] if mine else ""

    def get(path: str) -> Any:
        return s28.call(bk, "GET", path)

    def post(path: str, body: dict[str, Any]) -> Any:
        return s28.call(bk, "POST", path, body)

    def q(ws: str, rs: str, **more: str) -> str:
        return urlencode({"ws": ws, "study": rs, **{k: v for k, v in more.items() if v}})

    def ctx(sess: Session, ws: str, rs: str) -> dict[str, Any]:
        lang = lang_of(sess)
        return {
            "ws": ws,
            "rs": rs,
            "studies": sorted({*studies(sess), *([rs] if rs else [])}),
            "editable": can_setup(sess.user) and site_wide(sess.user),
            "site_wide": site_wide(sess.user),  # D-179: a study-scoped account sees readiness and help only
            "qs": q(ws, rs),
            "reason_label": lambda code: t_reason(lang, str(code or "")),
        }

    # ------------------------------------------------------------------ actions (one per page and /api/v1)
    def act_chart(sess: Session, ws: str, chart_no: str, text: str, name: str, data: bytes | None) -> dict[str, Any]:
        need_change(sess, "/site/charts")
        body: dict[str, Any] = {"chart_no": chart_no[:40], "lang": lang_of(sess), "by": h.actor(sess)}
        if data:
            body |= {"name": name[:200], "b64": base64.b64encode(data).decode("ascii")}
        else:
            body |= {"text": text[:60_000]}
        out = dict(post(f"/setup/{ws}/charts", body))
        au.append(
            "console.site_chart",
            actor=h.actor(sess),
            detail={"ws": ws, "input": out.get("input"), "proposed": out.get("facts")},
        )
        return out

    def act_fact(sess: Session, ws: str, fid: int, action: str, changes: dict[str, str]) -> dict[str, Any]:
        need_change(sess, "/site/facts")
        out = dict(post(f"/setup/{ws}/facts/{fid}", {"action": action, "changes": changes, "by": h.actor(sess)}))
        au.append("console.site_fact", actor=h.actor(sess), detail={"ws": ws, "fact": fid, "action": action})
        return out

    def act_code(sess: Session, ws: str, domain: str, system: str, code: str, target: str) -> dict[str, Any]:
        need_change(sess, "/site/codes")
        tsys = {
            "condition": "http://hl7.org/fhir/sid/icd-10-cm",
            "observation": "http://loinc.org",
            "medication": "http://www.whocc.no/atc",
        }.get(domain, "")
        out = dict(
            post(
                f"/setup/{ws}/codes",
                {
                    "domain": domain,
                    "system": system,
                    "code": code,
                    "target_system": tsys,
                    "target_code": target.strip().upper(),
                    "by": h.actor(sess),
                },
            )
        )
        au.append("console.site_map", actor=h.actor(sess), detail={"ws": ws, "local": code[:40], "to": target[:20]})
        return out

    def act_check(sess: Session, ws: str, cid: int, answer: str) -> dict[str, Any]:
        need_change(sess, "/site/checks")
        out = dict(post(f"/setup/{ws}/checks/{cid}", {"answer": answer, "by": h.actor(sess)}))
        au.append("console.site_check", actor=h.actor(sess), detail={"ws": ws, "check": cid, "answer": answer})
        return out

    # ------------------------------------------------------------------ the assistant (read only)
    def assistant(sess: Session, question: str, ws: str, rs: str, pid: str = "") -> dict[str, Any]:
        """Explain and link; never change anything. Every read is a GET; the only POST is ``/assist``, which puts the
        draft to the local model for phrasing and itself reads and writes nothing."""
        lang = lang_of(sess)

        def t(key: str, **kw: Any) -> str:
            return translate(lang, key, **kw)

        links: list[dict[str, str]] = []
        points: list[str] = []
        kind = (
            "why"
            if (pid or _WHY.search(question or "")) and sess.user.can_view_phi
            else ("next" if _NEXT.search(question or "") or not question else "help")
        )
        if kind == "next":
            if not can_setup(sess.user) and sess.user.role != "investigator":
                points.append(t("ask.next.reader"))
            else:
                try:
                    rd = get(f"/setup/{ws}/readiness?study={quote(rs)}") if rs else None
                except (Problem, Unavailable):
                    rd = None
                if rd is None:
                    points.append(t("ask.next.nostudy"))
                    links.append({"href": "/pilot/protocol", "label": t("site.link.protocol")})
                else:
                    for name in ("trial", "patients", "records"):
                        for m in rd["questions"][name]["missing"]:
                            points.append(t(f"site.miss.{m['key'].split('.', 1)[1]}", **_args(m)))
                            links.append(
                                {"href": link_of(m, ws, rs), "label": t(f"site.fix.{m['key'].split('.', 1)[1]}")}
                            )
                    if not points:
                        points.append(t("ask.next.ready"))
                        links.append({"href": f"/studies/{rs}/week", "label": t("site.link.week")})
                    points = points[:1] + ([t("ask.next.more", n=len(points) - 1)] if len(points) > 1 else [])
                    links = links[:3]
        elif kind == "why":
            rows = trail(sess, ws, rs, pid)
            if rows is None:
                points.append(t("ask.why.unknown"))
            else:
                met = [r["label"] for r in rows if r["verdict"] in ("met", "clear", "pass")]
                open_ = [f"{r['label']} ({t_reason(lang, r['reason'])})" for r in rows if r["verdict"] == "unknown"]
                out_ = [r["label"] for r in rows if r["verdict"] in ("not_met", "excluded", "fail")]
                if out_:
                    points.append(t("ask.why.out", items="、".join(out_) if lang != "en" else ", ".join(out_)))
                if met:
                    points.append(t("ask.why.met", items="、".join(met) if lang != "en" else ", ".join(met)))
                if open_:
                    points.append(t("ask.why.open", items="、".join(open_) if lang != "en" else "; ".join(open_)))
                links.append({"href": f"/site/patients?{q(ws, rs)}#p-{pid[:8]}", "label": t("site.link.patients")})
                if any(r["reason"] == "proposed_fact" for r in rows):
                    links.append({"href": f"/site/facts?{q(ws, rs)}", "label": t("site.fix.proposed")})
        else:
            points.append(t("ask.answer.help"))
            links.append({"href": f"/help?back={quote('/ask')}", "label": t("help.title")})
        if not site_wide(sess.user):  # D-179: no link to a site-wide page a study-scoped account cannot open
            links = [x for x in links if not x["href"].startswith("/site/") or x["href"].split("?")[0] in PER_STUDY]
        draft = " ".join(points)
        try:
            res = post("/assist", {"question": question[:300], "lang": lang, "draft": draft, "points": points})
            text = str(res.get("answer") or draft)
        except (Problem, Unavailable):
            text = draft
        return {"kind": kind, "answer": text, "links": links}

    def trail(sess: Session, ws: str, rs: str, pid: str) -> list[dict[str, Any]] | None:
        """The screening trail of one patient: this week's list first (the SCREEN run), else the site check.

        D-273 (PV-7): one patient's verdicts are patient-level data. The study must be one of the account's, an
        investigator must be delegated ("screen") as on the patient page, an opted-out patient is never answered
        (the site-check fallback does not read the register), each answer is capped per person and hour as the
        candidate page is, and it leaves one audit event."""
        if not _PID.match(pid or "") or not rs:
            return None
        rs = rs.strip().upper()
        if not sess.user.sees_study(rs) or not h.delegated_ok(sess.user, rs) or pid in h.gone():
            au.append("console.denied", actor=h.actor(sess), detail={"action": "ask why", "ruleset": rs})
            return None
        if h.team is not None:
            since = (h.clock() - timedelta(hours=1)).isoformat()
            if h.team.count_views(sess.user.username, "ask", since) >= ASK_PER_HOUR:
                au.append("console.rate_limited", actor=h.actor(sess), detail={"action": "ask", "limit": ASK_PER_HOUR})
                return None
            h.team.record_view(rs, pid, "ask", "ask", sess.user.username, h.clock().isoformat())
        au.append("console.ask_patient", ruleset=rs, actor=h.actor(sess), detail={"pid": pid, "role": sess.user.role})
        if h.week_bundle is not None:
            try:
                bundle = h.week_bundle(sess, rs) or {}
            except Exception:
                bundle = {}
            try:
                labels = {c["id"]: c["label"] for c in bk.criteria(rs)}
            except Exception:
                labels = {}
            for r in (bundle.get("cl") or {}).get("rows") or []:
                if r.get("pid") == pid:
                    return [
                        {
                            "label": labels.get(v.get("id"), v.get("id")),
                            "verdict": v.get("verdict"),
                            "reason": (v.get("evidence") or {}).get("reason") or "",
                        }
                        for v in r.get("criteria") or []
                    ]
        if not site_wide(sess.user):  # D-179: the site-wide patient check is not a study-scoped account's
            return None
        try:
            out = get(f"/setup/{ws}/patients?study={quote(rs)}")
        except (Problem, Unavailable):
            return None
        for p in out.get("patients") or []:
            if p["pid"] == pid:
                return list(p["criteria"])
        return None

    def link_of(m: dict[str, Any], ws: str, rs: str) -> str:
        target = str(m.get("link") or "")
        if target.startswith("/"):
            return target
        if target == "forms":
            return f"/studies/{rs}/forms" if rs else "/site"
        return f"/site/{target}?{q(ws, rs)}"

    def page_data(sess: Session, ws: str, rs: str) -> dict[str, Any]:
        rd: dict[str, Any] | None = None
        err = None
        try:
            rd = dict(get(f"/setup/{ws}/readiness?study={quote(rs)}"))
            for name in ("trial", "patients", "records"):
                for m in rd["questions"][name]["missing"]:
                    m["href"] = link_of(m, ws, rs)
                    if not site_wide(sess.user) and m["href"].startswith("/site/"):
                        m["href"] = ""  # D-179: the fix is the steward's; a study-scoped account has no link
        except (Problem, Unavailable) as exc:
            err = str(exc)[:200]
        return {"rd": rd, "err": err}

    # ------------------------------------------------------------------ pages
    @app.get("/site")
    def site(request: Request, ws: str = "main", study: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        data = page_data(sess, w, rs)
        feas: dict[str, Any] | None = None
        if rs and data["rd"] is not None:
            try:
                feas = dict(get(f"/setup/{w}/feasibility?study={quote(rs)}"))
            except (Problem, Unavailable):
                feas = None
        return h.page(request, "site_ready.html", sess, **ctx(sess, w, rs), **data, feas=feas)

    @app.get("/site/start")
    def wizard(request: Request, ws: str = "main", study: str = "", step: int = 1) -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        step = min(max(step, 1), len(WIZARD))
        data = page_data(sess, w, rs)
        return h.page(
            request, "site_wizard.html", sess, **ctx(sess, w, rs), **data, step=step, steps=WIZARD, key=WIZARD[step - 1]
        )

    @app.get("/site/charts")
    def charts_page(request: Request, ws: str = "main", study: str = "", done: str = "", err: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        inputs = []
        with contextlib.suppress(Problem, Unavailable):
            inputs = [i for i in get(f"/setup/{w}/inputs") if i["kind"] == "chart"]
        return h.page(
            request,
            "site_charts.html",
            sess,
            **ctx(sess, w, rs),
            inputs=inputs[-20:][::-1],
            done=done[:40],
            err=err[:200],
        )

    @app.post("/site/charts")
    async def charts_post(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        w, rs = ws_of(str(form.get("ws") or "")), study_of(sess, str(form.get("study") or ""))
        up = form.get("file")
        data = None
        name = "pasted.txt"
        if up is not None and not isinstance(up, str) and getattr(up, "filename", None):
            data = await up.read(MAX_UPLOAD + 1)
            name = str(up.filename)
        try:
            out = act_chart(sess, w, str(form.get("chart_no") or ""), str(form.get("text") or ""), name, data)
        except Problem as exc:
            return RedirectResponse(f"/site/charts?{q(w, rs, err=exc.code)}", status_code=303)
        except Unavailable:
            return RedirectResponse(f"/site/charts?{q(w, rs, err='unavailable')}", status_code=303)
        return RedirectResponse(f"/site/charts?{q(w, rs, done=str(out.get('facts', 0)))}", status_code=303)

    @app.get("/site/facts")
    def facts_page(
        request: Request,
        ws: str = "main",
        study: str = "",
        show: str = "proposed",
        done: str = "",
        err: str = "",
        fact: int = 0,
    ) -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        show = show if show in ("proposed", "confirmed", "rejected") else "proposed"
        facts: list[dict[str, Any]] = []
        with contextlib.suppress(Problem, Unavailable):
            facts = list(get(f"/setup/{w}/facts?status={show}"))
        return h.page(
            request,
            "site_facts.html",
            sess,
            **ctx(sess, w, rs),
            facts=facts[:200],
            show=show,
            n=len(facts),
            done=done[:20],
            err=err[:80],
            undo_fact=fact if done in ("confirm", "correct", "reject") and fact > 0 else 0,  # D-178: the toast
        )

    @app.post("/site/facts/{fid}")
    async def facts_post(request: Request, fid: int) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        w, rs = ws_of(str(form.get("ws") or "")), study_of(sess, str(form.get("study") or ""))
        action = str(form.get("action") or "")
        changes = {
            k: str(form.get(k) or "").strip() for k in ("value", "day", "code") if str(form.get(k) or "").strip()
        }
        if action == "reject" and str(form.get("confirm") or "") != "yes" and h.confirm is not None:
            need_change(sess, "/site/facts")  # D-178 (review J-14): a rejected fact never counts; say so first
            text = translate(lang_of(sess), "confirm.reject_fact")
            fields = {"action": "reject", "ws": w, "study": rs}
            return h.confirm(request, sess, text, request.url.path, fields, f"/site/facts?{q(w, rs)}#fact-{fid}")
        try:
            act_fact(sess, w, fid, action, changes)
        except Problem as exc:
            return RedirectResponse(f"/site/facts?{q(w, rs, err=exc.code)}", status_code=303)
        more = {"fact": str(fid)} if action != "undo" else {}
        return RedirectResponse(f"/site/facts?{q(w, rs, done=action, **more)}#facts", status_code=303)

    @app.get("/site/codes")
    def codes_page(request: Request, ws: str = "main", study: str = "", done: str = "", err: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        codes: list[dict[str, Any]] = []
        with contextlib.suppress(Problem, Unavailable):
            codes = list(get(f"/setup/{w}/codes"))
        terms: list[dict[str, Any]] = []
        with contextlib.suppress(Problem, Unavailable):
            terms = list(get("/setup/terminology"))  # D-137: the licensed Japanese code lists
        todo = [c for c in codes if c["mapped_code"] is None]
        return h.page(
            request,
            "site_codes.html",
            sess,
            **ctx(sess, w, rs),
            todo=todo,
            terms=terms,
            mapped=[c for c in codes if c["mapped_code"] is not None],
            done=done[:20],
            err=err[:80],
        )

    @app.post("/site/codes")
    async def codes_post(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        w, rs = ws_of(str(form.get("ws") or "")), study_of(sess, str(form.get("study") or ""))
        up = form.get("file")
        try:
            if up is not None and not isinstance(up, str) and getattr(up, "filename", None):
                need_change(sess, "/site/codes")
                data = await up.read(MAX_UPLOAD + 1)
                post(f"/setup/{w}/codes/sheet", {"b64": base64.b64encode(data).decode("ascii"), "by": h.actor(sess)})
                au.append("console.site_map", actor=h.actor(sess), detail={"ws": w, "sheet": True})
            else:
                target = str(form.get("use") or form.get("target") or "")
                act_code(
                    sess,
                    w,
                    str(form.get("domain") or ""),
                    str(form.get("system") or ""),
                    str(form.get("code") or ""),
                    target if target != "-" else "",
                )
        except Problem as exc:
            return RedirectResponse(f"/site/codes?{q(w, rs, err=exc.code)}", status_code=303)
        return RedirectResponse(f"/site/codes?{q(w, rs, done='mapped')}", status_code=303)

    @app.get("/site/checks")
    def checks_page(request: Request, ws: str = "main", study: str = "", done: str = "", err: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        checks: list[dict[str, Any]] = []
        fixes: list[dict[str, Any]] = []
        with contextlib.suppress(Problem, Unavailable):
            checks = list(get(f"/setup/{w}/checks"))
            fixes = list(get(f"/setup/{w}/fixes"))
        return h.page(
            request,
            "site_checks.html",
            sess,
            **ctx(sess, w, rs),
            open_checks=[c for c in checks if c["answer"] is None],
            answered=[c for c in checks if c["answer"] is not None],
            fixes=fixes,
            done=done[:20],
            err=err[:80],
        )

    @app.post("/site/checks/{cid}")
    async def checks_post(request: Request, cid: int) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        w, rs = ws_of(str(form.get("ws") or "")), study_of(sess, str(form.get("study") or ""))
        try:
            act_check(sess, w, cid, str(form.get("answer") or ""))
        except Problem as exc:
            return RedirectResponse(f"/site/checks?{q(w, rs, err=exc.code)}", status_code=303)
        return RedirectResponse(f"/site/checks?{q(w, rs, done='answered')}", status_code=303)

    @app.get("/site/sheets")
    def sheets_page(request: Request, ws: str = "main", study: str = "", done: str = "", err: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        inputs: list[dict[str, Any]] = []
        with contextlib.suppress(Problem, Unavailable):
            inputs = [i for i in get(f"/setup/{w}/inputs") if i["kind"] in ("sheet", "dump")]
        return h.page(
            request,
            "site_sheets.html",
            sess,
            **ctx(sess, w, rs),
            inputs=inputs,
            roles=ROLES,
            done=done[:20],
            err=err[:80],
        )

    @app.post("/site/sheets")
    async def sheets_post(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        w, rs = ws_of(str(form.get("ws") or "")), study_of(sess, str(form.get("study") or ""))
        try:
            need_change(sess, "/site/sheets")
            iid = str(form.get("input") or "")
            if iid.isdigit():  # new column roles for a sheet already in
                roles = {str(k)[5:]: str(v) for k, v in form.items() if str(k).startswith("role:") and v in ROLES}
                post(f"/setup/{w}/sheets/{iid}/roles", {"roles": roles, "by": h.actor(sess)})
            else:
                up = form.get("file")
                if up is None or isinstance(up, str) or not getattr(up, "filename", None):
                    return RedirectResponse(f"/site/sheets?{q(w, rs, err='SETUP-FILE')}", status_code=303)
                data = await up.read(MAX_UPLOAD + 1)
                kind = "dump" if str(form.get("kind") or "") == "dump" else "sheet"
                post(
                    f"/setup/{w}/sheets",
                    {
                        "kind": kind,
                        "name": str(up.filename)[:200],
                        "roles": {},
                        "b64": base64.b64encode(data).decode("ascii"),
                        "by": h.actor(sess),
                    },
                )
            au.append("console.site_sheet", actor=h.actor(sess), detail={"ws": w})
        except Problem as exc:
            return RedirectResponse(f"/site/sheets?{q(w, rs, err=exc.code)}", status_code=303)
        return RedirectResponse(f"/site/sheets?{q(w, rs, done='read')}", status_code=303)

    @app.get("/site/people")
    def people_page(request: Request, ws: str = "main", study: str = "", done: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        data: dict[str, Any] = {"people": [], "disagreements": []}
        with contextlib.suppress(Problem, Unavailable):
            data = dict(get(f"/setup/{w}/people"))
        return h.page(
            request,
            "site_people.html",
            sess,
            **ctx(sess, w, rs),
            people=data["people"][:300],
            disagreements=data["disagreements"],
            done=done[:20],
        )

    @app.post("/site/people/resolve")
    async def people_post(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        w, rs = ws_of(str(form.get("ws") or "")), study_of(sess, str(form.get("study") or ""))
        need_change(sess, request.url.path)
        body = {k: str(form.get(k) or "") for k in ("pid", "what", "keep")} | {"by": h.actor(sess)}
        try:
            post(f"/setup/{w}/people/resolve", body)
            au.append("console.site_resolve", actor=h.actor(sess), detail={"ws": w, "pid": body["pid"][:8]})
        except Problem:
            return RedirectResponse(f"/site/people?{q(w, rs, done='refused')}", status_code=303)
        return RedirectResponse(f"/site/people?{q(w, rs, done='resolved')}", status_code=303)

    @app.get("/site/patients")
    def patients_page(request: Request, ws: str = "main", study: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        out: dict[str, Any] = {"approved": False, "patients": []}
        if rs:
            with contextlib.suppress(Problem, Unavailable):
                out = dict(get(f"/setup/{w}/patients?study={quote(rs)}"))
        return h.page(request, "site_patients.html", sess, **ctx(sess, w, rs), out=out)

    @app.get("/site/help")
    def help_page(request: Request, ws: str = "main", study: str = "", done: str = "", err: str = "") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        w, rs = ws_of(ws), study_of(sess, study)
        remote: dict[str, Any] = {"on": False, "approved_by": "", "real_data": False}
        with contextlib.suppress(Problem, Unavailable):
            remote = dict(get("/setup/remote"))
        return h.page(
            request,
            "site_help.html",
            sess,
            **ctx(sess, w, rs),
            remote=remote,
            is_admin=sess.user.is_admin,
            done=done[:20],
            err=err[:80],
        )

    @app.post("/site/practice")
    async def practice_post(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        need_change(sess, request.url.path)
        rs = study_of(sess, str(form.get("study") or ""))
        action = "reset" if str(form.get("action") or "") == "reset" else "load"
        try:
            post(f"/setup/practice/{action}", {"by": h.actor(sess)})
        except (Problem, Unavailable):
            return RedirectResponse(f"/site/help?{q('main', rs, err='unavailable')}", status_code=303)
        au.append("console.site_practice", actor=h.actor(sess), detail={"action": action})
        if action == "reset":
            return RedirectResponse(f"/site/help?{q('main', rs, done='reset')}", status_code=303)
        return RedirectResponse(f"/site?{q('practice', rs)}", status_code=303)

    @app.post("/site/remote")
    async def remote_post(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            au.append("console.denied", actor=h.actor(sess), detail={"action": "remote help"})
            raise h.problem(403, "forbidden")
        on = str(form.get("on") or "") == "1"
        body = {"on": on, "approved_by": str(form.get("approved_by") or "")[:80], "by": h.actor(sess)}
        try:
            s28.call(bk, "PUT", "/setup/remote", body)
        except Problem as exc:
            return RedirectResponse(f"/site/help?{urlencode({'err': exc.code})}#remote", status_code=303)
        au.append("console.site_remote", actor=h.actor(sess), detail={"on": on})
        return RedirectResponse(f"/site/help?{urlencode({'done': 'remote'})}#remote", status_code=303)

    @app.get("/site/templates/{name}.xlsx")
    def template_file(request: Request, name: str, ws: str = "main") -> Response:
        sess = h.need(request)
        need_view(sess, request.url.path)
        if name not in ("candidates", "codes"):
            raise h.problem(404, "notfound")
        out = get(f"/setup/templates/{name}?lang={lang_of(sess)}&ws={ws_of(ws)}")
        au.append("console.export", actor=h.actor(sess), detail={"filename": str(out["name"])})
        return Response(
            base64.b64decode(out["b64"]),
            media_type=str(out["media_type"]),
            headers={"Content-Disposition": f'attachment; filename="{out["name"]}"'},
        )

    @app.get("/ask")
    def ask_page(request: Request, pid: str = "", ws: str = "main", study: str = "", back: str = "") -> Response:
        sess = h.need(request)
        question = str(request.query_params.get("q") or "")[:300]
        w, rs = ws_of(ws), study_of(sess, study)
        pid = pid.strip().lower()[:32]
        ans = assistant(sess, question, w, rs, pid) if (question or pid) else None
        safe_back = back if back.startswith("/") and not back.startswith("//") else "/home"
        return h.page(
            request, "ask.html", sess, **ctx(sess, w, rs), question=question, pid=pid, ans=ans, back=safe_back
        )

    # ------------------------------------------------------------------ /api/v1 (D-125, D-127)
    def api_session(request: Request) -> Session:
        assert h.api_session is not None, "console.home.register runs first"
        return h.api_session(request)

    def refused(exc: Exception) -> Response:
        if isinstance(exc, Unavailable):
            return JSONResponse({"error": "unavailable", "detail": {"detail": str(exc)[:200]}}, status_code=503)
        assert isinstance(exc, Problem)
        status = exc.status if 400 <= exc.status < 500 else 502
        return JSONResponse(
            {"error": "request.refused", "detail": {"code": exc.code, "reason": exc.message}}, status_code=status
        )

    @app.get("/api/v1/site/readiness", response_model=None)
    def api_readiness(request: Request, ws: str = "main", study: str = "") -> Any:
        sess = api_session(request)
        need_view(sess, request.url.path)
        mine = studies(sess)
        if not study.strip() and len(mine) > 1:  # D-146 (review J-16): never the readiness of a study it did not name
            return JSONResponse(
                {"error": "request.refused", "detail": {"code": "study-required", "studies": mine,
                 "reason": "give study=<id>: the readiness is per study and this account has several"}},
                status_code=400,
            )  # fmt: skip
        try:
            return get(f"/setup/{ws_of(ws)}/readiness?study={quote(study_of(sess, study))}")
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.get("/api/v1/site/facts", response_model=None)
    def api_facts(request: Request, ws: str = "main", status: str = "proposed") -> Any:
        sess = api_session(request)
        need_view(sess, request.url.path)
        try:
            return get(f"/setup/{ws_of(ws)}/facts?status={quote(status)}")
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.post("/api/v1/site/facts/{fid}", response_model=None)
    def api_fact(request: Request, fid: int, body: ApiDecide, ws: str = "main") -> Any:
        sess = api_session(request)
        try:
            return act_fact(sess, ws_of(ws), fid, body.action, dict(body.changes))
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.post("/api/v1/site/charts", response_model=None)
    def api_chart(request: Request, body: ApiChart, ws: str = "main") -> Any:
        sess = api_session(request)
        data = base64.b64decode(body.b64) if body.b64 else None
        try:
            return act_chart(sess, ws_of(ws), body.chart_no, body.text, body.name, data)
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.get("/api/v1/site/codes", response_model=None)
    def api_codes(request: Request, ws: str = "main") -> Any:
        sess = api_session(request)
        need_view(sess, request.url.path)
        try:
            return get(f"/setup/{ws_of(ws)}/codes")
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.post("/api/v1/site/codes", response_model=None)
    def api_code(request: Request, body: ApiMap, ws: str = "main") -> Any:
        sess = api_session(request)
        try:
            return act_code(sess, ws_of(ws), body.domain, body.system, body.code, body.target_code)
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.get("/api/v1/site/checks", response_model=None)
    def api_checks(request: Request, ws: str = "main") -> Any:
        sess = api_session(request)
        need_view(sess, request.url.path)
        try:
            return get(f"/setup/{ws_of(ws)}/checks")
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.post("/api/v1/site/checks/{cid}", response_model=None)
    def api_check(request: Request, cid: int, body: ApiAnswer, ws: str = "main") -> Any:
        sess = api_session(request)
        try:
            return act_check(sess, ws_of(ws), cid, body.answer)
        except (Problem, Unavailable) as exc:
            return refused(exc)

    @app.get("/api/v1/ask", response_model=None)
    def api_ask(request: Request, q: str = "", pid: str = "", ws: str = "main", study: str = "") -> Any:
        sess = api_session(request)
        return assistant(sess, q[:300], ws_of(ws), study_of(sess, study), pid.strip().lower()[:32])


def _args(m: dict[str, Any]) -> dict[str, Any]:
    return {k: m[k] for k in ("n", "rows", "pct", "of") if k in m}


def t_reason(lang: str, code: str) -> str:
    from tb_common.reasons import LABELS

    return (LABELS.get(code) or {}).get(lang) or code
