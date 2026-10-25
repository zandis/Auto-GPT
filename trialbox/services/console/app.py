"""TrialBox console: the admin control plane (spec v4 §3.8, ``services/console/app.py``) plus the pilot workspace.

Two route sets, decided at start-up:

* **Control plane** (always): sign-in, service health, the job list and the audit trail, metadata only, and the
  ``Operate`` action "ingest". This is the §3.8 surface; it renders no study content (FR-UX-21).
* **Pilot workspace** (``/pilot/...``): only with ``TB_CONSOLE_PILOT=1`` **and** ``TB_ENV`` DEV or TEST **and**
  ``TB_DATA_CLASS=D0``. It shows study content (attrition tables, the feasibility PDF/XLSX, the DL-1 pack, the
  recall certificate) of synthetic data, and lets an administrator start requests from the browser. It is not one of
  the five C-5′ product surfaces (FR-UX-12, §2.6 non-goals), so it can never be on in VALIDATION or PRODUCTION: the
  app refuses to start when asked to (fail closed), and ``tests/console`` prove that a production app has no
  ``/pilot`` route.

Nothing here is a side door. A browser request becomes the exact grammar line of the e-mail subject
(``console.proposals``) and the same ``JobCreate`` on the orchestrator's ``POST /jobs`` the mail gateway sends, so
permissions, rate limits, job audit and the delivery routing rule apply; results still go out by e-mail. The console
adds ``console.*`` events to the shared audit chain before it acts.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from tb_common.audit import AuditLog
from tb_common.crypto import sha256_bytes
from tb_common.ulid import new_ulid
from tb_contracts import Job, JobOutput

from console.auth import Session, UserStore, csrf_ok
from console.backend import Backend, MailItem, Refused, Unavailable
from console.cascade import CascadeRuns
from console.i18n import CATALOGUES, LANGS, pick_language, translate
from console.proposals import Classifier, Proposal, ProposalError, job_create, propose

HERE = Path(__file__).resolve().parent
COOKIE = "tb_console"
LOGIN_COOKIE = "tb_console_login"
TERMINAL = frozenset({"done", "failed", "cancelled"})
PILOT_ENVS = frozenset({"DEV", "TEST"})
DOC_EXT = (".pdf", ".docx", ".txt", ".md")
MAX_UPLOAD = 50 * 1024 * 1024
_RULESET_ID = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}$")
_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_VERSION = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
_FILE = re.compile(r"^[\w.\-]{1,160}$")
PROPOSAL_TTL = 3600.0
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'none'; object-src 'none'; "
    "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
)


class PilotRefused(RuntimeError):
    """The pilot workspace was requested where it may not run."""


_CLASS = re.compile(r"<td>(?:inclusion|exclusion)</td><td>(structured|note|human)</td>")


def _num(v: object) -> object:
    """1.0 -> 1 for counts of people; anything else unchanged."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


@dataclass(frozen=True)
class ConsoleSettings:
    environment: str
    pilot: bool
    data_class: str
    data_dir: Path
    admin_email: str
    admin_password_file: Path | None
    secure_cookie: bool
    test_smtp: str
    webmail_url: str
    intake_addr: str
    source_dir: Path | None
    samples_dir: Path | None
    gateway_url: str
    gateway_model: str | None
    small_cell: int
    trials: tuple[str, ...]

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ConsoleSettings:
        environment = (env.get("TB_ENV") or "PRODUCTION").upper()
        want_pilot = env.get("TB_CONSOLE_PILOT", "0").strip().lower() in ("1", "true", "yes")
        data_class = (env.get("TB_DATA_CLASS") or "").upper()
        if want_pilot and environment not in PILOT_ENVS:
            raise PilotRefused(
                f"TB_CONSOLE_PILOT=1 is refused in TB_ENV={environment}: the pilot workspace is not a product "
                f"surface (FR-UX-12) and runs only in DEV or TEST"
            )
        if want_pilot and data_class != "D0":
            raise PilotRefused(
                f"TB_CONSOLE_PILOT=1 needs TB_DATA_CLASS=D0 (synthetic or open data), got {data_class!r}"
            )
        pw = env.get("TB_CONSOLE_ADMIN_PASSWORD_FILE", "").strip()
        src = env.get("TB_CONSOLE_SOURCE_DIR", "").strip()
        samples = env.get("TB_CONSOLE_SAMPLES_DIR", "").strip()
        return cls(
            environment=environment,
            pilot=want_pilot,
            data_class=data_class or "-",
            data_dir=Path(env.get("TB_CONSOLE_DIR") or "/data/console"),
            admin_email=(env.get("TB_CONSOLE_ADMIN_EMAIL") or "").strip().lower(),
            admin_password_file=Path(pw) if pw else None,
            secure_cookie=env.get("TB_CONSOLE_SECURE_COOKIE", "0") in ("1", "true"),
            test_smtp=env.get("TB_CONSOLE_TEST_SMTP", "").strip(),
            webmail_url=env.get("TB_CONSOLE_WEBMAIL_URL", "").strip(),
            intake_addr=(env.get("MAIL_INTAKE_ADDR") or "trialbox@hospa.test").strip().lower(),
            source_dir=Path(src) if src else None,
            samples_dir=Path(samples) if samples else None,
            gateway_url=env.get("TB_GATEWAY_URL", "").strip(),
            gateway_model=env.get("TB_GATEWAY_MODEL") or None,
            small_cell=int(env.get("TB_CONSOLE_SMALL_CELL") or 5),
            trials=tuple(t for t in (env.get("TB_CONSOLE_TRIALS") or "GZQO").split(",") if t),
        )


