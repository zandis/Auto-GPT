"""Console unit tests (FastAPI TestClient, in-memory backend): sign-in, sessions, CSRF, roles, the pilot gate, the
request paths (exact line, form, proposal, protocol, approval) and the display rules (no patient-level downloads,
small cells)."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from channels.base import ClassifiedIntent
from console.app import PilotRefused, cell, create_app
from console.auth import UserStore, hash_password, verify_password
from console.backend import AuditRecord, Health, MailItem, Refused, RulesetInfo, read_audit
from console.cascade import CascadeRuns
from console.i18n import CATALOGUES, EN
from console.proposals import ProposalError, propose
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog, verify
from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobCreate, JobFile, JobOutput

ADMIN_PW = "correct-horse-battery-1"
VIEWER_PW = "viewer-password-0001"
PILOT_ENV = {
    "TB_ENV": "TEST",
    "TB_CONSOLE_PILOT": "1",
    "TB_DATA_CLASS": "D0",
    "TB_CONSOLE_ADMIN_EMAIL": "admin@hospa.test",
    "TB_CONSOLE_TEST_SMTP": "greenmail:3025",
    "TB_CONSOLE_WEBMAIL_URL": "http://127.0.0.1:8025",
}
FEAS_JSON = {
    "ruleset": "GZQO",
    "version": "1.0.0",
    "snapshot": "2026-10-04",
    "population": "hospital",
    "lookback_months": 36,
    "start_n": 600,
    "funnel": [
        {"criterion_id": "GZQO-INC-01", "label": "Gout", "remaining": 120, "dropped": 480, "pct": 20.0},
        {"criterion_id": "GZQO-INC-02", "label": "Flares", "remaining": 3, "dropped": 117, "pct": 0.5},
        {"criterion_id": "GZQO-EXC-01", "label": "Dialysis", "remaining": "<5", "dropped": "<5", "pct": None},
    ],
    "sensitivity": [],
    "monthly_new": [],
    "simulation": {"months": 12, "low": 1, "mid": 2, "high": 4},
    "notes": [],
}


def _ulid(n: int) -> str:
    return f"01JTEST{n:019d}"[:26].replace("I", "1").replace("L", "1").replace("O", "0").replace("U", "V")


class FakeBackend:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.objects: dict[str, bytes] = {}
        self.created: list[JobCreate] = []
        self.mails: list[tuple[str, str, str, list[tuple[str, bytes]]]] = []
        self.refuse: str | None = None
        self.audit_dir: Path | None = None
        self.ingested = 0

    def add_job(self, job: Job) -> Job:
        self.jobs[job.job_id] = job
        return job

    def list_jobs(self, limit: int = 100) -> list[Job]:
        return list(self.jobs.values())[:limit]

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def create_job(self, req: JobCreate) -> Job:
        if self.refuse:
            raise Refused(self.refuse)
        self.created.append(req)
        now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
        job = Job(
            job_id=req.job_id or _ulid(len(self.jobs) + 1),
            type=req.type,
            ruleset=req.ruleset,
            requested_by=req.requested_by,
            received_at=now,
            updated_at=now,
            state="received",
            options=dict(req.options or {}),
            inputs=list(req.inputs or []),
            outputs=[],
        )
        return self.add_job(job)

    def put_input(self, job_id: str, filename: str, data: bytes, content_type: str) -> JobFile:
        key = f"attachments/{job_id}/{filename}"
        self.objects[key] = data
        return JobFile(filename=filename, sha256=sha256_bytes(data), minio_key=key, content_type=content_type)

    def get_object(self, key: str) -> bytes:
        return self.objects[key]

    def thread(self, job_id: str) -> list[MailItem]:
        return [
            MailItem(
                "out",
                "2026-10-25T09:00:05+08:00",
                f"Received {job_id} — FEAS GZQO",
                "admin@hospa.test",
                "aggregate",
                "<m1@x>",
            )
        ]

    def audit(self, job_id: str | None = None, limit: int = 200) -> list[AuditRecord]:
        assert self.audit_dir is not None
        return read_audit(self.audit_dir, job_id, limit)

    def rulesets(self) -> list[RulesetInfo]:
        return [RulesetInfo("GZQO", "1.0.0", "approved", "trial"), RulesetInfo("RA-BIO", "1.0.0", "approved", "nhi")]

    def health(self) -> list[Health]:
        return [Health("orchestrator", True, "0 queued or running"), Health("lake", True, "snapshot 2026-10-04")]

    def ingest(self) -> dict[str, Any]:
        self.ingested += 1
        return {"passed": True}

    def send_test_mail(self, sender: str, to: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> str:
        self.mails.append((sender, to, subject, files))
        return "<test@hospa.test>"


def _done_feas(backend: FakeBackend) -> Job:
    jid = _ulid(900)
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    stem = "feasibility_GZQO_v1.0.0_2026-10-04"
    outs = []
    for name, data, tag in (
        (f"{stem}.pdf", b"%PDF-1.4 synthetic", "aggregate"),
        (f"{stem}.json", json.dumps(FEAS_JSON).encode(), "aggregate"),
        (f"{stem}.raw.json", b'{"exact": 3}', "phi"),
    ):
        key = f"outputs/{jid}/{name}"
        backend.objects[key] = data
        outs.append(JobOutput(filename=name, sha256=sha256_bytes(data), minio_key=key, recipients=[], tag=tag))  # type: ignore[arg-type]
    return backend.add_job(
        Job(
            job_id=jid,
            type="FEAS",
            ruleset="GZQO",
            ruleset_version="1.0.0",
            requested_by="admin@hospa.test",
            received_at=now,
            updated_at=now,
            state="done",
            options={},
            inputs=[],
            outputs=outs,
        )
    )


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Any]:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    audit = AuditLog(backend.audit_dir)
    users = UserStore(tmp_path / "console" / "console.sqlite")
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    users.create("viewer", "viewer", VIEWER_PW)

    def classify(text: str, language: str) -> ClassifiedIntent:
        if "GZQO" in text and re.search(r"feasib|做得起來", text):
            return ClassifiedIntent(type="FEAS", study="GZQO", lookback_months=36, language="en")
        return ClassifiedIntent(type="UNKNOWN", language="en")

    def runner(source: Path, trial: str, out: Path) -> dict[str, Any]:
        (out / "dl1").mkdir(parents=True)
        (out / "recall").mkdir()
        (out / "cascade").mkdir()
        obj = {
            "cascade": {"data_class": "D1", "n_scope": 600, "n_after": {"S0": 600, "S1": 20, "S5": "<11"}},
            "headline": {"projection_12m": {"p10": 2, "p50": 5}, "recall_sentence": "x"},
        }
        (out / "dl1" / f"DL1_{trial}.json").write_text(json.dumps({"object": obj, "sha256": "0" * 64}))
        (out / "dl1" / f"DL1_{trial}.pdf").write_bytes(b"%PDF-1.4 dl1")
        (out / "recall" / "recall_certificate.json").write_text('{"alpha": 0.05}')
        (out / "cascade" / "final_list.json").write_text('{"patients": ["p1"]}')
        (out / "e2e_summary.json").write_text(
            json.dumps(
                {
                    "certificate_status": "issued",
                    "certificate_statement": "Recall is at least 0.9.",
                    "checks": {"a": True},
                }
            )
        )
        return {"passed": True}

    src = tmp_path / "site-a"
    src.mkdir()
    (src / "patient.csv").write_text("pid\n")
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "GZQO_protocol_v3.pdf").write_bytes(b"%PDF-1.4 protocol")
    (samples / "GZQO_ICF_v2.md").write_text("# Consent\n\nTaking part is voluntary.\n")
    cascades = CascadeRuns(tmp_path / "cascade", src, runner)
    env = {
        **PILOT_ENV,
        "TB_CONSOLE_DIR": str(tmp_path / "console"),
        "TB_CONSOLE_SAMPLES_DIR": str(samples),
        "TB_CONSOLE_CONSENT_SAMPLE": str(samples / "GZQO_ICF_v2.md"),
    }
    app = create_app(env, backend=backend, audit=audit, users=users, classify=classify, cascades=cascades)
    return {"app": app, "backend": backend, "audit": audit, "users": users, "dir": tmp_path}


def login(app: Any, user: str = "admin", pw: str = ADMIN_PW) -> tuple[TestClient, str]:
    c = TestClient(app)
    r = c.get("/login")
    token = re.search(r'name="login_csrf" value="([^"]+)"', r.text)
    assert token
    r = c.post("/login", data={"username": user, "password": pw, "login_csrf": token.group(1)}, follow_redirects=False)
    assert r.status_code == 303, r.text
    page = c.get("/").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)
    assert csrf
    return c, csrf.group(1)


# ---------------------------------------------------------------------------------------------- accounts
def test_password_hash_roundtrip_and_policy(tmp_path: Path) -> None:
    h = hash_password("a-very-long-secret")
    assert h.startswith("scrypt$") and "a-very-long-secret" not in h
    assert verify_password("a-very-long-secret", h) and not verify_password("wrong", h)
    store = UserStore(tmp_path / "u.sqlite")
    with pytest.raises(ValueError, match="12"):
        store.create("x", "admin", "short")


def test_no_default_password_and_bootstrap_from_secret(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    audit = AuditLog(backend.audit_dir)
    users = UserStore(tmp_path / "c.sqlite")
    app = create_app({**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path)}, backend=backend, audit=audit, users=users)
    c = TestClient(app)
    assert "bootstrap-admin" in c.get("/login").text  # nobody can sign in until an administrator is created
    for pw in ("admin", "trialbox", "password", "changeme"):
        tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
        assert tok
        r = c.post("/login", data={"username": "admin", "password": pw, "login_csrf": tok.group(1)})
        assert r.status_code == 401
    secret = tmp_path / "admin_pw"
    secret.write_text("first-start-secret-42\n")
    app2 = create_app(
        {**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path), "TB_CONSOLE_ADMIN_PASSWORD_FILE": str(secret)},
        backend=backend,
        audit=audit,
        users=users,
    )
    login(app2, "admin", "first-start-secret-42")
    assert users.get("admin") is not None and users.get("admin").mailbox == "admin@hospa.test"  # type: ignore[union-attr]


def test_lockout_after_five_failures(box: dict[str, Any]) -> None:
    users: UserStore = box["users"]
    for _ in range(5):
        assert users.authenticate("admin", "nope-nope-nope") is None
    assert users.locked("admin")
    assert users.authenticate("admin", ADMIN_PW) is None  # locked even with the right password


def test_session_idle_timeout(tmp_path: Path) -> None:
    t = [datetime(2026, 10, 25, 9, 0, tzinfo=UTC)]
    store = UserStore(tmp_path / "s.sqlite", clock=lambda: t[0])
    user = store.create("a", "admin", ADMIN_PW)
    token, _ = store.new_session(user)
    assert store.session(token) is not None
    t[0] += timedelta(minutes=31)
    assert store.session(token) is None


@pytest.mark.req("FR-SIG-14")
def test_security_headers_and_cookie_flags(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])
    r = c.get("/login")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "script-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    tok = re.search(r'name="login_csrf" value="([^"]+)"', r.text)
    assert tok
    r = c.post(
        "/login", data={"username": "admin", "password": ADMIN_PW, "login_csrf": tok.group(1)}, follow_redirects=False
    )
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie


def test_login_requires_login_csrf(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])
    r = c.post("/login", data={"username": "admin", "password": ADMIN_PW, "login_csrf": "forged"})
    assert r.status_code == 400


def test_pages_require_login(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])
    for path in ("/", "/jobs", "/audit", "/pilot/request", f"/pilot/jobs/{_ulid(1)}"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", path


@pytest.mark.req("FR-SIG-14")
def test_csrf_required_on_every_post(box: dict[str, Any]) -> None:
    c, _ = login(box["app"])
    for path, data in (
        ("/pilot/request", {"kind": "FEAS", "ruleset": "GZQO"}),
        ("/pilot/propose", {"text": "FEAS GZQO"}),
        ("/ops/ingest", {}),
        ("/logout", {}),
    ):
        r = c.post(path, data={**data, "csrf": "wrong"})
        assert r.status_code == 400, path
    assert box["backend"].created == [] and box["backend"].ingested == 0


def test_viewer_cannot_start_or_operate(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"], "viewer", VIEWER_PW)
    assert "viewer" in c.get("/").text
    for path, data in (
        ("/pilot/request", {"kind": "FEAS", "ruleset": "GZQO"}),
        ("/pilot/propose", {"text": "FEAS GZQO"}),
        ("/pilot/protocol", {"ruleset": "X1", "use_sample": "1"}),
        ("/pilot/cascade", {"trial": "GZQO"}),
        ("/pilot/mailbox", {"subject": "FEAS GZQO"}),
        ("/ops/ingest", {}),
    ):
        r = c.post(path, data={**data, "csrf": csrf})
        assert r.status_code == 403, path
    assert box["backend"].created == [] and box["backend"].mails == [] and box["backend"].ingested == 0
    events = [r.event for r in read_audit(box["dir"] / "audit")]
    assert events.count("console.denied") == 6
    page = c.get("/pilot/request").text
    assert 'data-testid="start-feas" disabled' in page or "disabled" in page


# ---------------------------------------------------------------------------------------------- request paths
@pytest.mark.req("FR-UX-10")
def test_feas_form_becomes_the_email_jobcreate(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    r = c.post(
        "/pilot/request",
        data={"csrf": csrf, "kind": "FEAS", "ruleset": "gzqo", "lookback": "36"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    (req,) = box["backend"].created
    assert req.type == "FEAS" and req.ruleset == "GZQO" and req.options == {"lookback": "36"}
    assert req.requested_by == "admin@hospa.test"  # the admin's mailbox: settings.permissions apply as for e-mail
    page = c.get(r.headers["location"]).text
    assert "FEAS GZQO lookback=36" in page  # the equivalent e-mail subject is printed
    rec = next(x for x in read_audit(box["dir"] / "audit") if x.event == "console.request")
    assert rec.actor == "console:admin" and rec.detail["line"] == "FEAS GZQO lookback=36"


def test_feas_lookback_out_of_range_stays_on_the_form(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    for bad in ("0", "999", "abc"):
        r = c.post("/pilot/request", data={"csrf": csrf, "kind": "FEAS", "ruleset": "GZQO", "lookback": bad})
        assert r.status_code == 422 and "1 to 120" in r.text and 'data-testid="request-error"' in r.text
    assert box["backend"].created == []  # no job that would fail a step later


def test_screen_form_runs_the_approved_version(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    assert 'name="version"' not in c.get("/pilot/request").text  # the ruleset list already carries the version
    r = c.post("/pilot/request", data={"csrf": csrf, "kind": "SCREEN", "ruleset": "GZQO"}, follow_redirects=False)
    assert r.status_code == 303
    rec = next(x for x in read_audit(box["dir"] / "audit") if x.event == "console.request")
    assert rec.detail["line"] == "SCREEN GZQO version=1.0.0"


def test_empty_protocol_file_is_refused_on_the_form(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    files = {"protocol": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    r = c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "E1"}, files=files)
    assert r.status_code == 422 and 'data-testid="protocol-error"' in r.text
    assert box["backend"].created == []


def test_sentence_starting_with_a_command_word_goes_to_the_model() -> None:
    def classify(text: str, language: str) -> ClassifiedIntent:
        return ClassifiedIntent(type="FEAS", study="GZQO", language="en")

    assert propose("FEAS for GZQO or RA-BIO?", "en", classify).line == "FEAS GZQO"
    with pytest.raises(ProposalError, match="key=value"):  # a malformed exact line still gets the parser message
        propose("FEAS GZQO lookback", "en", classify)


def test_state_badges_are_translated_but_keep_the_machine_state(box: dict[str, Any]) -> None:
    job = _done_feas(box["backend"])
    c, csrf = login(box["app"])
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    page = c.get(f"/pilot/jobs/{job.job_id}").text
    assert 'data-testid="job-state" data-state="done">完了<' in page
    assert "日本語" in page and "繁體中文" in page  # languages by their own names


def test_orchestrator_refusal_is_shown_and_audited(box: dict[str, Any]) -> None:
    box["backend"].refuse = "admin@hospa.test is not permitted to run SCREEN"
    c, csrf = login(box["app"])
    r = c.post("/pilot/request", data={"csrf": csrf, "kind": "SCREEN", "ruleset": "GZQO", "version": "1.0.0"})
    assert r.status_code == 403 and "not permitted" in r.text
    assert any(x.event == "console.refused" for x in read_audit(box["dir"] / "audit"))


@pytest.mark.req("FR-UX-10", "FR-UX-9")
def test_free_text_becomes_a_proposal_and_runs_only_after_confirm(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    text = "Is GZQO feasible at our hospital? patient MRN 12345678"
    r = c.post("/pilot/propose", data={"csrf": csrf, "text": text})
    assert r.status_code == 200
    assert "FEAS GZQO lookback=36" in r.text and "12345678" not in r.text  # free text never echoed back
    assert box["backend"].created == []  # nothing runs on a proposal
    pid = re.search(r"/pilot/propose/([^/]+)/confirm", r.text)
    assert pid
    r = c.post(f"/pilot/propose/{pid.group(1)}/confirm", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert [x.type for x in box["backend"].created] == ["FEAS"]
    r = c.post(f"/pilot/propose/{pid.group(1)}/confirm", data={"csrf": csrf})
    assert r.status_code == 410  # a proposal runs once
    log = (box["dir"] / "audit").read_text() if (box["dir"] / "audit").is_file() else ""
    raw = "".join(p.read_text() for p in (box["dir"] / "audit").glob("*.jsonl")) + log
    assert "12345678" not in raw  # only the text's hash is audited


def test_exact_line_needs_no_model_and_bad_line_gets_parser_message() -> None:
    p = propose("FEAS GZQO lookback=24m", "en", None)
    assert p.line == "FEAS GZQO lookback=24" and p.source == "grammar"
    assert propose("APPROVE GZQO version=1.0.0", "en", None).line == "APPROVE GZQO version=1.0.0"
    with pytest.raises(ProposalError, match="key=value"):
        propose("FEAS GZQO lookback", "en", None)
    with pytest.raises(ProposalError, match="not available"):
        propose("can we run gout trials", "en", None)


def test_protocol_upload_and_approve_loop(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    files = {"protocol": ("demo.pdf", io.BytesIO(b"%PDF-1.4 demo"), "application/pdf")}
    r = c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "gzqo-demo"}, files=files, follow_redirects=False)
    assert r.status_code == 303
    feas = box["backend"].created[-1]
    assert feas.type == "FEAS" and feas.ruleset == "GZQO-DEMO" and feas.inputs[0].filename == "demo.pdf"
    assert box["backend"].objects[feas.inputs[0].minio_key] == b"%PDF-1.4 demo"
    # the compiler answered with a review round: the job waits for approval with the review workbook
    job = box["backend"].jobs[feas.job_id or ""]
    key = f"outputs/{job.job_id}/review_GZQO-DEMO_v1.0.0_r1.xlsx"
    box["backend"].objects[key] = b"PK-review"
    out = JobOutput(
        filename="review_GZQO-DEMO_v1.0.0_r1.xlsx",
        sha256=sha256_bytes(b"PK-review"),
        minio_key=key,
        recipients=["admin@hospa.test"],
        tag="aggregate",
    )
    box["backend"].jobs[job.job_id] = job.model_copy(
        update={"state": "awaiting_approval", "ruleset_version": "1.0.0", "outputs": [out]}
    )
    page = c.get(f"/pilot/jobs/{job.job_id}").text
    assert 'data-testid="review"' in page
    r = c.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    appr = box["backend"].created[-1]
    assert appr.type == "APPROVE" and appr.ruleset == "GZQO-DEMO" and appr.options == {"version": "1.0.0"}
    assert box["backend"].objects[appr.inputs[0].minio_key] == b"PK-review"


def test_protocol_sample_and_bad_upload(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    r = c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "S1", "use_sample": "1"}, follow_redirects=False)
    assert r.status_code == 303 and box["backend"].created[-1].inputs[0].filename == "GZQO_protocol_v3.pdf"
    files = {"protocol": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    r = c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "S2"}, files=files)
    assert r.status_code == 400


# ---------------------------------------------------------------------------------------------- consent explainer
def _consent_done(backend: FakeBackend, jid: str) -> Job:
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    rec = {
        "counts": {"items": 12, "questions": 3, "removed": 1, "held": 2, "unverified": 0, "ok": 40},
        "verified": True,
    }
    files = {
        "consent_GZQO.json": json.dumps(rec).encode(),
        "consent_GZQO_review.html": b"<!doctype html><title>review</title><style>p{}</style>",
        "consent_GZQO_en_DRAFT.html": b"<!doctype html><p>DRAFT</p>",
        "consent_GZQO_ja_DRAFT.html": b"<!doctype html><p>DRAFT</p>",
    }
    outs = []
    for name, data in files.items():
        backend.objects[f"outputs/{jid}/{name}"] = data
        outs.append(
            JobOutput(
                filename=name,
                sha256=sha256_bytes(data),
                minio_key=f"outputs/{jid}/{name}",
                recipients=["admin@hospa.test"],
                tag="aggregate",
            )
        )
    return backend.add_job(
        Job(
            job_id=jid,
            type="CONSENT",
            ruleset="GZQO",
            requested_by="admin@hospa.test",
            received_at=now,
            updated_at=now,
            state="done",
            options={"lang": "en,ja"},
            outputs=outs,
        )
    )


def test_consent_form_sample_upload_and_languages(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    page = c.get("/pilot/consent").text
    assert 'data-testid="consent-notice"' in page and "not the consent form" in page and "use_sample" in page
    data = {"csrf": csrf, "study": "gzqo", "use_sample": "1", "langs": ["en", "zh-TW"]}
    r = c.post("/pilot/consent", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    req = box["backend"].created[-1]
    assert req.type == "CONSENT" and req.ruleset == "GZQO" and req.options == {"lang": "en,zh-TW"}
    assert req.inputs[0].filename == "GZQO_ICF_v2.md"
    files = {"icf": ("icf.docx", io.BytesIO(b"PK docx"), "application/octet-stream")}
    r = c.post(
        "/pilot/consent", data={"csrf": csrf, "study": "S1", "langs": ["ja"]}, files=files, follow_redirects=False
    )
    assert r.status_code == 303 and box["backend"].created[-1].options == {"lang": "ja"}
    r = c.post("/pilot/consent", data={"csrf": csrf, "study": "S1", "use_sample": "1"})
    assert r.status_code == 422 and "at least one language" in r.text
    files = {"icf": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    assert c.post("/pilot/consent", data={"csrf": csrf, "study": "S1", "langs": ["en"]}, files=files).status_code == 400
    viewer, vcsrf = login(box["app"], "viewer", VIEWER_PW)
    data = {"csrf": vcsrf, "study": "S1", "use_sample": "1", "langs": ["en"]}
    assert viewer.post("/pilot/consent", data=data).status_code == 403


def test_consent_job_card_preview_and_release(box: dict[str, Any]) -> None:
    jid = _ulid(950)
    _consent_done(box["backend"], jid)
    c, csrf = login(box["app"])
    page = c.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="consent"' in page and 'data-testid="release"' in page
    assert "12 statements and 3 questions" in page and "held back by the second model: 2" in page
    assert f"/pilot/jobs/{jid}/view/consent_GZQO_ja_DRAFT.html" in page
    r = c.get(f"/pilot/jobs/{jid}/view/consent_GZQO_review.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp and "default-src 'none'" in csp and "script" not in csp
    assert c.get(f"/pilot/jobs/{jid}/view/consent_GZQO.json").status_code == 404  # html pages only
    assert c.get(f"/pilot/jobs/{jid}/view/other.html").status_code == 404
    assert c.get("/").headers["content-security-policy"].startswith("default-src 'self'")  # the app keeps its own
    r = c.post(f"/pilot/jobs/{jid}/release", data={"csrf": csrf, "drop": "i03, q2", "keep": ""}, follow_redirects=False)
    assert r.status_code == 303
    rel = box["backend"].created[-1]
    assert rel.type == "RELEASE" and rel.options == {"target": jid, "drop": "I03,Q2"} and rel.ruleset is None
    assert c.post(f"/pilot/jobs/{jid}/release", data={"csrf": csrf, "keep": "x;1"}).status_code == 400
    viewer, vcsrf = login(box["app"], "viewer", VIEWER_PW)
    vpage = viewer.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="consent"' in vpage and 'data-testid="release"' not in vpage
    assert viewer.post(f"/pilot/jobs/{jid}/release", data={"csrf": vcsrf}).status_code == 403


# ---------------------------------------------------------------------------------------------- results
def test_result_page_funnel_downloads_and_phi_rule(box: dict[str, Any]) -> None:
    job = _done_feas(box["backend"])
    c, _ = login(box["app"], "viewer", VIEWER_PW)  # viewers read results
    page = c.get(f"/pilot/jobs/{job.job_id}").text
    assert 'data-testid="funnel"' in page and "GZQO-INC-01" in page
    assert ">3<" not in page and "&lt;5" in page  # a count below k is never displayed
    assert "raw.json" in page and "never mailed" in page
    pdf = c.get(f"/pilot/jobs/{job.job_id}/files/feasibility_GZQO_v1.0.0_2026-10-04.pdf")
    assert (
        pdf.status_code == 200
        and pdf.content.startswith(b"%PDF")
        and "attachment" in pdf.headers["content-disposition"]
    )
    assert c.get(f"/pilot/jobs/{job.job_id}/files/feasibility_GZQO_v1.0.0_2026-10-04.raw.json").status_code == 404
    assert c.get(f"/pilot/jobs/{job.job_id}/files/..%2f..%2fetc").status_code == 404
    dl = [r for r in read_audit(box["dir"] / "audit") if r.event == "console.download"]
    assert dl and dl[0].actor == "console:viewer"
    assert "Received" in page  # the e-mail thread is on the page


def test_cell_rule() -> None:
    assert cell(3, 5) == "<5" and cell(0, 5) == "0" and cell(5, 5) == "5" and cell("<11", 5) == "<11"


def test_cascade_run_shows_released_numbers_only(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    r = c.post("/pilot/cascade", data={"csrf": csrf, "trial": "GZQO"}, follow_redirects=False)
    assert r.status_code == 303
    run_url = r.headers["location"]
    import time

    for _ in range(50):
        if 'data-testid="cascade-state" data-state="done"' in c.get(run_url).text:
            break
        time.sleep(0.05)
    page = c.get(run_url).text
    assert "issued" in page and "&lt;11" in page and "S1" in page
    assert c.get(f"{run_url}/files/dl1_pdf").content.startswith(b"%PDF")
    assert c.get(f"{run_url}/files/recall_certificate").status_code == 200
    assert c.get(f"{run_url}/files/cascade_final_list").status_code == 404  # D3 never served
    assert "final_list" not in page


def test_test_mailbox_sends_from_the_admin_mailbox(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    r = c.post("/pilot/mailbox", data={"csrf": csrf, "subject": "FEAS GZQO", "body": "hi"})
    assert r.status_code == 200 and "Sent" in r.text
    assert box["backend"].mails[0][:3] == ("admin@hospa.test", "trialbox@hospa.test", "FEAS GZQO")


def test_ingest_operate_action(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    r = c.post("/ops/ingest", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and box["backend"].ingested == 1


def test_audit_chain_stays_valid(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    c.post("/pilot/request", data={"csrf": csrf, "kind": "FEAS", "ruleset": "GZQO"})
    c.post("/logout", data={"csrf": csrf})
    assert verify(box["dir"] / "audit").ok
    page = login(box["app"])[0].get("/audit").text
    assert "console.login" in page and "console.request" in page


def test_language_switch(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/jobs"})
    assert "ジョブ" in c.get("/jobs").text


@pytest.mark.req("FR-UX-32")
def test_catalogues_complete() -> None:
    for lang, cat in CATALOGUES.items():
        assert set(cat) == set(EN), lang


# ---------------------------------------------------------------------------------------------- surface rules
@pytest.mark.req("FR-UX-12", "FR-UX-21")
@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION"])
def test_pilot_refused_outside_dev_test(env: str, tmp_path: Path) -> None:
    with pytest.raises(PilotRefused):
        create_app(
            {**PILOT_ENV, "TB_ENV": env, "TB_CONSOLE_DIR": str(tmp_path)},
            backend=FakeBackend(),
            audit=AuditLog(tmp_path / "a"),
        )


def test_pilot_refused_without_d0(tmp_path: Path) -> None:
    with pytest.raises(PilotRefused, match="D0"):
        create_app(
            {**PILOT_ENV, "TB_DATA_CLASS": "D3", "TB_CONSOLE_DIR": str(tmp_path)},
            backend=FakeBackend(),
            audit=AuditLog(tmp_path / "a"),
        )


@pytest.mark.req("FR-UX-12", "FR-UX-21")
def test_production_console_has_only_control_plane_routes(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    _done_feas(backend)
    users = UserStore(tmp_path / "c.sqlite")
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    app = create_app(
        {"TB_ENV": "PRODUCTION", "TB_CONSOLE_DIR": str(tmp_path)},
        backend=backend,
        audit=AuditLog(backend.audit_dir),
        users=users,
    )
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.startswith("/pilot") for p in paths)
    assert paths >= {"/", "/login", "/logout", "/jobs", "/audit", "/healthz", "/ops/ingest"}
    c, _ = login(app)
    jobs = c.get("/jobs").text
    assert "/pilot/" not in jobs and "GZQO-INC-01" not in jobs  # metadata only: no study content
    assert c.get(f"/pilot/jobs/{next(iter(backend.jobs))}").status_code == 404


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("How many gout patients could we enrol in GZQO over the last 3 years?", "FEAS GZQO lookback=36"),
        ("請幫我評估GZQO試驗在本院過去三年的可收案人數", "FEAS GZQO lookback=36"),
        ("GZQO試験の過去3年間の候補患者数を教えてください", "FEAS GZQO lookback=36"),
        ("幫我跑 feasibility for GZQO, lookback 24個月", "FEAS GZQO lookback=24"),
    ],
)
def test_proposal_keeps_the_study_and_lookback_the_text_states(text: str, line: str) -> None:
    """A small hosted model often returned FEAS with no study or look-back (stress test 2026-10-25): the console fills
    only those empty fields from the text itself."""
    assert propose(text, "en", lambda _t, _l: ClassifiedIntent(type="FEAS")).line == line
    two = "Could we run GZQO or RA-BIO here?"
    with pytest.raises(ProposalError, match="Which study"):
        propose(two, "en", lambda _t, _l: ClassifiedIntent(type="FEAS"))
