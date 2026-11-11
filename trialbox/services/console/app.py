"""TrialBox console: the admin control plane (spec v4 §3.8, ``services/console/app.py``) plus the clinical workspace.

Two route sets, decided at start-up:

* **Control plane** (always): sign-in, service health, the job list and the audit trail, metadata only, and the
  ``Operate`` action "ingest". This is the §3.8 surface; it renders no study content (FR-UX-21).
* **Workspace** (``/pilot/...``, the path name is historical): the clinical product (D-127, review F-01): the PI
  and CRC lists, marks, approval, the screening log, the REDCap link, reports and requests from the browser. On in
  every environment unless ``TB_CONSOLE_WORKSPACE=off`` (the old ``TB_CONSOLE_PILOT=0`` still works), which leaves
  the control plane alone. Real patient data still waits for the owner's gates (the ethics gate, the data class).

Nothing here is a side door. A browser request becomes the exact grammar line of the e-mail subject
(``console.proposals``) and the same ``JobCreate`` on the orchestrator's ``POST /jobs`` the mail gateway sends, so
permissions, rate limits, job audit and the delivery routing rule apply; results still go out by e-mail. The console
adds ``console.*`` events to the shared audit chain before it acts.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import io
import ipaddress
import os
import re
import secrets
import time
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.exceptions import HTTPException as StarletteHTTPException
from tb_common.audit import ID_IN_TEXT, ID_KEYS, AuditLog, mask_ids
from tb_common.audit_writer import open_audit
from tb_common.authz import BEST_STANDING, admin_allowed, permit, role_rights
from tb_common.config import environment_name
from tb_common.crypto import sha256_bytes
from tb_common.feas_notes import notes_for as feas_notes
from tb_common.flowledger import level_of_tag, record_export
from tb_common.reasons import label as reason_label
from tb_common.service_auth import bind_session
from tb_common.ulid import new_ulid
from tb_contracts import Job, JobOutput, RegistryPromote, RegistryUpdate

from console import demo_guard, feedback, i18n_roles
from console.admin_accounts import end_date
from console.auth import (
    AFFILIATIONS,
    ROLES,
    AuthError,
    Session,
    User,
    UserStore,
    csrf_ok,
    random_password,
    scope_values,
)
from console.backend import AuditRecord, Backend, MailItem, Refused, RulesetInfo, Unavailable
from console.cascade import CascadeRuns
from console.i18n import CATALOGUES, LANGS, pick_language, translate
from console.identity import (
    MUST_CHANGE_OPEN,
    Hooks,
    Identity,
    IdentitySettings,
    client_source,
    secure_cookie_default,
)
from console.identity import register as register_identity
from console.proposals import Classifier, Proposal, ProposalError, job_create, propose
from console.refusals import localize as localize_refusal
from console.registry_view import RECORDED_ELSEWHERE, STATUSES, status_options
from console.timefmt import local_time, local_today, site_zone

HERE = Path(__file__).resolve().parent
COOKIE = "tb_console"
LOGIN_COOKIE = "tb_console_login"
LANG_COOKIE = "tb_console_lang"  # D-133: the language picked on the sign-in page (a preference, not a secret)
AUDIT_PAGE, AUDIT_PAGES = 50, 20  # D-133: the audit trail page by page (the newest 1,000 events)
TERMINAL = frozenset({"done", "failed", "cancelled"})
DOC_EXT = (".pdf", ".docx", ".txt", ".md")
MAX_UPLOAD = 50 * 1024 * 1024
_RULESET_ID = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}$")
_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_VERSION = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
_FILE = re.compile(r"^[\w.\-]{1,160}$")
_ITEM_IDS = re.compile(r"^(?:I\d{2}|Q\d)(?:,(?:I\d{2}|Q\d))*$")
PROPOSAL_TTL = 3600.0
# D-133: one small first-party script (copy the one-time password, warn before leaving a form with unsaved edits),
# inlined on every page and allowed by its SHA-256 hash only: no other script, inline or from any origin, runs. Every
# page works without it (a progressive enhancement).
CONSOLE_JS = (HERE / "static" / "console.js").read_text(encoding="utf-8").strip()
_JS_HASH = base64.b64encode(hashlib.sha256(CONSOLE_JS.encode("utf-8")).digest()).decode("ascii")
CSP = (
    f"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'sha256-{_JS_HASH}'; "
    "object-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
)
_ASCII_WORDS = re.compile(r"[\x00-\x7F]+")


class PilotRefused(RuntimeError):
    """The pilot workspace was requested where it may not run."""


_CLASS = re.compile(r"<td>(?:inclusion|exclusion)</td><td>(structured|note|human|mixed)</td>")


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
    consent_sample: Path | None
    gateway_url: str
    gateway_model: str | None
    small_cell: int
    trials: tuple[str, ...]
    # D-93: sign-in by the hospital's identity provider through a reverse proxy that sets a trusted header
    sso_header: str = ""
    sso_role_header: str = ""
    sso_mailbox_header: str = ""
    sso_trusted: tuple[str, ...] = ()
    sso_role_map: tuple[tuple[str, str], ...] = ()
    sso_default_role: str = "viewer"
    # D-120: where the box's records come from ("synthetic" or "public": a public-data site), for the banner
    data_source: str = "synthetic"
    # D-120: the studies this site runs (TB_CONSOLE_STUDIES); the request menu lists only these. Empty: every
    # approved study
    studies: tuple[str, ...] = ()
    # D-192: the second factor, session timeouts and the optional OIDC sign-in (console.identity)
    identity: IdentitySettings = field(default_factory=IdentitySettings)

    @property
    def sso(self) -> bool:
        return bool(self.sso_header and self.sso_trusted)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ConsoleSettings:
        environment = environment_name(env)
        # D-127 (review F-01): the clinical workspace (PI/CRC lists, marks, approval, screening log, REDCap link) is
        # the product, on in every environment. TB_CONSOLE_WORKSPACE=off (or the old TB_CONSOLE_PILOT=0) leaves the
        # admin plane only. Real patient data still waits for the owner's gates (ethics gate, data class).
        raw = env.get("TB_CONSOLE_WORKSPACE") or env.get("TB_CONSOLE_PILOT") or "on"
        want_pilot = raw.strip().lower() not in ("0", "off", "false", "no")
        data_class = (env.get("TB_DATA_CLASS") or "").upper()
        pw = env.get("TB_CONSOLE_ADMIN_PASSWORD_FILE", "").strip()
        src = env.get("TB_CONSOLE_SOURCE_DIR", "").strip()
        samples = env.get("TB_CONSOLE_SAMPLES_DIR", "").strip()
        obj = cls(
            environment=environment,
            pilot=want_pilot,
            data_class=data_class or "-",
            data_dir=Path(env.get("TB_CONSOLE_DIR") or "/data/console"),
            admin_email=(env.get("TB_CONSOLE_ADMIN_EMAIL") or "").strip().lower(),
            admin_password_file=Path(pw) if pw else None,
            secure_cookie=secure_cookie_default(env, environment),  # D-192: on by default in PRODUCTION
            test_smtp=env.get("TB_CONSOLE_TEST_SMTP", "").strip(),
            webmail_url=env.get("TB_CONSOLE_WEBMAIL_URL", "").strip(),
            intake_addr=(env.get("MAIL_INTAKE_ADDR") or "trialbox@hospa.test").strip().lower(),
            source_dir=Path(src) if src else None,
            samples_dir=Path(samples) if samples else None,
            consent_sample=Path(env["TB_CONSOLE_CONSENT_SAMPLE"]) if env.get("TB_CONSOLE_CONSENT_SAMPLE") else None,
            gateway_url=env.get("TB_GATEWAY_URL", "").strip(),
            gateway_model=env.get("TB_GATEWAY_MODEL") or None,
            small_cell=int(env.get("TB_CONSOLE_SMALL_CELL") or 5),
            trials=tuple(t for t in (env.get("TB_CONSOLE_TRIALS") or "GZQO").split(",") if t),
            sso_header=env.get("TB_CONSOLE_SSO_HEADER", "").strip().lower(),
            sso_role_header=env.get("TB_CONSOLE_SSO_ROLE_HEADER", "").strip().lower(),
            sso_mailbox_header=env.get("TB_CONSOLE_SSO_MAILBOX_HEADER", "").strip().lower(),
            sso_trusted=tuple(x.strip() for x in env.get("TB_CONSOLE_SSO_TRUSTED_PROXIES", "").split(",") if x.strip()),
            sso_role_map=tuple(
                (k.strip().lower(), v.strip().lower())
                for k, _, v in (item.partition(":") for item in env.get("TB_CONSOLE_SSO_ROLE_MAP", "").split(","))
                if k.strip() and v.strip().lower() in ROLES
            ),
            sso_default_role=(env.get("TB_CONSOLE_SSO_DEFAULT_ROLE") or "viewer").strip().lower(),
            data_source=(
                "public" if (env.get("TB_CONSOLE_DATA_SOURCE") or "").strip().lower() == "public" else "synthetic"
            ),
            studies=tuple(x.strip().upper() for x in (env.get("TB_CONSOLE_STUDIES") or "").split(",") if x.strip()),
            identity=IdentitySettings.from_env(env, environment, Path(env.get("TB_CONSOLE_DIR") or "/data/console")),
        )
        if obj.sso_header and not obj.sso_trusted:
            raise PilotRefused("TB_CONSOLE_SSO_HEADER needs TB_CONSOLE_SSO_TRUSTED_PROXIES (the proxy addresses)")
        if obj.sso_default_role not in ROLES:
            raise PilotRefused(f"TB_CONSOLE_SSO_DEFAULT_ROLE must be one of {', '.join(ROLES)}")
        if obj.sso_header and (obj.identity.totp_required or obj.identity.oidc.enabled):
            # D-192 review H1: a trusted header skips the password and the second factor. It is allowed only where
            # TOTP is off (DEV and TEST); a hospital uses the OIDC sign-in through Authelia instead.
            raise PilotRefused(
                "TB_CONSOLE_SSO_HEADER works only with TB_CONSOLE_MFA=off (DEV or TEST) and OIDC off; "
                "use TB_OIDC_ENABLED (Authelia) for the hospital account"
            )
        return obj


class _LoginRequired(Exception):
    pass


class _MustChange(Exception):
    """A page asked by an account whose password someone else set (D-279): it goes to /account first."""


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


# options that identify a patient: never shown on a page (UX review 2026-11-08, F-01: the CASE job line printed the
# chart number in clear to every role that could open the job)
# D-146 (review J-03/J-04/J-05): the paths an aggregate-only account (viewer, CRO) is refused, pages and /api/v1 alike;
# job pages are decided by the job's type (see create_app._aggregate_denied)
_AGGREGATE_DENY = re.compile(
    r"^/(?:jobs|audit|admin/redcap|pilot/registry|pilot/mailbox|pilot/cascade|site|api/v1/site)(?:/|$)"
    r"|^/(?:api/v1/)?studies/[^/]+/(?!feasibility$|monitor/)"
)
# D-380 (FIT-002 grant half): the one patient-level route a CRO account may reach, under a monitor grant (team.py)
_MONITOR_ROUTE = re.compile(r"/(?:api/v1/)?studies/[A-Za-z0-9_-]+/monitor/[A-Za-z0-9_-]+")
for _lang, _cat in (("en", i18n_roles.EN), ("ja", i18n_roles.JA), ("zh-TW", i18n_roles.ZH)):
    CATALOGUES[_lang].update(_cat)


def role_description(role: str, lang: str) -> str:
    """ROLE-018 (D-380): what a role may do, generated from the matrix (``tb_common.authz.role_rights``): one label
    per row or group of rows, marked where it holds only as the study's delegation log allows."""
    seen: dict[str, bool] = {}
    for action, _what, conditional in role_rights(role):
        key = i18n_roles.right_key(action)
        seen[key] = seen.get(key, True) and conditional
    if not seen:
        return translate(lang, "roles.none")
    parts = [translate(lang, k) for k in seen]
    return "; ".join(translate(lang, "roles.cond", what=p) if seen[k] else p for k, p in zip(seen, parts, strict=True))