class _LoginRequired(Exception):
    pass


class _Problem(Exception):
    def __init__(self, status: int, key: str, **values: object) -> None:
        super().__init__(key)
        self.status = status
        self.key = key
        self.values = values


@dataclass
class _Pending:
    proposal: Proposal
    session_sha: str
    created: float


def cell(value: object, k: int) -> str:
    """Display rule for counts: an integer between 1 and k-1 is shown as ``<k`` (defence in depth: the aggregate
    outputs are already suppressed by the producer)."""
    if isinstance(value, bool) or value is None:
        return "–" if value is None else str(value)
    if isinstance(value, int) and 0 < value < k:
        return f"<{k}"
    return str(value)


def job_line(job: Job) -> str:
    opts = dict(job.options or {})
    target = job.ruleset or opts.pop("target", "")
    opts.pop("target", None)
    return " ".join([job.type, target, *[f"{k}={v}" for k, v in sorted(opts.items())]]).strip()


def _env_map(env: Mapping[str, str] | None) -> dict[str, str]:
    return dict(env if env is not None else os.environ)


def _default_backend(settings: ConsoleSettings) -> tuple[Backend, AuditLog]:
    from tb_common.config import get_config
    from tb_common.objstore import from_config

    from console.backend import HttpBackend

    cfg = get_config()
    audit = AuditLog(cfg.env.audit_path, cfg.env.tz)
    return HttpBackend(cfg, from_config(), audit, gateway_url=settings.gateway_url, test_smtp=settings.test_smtp), audit


def create_app(
    env: Mapping[str, str] | None = None,
    *,
    backend: Backend | None = None,
    audit: AuditLog | None = None,
    users: UserStore | None = None,
    classify: Classifier | None = None,
    cascades: CascadeRuns | None = None,
) -> FastAPI:
    settings = ConsoleSettings.from_env(_env_map(env))
    if backend is None or audit is None:
        backend, audit = _default_backend(settings)
    users = users or UserStore(settings.data_dir / "console.sqlite")
    if settings.admin_password_file is not None:
        made = users.bootstrap_from_file(settings.admin_password_file, mailbox=settings.admin_email or None)
        if made is not None:
            audit.append("console.user", actor="console:bootstrap", detail={"action": "create", "role": "admin"})
    if settings.pilot and classify is None and settings.gateway_url:
        from console.proposals import gateway_classifier

        classify = gateway_classifier(settings.gateway_url, settings.gateway_model, "D0", date.today)
    if settings.pilot and cascades is None:
        cascades = CascadeRuns(settings.data_dir / "cascade", settings.source_dir)
    pending: dict[str, _Pending] = {}
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    bk: Backend = backend
    au: AuditLog = audit
    us: UserStore = users

    app = FastAPI(title="trialbox-console", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.state.settings = settings

    # ------------------------------------------------------------------ plumbing
    @app.middleware("http")
    async def headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def session_of(request: Request) -> Session | None:
        return us.session(request.cookies.get(COOKIE))

    def need(request: Request) -> Session:
        sess = session_of(request)
        if sess is None:
            raise _LoginRequired()
        return sess

    def need_admin(request: Request, csrf: str) -> Session:
        sess = need(request)
        if not csrf_ok(sess, csrf):
            raise _Problem(400, "csrf")
        if not sess.user.is_admin:
            au.append("console.denied", actor=f"console:{sess.user.username}", detail={"action": request.url.path[:80]})
            raise _Problem(403, "forbidden")
        return sess

    def lang_of(request: Request, sess: Session | None) -> str:
        if sess is not None and sess.lang in LANGS:
            return sess.lang
        return pick_language(request.headers.get("accept-language"))

    def page(request: Request, name: str, sess: Session | None, status: int = 200, **ctx: Any) -> HTMLResponse:
        lang = lang_of(request, sess)

        def t(key: str, **values: object) -> str:
            return translate(lang, key, **values)

        def state(value: str) -> str:  # badge text; the machine state stays in data-state
            key = f"state.{value}"
            text = t(key)
            return value if text == key else text

        base = {
            "t": t,
            "lang": lang,
            "langs": LANGS,
            "sess": sess,
            "user": sess.user if sess else None,
            "csrf": sess.csrf if sess else "",
            "settings": settings,
            "pilot": settings.pilot,
            "path": request.url.path,
            "k": settings.small_cell,
            "cell": lambda v: cell(v, settings.small_cell),
            "state": state,
            "num": _num,
        }
        return templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status)

    @app.exception_handler(_LoginRequired)
    async def _to_login(request: Request, _exc: _LoginRequired) -> Response:
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(_Problem)
    async def _problem(request: Request, exc: _Problem) -> Response:
        sess = session_of(request)
        return page(request, "problem.html", sess, status=exc.status, key=exc.key, values=exc.values)

    @app.exception_handler(Unavailable)
    async def _unavailable(request: Request, exc: Unavailable) -> Response:
        sess = session_of(request)
        return page(request, "problem.html", sess, status=503, key="unavailable", values={"detail": str(exc)[:300]})

    def actor(sess: Session) -> str:
        return f"console:{sess.user.username}"

    def submit(sess: Session, line: str, files: list[tuple[str, bytes, str]] | None = None) -> Job:
        """Audit, store the inputs, then the same ``POST /jobs`` the mail gateway makes."""
        mailbox = sess.user.mailbox or settings.admin_email
        if not mailbox:
            raise _Problem(400, "request.refused", reason="this account has no mailbox (console.cli set-mailbox)")
        job_id = new_ulid()
        inputs = [bk.put_input(job_id, name, data, ctype) for name, data, ctype in files or []]
        try:
            req = job_create(line, mailbox, job_id, f"web console ({sess.user.username})", inputs)
        except ProposalError as exc:
            raise _Problem(400, "request.refused", reason=str(exc)) from exc
        au.append(
            "console.request",
            job_id=job_id,
            ruleset=req.ruleset,
            actor=actor(sess),
            input_sha=",".join(f.sha256 for f in inputs) or None,
            detail={"line": line, "mailbox": mailbox, "role": sess.user.role, "channel": "web"},
        )
        try:
            return bk.create_job(req)
        except Refused as exc:
            au.append("console.refused", job_id=job_id, actor=actor(sess), detail={"reason": str(exc)[:200]})
            raise _Problem(403, "request.refused", reason=str(exc)) from exc

    def need_pilot() -> None:
        if not settings.pilot:
            raise _Problem(404, "notfound")

    # ------------------------------------------------------------------ control plane
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": "console", "pilot": settings.pilot, "env": settings.environment}

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> Response:
        token = secrets.token_urlsafe(24)
        resp = page(request, "login.html", None, login_csrf=token, failed=False, uninitialised=us.count("admin") == 0)
        resp.set_cookie(
            LOGIN_COOKIE, token, httponly=True, samesite="strict", secure=settings.secure_cookie, max_age=900
        )
        return resp

    @app.post("/login")
    def login(
        request: Request, username: str = Form(""), password: str = Form(""), login_csrf: str = Form("")
    ) -> Response:
        cookie = request.cookies.get(LOGIN_COOKIE, "")
        if not cookie or not secrets.compare_digest(cookie, login_csrf):
            raise _Problem(400, "csrf")
        user = us.authenticate(username[:64], password[:256])
        if user is None:
            au.append("console.login_failed", actor=f"console:{username.strip().lower()[:32] or '-'}")
            token = secrets.token_urlsafe(24)
            resp = page(request, "login.html", None, 401, login_csrf=token, failed=True, uninitialised=False)
            resp.set_cookie(
                LOGIN_COOKIE, token, httponly=True, samesite="strict", secure=settings.secure_cookie, max_age=900
            )
            return resp
        token, _ = us.new_session(user, pick_language(request.headers.get("accept-language")))
        au.append("console.login", actor=f"console:{user.username}", detail={"role": user.role})
        done = RedirectResponse("/", status_code=303)
        done.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=settings.secure_cookie)
        done.delete_cookie(LOGIN_COOKIE)
        return done

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form("")) -> Response:
        sess = need(request)
        if not csrf_ok(sess, csrf):
            raise _Problem(400, "csrf")
        us.end_session(request.cookies.get(COOKIE, ""))
        au.append("console.logout", actor=actor(sess))
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.post("/lang")
    def set_lang(request: Request, lang: str = Form("en"), csrf: str = Form(""), back: str = Form("/")) -> Response:
        sess = need(request)
        if not csrf_ok(sess, csrf):
            raise _Problem(400, "csrf")
        if lang in CATALOGUES:
            us.set_lang(sess, lang)
        target = back if back.startswith("/") and not back.startswith("//") else "/"
        return RedirectResponse(target, status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, notice: str = "") -> Response:
        sess = need(request)
        jobs = bk.list_jobs(limit=8)
        return page(
            request,
            "overview.html",
            sess,
            health=bk.health(),
            rulesets=bk.rulesets() if settings.pilot else [],
            jobs=jobs,
            notice=notice if notice in ("ingested",) else "",
        )

    @app.post("/ops/ingest")
    def ingest(request: Request, csrf: str = Form("")) -> Response:
        sess = need_admin(request, csrf)
        au.append("console.operate", actor=actor(sess), detail={"action": "ingest"})
        report = bk.ingest()
        au.append(
            "console.operate",
            actor=actor(sess),
            detail={"action": "ingest.done", "reason": "passed" if report.get("passed") else "not passed"},
        )
        return RedirectResponse("/?notice=ingested", status_code=303)

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request) -> Response:
        sess = need(request)
        items = bk.list_jobs(limit=100)
        running = any(j.state not in TERMINAL and j.state != "awaiting_approval" for j in items)
        return page(request, "jobs.html", sess, jobs=items, refresh=running)

    @app.get("/audit", response_class=HTMLResponse)
    def audit_view(request: Request) -> Response:
        sess = need(request)
        return page(request, "audit.html", sess, records=bk.audit(None, 300))

    # ------------------------------------------------------------------ pilot workspace
    if not settings.pilot:
        return app

    def _job_or_404(job_id: str) -> Job:
        if not _ULID.match(job_id):
            raise _Problem(404, "notfound")
        job = bk.get_job(job_id)
        if job is None:
            raise _Problem(404, "notfound")
        return job

    def _feas_result(job: Job) -> dict[str, Any] | None:
        import json

        for o in job.outputs or []:
            if o.tag == "aggregate" and o.filename.startswith("feasibility_") and o.filename.endswith(".json"):
                try:
                    data: dict[str, Any] = json.loads(bk.get_object(o.minio_key))
                except (KeyError, ValueError, OSError):
                    return None
                return data
        return None

    def _review_book(job: Job) -> JobOutput | None:
        books = [o for o in job.outputs or [] if o.filename.startswith("review_") and o.filename.endswith(".xlsx")]
        return sorted(books, key=lambda o: o.filename)[-1] if books else None

    def _check_split(review_html: JobOutput | None) -> dict[str, int] | None:
        """How many criteria the filter, the model on notes, and a person check (the review table's class column)."""
        if review_html is None:
            return None
        try:
            found = _CLASS.findall(bk.get_object(review_html.minio_key).decode("utf-8", "replace"))
        except (KeyError, OSError):
            return None
        if not found:
            return None
        return {"n": len(found), "s": found.count("structured"), "m": found.count("note"), "h": found.count("human")}

    @app.get("/pilot/jobs/{job_id}", response_class=HTMLResponse)
    def job_view(request: Request, job_id: str) -> Response:
        sess = need(request)
        job = _job_or_404(job_id)
        review_html = next(
            (o for o in job.outputs or [] if o.filename.startswith("review_") and o.filename.endswith(".html")), None
        )
        audit_recs = bk.audit(job_id, 200)
        subjects = [str(r.detail.get("subject", "")) for r in audit_recs if r.event == "mail.received"]
        thread = bk.thread(job_id)
        thread_rows: list[tuple[MailItem | None, str]] = [
            (m, m.subject or (subjects[0] if m.direction == "in" and subjects else "")) for m in thread
        ]
        if not any(m.direction == "in" for m in thread) and any(r.event == "console.request" for r in audit_recs):
            web = next(r for r in audit_recs if r.event == "console.request")
            thread_rows.insert(0, (None, str(web.detail.get("line", ""))))
        return page(
            request,
            "job.html",
            sess,
            job=job,
            line=job_line(job),
            result=_feas_result(job),
            aggregate=[o for o in job.outputs or [] if o.tag == "aggregate"],
            phi=[o for o in job.outputs or [] if o.tag == "phi"],
            review=_review_book(job) if job.state == "awaiting_approval" else None,
            review_html=review_html,
            split=_check_split(review_html) if job.state == "awaiting_approval" else None,
            thread=thread_rows,
            audit=sorted(audit_recs, key=lambda r: r.ts),
            refresh=job.state not in TERMINAL and job.state != "awaiting_approval",
            rulesets=[r for r in bk.rulesets() if r.status == "approved"],
        )

    @app.get("/pilot/jobs/{job_id}/files/{filename}")
    def job_file(request: Request, job_id: str, filename: str) -> Response:
        sess = need(request)
        job = _job_or_404(job_id)
        if not _FILE.match(filename):
            raise _Problem(404, "notfound")
        out = next((o for o in job.outputs or [] if o.filename == filename), None)
        if out is None or out.tag != "aggregate":  # patient-level files never leave by the browser
            raise _Problem(404, "notfound")
        data = bk.get_object(out.minio_key)
        au.append(
            "console.download",
            job_id=job_id,
            actor=actor(sess),
            output_sha=sha256_bytes(data),
            detail={"filename": filename, "tag": out.tag},
        )
        ctype = {
            ".pdf": "application/pdf",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".json": "application/json",
            ".html": "text/html; charset=utf-8",
            ".zip": "application/zip",
            ".yaml": "text/plain; charset=utf-8",
        }.get(Path(filename).suffix.lower(), "application/octet-stream")
        return Response(
            data,
            media_type=ctype,
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Download-Options": "noopen"},
        )

    @app.post("/pilot/jobs/{job_id}/approve")
    async def approve(
        request: Request, job_id: str, csrf: str = Form(""), workbook: Annotated[UploadFile | None, File()] = None
    ) -> Response:
        sess = need_admin(request, csrf)
        job = _job_or_404(job_id)
        book = _review_book(job)
        if job.state != "awaiting_approval" or book is None or not job.ruleset or not job.ruleset_version:
            raise _Problem(409, "request.refused", reason="this job is not waiting for approval")
        if workbook is not None and workbook.filename:
            data = await workbook.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD or not workbook.filename.lower().endswith(".xlsx"):
                raise _Problem(400, "request.refused", reason="upload the review workbook (.xlsx, at most 50 MB)")
        else:
            data = bk.get_object(book.minio_key)
        ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        new = submit(sess, f"APPROVE {job.ruleset} version={job.ruleset_version}", [("review.xlsx", data, ctype)])
        return RedirectResponse(f"/pilot/jobs/{new.job_id}", status_code=303)

    def _request_page(request: Request, sess: Session, status: int = 200, **ctx: Any) -> HTMLResponse:
        approved = [r for r in bk.rulesets() if r.status == "approved"]
        return page(request, "request.html", sess, status, rulesets=approved, **ctx)

    @app.get("/pilot/request", response_class=HTMLResponse)
    def request_form(request: Request, ruleset: str = "") -> Response:
        sess = need(request)
        return _request_page(request, sess, selected=ruleset)

    @app.post("/pilot/request")
    def request_run(
        request: Request,
        csrf: str = Form(""),
        kind: str = Form("FEAS"),
        ruleset: str = Form(""),
        lookback: str = Form(""),
        version: str = Form(""),
    ) -> Response:
        sess = need_admin(request, csrf)
        rs = ruleset.strip().upper()
        if kind not in ("FEAS", "SCREEN") or not _RULESET_ID.match(rs):
            raise _Problem(400, "request.refused", reason="choose FEAS or SCREEN and an approved ruleset")
        parts = [kind, rs]
        if kind == "FEAS" and lookback.strip():
            # checked here so the form says what to fix, instead of a job that fails a step later
            lb = lookback.strip()
            if not lb.isdigit() or not 1 <= int(lb) <= 120:
                msg = translate(lang_of(request, sess), "request.lookback.range")
                return _request_page(request, sess, 422, error=msg, selected=rs)
            parts.append(f"lookback={int(lb)}")
        if kind == "SCREEN" and not version.strip():  # the form lists approved rulesets only: run that version
            version = next((r.version or "" for r in bk.rulesets() if r.id == rs and r.status == "approved"), "")
        if version.strip():
            if not _VERSION.match(version.strip()):
                raise _Problem(400, "request.refused", reason="version is x.y.z")
            parts.append(f"version={version.strip()}")
        job = submit(sess, " ".join(parts))
        return RedirectResponse(f"/pilot/jobs/{job.job_id}", status_code=303)

    @app.post("/pilot/propose", response_class=HTMLResponse)
    def propose_view(request: Request, csrf: str = Form(""), text: str = Form("")) -> Response:
        sess = need_admin(request, csrf)
        from channels.native.engine import detect_language

        lang = detect_language(text)
        au.append(
            "console.proposal",
            actor=actor(sess),
            input_sha=sha256_bytes(text.encode("utf-8")),
            detail={"action": "propose", "role": sess.user.role},
        )
        try:
            prop = propose(text, "en" if lang == "mixed" else lang, classify)
        except ProposalError as exc:
            return _request_page(request, sess, 422, error=str(exc))
        now = time.time()
        for pid in [p for p, v in pending.items() if now - v.created > PROPOSAL_TTL]:
            pending.pop(pid, None)
        pid = secrets.token_urlsafe(12)
        pending[pid] = _Pending(prop, sess.token_sha, now)
        au.append("console.proposal", actor=actor(sess), detail={"action": "proposed", "line": prop.line})
        return _request_page(request, sess, proposal=prop, proposal_id=pid)

    @app.post("/pilot/propose/{pid}/confirm")
    def propose_confirm(request: Request, pid: str, csrf: str = Form("")) -> Response:
        sess = need_admin(request, csrf)
        item = pending.get(pid)
        if item is None or item.session_sha != sess.token_sha or time.time() - item.created > PROPOSAL_TTL:
            raise _Problem(410, "request.refused", reason="the proposal expired; propose again")
        pending.pop(pid, None)
        job = submit(sess, item.proposal.line)
        return RedirectResponse(f"/pilot/jobs/{job.job_id}", status_code=303)

    @app.get("/pilot/protocol", response_class=HTMLResponse)
    def protocol_form(request: Request) -> Response:
        sess = need(request)
        return page(request, "protocol.html", sess, sample=_sample() is not None)

    def _sample() -> Path | None:
        if settings.samples_dir is None:
            return None
        p = settings.samples_dir / "GZQO_protocol_v3.pdf"
        return p if p.is_file() else None

    @app.post("/pilot/protocol")
    async def protocol_submit(
        request: Request,
        csrf: str = Form(""),
        ruleset: str = Form(""),
        use_sample: str = Form(""),
        protocol: Annotated[UploadFile | None, File()] = None,
    ) -> Response:
        sess = need_admin(request, csrf)
        rs = ruleset.strip().upper()
        if not _RULESET_ID.match(rs):
            raise _Problem(400, "request.refused", reason="ruleset ids are 1-16 letters, digits, '-' or '_'")
        sample = _sample()
        if protocol is not None and protocol.filename:
            name = re.sub(r"[^\w.\-]+", "_", protocol.filename)[-120:]
            data = await protocol.read(MAX_UPLOAD + 1)
            ctype = protocol.content_type or "application/octet-stream"
        elif use_sample and sample is not None:
            name, data, ctype = sample.name, sample.read_bytes(), "application/pdf"
        else:
            raise _Problem(400, "request.refused", reason="attach a protocol file")
        if not data:
            msg = translate(lang_of(request, sess), "protocol.empty")
            return page(request, "protocol.html", sess, 422, sample=sample is not None, error=msg)
        if len(data) > MAX_UPLOAD or not name.lower().endswith(DOC_EXT):
            raise _Problem(400, "request.refused", reason="protocols are PDF, DOCX, TXT or MD, at most 50 MB")
        job = submit(sess, f"FEAS {rs}", [(name, data, ctype)])
        return RedirectResponse(f"/pilot/jobs/{job.job_id}", status_code=303)

    cr: CascadeRuns | None = cascades

    def _runs() -> CascadeRuns:
        if cr is None:
            raise _Problem(404, "notfound")
        return cr

    @app.get("/pilot/cascade", response_class=HTMLResponse)
    def cascade_view(request: Request) -> Response:
        sess = need(request)
        runs = _runs()
        items = runs.list()
        return page(
            request,
            "cascade.html",
            sess,
            runs=items,
            available=runs.available,
            trials=settings.trials,
            refresh=any(r.state == "running" for r in items),
        )

    @app.post("/pilot/cascade")
    def cascade_start(request: Request, csrf: str = Form(""), trial: str = Form("GZQO")) -> Response:
        sess = need_admin(request, csrf)
        runs = _runs()
        if trial not in settings.trials:
            raise _Problem(400, "request.refused", reason="unknown trial")
        au.append("console.cascade", actor=actor(sess), ruleset=trial, detail={"action": "start"})

        def done(run: Any) -> None:
            au.append(
                "console.cascade",
                actor=actor(sess),
                ruleset=trial,
                detail={"action": run.state, "run": run.run_id},
            )

        try:
            run = runs.start(trial, sess.user.username, done)
        except RuntimeError as exc:
            raise _Problem(409, "request.refused", reason=str(exc)) from exc
        return RedirectResponse(f"/pilot/cascade/{run.run_id}", status_code=303)

    @app.get("/pilot/cascade/{run_id}", response_class=HTMLResponse)
    def cascade_run(request: Request, run_id: str) -> Response:
        sess = need(request)
        runs = _runs()
        run = runs.get(run_id)
        if run is None:
            raise _Problem(404, "notfound")
        files = [n for n in ("dl1_pdf", "dl1_xlsx", "dl1_json", "recall_certificate") if runs.file(run, n)]
        return page(
            request,
            "cascade_run.html",
            sess,
            run=run,
            summary=runs.summary(run) if run.state != "running" else {},
            files=files,
            refresh=run.state == "running",
        )

    @app.get("/pilot/cascade/{run_id}/files/{name}")
    def cascade_file(request: Request, run_id: str, name: str) -> Response:
        sess = need(request)
        runs = _runs()
        run = runs.get(run_id)
        path = runs.file(run, name) if run is not None else None
        if run is None or path is None:
            raise _Problem(404, "notfound")
        data = path.read_bytes()
        au.append(
            "console.download",
            actor=actor(sess),
            ruleset=run.trial,
            output_sha=sha256_bytes(data),
            detail={"filename": path.name, "tag": "D1", "run": run.run_id},
        )
        media = {".pdf": "application/pdf", ".json": "application/json"}.get(path.suffix, "application/octet-stream")
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})

    @app.get("/pilot/mailbox", response_class=HTMLResponse)
    def mailbox_form(request: Request) -> Response:
        sess = need(request)
        if not settings.test_smtp:
            raise _Problem(404, "notfound")
        return page(request, "mailbox.html", sess, sent="", subject="FEAS GZQO")

    @app.post("/pilot/mailbox", response_class=HTMLResponse)
    async def mailbox_send(
        request: Request,
        csrf: str = Form(""),
        subject: str = Form(""),
        body: str = Form(""),
        attachment: Annotated[UploadFile | None, File()] = None,
    ) -> Response:
        sess = need_admin(request, csrf)
        if not settings.test_smtp:
            raise _Problem(404, "notfound")
        sender = sess.user.mailbox or settings.admin_email
        files: list[tuple[str, bytes]] = []
        if attachment is not None and attachment.filename:
            data = await attachment.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise _Problem(400, "request.refused", reason="attachments are at most 50 MB")
            files.append((re.sub(r"[^\w.\-]+", "_", attachment.filename)[-120:], data))
        subject = " ".join(subject.split())[:200]  # one header line: CR/LF would make the mail unbuildable
        mid = bk.send_test_mail(sender, settings.intake_addr, subject, body[:5000], files)
        au.append("console.testmail", actor=actor(sess), detail={"subject": subject, "action": "send"})
        return page(request, "mailbox.html", sess, sent=mid, subject=subject)

    return app