_PSEUDONYM = re.compile(r"\b[0-9a-f]{32}\b")
_PID_KEYS = frozenset({"pid", "pids"})


def hide_pids(records: list[AuditRecord]) -> list[AuditRecord]:
    """D-380 (CR-023): the audit trail for a reader without ``audit.ids`` (the administrator): every pseudonym in an
    event's detail is hidden, the event itself stays."""

    def one(k: str, v: Any) -> Any:
        if k in _PID_KEYS:
            return "•••"
        return _PSEUDONYM.sub("•••", v) if isinstance(v, str) else v

    return [dataclasses.replace(r, detail={k: one(k, v) for k, v in dict(r.detail or {}).items()}) for r in records]


# D-272 (CR-016): one rule for the job line, the pages and the audit's stored form (``tb_common.audit``): ``mask_ids``
# turns ``CASE GZQO mrn=70000054`` into ``CASE GZQO mrn=•••`` and masks the same keys in a printed mapping
_HIDDEN_OPTIONS = ID_KEYS


def unmask_ids(text: str, options: Mapping[str, Any] | None) -> str:
    """A masked request line with the job's own options put back (``mrn=•••`` -> ``mrn=<the job's mrn>``): the audit
    keeps the line masked (D-272), the job keeps what it was asked; the page decides who sees it (D-143)."""
    opts = {str(k).lower(): v for k, v in (options or {}).items()}

    def back(m: re.Match[str]) -> str:
        val = opts.get(m.group(1).lower())
        return f"{m.group(1)}={val}" if val not in (None, "") else m.group(0)

    return ID_IN_TEXT.sub(back, text or "")


def job_line(job: Job) -> str:
    opts = dict(job.options or {})
    target = job.ruleset or opts.pop("target", "")
    opts.pop("target", None)
    shown = [f"{k}={v}" for k, v in sorted(opts.items()) if k.lower() not in _HIDDEN_OPTIONS]
    return " ".join([job.type, target, *shown]).strip()


def _env_map(env: Mapping[str, str] | None) -> dict[str, str]:
    return dict(env if env is not None else os.environ)


def _default_backend(settings: ConsoleSettings) -> tuple[Backend, AuditLog]:
    from tb_common.config import get_config
    from tb_common.objstore import from_config

    from console.backend import HttpBackend

    cfg = get_config()
    audit = open_audit(cfg.env.audit_path, cfg.env.tz)
    return HttpBackend(cfg, from_config(), audit, gateway_url=settings.gateway_url, test_smtp=settings.test_smtp), audit


def build_sponsor_pack(
    job: Job, files: list[tuple[str, bytes]], detail: Mapping[str, Any], models: Mapping[str, Any] | None
) -> bytes:
    """Deterministic zip (fixed timestamps) of the aggregate files plus README.txt with the provenance (D-101)."""
    review = detail.get("review") or {}
    population = detail.get("population") or {}
    split = review.get("split") or {}
    version = job.ruleset_version or detail.get("version") or "-"
    screening = ""
    if models:
        verifier = f", verifier {models['verifier_model']}" if models.get("verifier_model") else ", no verifier"
        screening = (
            f"Screening on this box: judge {models.get('judge_model') or '-'}{verifier}, note answers may exclude: "
            f"{'yes' if models.get('may_block') else 'no'}."
        )
    lines = [
        f"TrialBox sponsor pack · {job.ruleset} v{version} · job {job.job_id}",
        "",
        "What this is: aggregate feasibility counts from one hospital's TrialBox. Counts below 5 are printed as '<5'.",
        "No patient-level data is in this pack; the box keeps those files and never mails them.",
        "",
        f"Protocol: {detail.get('title') or '-'}" + (f" ({detail['nct_id']})" if detail.get("nct_id") else ""),
        f"Population (as entered at import): stage = {population.get('disease_stage') or '-'}; "
        f"arm = {population.get('study_arm') or '-'}",
        f"Ruleset version: {version}; criteria: {detail.get('criteria', '-')}",
        f"Approved by: {review.get('approved_by') or '-'} via {review.get('approved_via') or '-'} on "
        f"{review.get('approved_at') or '-'} (review rounds: {review.get('rounds', '-')}); "
        f"routing confirmed by the approver: {'yes' if review.get('routing_confirmed') else 'not recorded'}",
        f"Criteria routing: {split.get('structured', '-')} filter, {split.get('mixed', '-')} filter then model, "
        f"{split.get('note', '-')} model on notes, {split.get('human', '-')} person at screening",
        f"Data snapshot: {job.snapshot_date.isoformat() if job.snapshot_date else '-'}; "
        f"run date: {job.run_date.isoformat() if job.run_date else '-'}",
        "Models: feasibility counts run on filters only (no language model). " + screening,
        f"Requested by: {job.requested_by}",
        "",
        "Files:",
    ] + [f"  {name}  sha256 {sha256_bytes(data)}" for name, data in files]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [("README.txt", ("\n".join(lines) + "\n").encode("utf-8")), *files]:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


_INC_HEAD = re.compile(r"^\W*(inclusion( criteria)?|納入(條件|標準|基準)?|收案條件|選択基準|組入れ基準)\W*$", re.I)
_EXC_HEAD = re.compile(r"^\W*(exclusion( criteria)?|排除(條件|標準|基準)?|除外基準)\W*$", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•・]|\(?\d{1,3}[.)、．]|[（(]\d{1,3}[）)])\s*")


def criteria_markdown(text: str) -> str | None:
    """Pasted criteria (S2) -> Markdown with ``## Inclusion criteria`` / ``## Exclusion criteria`` sections. A line
    that is only a heading (EN, JA or zh-TW) switches section; lines before any heading are inclusion criteria;
    bullets and numbers are dropped. ``None`` when nothing is left."""
    sections: dict[str, list[str]] = {"inclusion": [], "exclusion": []}
    cur = "inclusion"
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip().lstrip("#").strip()
        if not line:
            continue
        if _INC_HEAD.match(line):
            cur = "inclusion"
            continue
        if _EXC_HEAD.match(line):
            cur = "exclusion"
            continue
        item = _BULLET.sub("", line).strip()
        if item:
            sections[cur].append(item[:2000])
    if not any(sections.values()):
        return None
    out = ["# Criteria", ""]
    for key, head in (("inclusion", "Inclusion criteria"), ("exclusion", "Exclusion criteria")):
        if sections[key]:
            out += [f"## {head}", ""] + [f"{i}. {c}" for i, c in enumerate(sections[key], 1)] + [""]
    return "\n".join(out)


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
    users = users or UserStore()  # schema auth of the trial database (TB_DB_URL, D-126)
    users.idle, users.absolute = settings.identity.idle, settings.identity.absolute  # D-192
    ident = Identity(settings.identity, users, audit, settings.secure_cookie)
    if settings.admin_password_file is not None:
        made = users.bootstrap_from_file(settings.admin_password_file, mailbox=settings.admin_email or None)
        if made is not None:
            audit.append("console.user", actor="console:bootstrap", detail={"action": "create", "role": "admin"})
    if settings.pilot and classify is None and settings.gateway_url:
        from console.proposals import gateway_classifier

        zone = site_zone(backend)  # the site's date, not the container's (D-270)
        classify = gateway_classifier(
            settings.gateway_url, settings.gateway_model, "D0", lambda: local_today(datetime.now(UTC), zone)
        )
    if settings.pilot and cascades is None:
        cascades = CascadeRuns(settings.data_dir / "cascade", settings.source_dir)
    pending: dict[str, _Pending] = {}
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    site_tz = site_zone(backend)
    templates.env.filters["local"] = lambda v, n=16: local_time(v, site_tz, n)
    templates.env.filters["mask_ids"] = lambda v: mask_ids(str(v))  # audit tables never show a chart number (P-01)
    # D-146 (review J-17): a person, not the raw actor id ("console:crc" -> "crc"), on every translated page
    templates.env.filters["who"] = lambda v: str(v or "").removeprefix("console:") or "–"
    templates.env.globals["reason_label"] = reason_label  # a candidate row's reason code in the page language (D-118)
    templates.env.globals["feas_notes"] = feas_notes  # a feasibility result's notes in the page language (D-119)
    # D-380 (ROLE-018): the menu asks the matrix, as the routes do (``permit(user.role, action, BEST)``)
    templates.env.globals["permit"] = permit
    templates.env.globals["BEST"] = BEST_STANDING
    bk: Backend = backend
    au: AuditLog = audit
    us: UserStore = users
    us.zone = site_tz  # an account's end date is a site day (D-270)

    boot: list[Callable[[], Any]] = []  # started with the app (the box's own timers, D-121)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        running = [fn() for fn in boot]
        try:
            yield
        finally:
            for sched in running:
                if sched is not None:
                    sched.shutdown(wait=False)

    app = FastAPI(title="trialbox-console", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.state.settings = settings
    app.state.identity = ident

    # ------------------------------------------------------------------ plumbing
    @app.middleware("http")
    async def headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("Content-Security-Policy", CSP)  # the sandboxed preview sets its own
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        resp.headers.setdefault("Cache-Control", "no-store")
        token = getattr(request.state, "sso_cookie", None)
        if token:
            resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=settings.secure_cookie)
        return resp

    def _trusted_peer(request: Request) -> bool:
        host = request.client.host if request.client else None
        if not host:
            return False
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:  # not an address (a unix socket peer, the test client): exact name match only
            return host in settings.sso_trusted
        for item in settings.sso_trusted:
            try:
                if "/" in item:
                    if ip in ipaddress.ip_network(item, strict=False):
                        return True
                elif ip == ipaddress.ip_address(item):
                    return True
            except ValueError:
                continue
        return False

    def sso_user(request: Request) -> User | None:
        """The account behind a trusted identity header (D-93), or None. Only a request from a configured proxy
        address counts; a header on any other connection is ignored and audited once per request."""
        if not settings.sso or request.cookies.get(COOKIE):
            return None
        ident = (request.headers.get(settings.sso_header) or "").strip().lower()
        if not ident:
            return None
        if not _trusted_peer(request):
            au.append("console.sso_rejected", actor="console:-", detail={"reason": "untrusted peer"})
            return None
        username = re.sub(r"[^a-z0-9._-]+", "_", ident.split("@", 1)[0])[:32] or "sso"
        groups = (request.headers.get(settings.sso_role_header) or "").lower() if settings.sso_role_header else ""
        role = settings.sso_default_role
        for group, mapped in settings.sso_role_map:
            if group in {g.strip() for g in re.split(r"[;,]", groups)}:
                role = mapped
                if mapped == "admin":
                    break
        mailbox = ""
        if settings.sso_mailbox_header:
            mailbox = (request.headers.get(settings.sso_mailbox_header) or "").strip().lower()
        if not mailbox and "@" in ident:
            mailbox = ident
        try:
            return us.upsert_sso(username, role, mailbox or None)  # type: ignore[arg-type]
        except AuthError as exc:
            au.append("console.sso_rejected", actor=f"console:{username}", detail={"reason": str(exc)[:80]})
            return None

    def session_of(request: Request) -> Session | None:
        # D-192 review H3: a page's own auto-refresh (?auto=1, base.html) is not activity: the idle lock still runs
        return us.session(request.cookies.get(COOKIE), touch=request.query_params.get("auto") != "1")

    def need(request: Request) -> Session:
        sess = session_of(request)
        if sess is None:
            user = sso_user(request)
            if user is None:
                raise _LoginRequired()
            token, sess = us.new_session(user, pick_language(request.headers.get("accept-language")), "sso")
            request.state.sso_cookie = token
            au.append("console.login", actor=f"console:{user.username}", detail={"role": user.role, "via": "sso"})
        # D-279 (SEC-1): with a password someone else set, the account reaches only its own password page
        if request.url.path not in MUST_CHANGE_OPEN and us.must_change(sess.user.username):
            if request.method == "GET" and not request.url.path.startswith("/api/"):
                raise _MustChange()
            raise _Problem(403, "account.must_change")
        _scope_check(request, sess)
        bind_session(sess.token_sha[:16])  # S-09: the actor this request names to the orchestrator is signed with it
        return sess

    def _aggregate_denied(path: str) -> bool:
        """D-146 (review J-03/J-04/J-05): what an aggregate-only account (viewer, CRO; D-104) never opens, as a page or
        through ``/api/v1``: the cross-study lists (runs, audit trail, registry), a study's patient-level and set-up
        pages and APIs (all but its feasibility report), the site set-up, the REDCap connections, and any job page but
        a feasibility run's (a CASE or SCREEN job page names patients). Masking (D-143) stays as it was."""
        if _AGGREGATE_DENY.match(path):
            return True
        m = re.match(r"^/pilot/jobs/([0-9A-HJKMNP-TV-Z]{26})(?:/|$)", path)
        if m:
            job = bk.get_job(m.group(1))
            return job is None or job.type != "FEAS"
        return False

    def _scope_check(request: Request, sess: Session) -> None:
        """D-104: a CRO account sees the reports pages only; a study-scoped account (an SMO coordinator) reaches no
        job or registry page of another study."""
        path = request.url.path
        u = sess.user
        if u.sponsor_form and not (
            path
            in ("/", "/home", "/reports", "/lang", "/logout", "/cmd", "/account", "/account/password", "/help", "/ask")
            or re.fullmatch(r"/studies/[A-Za-z0-9_-]+/feasibility", path)
            or _MONITOR_ROUTE.fullmatch(path)  # D-380: refused there unless a monitor grant holds
            or re.fullmatch(r"/pilot/jobs/[0-9A-HJKMNP-TV-Z]{26}/sponsor-pack\.zip", path)
            or path == "/api/v1/studies"
        ):
            au.append("console.denied", actor=f"console:{u.username}", detail={"action": path[:80]})
            raise _Problem(403, "forbidden")
        if u.aggregate_only and _aggregate_denied(path):
            au.append("console.denied", actor=f"console:{u.username}", detail={"action": path[:80]})
            raise _Problem(403, "forbidden")
        if not u.studies:
            return
        # cross-study lists a study-scoped account (an SMO coordinator) has no business with
        if path in ("/jobs", "/audit", "/pilot/mailbox") or path.startswith("/pilot/cascade"):
            au.append("console.denied", actor=f"console:{u.username}", detail={"action": path[:80]})
            raise _Problem(403, "forbidden")
        m = re.match(r"^/pilot/(?:jobs/([0-9A-HJKMNP-TV-Z]{26})|registry/([A-Za-z0-9_-]+))", path)
        if not m:
            return
        rs = m.group(2)
        if m.group(1):
            job = bk.get_job(m.group(1))
            rs = job.ruleset if job is not None else None
        if rs and not u.sees_study(rs):
            au.append("console.denied", actor=f"console:{u.username}", detail={"action": path[:80]})
            raise _Problem(404, "notfound")

    def _need_role(request: Request, csrf: str, ok: bool, sess: Session) -> Session:
        if not csrf_ok(sess, csrf):
            raise _Problem(400, "csrf")
        if not ok:
            au.append("console.denied", actor=f"console:{sess.user.username}", detail={"action": request.url.path[:80]})
            raise _Problem(403, "forbidden")
        return sess

    def confirm_step(request: Request, sess: Session, text: str, action: str, fields: Mapping[str, str],
                     back: str) -> Response:  # fmt: skip
        """Review 2026-11-09 P-10 (D-143): one sheet with the consequence in a sentence, Yes and No; Yes posts the same
        form again with ``confirm=yes``. Used for Disable, Keep / Take a value, Detach REDCap and Approve all."""
        return page(request, "confirm.html", sess, text=text, action=action, fields=dict(fields), back=back)

    def need_admin(request: Request, csrf: str) -> Session:
        """Operations: ingest, users. Administrators only."""
        sess = need(request)
        return _need_role(request, csrf, sess.user.is_admin, sess)

    def need_requester(request: Request, csrf: str) -> Session:
        """Clinical workspace actions: requests, approvals, the registry. Administrators and coordinators (D-93)."""
        sess = need(request)
        return _need_role(request, csrf, sess.user.can_request, sess)

    def need_runner(request: Request, csrf: str, command: str, ruleset: str) -> Session:
        """Starting a FEAS, SCREEN or CASE run (T-512, D-349): coordinators and administrators as before; an
        investigator by ``tb_common.authz.can_request`` with the study's delegation log (``Helpers.may_run``)."""
        sess = need(request)
        return _need_role(request, csrf, helpers.may_run(sess.user, ruleset.strip().upper(), command), sess)

    def lang_of(request: Request, sess: Session | None) -> str:
        if sess is not None and sess.lang in LANGS:
            return sess.lang
        chosen = getattr(request.state, "lang", None) or request.cookies.get(LANG_COOKIE)  # the sign-in page's choice
        if chosen in LANGS:
            return str(chosen)
        return pick_language(request.headers.get("accept-language"))

    def page(request: Request, name: str, sess: Session | None, status: int = 200, **ctx: Any) -> HTMLResponse:
        lang = lang_of(request, sess)

        def t(key: str, **values: object) -> str:
            return translate(lang, key, **values)

        def t_or(key: str, fallback: str) -> str:  # a translation when the catalogue has one, else the fallback
            text = t(key)
            return fallback if text == key else text

        def state(value: str) -> str:  # badge text; the machine state stays in data-state
            key = f"state.{value}"
            text = t(key)
            return value if text == key else text

        def given(value: object, cls: str = "") -> Markup | str:
            """D-133 (review F-09): words that come from the study or the hospital's data (a criterion label, a
            doctor's name) are shown as written. On a Japanese or Chinese page an English one is marked "as given"
            (原文) and carries lang="en", so a reader sees it is the source's own word, not an untranslated label."""
            text = str(value or "")
            if not text:
                return ""
            if lang == "en" or not _ASCII_WORDS.fullmatch(text) or not re.search(r"[A-Za-z]{3,}", text):
                return Markup('<span class="{}">{}</span>').format(cls, text) if cls else text
            return Markup('<span class="given {}" lang="en" data-authored data-given="{}">{}</span>').format(
                cls, t("given.mark"), text
            )

        base = {
            "t": t,
            "t_or": t_or,
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
            "given": given,
            "num": _num,
            "console_js": CONSOLE_JS,
            # the 5-second refresh of a running job's page asks with auto=1, so it does not keep the session awake
            "refresh_url": request.url.path
            + "?"
            + urlencode([*((k, v) for k, v in request.query_params.multi_items() if k != "auto"), ("auto", "1")]),
        }
        return templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status)

    @app.exception_handler(_LoginRequired)
    async def _to_login(request: Request, _exc: _LoginRequired) -> Response:
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(_MustChange)
    async def _to_account(request: Request, _exc: _MustChange) -> Response:
        return RedirectResponse("/account?must_change=1", status_code=303)  # D-279: the password page first

    @app.exception_handler(_Problem)
    async def _problem(request: Request, exc: _Problem) -> Response:
        if request.url.path.startswith("/api/"):  # D-125: the API answers in JSON, never with a page
            return JSONResponse(
                {"error": exc.key, "detail": {k: str(v) for k, v in exc.values.items()}}, status_code=exc.status
            )
        sess = session_of(request)
        values = localize_refusal(exc.values, lang_of(request, sess))  # no English refusal on a JA/zh-TW page
        return page(request, "problem.html", sess, status=exc.status, key=exc.key, values=values)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # an unknown URL typed or followed in the browser gets the console's own page in the user's language, not
        # the framework's JSON; API clients (no text/html in Accept) keep the JSON answer
        if exc.status_code == 404 and "text/html" in request.headers.get("accept", ""):
            return page(request, "problem.html", session_of(request), status=404, key="notfound", values={})
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Unavailable)
    async def _unavailable(request: Request, exc: Unavailable) -> Response:
        sess = session_of(request)
        detail = str(exc)[:300] if lang_of(request, sess) not in ("ja", "zh-TW") else ""
        return page(request, "problem.html", sess, status=503, key="unavailable", values={"detail": detail})

    def actor(sess: Session) -> str:
        return f"console:{sess.user.username}"

    def submit(sess: Session, line: str, files: list[tuple[str, bytes, str]] | None = None) -> Job:
        """Audit, store the inputs, then the same ``POST /jobs`` the mail gateway makes."""
        mailbox = sess.user.mailbox or settings.admin_email
        if not mailbox:
            raise _Problem(400, "request.refused", reason="this account has no mailbox (console.cli set-mailbox)")
        job_id = new_ulid()
        inputs = [bk.put_input(job_id, name, data, ctype) for name, data, ctype in files or []]
        cmd = line.split(" ", 1)[0].upper()
        if cmd in ("FEAS", "SCREEN", "CASE", "NAV", "MICROBATCH") and " lang=" not in f" {line}" and " -- " not in line:
            line = f"{line} lang={sess.lang}"  # D-100: mail and reports in the requester's language
        try:
            req = job_create(line, mailbox, job_id, f"web console ({sess.user.username})", inputs)
        except ProposalError as exc:
            raise _Problem(400, "request.refused", reason=str(exc)) from exc
        if req.ruleset and not sess.user.sees_study(req.ruleset):  # D-104: a scoped account requests its studies only
            au.append("console.denied", actor=actor(sess), detail={"action": f"request {req.ruleset}"})
            raise _Problem(404, "notfound")
        au.append(
            "console.request",
            job_id=job_id,
            ruleset=req.ruleset,
            actor=actor(sess),
            input_sha=",".join(f.sha256 for f in inputs) or None,
            # D-272 (CR-016, PX-3): the request line is audited with its chart number masked
            detail={"line": mask_ids(line), "mailbox": mailbox, "role": sess.user.role, "channel": "web"},
        )
        try:
            # D-146 (review J-01): the orchestrator authorises by the signed-in person's role, sent signed
            return bk.create_job(req, by=actor(sess), role=sess.user.role)
        except Refused as exc:
            au.append("console.refused", job_id=job_id, actor=actor(sess), detail={"reason": str(exc)[:200]})
            raise refusal_problem(str(exc), cmd, mailbox) from exc

    def refusal_problem(reason: str, cmd: str, mailbox: str) -> _Problem:
        """The orchestrator's refusal of a request as a page in the user's language (D-146, review J-01/J-02): the
        daily limit, a role or a mailbox that may not start the request; anything else as before."""
        m = re.search(r"rate limit reached \((\d+) (\w+) jobs", reason)
        if m:
            return _Problem(429, "request.limit", n=int(m.group(1)), kind=m.group(2))
        if re.search(r"role may not run \w+", reason):
            return _Problem(403, "request.role", kind=cmd)
        if re.search(r"is not permitted to run \w+", reason):
            return _Problem(403, "request.mailbox", kind=cmd, mailbox=mailbox)
        return _Problem(403, "request.refused", reason=reason)

    def need_pilot() -> None:
        if not settings.pilot:
            raise _Problem(404, "notfound")

    # ------------------------------------------------------------------ control plane
    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Touches the console's own store (D-142, review A-02): with the database gone every page fails, so the
        container must not look healthy. A lost connection is reopened on the way."""
        body: dict[str, Any] = {
            "status": "ok",
            "service": "console",
            "pilot": settings.pilot,
            "env": settings.environment,
        }
        try:
            body["checks"] = users.db.ping()
        except Exception as exc:  # health must report, not raise
            body.update(status="degraded", checks={"db": f"error: {type(exc).__name__}"})
            return JSONResponse(body, status_code=503)
        return JSONResponse(body)

    def login_page(request: Request, status: int = 200, failed: bool = False, **ctx: Any) -> Response:
        token = secrets.token_urlsafe(24)
        resp = page(
            request,
            "login.html",
            None,
            status,
            login_csrf=token,
            failed=failed,
            admin_mail=settings.admin_email,
            sso=settings.sso,
            oidc=ident.oidc_enabled,
            **ctx,
        )
        resp.set_cookie(
            LOGIN_COOKIE, token, httponly=True, samesite="strict", secure=settings.secure_cookie, max_age=900
        )
        chosen = getattr(request.state, "lang", None)
        if chosen:  # D-133 (review F-05): the language chosen on the sign-in page, kept for the session it starts
            resp.set_cookie(LANG_COOKIE, chosen, httponly=True, samesite="strict", secure=settings.secure_cookie)
        return resp

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, lang: str = "") -> Response:
        if settings.sso and (session_of(request) is not None or sso_user(request) is not None):
            return RedirectResponse("/", status_code=303)
        if lang in LANGS:
            request.state.lang = lang
        return login_page(request, uninitialised=us.count("admin") == 0)

    @app.post("/login")
    def login(
        request: Request, username: str = Form(""), password: str = Form(""), login_csrf: str = Form("")
    ) -> Response:
        cookie = request.cookies.get(LOGIN_COOKIE, "")
        if not cookie or not secrets.compare_digest(cookie, login_csrf):
            raise _Problem(400, "csrf")
        src = client_source(request)  # D-279 (SEC-9): failures count per account and address
        wait = us.throttled(src)
        if wait:  # this address made many failed tries: it waits, nobody is locked out
            au.append("console.login_failed", actor=f"console:{username.strip().lower()[:32] or '-'}",
                      detail={"reason": "slowed", "source": src})  # fmt: skip
            resp = login_page(request, 429, failed=True, uninitialised=False, wait=wait)
            resp.headers["Retry-After"] = str(wait)
            return resp
        # D-192: with a TOTP step to come, a right password does not clear the failure count; the code does
        user = us.authenticate(
            username[:64], password[:256], clear_failures=not settings.identity.totp_required, source=src
        )
        if user is None:
            au.append("console.login_failed", actor=f"console:{username.strip().lower()[:32] or '-'}",
                      detail={"source": src})  # fmt: skip
            ident.after_failure(username, src)
            until = us.locked_until(username[:64], src)
            left = max(1, -(-int((until - us.clock()).total_seconds()) // 60)) if until else 0
            return login_page(
                request, 401, failed=True, uninitialised=False, until=until.isoformat() if until else "", left=left
            )
        if ident.needs_code(user):  # D-192: local accounts give a TOTP code before a session exists
            return ident.second_step(user)
        token, _ = us.new_session(user, lang_of(request, None), "password")
        au.append("console.login", actor=f"console:{user.username}", detail={"role": user.role})
        landing = "/home" if settings.pilot else "/"  # S1: land on the work list
        if us.must_change(user.username):  # D-279: a password someone else set is replaced first
            landing = "/account?must_change=1"
        done = RedirectResponse(landing, status_code=303)
        done.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=settings.secure_cookie)
        done.delete_cookie(LOGIN_COOKIE)
        done.delete_cookie(LANG_COOKIE)
        return done

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form("")) -> Response:
        sess = need(request)
        if not csrf_ok(sess, csrf):
            raise _Problem(400, "csrf")
        us.end_session(request.cookies.get(COOKIE, ""))
        au.append("console.logout", actor=actor(sess))
        resp = RedirectResponse(ident.logout_target(sess.user.username), status_code=303)  # D-192: OIDC logout
        resp.delete_cookie(COOKIE)
        return resp

    register_identity(  # D-192: the TOTP step, the OIDC sign-in, /ops/identity (unlock, reset authenticator)
        app,
        ident,
        Hooks(
            need=need,
            page=page,
            login_page=login_page,
            confirm=confirm_step,
            lang_of=lang_of,
            translate=translate,
            csrf_ok=csrf_ok,
            problem=_Problem,
            secure=settings.secure_cookie,
            session_cookie=COOKIE,
            home="/home" if settings.pilot else "/",
        ),
    )

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
        if settings.pilot and not sess.user.is_admin:  # D-104: every role but the administrator starts on its home
            return RedirectResponse("/home", status_code=303)
        jobs = bk.list_jobs(limit=8)
        return page(
            request,
            "overview.html",
            sess,
            health=bk.health(),
            models=bk.models(),
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
    def audit_view(
        request: Request, page_no: Annotated[int, Query(alias="page", ge=1, le=AUDIT_PAGES)] = 1
    ) -> Response:
        """The audit trail, newest first, AUDIT_PAGE events per page (D-133, review F-07: one page used to hold 300
        events, 130 phone screens)."""
        sess = need(request)
        recs = bk.audit(None, AUDIT_PAGE * page_no + 1)
        more = len(recs) > AUDIT_PAGE * page_no
        rows = recs[AUDIT_PAGE * (page_no - 1) : AUDIT_PAGE * page_no]
        if not permit(sess.user.role, "audit.ids"):  # D-380 (CR-023): the administrator sees no pseudonym here
            rows = hide_pids(list(rows))
        return page(request, "audit.html", sess, records=rows, page_no=page_no, more=more and page_no < AUDIT_PAGES)

    # D-133 (review F-02): a new or reset one-time password never travels in a URL (history, proxy and access logs,
    # a forwarded link). It is kept here, in memory, for the session that made it, and shown once by the next page.
    # Never written to a log, the audit trail or a database; a restart forgets it (reset the password again).
    one_time: dict[str, tuple[str, str, float]] = {}

    def keep_once(sess: Session, username: str, password: str) -> None:
        now = time.monotonic()
        for k in [k for k, v in one_time.items() if now - v[2] > 600]:  # unread for 10 minutes: gone
            one_time.pop(k, None)
        one_time[sess.token_sha] = (username, password, now)

    @app.get("/ops/users", response_class=HTMLResponse)
    def users_view(request: Request, undo: str = "", done: str = "") -> Response:
        sess = need(request)
        if not sess.user.is_admin:
            raise _Problem(403, "forbidden")
        made, pw, _ = one_time.pop(sess.token_sha, ("", "", 0.0))
        rows = [(u, us.is_sso(u.username)) for u in us.users()]
        off = us.disabled_users()
        return page(
            request,
            "users.html",
            sess,
            users=rows,
            disabled=off,
            undo=undo if undo in {u.username for u in off} else "",  # D-178: the toast's Undo after Disable
            done=done if done in ("enabled",) else "",
            roles=ROLES,
            role_desc={r: role_description(r, lang_of(request, sess)) for r in ROLES},  # ROLE-018: from the matrix
            affiliations=AFFILIATIONS,
            made=made,
            pw=pw,
            pw_groups=pw.split("-") if pw else [],
            sso=settings.sso,
        )

    @app.post("/ops/users")
    def users_edit(
        request: Request,
        csrf: str = Form(""),
        action: str = Form(""),
        username: str = Form(""),
        role: str = Form("viewer"),
        mailbox: str = Form(""),
        affiliation: str = Form("hospital"),
        studies: str = Form(""),
        expires: str = Form(""),
        confirm: str = Form(""),
    ) -> Response:
        """Add a user (password shown once), reset a password (shown once) or disable an account (after a
        confirmation, P-10). Same as the console.cli commands; every change is an audit event."""
        sess = need_admin(request, csrf)
        name = username.strip().lower()[:32]
        perm = {"reset": "account.reset", "disable": "account.disable", "enable": "account.enable"}.get(action)
        if perm and not admin_allowed(sess.user.role, perm):  # D-178: the one role table (tb_common.authz)
            au.append("console.denied", actor=actor(sess), detail={"action": f"/ops/users {action}"})
            raise _Problem(403, "forbidden")
        try:
            if action == "add":
                if role not in ROLES:
                    raise AuthError("unknown role")
                scope_values(
                    affiliation, studies, expires or None, role
                )  # refuse a bad scope before the account exists
                expires = end_date(role, expires or None, us.today()) or ""  # D-406 (OPS-059): at most 12 months
                password = random_password()
                us.create(name, role, password, mailbox.strip() or None, must_change=True)  # D-279: the owner's first
                made_user = us.set_scope(name, affiliation, studies, expires or None)
                au.append(
                    "console.user",
                    actor=actor(sess),
                    detail={
                        "action": "create",
                        "user": name,
                        "role": role,
                        "affiliation": made_user.affiliation,
                        "studies": ",".join(made_user.studies),
                        "expires": made_user.expires or "",
                    },
                )
                keep_once(sess, name, password)
                return RedirectResponse("/ops/users#made", status_code=303)
            if action == "reset":
                if us.is_sso(name):
                    raise AuthError("this account signs in through the hospital identity provider")
                if confirm != "yes":  # D-178 (review J-14): the consequence first; a reset cannot be undone
                    text = translate(lang_of(request, sess), "confirm.reset", user=name)
                    return confirm_step(request, sess, text, "/ops/users", {"action": "reset", "username": name},
                                        "/ops/users")  # fmt: skip
                password = random_password()
                us.set_password(name, password, must_change=True)  # D-279: the owner replaces it at sign-in
                au.append("console.user", actor=actor(sess), detail={"action": "reset", "user": name})
                keep_once(sess, name, password)
                return RedirectResponse("/ops/users#made", status_code=303)
            if action == "scope":
                scope_values(affiliation, studies, expires or None)
                was = next((u for u in us.users() if u.username == name), None)
                if was is not None:  # D-406 (OPS-059): a local account's end date, at most 12 months ahead
                    expires = end_date(was.role, expires or None, us.today(), sso=us.is_sso(name)) or ""
                u2 = us.set_scope(name, affiliation, studies, expires or None)
                au.append(
                    "console.user",
                    actor=actor(sess),
                    detail={
                        "action": "scope",
                        "user": name,
                        "affiliation": u2.affiliation,
                        "studies": ",".join(u2.studies),
                        "expires": u2.expires or "",
                    },
                )
                return RedirectResponse("/ops/users", status_code=303)
            if action == "disable":
                if name == sess.user.username:
                    raise AuthError("you cannot disable your own account")
                if confirm != "yes":
                    text = translate(lang_of(request, sess), "confirm.disable", user=name)
                    return confirm_step(request, sess, text, "/ops/users", {"action": "disable", "username": name},
                                        "/ops/users")  # fmt: skip
                us.disable(name)
                au.append("console.user", actor=actor(sess), detail={"action": "disable", "user": name})
                return RedirectResponse(f"/ops/users?undo={name}#undo", status_code=303)
            if action == "enable":  # D-178 (review J-14): the undo of Disable, from the toast or the disabled list
                us.enable(name)
                au.append("console.user", actor=actor(sess),
                          detail={"action": "enable", "user": name, "undo": confirm == "undo"})  # fmt: skip
                return RedirectResponse("/ops/users?done=enabled", status_code=303)
        except AuthError as exc:
            raise _Problem(400, "request.refused", reason=str(exc)) from exc
        raise _Problem(400, "request.refused", reason="unknown action")

    # ------------------------------------------------------------------ pilot workspace
    if not settings.pilot:
        return app

    from console import (
        admin_flags,
        approval,
        data_pages,
        edc_pages,
        entry_pages,
        lifecycle_pages,
        notify,
        recorded_opinions,
        screening_log,
        site_pages,
        step4,
        study_setup,
        team,
    )
    from console.home import Helpers
    from console.home import register as register_home
    from console.sitestore import SiteStore

    helpers = Helpers(
        need=need,
        page=page,
        confirm=confirm_step,
        scope_check=_scope_check,
        problem=_Problem,
        csrf_ok=csrf_ok,
        actor=actor,
        bk=bk,
        au=au,
        store=SiteStore(),  # schema site of the trial database (TB_DB_URL, D-126)
        users=us,
        clock=us.clock,
        submit=submit,
        identity=ident,  # D-279: the second factor at signing (console.edc_pages)
        recorded=recorded_opinions.from_env(_env_map(env)),  # T-515: DEV demo opinions (TB_DEMO_OPINIONS)
    )
    app.state.helpers = helpers  # console.notify (CLI) reads the same helpers
    register_home(app, helpers)
    approval.register(app, helpers, submit)  # S20 (D-108): the investigator approves, on one page
    screening_log.register(app, helpers)
    notify.register(app, helpers)
    study_setup.register(app, helpers)  # S21 and S36 (D-109)
    data_pages.register(app, helpers)  # TB-PLAN-04 step 3: Sources, Conflicts, Forms and their /api/v1 (D-123)
    entry_pages.register(app, helpers)  # TB-PLAN-04 step 4: Entry, History, exports, built-in forms (D-129)
    lifecycle_pages.register(app, helpers)  # TB-PLAN-04 step 5: participants, visits, schedule, report (D-134)
    site_pages.register(app, helpers)  # TB-PLAN-04 step 5b: site set-up, readiness, review lists, Ask (D-135)
    step4.register(app, helpers)  # header command field, S22, S29, S37, S13 tabs with S24 and S26 (D-110)
    raw_env = _env_map(env)
    team.register(app, helpers, raw_env)  # delegation log, candidates, referral, IRB warning, opt-outs (D-147)
    admin_flags.register(app, helpers)  # /ops/flags and the flags' first-start seed (T-008, D-207)
    edc_pages.register(app, helpers)  # EDC prefill: switch, map, review, e-signature, send, ODM (D-160)
    demo_guard.register(app, helpers)  # T-502 (D-328): demo mode's refusals, banner and acknowledgement
    feedback.register(app, helpers)  # T-510 (D-331): the feedback control of every page and its CSV export
    from console import items_page

    items_page.register(app, helpers)  # T-107 (D-353): /data/items, the clinical item catalogue for the steward
    from console import conflicts_page

    conflicts_page.register(app, helpers)  # T-201 (D-426): /data/conflicts, the steward's clinical conflicts
    from console import dataops_page

    dataops_page.register(app, helpers)  # T-112b (D-443): /data-ops and /api/v1/data/*, the nights of every source
    from console import instruments_page

    instruments_page.register(app, helpers)  # T-307 (D-375): /data/instruments, the instrument copyright register

    from console import ops_pages

    ops_pages.register(app, helpers, raw_env)  # D-178: backups, update and rollback, logs, secrets, network sheet
    from console import metrics_page

    metrics_page.register(app, helpers)  # T-209a (D-379): /metrics and the box's health for the morning mail
    from console import sae_pages

    sae_pages.register(app, helpers)  # the SAE register and its worklist (D-191)
    from console import admin_accounts

    admin_accounts.register(app, helpers)  # T-209c (D-406): backup, update and account tiles; unused-account report
    from console import breakglass

    breakglass.register(app, helpers)  # D-280 (OD-5): the administrator's break-glass grants and the steward's review
    from console import notmatched_pages

    notmatched_pages.register(app, helpers, raw_env)  # T-310a (D-446): weekly sample, send-back, the site's check
    from console import twin_api

    twin_api.register(app, helpers)  # T-204 (D-440): the patient twin's read route, after break-glass (it uses grants)
    from console import timers

    timers.plan(raw_env)  # a bad HH:MM fails at start, not at 07:00
    boot.append(lambda: timers.start(helpers, raw_env, site_tz))

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

    def _barriers(result: dict[str, Any] | None) -> list[str]:
        """The three criteria that drop the most patients (L4): the answer the PDF opens with, now on the page too."""
        if not result:
            return []
        rows = [
            f for f in result.get("funnel") or [] if isinstance(f.get("dropped"), int) and f.get("applied") is not False
        ]
        rows.sort(key=lambda f: -int(f["dropped"]))
        return [f"{f.get('label') or f.get('criterion_id')} (−{f['dropped']})" for f in rows[:3] if f["dropped"] > 0]

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
        h = found.count("human")
        return {
            "n": len(found),
            "s": found.count("structured"),
            "m": found.count("note"),
            "x": found.count("mixed"),
            "h": h,
            "human_heavy": h * 2 >= len(found),  # D-101: half or more left to a person
        }

    def _consent_card(job: Job) -> dict[str, Any] | None:
        """The consent explainer card: counts from the explainer record, the pages to preview."""
        if job.type not in ("CONSENT", "RELEASE") or job.state != "done":
            return None
        import json

        outs = {o.filename: o for o in job.outputs or [] if o.tag == "aggregate"}
        study = (job.ruleset or "").upper()
        card: dict[str, Any] = {"review": None, "pages": [], "counts": {}, "verified": True}
        suffix = "_DRAFT.html" if job.type == "CONSENT" else ".html"
        for lang in ("en", "ja", "zh-TW"):
            name = f"consent_{study}_{lang}{suffix}"
            if name in outs:
                card["pages"].append((lang, name))
        if job.type == "CONSENT":
            rec_out = outs.get(f"consent_{study}.json")
            if rec_out is None:
                return None
            try:
                rec = json.loads(bk.get_object(rec_out.minio_key))
            except (KeyError, ValueError, OSError):
                return None
            card["counts"] = rec.get("counts") or {}
            card["verified"] = bool(rec.get("verified"))
            card["review"] = f"consent_{study}_review.html" if f"consent_{study}_review.html" in outs else None
        return card

    @app.get("/pilot/jobs/{job_id}/view/{filename}")
    def job_view_file(request: Request, job_id: str, filename: str) -> Response:
        """An aggregate HTML output shown in the browser (consent explainer pages); sandboxed, no script."""
        sess = need(request)
        job = _job_or_404(job_id)
        out = next((o for o in job.outputs or [] if o.filename == filename), None)
        if not _FILE.match(filename) or out is None or not filename.endswith(".html"):
            raise _Problem(404, "notfound")
        # D-91/D-101: the CASE eligibility sheet carries chart text (phi); in the pilot workspace a requester or an
        # investigator may read it in the browser, exactly as the study team receives it by mail. Viewers may not.
        # D-280 (OD-5): the administrator reads it only under a break-glass grant for this job; T-309 (D-430): so does
        # an investigator the delegation log does not reach (one rule)
        grant = _bg(sess, job, "case sheet") if out.tag != "aggregate" and job.type == "CASE" else None
        if out.tag != "aggregate" and not (job.type == "CASE" and (sess.user.can_view_phi or grant is not None)):
            raise _Problem(404, "notfound")
        if out.tag != "aggregate" and grant is None:  # D-273 (PV-3): an investigator reads it only as delegated
            helpers.delegated(sess, job.ruleset or "", request.url.path)
        data = bk.get_object(out.minio_key)
        au.append(
            "console.view",
            job_id=job_id,
            actor=actor(sess),
            output_sha=sha256_bytes(data),
            detail={"filename": filename, "tag": out.tag},
        )
        return Response(
            data,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
            },
        )

    @app.post("/pilot/jobs/{job_id}/release")
    def consent_release(
        request: Request, job_id: str, csrf: str = Form(""), drop: str = Form(""), keep: str = Form("")
    ) -> Response:
        sess = need_requester(request, csrf)
        job = _job_or_404(job_id)
        if job.type != "CONSENT" or job.state != "done":
            raise _Problem(409, "request.refused", reason="only a finished consent explainer can be released")
        parts = ["RELEASE", job.job_id]
        for key, raw in (("drop", drop), ("keep", keep)):
            value = re.sub(r"\s+", "", raw).upper().strip(",")
            if value:
                if not _ITEM_IDS.match(value):
                    raise _Problem(400, "request.refused", reason="item ids look like I03 or Q2, separated by commas")
                parts.append(f"{key}={value}")
        new = submit(sess, " ".join(parts))
        return RedirectResponse(f"/pilot/jobs/{new.job_id}", status_code=303)

    @app.get("/pilot/jobs/{job_id}", response_class=HTMLResponse)
    def job_view(request: Request, job_id: str) -> Response:
        sess = need(request)
        job = _job_or_404(job_id)
        return _job_page(request, sess, job)

    def _bg(sess: Session, job: Job, what: str) -> Any:
        """D-280 (OD-5): the open break-glass grant for this job (one audited use), else None. T-309 (D-430): asked
        only when the account does not read the job's study by its own rights (``Helpers.reads``)."""
        if helpers.breakglass is None or helpers.reads(sess.user, job.ruleset):
            return None
        return helpers.breakglass(sess, job_id=job.job_id, what=what)

    def _job_page(request: Request, sess: Session, job: Job, revealed: dict[str, str] | None = None) -> Response:
        job_id = job.job_id
        grant = _bg(sess, job, "job page")
        review_html = next(
            (o for o in job.outputs or [] if o.filename.startswith("review_") and o.filename.endswith(".html")), None
        )
        audit_recs = bk.audit(job_id, 200)
        subjects = [str(r.detail.get("subject", "")) for r in audit_recs if r.event == "mail.received"]
        thread = bk.thread(job_id)
        raw_rows: list[tuple[MailItem | None, str]] = [
            (m, m.subject or (subjects[0] if m.direction == "in" and subjects else "")) for m in thread
        ]
        if not any(m.direction == "in" for m in thread) and any(r.event == "console.request" for r in audit_recs):
            web = next(r for r in audit_recs if r.event == "console.request")
            # the audit holds the line masked (D-272); the chart number comes back from the job's options
            raw_rows.insert(0, (None, unmask_ids(mask_ids(str(web.detail.get("line", ""))), job.options)))
        case = _case_card(job)
        out = _case_opted_out(job, case)
        auto = request.query_params.get("auto") == "1"  # the page's own 5-second refresh (base.html)
        thread_rows = [(m, shown_ids(sess, job, text, "thread", opted_out=out, bg=grant is not None, auto=auto))
                       for m, text in raw_rows]  # fmt: skip
        return page(
            request,
            "job.html",
            sess,
            job=job,
            line=job_line(job),
            result=(feas := _feas_result(job)),
            barriers=_barriers(feas),
            aggregate=[o for o in job.outputs or [] if o.tag == "aggregate"],
            phi=[o for o in job.outputs or [] if o.tag == "phi"],
            phi_dl={o.filename for o in job.outputs or [] if o.tag == "phi" and phi_download_ok(sess, job, o)},
            review=_review_book(job) if job.state == "awaiting_approval" else None,
            review_html=review_html,
            split=_check_split(review_html) if job.state == "awaiting_approval" else None,
            thread=thread_rows,
            audit=sorted(audit_recs, key=lambda r: r.ts),
            refresh=job.state not in TERMINAL and job.state != "awaiting_approval",
            rulesets=[r for r in bk.rulesets() if r.status == "approved"],
            consent=_consent_card(job),
            case=case,
            screen=_screen_card(job, sess, revealed, bg=grant is not None),
            breakglass=grant,
        )

    def _case_opted_out(job: Job, case: dict[str, Any] | None) -> bool:
        """D-273 (PV-4): is the job's subject on the opt-out register now? The pseudonym comes from the finished
        CASE card or the job's options; for a CASE job still running, or failed, the box turns the job's own chart
        number into the pseudonym (never shown, never returned). If the box cannot answer, the line stays masked."""
        gone = helpers.gone()
        if not gone:
            return False
        subj = str(((case or {}).get("subject") or {}).get("pid") or (job.options or {}).get("pid") or "")
        if subj:
            return subj in gone
        chart = str((job.options or {}).get("mrn") or "").strip()
        if job.type != "CASE" or not chart:
            return False
        from console import s28

        try:
            got = s28.call(bk, "POST", "/setup/pseudonym", {"chart_no": chart})
        except Exception:  # the box is down or refuses: fail closed
            return True
        pid = str((got or {}).get("pid") or "")
        return not pid or pid in gone

    def shown_ids(sess: Session, job: Job, text: str, where: str, opted_out: bool = False, bg: bool = False,
                  auto: bool = False) -> str:  # fmt: skip
        """A request line or subject as this reader may see it (P-01, D-143): the chart number in clear for an
        account with identifier authority for the job's study (coordinator, the study's delegated investigator) or
        under the page's break-glass grant, through the one reveal path (T-103, D-438: one use of the cap per person,
        job and hour, one record; the auto-refresh costs nothing); masked for everyone else (viewer, CRO)."""
        masked = mask_ids(text)
        if masked == text or opted_out:
            return masked
        basis = helpers.reveal.own_basis(sess, job.ruleset) if job.ruleset else ""
        if not basis and not job.ruleset and sess.user.sees_ids(None):
            basis = "role"  # a job without a study: an unscoped account with the ``id.reveal`` row
        if not basis and not bg:
            return masked
        ok = helpers.reveal.shown_in_line(sess, job.ruleset or "", job.job_id, where, auto=auto,
                                          basis=basis or "breakglass")  # fmt: skip
        return text if ok else masked

    def _screen_card(job: Job, sess: Session, revealed: dict[str, str] | None = None,
                     bg: bool = False) -> dict[str, Any] | None:  # fmt: skip
        """The coordinator's screen for a finished SCREEN / MICROBATCH job (D-99): the run summary from the
        ``screen_*.json`` aggregate, and for administrators and coordinators the candidate rows (tier, next visit,
        practitioner, open questions, note quotes) from the candidate-list JSON the mail also carried. Viewers see the
        summary only: the rows are patient-level."""
        if job.type not in ("SCREEN", "MICROBATCH") or job.state != "done":
            return None
        import json

        outs = job.outputs or []
        summary_out = next((o for o in outs if o.filename.startswith("screen_") and o.filename.endswith(".json")), None)
        list_out = next(
            (o for o in outs if o.filename.startswith("candidate_list_") and o.filename.endswith(".json")), None
        )
        if summary_out is None and list_out is None:
            return None
        card: dict[str, Any] = {"summary": None, "rows": None, "revealed": revealed or {}, "practitioners": {}}
        if summary_out is not None:
            try:
                card["summary"] = json.loads(bk.get_object(summary_out.minio_key))
            except (KeyError, ValueError, OSError):
                card["summary"] = None
        # D-273 (PV-3, PV-4): the rows are patient level; an investigator sees them only as delegated ("screen"),
        # and a patient on the opt-out register now is not shown, however old the job (only the count is)
        # D-280 (OD-5): the administrator only under a break-glass grant for this job (``bg``)
        if list_out is not None and (helpers.reads(sess.user, job.ruleset) or bg):
            try:
                cl = json.loads(bk.get_object(list_out.minio_key))
            except (KeyError, ValueError, OSError):
                cl = None
            if cl is not None:
                rows = []
                gone = helpers.gone()
                card["removed"] = 0
                for r in cl.get("rows") or []:
                    if r.get("tier") not in ("high", "review"):
                        continue
                    if str(r.get("pid", "")) in gone:
                        card["removed"] += 1
                        continue
                    unknown = [v["id"] for v in r.get("criteria") or [] if v.get("verdict") == "unknown"]
                    failing = [v["id"] for v in r.get("criteria") or [] if v.get("verdict") == "fail"]
                    quotes = [
                        {
                            "id": v["id"],
                            "verdict": v.get("verdict"),
                            "quote": (v.get("evidence") or {}).get("quote"),
                            "date": (v.get("evidence") or {}).get("quote_date"),
                        }
                        for v in r.get("criteria") or []
                        if (v.get("evidence") or {}).get("quote")
                    ]
                    rows.append(
                        {
                            "pid": r.get("pid", ""),
                            "tier": r.get("tier"),
                            "next_appointment": (r.get("next_appointment") or "")[:16].replace("T", " "),
                            "practitioner": r.get("practitioner_id") or "",
                            "department": r.get("department") or "",
                            "unknown": unknown,
                            "failing": failing,
                            "quotes": quotes,
                            "actions": r.get("actions") or [],
                            "changed": r.get("changed") or [],
                        }
                    )
                order = {"high": 0, "review": 1}
                rows.sort(key=lambda r: (order.get(str(r["tier"]), 2), r["next_appointment"] or "9", r["pid"]))
                card["rows"] = rows
        card["practitioners"] = (card["summary"] or {}).get("practitioner_names") or {}
        return card

    @app.post("/pilot/jobs/{job_id}/reveal")
    def job_reveal(
        request: Request,
        job_id: str,
        csrf: str = Form(""),
        pid: str = Form(""),
        reason: str = Form(""),
        note: str = Form(""),
    ) -> Response:
        """One chart number for one listed pseudonym, shown once on the page (D-99): a thin handler over the one reveal
        path (T-103, D-438), with the job so that a break-glass grant for this job counts."""
        sess = need(request)
        job = _job_or_404(job_id)
        _need_role(request, csrf, True, sess)
        helpers.reveal.guard(sess, job.ruleset, request.url.path, "screening_list", reason, "job", job.job_id)
        if job.type not in ("SCREEN", "MICROBATCH") or job.state != "done":
            raise _Problem(409, "request.refused", reason="chart numbers are revealed for finished screening jobs only")
        pid = pid.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", pid):
            raise _Problem(400, "request.refused", reason="bad pseudonym")
        if not job.ruleset:
            raise _Problem(403, "forbidden")
        got = helpers.reveal.identifier(sess, job.ruleset, pid, "screening_list", reason, note=note, via="job",
                                        path=request.url.path, job_id=job.job_id)  # fmt: skip
        return _job_page(request, sess, job, revealed={pid: got.mrn})

    def _case_card(job: Job) -> dict[str, Any] | None:
        if job.type != "CASE" or job.state != "done":
            return None
        import json

        outs = [o for o in job.outputs or [] if o.filename.startswith("case_")]
        rec_out = next((o for o in outs if o.filename.endswith(".json")), None)
        sheet = next((o for o in outs if o.filename.endswith(".html")), None)
        if rec_out is None or sheet is None:
            return None
        try:
            rec = json.loads(bk.get_object(rec_out.minio_key))
        except (KeyError, ValueError, OSError):
            return None
        return {
            "counts": rec.get("counts") or {},
            "sheet": sheet.filename,
            "lang": rec.get("lang"),
            "subject": rec.get("subject") or {},
        }

    def phi_download_ok(sess: Session, job: Job, out: JobOutput) -> bool:
        """D-369 (OD-1, PV-18): the guarded download of link mode. A patient-level file leaves by the browser only
        to a person the job mailed it to (its named recipients, by the account's mailbox), who may read patient data
        (coordinator or investigator) for that study. The administrator, viewers and every other account never."""
        box = (sess.user.mailbox or "").strip().lower()
        named = {r.strip().lower() for r in out.recipients}
        return (
            out.tag == "phi"
            and bool(box)
            and box in named
            and sess.user.can_view_phi
            and sess.user.sees_study(job.ruleset or "")
            and helpers.delegated_ok(sess.user, job.ruleset)
        )

    @app.get("/pilot/jobs/{job_id}/files/{filename}")
    def job_file(request: Request, job_id: str, filename: str) -> Response:
        sess = need(request)
        job = _job_or_404(job_id)
        if not _FILE.match(filename):
            raise _Problem(404, "notfound")
        out = next((o for o in job.outputs or [] if o.filename == filename), None)
        # patient-level files leave by the browser only to their named recipients (D-369 guarded download)
        if out is None or (out.tag != "aggregate" and not phi_download_ok(sess, job, out)):
            raise _Problem(404, "notfound")
        if out.tag == "phi" and filename.lower().endswith(".xlsx"):  # every listed patient's chart number
            data = helpers.reveal.workbook(sess, job, out, request.url.path)  # T-103 (D-438): the one path
        else:
            data = bk.get_object(out.minio_key)
        au.append(
            "console.download",
            job_id=job_id,
            actor=actor(sess),
            output_sha=sha256_bytes(data),
            detail={"filename": filename, "tag": out.tag},
        )
        level = level_of_tag(out.tag)
        record_export(au, channel="console_download", filename=filename, data=data, identifier_level=level,
                      approval=f"console role {sess.user.role}; {out.tag} output of job {job_id}"
                      + ("; named recipient (D-369)" if out.tag == "phi" else ""),
                      recipients=[sess.user.mailbox] if out.tag == "phi" and sess.user.mailbox else (),
                      actor=actor(sess), ruleset=job.ruleset, job_id=job_id)  # fmt: skip
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

    def _request_page(request: Request, sess: Session, status: int = 200, **ctx: Any) -> HTMLResponse:
        approved = [
            r
            for r in bk.rulesets()
            if r.status == "approved"
            and (not settings.studies or r.id in settings.studies)
            and sess.user.sees_study(r.id)
        ]  # D-120: this site's own studies, and only those the account may see
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
        pract: str = Form(""),
    ) -> Response:
        sess = need_runner(request, csrf, kind if kind in ("FEAS", "SCREEN") else "FEAS", ruleset)  # T-512
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
        if kind == "SCREEN" and pract.strip():  # D-108: a cohort study's list names the clinics it reads
            ids = re.sub(r"\s+", "", pract).upper().strip(",")
            if not re.fullmatch(r"[A-Z0-9_-]{1,32}(,[A-Z0-9_-]{1,32}){0,19}", ids):
                raise _Problem(
                    400, "request.refused", reason="practitioner ids are letters and digits, comma separated"
                )
            parts.append(f"pract={ids}")
        job = submit(sess, " ".join(parts))
        return RedirectResponse(f"/pilot/jobs/{job.job_id}", status_code=303)

    @app.post("/pilot/propose", response_class=HTMLResponse)
    def propose_view(request: Request, csrf: str = Form(""), text: str = Form("")) -> Response:
        sess = need_requester(request, csrf)
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
        sess = need_requester(request, csrf)
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
        criteria: str = Form(""),
        protocol: Annotated[UploadFile | None, File()] = None,
    ) -> Response:
        sess = need_requester(request, csrf)
        demo_guard.guard(request, _Problem)  # T-502: no upload or pasted text in demo mode
        rs = ruleset.strip().upper()
        if not _RULESET_ID.match(rs):
            raise _Problem(400, "request.refused", reason="ruleset ids are 1-16 letters, digits, '-' or '_'")
        sample = _sample()
        if criteria.strip() and not (protocol is not None and protocol.filename):
            # S2 (step 1): pasted criteria become a small Markdown protocol with the I/E headings the parser reads
            md = criteria_markdown(criteria)
            if md is None:
                msg = translate(lang_of(request, sess), "protocol.no_criteria")
                return page(request, "protocol.html", sess, 422, sample=sample is not None, error=msg)
            job = submit(sess, f"FEAS {rs}", [("criteria.md", md.encode("utf-8"), "text/markdown")])
            if job.state == "done":  # an in-process box runs it at once: straight to the report (S3)
                return RedirectResponse(f"/studies/{rs}/feasibility", status_code=303)
            return RedirectResponse(f"/pilot/jobs/{job.job_id}", status_code=303)
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

    @app.get("/pilot/consent", response_class=HTMLResponse)
    def consent_form(request: Request) -> Response:
        sess = need(request)
        return page(request, "consent.html", sess, sample=_consent_sample() is not None)

    def _consent_sample() -> Path | None:
        p = settings.consent_sample
        return p if p is not None and p.is_file() else None

    @app.post("/pilot/consent")
    async def consent_submit(
        request: Request,
        csrf: str = Form(""),
        study: str = Form(""),
        use_sample: str = Form(""),
        langs: Annotated[list[str] | None, Form()] = None,
        icf: Annotated[UploadFile | None, File()] = None,
    ) -> Response:
        sess = need_requester(request, csrf)
        demo_guard.guard(request, _Problem)  # T-502: no upload in demo mode
        code = study.strip().upper()
        sample = _consent_sample()

        def again(key: str) -> Response:
            msg = translate(lang_of(request, sess), key)
            return page(request, "consent.html", sess, 422, sample=sample is not None, error=msg, study=code)

        if not _RULESET_ID.match(code):
            raise _Problem(400, "request.refused", reason="study codes are 1-16 letters, digits, '-' or '_'")
        chosen = [lang for lang in ("en", "ja", "zh-TW") if lang in (langs or [])]
        if not chosen:
            return again("consent.need_lang")
        if icf is not None and icf.filename:
            name = re.sub(r"[^\w.\-]+", "_", icf.filename)[-120:]
            data = await icf.read(MAX_UPLOAD + 1)
            ctype = icf.content_type or "application/octet-stream"
        elif use_sample and sample is not None:
            name, data, ctype = sample.name, sample.read_bytes(), "text/markdown"
        else:
            raise _Problem(400, "request.refused", reason="attach the informed-consent form")
        if not data:
            return again("consent.empty")
        if len(data) > MAX_UPLOAD or not name.lower().endswith(DOC_EXT):
            raise _Problem(400, "request.refused", reason="consent forms are PDF, DOCX, TXT or MD, at most 50 MB")
        job = submit(sess, f"CONSENT {code} lang={','.join(chosen)}", [(name, data, ctype)])
        return RedirectResponse(f"/pilot/jobs/{job.job_id}", status_code=303)

    # ------------------------------------------------------------------ single case (CASE, D-91)
    def _trial_rulesets() -> list[Any]:
        """Approved trial rulesets: a single-case check is against a trial, never a cohort or NHI ruleset (M8)."""
        return [r for r in bk.rulesets() if r.status == "approved" and r.kind in ("trial", "")]

    @app.get("/pilot/case", response_class=HTMLResponse)
    def case_form(request: Request, ruleset: str = "") -> Response:
        sess = need(request)
        return page(request, "case.html", sess, rulesets=_trial_rulesets(), selected=ruleset, langs=LANGS)

    @app.post("/pilot/case")
    async def case_submit(
        request: Request,
        csrf: str = Form(""),
        ruleset: str = Form(""),
        mrn: str = Form(""),
        lang: str = Form(""),
        charts: Annotated[list[UploadFile] | None, File()] = None,
    ) -> Response:
        sess = need_runner(request, csrf, "CASE", ruleset)  # T-512 (D-349): the PI asks a case question too
        demo_guard.guard(request, _Problem)  # T-502: no chart upload in demo mode
        rs = ruleset.strip().upper()
        if not _RULESET_ID.match(rs):
            raise _Problem(400, "request.refused", reason="choose an approved ruleset")
        files: list[tuple[str, bytes, str]] = []
        for up in charts or []:
            if not up.filename:
                continue
            name = re.sub(r"[^\w.\-]+", "_", up.filename)[-120:]
            data = await up.read(MAX_UPLOAD + 1)
            if not data:
                continue
            if len(data) > MAX_UPLOAD or not name.lower().endswith(DOC_EXT):
                raise _Problem(400, "request.refused", reason="charts are PDF, DOCX, TXT or MD, at most 50 MB each")
            files.append((name, data, up.content_type or "application/octet-stream"))
        if not files:
            msg = translate(lang_of(request, sess), "case.need_file")
            return page(
                request, "case.html", sess, 422, rulesets=_trial_rulesets(), selected=rs, langs=LANGS, error=msg
            )
        parts = ["CASE", rs]
        chart_no = re.sub(r"\s+", "", mrn)
        if chart_no:
            if not re.match(r"^[A-Za-z0-9\-]{1,32}$", chart_no):
                raise _Problem(400, "request.refused", reason="chart numbers are letters, digits or '-'")
            parts.append(f"mrn={chart_no}")
        if lang:
            if lang not in LANGS:
                raise _Problem(400, "request.refused", reason="choose en, ja or zh-TW")
            parts.append(f"lang={lang}")
        job = submit(sess, " ".join(parts), files)
        return RedirectResponse(f"/pilot/jobs/{job.job_id}", status_code=303)

    # ------------------------------------------------------------------ candidate registry (D-92)
    def _registry_page(request: Request, sess: Session, rs: str, status: int = 200, **ctx: Any) -> HTMLResponse:
        gone = helpers.gone()  # D-273 (PV-4): the screening log's page leaves out who opted out, as its export does
        rows = [e for e in bk.registry_rows(rs) if e.pid not in gone]
        from orchestrator.candidates import counts as _counts

        return page(
            request,
            "registry_ruleset.html",
            sess,
            status,
            ruleset=rs,
            rows=rows,
            counts=_counts(rows),
            statuses=STATUSES,
            options=status_options,
            **ctx,
        )

    @app.get("/pilot/registry", response_class=HTMLResponse)
    def registry_home(request: Request) -> Response:
        sess = need(request)
        summaries = {s.ruleset: s for s in bk.registry_summaries()}
        rulesets = _trial_rulesets()
        known = {r.id for r in rulesets}
        # a registry may outlive its ruleset version (e.g. after a re-approval): still list it
        rulesets += [RulesetInfo(rs_id, None, "registry", "trial") for rs_id in sorted(summaries) if rs_id not in known]
        rulesets = [r for r in rulesets if sess.user.sees_study(r.id)]
        summaries = {k: v for k, v in summaries.items() if sess.user.sees_study(k)}
        return page(request, "registry.html", sess, rulesets=rulesets, summaries=summaries, statuses=STATUSES)

    @app.get("/pilot/registry/{ruleset}", response_class=HTMLResponse)
    def registry_view(request: Request, ruleset: str) -> Response:
        sess = need(request)
        rs = ruleset.strip().upper()
        if not _RULESET_ID.match(rs):
            raise _Problem(404, "notfound")
        helpers.delegated(sess, rs, request.url.path)  # D-273 (PV-3): an investigator as delegated only
        if sess.user.is_admin:  # D-280 (OD-5, CR-023): the registry's rows are patient level
            au.append("console.denied", actor=actor(sess), detail={"action": request.url.path[:80]})
            raise _Problem(403, "forbidden")
        try:
            return _registry_page(request, sess, rs)
        except Refused as exc:
            raise _Problem(400, "request.refused", reason=str(exc)) from exc

    @app.post("/pilot/registry/{ruleset}")
    def registry_edit(
        request: Request,
        ruleset: str,
        csrf: str = Form(""),
        pid: str = Form(""),
        mrn: str = Form(""),
        status: str = Form(""),
        reason: str = Form(""),
    ) -> Response:
        sess = need_requester(request, csrf)
        rs = ruleset.strip().upper()
        if not _RULESET_ID.match(rs) or status not in STATUSES:
            raise _Problem(400, "request.refused", reason="choose a ruleset and a status")
        if status in RECORDED_ELSEWHERE:  # D-399 (UX-012): one way to record consent, the consent form
            raise _Problem(
                400, "request.refused", reason="record consent on the participant page: it opens the consent form"
            )
        who = sess.user.mailbox or sess.user.username
        upd = RegistryUpdate(
            pid=pid.strip() or None,
            mrn=re.sub(r"\s+", "", mrn) or None,
            status=status,  # type: ignore[arg-type]
            reason=reason.strip()[:500] or None,
            by=who,
            source="manual",
        )
        au.append(
            "console.registry",
            actor=actor(sess),
            ruleset=rs,
            detail={"action": "update", "status": status, "by_mrn": bool(upd.mrn)},
        )
        try:
            bk.registry_update(rs, upd)
        except Refused as exc:
            return _registry_page(request, sess, rs, 422, error=str(exc))
        return RedirectResponse(f"/pilot/registry/{rs}", status_code=303)

    @app.post("/pilot/registry/{ruleset}/promote")
    def registry_promote(request: Request, ruleset: str, csrf: str = Form("")) -> Response:
        sess = need_requester(request, csrf)
        rs = ruleset.strip().upper()
        if not _RULESET_ID.match(rs):
            raise _Problem(404, "notfound")
        who = sess.user.mailbox or sess.user.username
        try:
            added = bk.registry_promote(rs, RegistryPromote(by=who))
        except Refused as exc:
            return _registry_page(request, sess, rs, 422, error=str(exc))
        au.append("console.registry", actor=actor(sess), ruleset=rs, detail={"action": "promote", "added": added})
        return RedirectResponse(f"/pilot/registry/{rs}?added={added}", status_code=303)

    @app.get("/pilot/jobs/{job_id}/sponsor-pack.zip")
    def sponsor_pack(request: Request, job_id: str) -> Response:
        """One zip a coordinator can send to a sponsor (D-101): the finished FEAS job's aggregate files plus a
        README that names the ruleset version, snapshot, approval record, population and the models that ran. The
        pack never contains a patient-level file; the download is audited."""
        sess = need(request)
        if not (sess.user.can_request or sess.user.sponsor_form):  # D-104: a CRO account gets the sponsor pack
            raise _Problem(403, "forbidden")
        job = _job_or_404(job_id)
        if not sess.user.sees_study(job.ruleset or ""):
            raise _Problem(404, "notfound")
        if job.type != "FEAS" or job.state != "done":
            raise _Problem(404, "notfound")
        files = [(o.filename, bk.get_object(o.minio_key)) for o in job.outputs or [] if o.tag == "aggregate"]
        if not files:
            raise _Problem(404, "notfound")
        detail = bk.ruleset_detail(job.ruleset or "") or {}
        data = build_sponsor_pack(job, files, detail, bk.models())
        au.append(
            "console.export",
            job_id=job_id,
            actor=actor(sess),
            ruleset=job.ruleset,
            output_sha=sha256_bytes(data),
            detail={"action": "sponsor_pack", "files": [n for n, _ in files]},
        )
        approval = f"ruleset {job.ruleset}@{job.ruleset_version}; console role {sess.user.role}"
        record_export(au, channel="console_export", filename=f"sponsor_pack_{job.ruleset}_{job_id}.zip", data=data,
                      identifier_level="aggregate", actor=actor(sess), ruleset=job.ruleset, job_id=job_id,
                      approval=approval)  # fmt: skip
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="sponsor_pack_{job.ruleset}_{job_id}.zip"',
                "X-Download-Options": "noopen",
            },
        )

    @app.get("/pilot/registry/{ruleset}/export.xlsx")
    def registry_export(request: Request, ruleset: str, reason: str = "", note: str = "") -> Response:
        """The study's screening log with every chart number: through the one reveal path (T-103, D-438): own rights
        and the delegation log (D-273 PV-5), a reason, one use of the cap, one record with the count; the
        orchestrator checks the signed role and studies again and keeps its export cap (S-09)."""
        sess = need(request)
        rs = ruleset.strip().upper()
        if not _RULESET_ID.match(rs):
            raise _Problem(404, "notfound")

        def requested() -> None:  # D-273: audited before the file is built, once the rule has let it through
            au.append("console.registry", actor=actor(sess), ruleset=rs,
                      detail={"action": "export_requested", "role": sess.user.role})  # fmt: skip

        data = helpers.reveal.screening_log(sess, rs, reason, note=note[:300], path=request.url.path,
                                            before=requested)  # fmt: skip
        au.append(
            "console.registry",
            actor=actor(sess),
            ruleset=rs,
            output_sha=sha256_bytes(data),
            detail={"action": "export"},
        )
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="screening_log_{rs}.xlsx"',
                "X-Download-Options": "noopen",
            },
        )

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
        sess = need_requester(request, csrf)
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
        record_export(au, channel="console_download", filename=path.name, data=data, identifier_level="aggregate",
                      approval=f"released (D1) cascade numbers of run {run.run_id}; console role {sess.user.role}",
                      actor=actor(sess), ruleset=run.trial)  # fmt: skip
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
        sess = need_requester(request, csrf)
        demo_guard.guard(request, _Problem)  # T-502: no attachment or pasted mail text in demo mode
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
