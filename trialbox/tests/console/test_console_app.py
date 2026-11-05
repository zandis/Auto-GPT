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
from tb_contracts import (
    Job,
    JobCreate,
    JobFile,
    JobOutput,
    RegistryEntry,
    RegistryPromote,
    RegistrySummary,
    RegistryUpdate,
)

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


_T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


MODELS_INFO: dict[str, Any] = {
    "engine": "cql",
    "screen_judge": "agreement",
    "gateway": True,
    "mode": "single",
    "judge_model": "j-workhorse",
    "verifier_model": None,
    "note_block": "never",
    "note_block_reason": "no verifier configured: a single model may not exclude",
    "configured_note_block": "both_agree",
    "may_block": False,
    "disagreements": 0,
    "failures": 0,
}


class FakeBackend:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.objects: dict[str, bytes] = {}
        self.created: list[JobCreate] = []
        self.mails: list[tuple[str, str, str, list[tuple[str, bytes]]]] = []
        self.refuse: str | None = None
        self.models_info: dict[str, Any] | None = dict(MODELS_INFO)
        self.revealed: list[tuple[str, str, str]] = []
        self.audit_dir: Path | None = None
        self.ingested = 0
        self.registry: dict[tuple[str, str], RegistryEntry] = {}

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

    def models(self) -> dict[str, Any] | None:
        return self.models_info

    def reveal(self, job_id: str, pid: str, by: str) -> str | None:
        self.revealed.append((job_id, pid, by))
        return {"a" * 32: "MRN-000123"}.get(pid)

    def ingest(self) -> dict[str, Any]:
        self.ingested += 1
        return {"passed": True}

    def send_test_mail(self, sender: str, to: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> str:
        self.mails.append((sender, to, subject, files))
        return "<test@hospa.test>"

    # ---- candidate registry (D-92): an in-memory stand-in for the orchestrator's tables
    def registry_summaries(self) -> list[RegistrySummary]:
        out: dict[str, dict[str, int]] = {}
        for (rs, _), e in self.registry.items():
            out.setdefault(rs, {})[e.status] = out.setdefault(rs, {}).get(e.status, 0) + 1
        return [RegistrySummary(ruleset=rs, counts=c, updated_at=_T0) for rs, c in out.items()]

    def registry_rows(self, ruleset: str) -> list[RegistryEntry]:
        if ruleset == "BAD":
            raise Refused("invalid ruleset id 'BAD'")
        return [e for (rs, _), e in self.registry.items() if rs == ruleset]

    def registry_update(self, ruleset: str, upd: RegistryUpdate) -> RegistryEntry:
        if upd.mrn == "nope":
            raise Refused("that does not look like a chart number of this site")
        pid = upd.pid or ("ab" * 16 if upd.mrn == "A1001" else "cd" * 16)
        prev = self.registry.get((ruleset, pid))
        e = RegistryEntry(
            ruleset=ruleset,
            pid=pid,
            status=upd.status,
            reason=upd.reason,
            updated_at=_T0,
            updated_by=upd.by,
            source=upd.source or "manual",
            source_job=upd.source_job,
            tier=None,
            events=(prev.events or 0) + 1 if prev else 1,
        )
        self.registry[(ruleset, pid)] = e
        return e

    def registry_promote(self, ruleset: str, req: RegistryPromote) -> int:
        n = 0
        for pid in ("11" * 16, "22" * 16):
            if (ruleset, pid) not in self.registry:
                self.registry[(ruleset, pid)] = RegistryEntry(
                    ruleset=ruleset,
                    pid=pid,
                    status="candidate",
                    reason=None,
                    updated_at=_T0,
                    updated_by=req.by,
                    source="screen",
                    source_job=_ulid(900),
                    tier="high",
                    events=1,
                )
                n += 1
        return n

    def registry_export(self, ruleset: str) -> bytes:
        return b"PK\x03\x04fake-xlsx-" + ruleset.encode()


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
    assert req.type == "FEAS" and req.ruleset == "GZQO" and req.options == {"lookback": "36", "lang": "en"}
    assert req.requested_by == "admin@hospa.test"  # the admin's mailbox: settings.permissions apply as for e-mail
    page = c.get(r.headers["location"]).text
    assert "FEAS GZQO lookback=36" in page  # the equivalent e-mail subject is printed
    rec = next(x for x in read_audit(box["dir"] / "audit") if x.event == "console.request")
    assert rec.actor == "console:admin" and rec.detail["line"] == "FEAS GZQO lookback=36 lang=en"


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
    assert rec.detail["line"] == "SCREEN GZQO version=1.0.0 lang=en"


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
    html = (
        b"<table><tr><td>GZQO-DEMO-INC-01</td><td>inclusion</td><td>structured</td></tr>"
        b"<tr><td>GZQO-DEMO-INC-02</td><td>inclusion</td><td>note</td></tr>"
        b"<tr><td>GZQO-DEMO-EXC-01</td><td>exclusion</td><td>human</td></tr></table>"
    )
    hkey = f"outputs/{job.job_id}/review_GZQO-DEMO_v1.0.0_r1.html"
    box["backend"].objects[hkey] = html
    hout = JobOutput(
        filename="review_GZQO-DEMO_v1.0.0_r1.html",
        sha256=sha256_bytes(html),
        minio_key=hkey,
        recipients=["admin@hospa.test"],
        tag="aggregate",
    )
    box["backend"].jobs[job.job_id] = job.model_copy(
        update={"state": "awaiting_approval", "ruleset_version": "1.0.0", "outputs": [hout, out]}
    )
    page = c.get(f"/pilot/jobs/{job.job_id}").text
    assert 'data-testid="review"' in page
    assert "check the 3 criteria: 1 by a fixed filter" in page and "1 by a person at screening" in page
    assert "not a regulated e-signature" in page  # lightweight approval (D-88)
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


# ---------------------------------------------------------------------------------------------- CASE sheet
def _case_done(backend: FakeBackend, jid: str) -> Job:
    """A finished CASE job shaped like the orchestrator writes it: ``counts`` keys are met/not_met/unknown/human."""
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    rec = {
        "counts": {"met": 15, "not_met": 2, "unknown": 3, "human": 3, "total": 23},
        "lang": "ja",
        "subject": {"in_lake": True, "snapshot": "2026-10-04"},
    }
    files = {"case_GZQO.json": json.dumps(rec).encode(), "case_GZQO_ja.html": b"<!doctype html><p>sheet</p>"}
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
            type="CASE",
            ruleset="GZQO",
            requested_by="admin@hospa.test",
            received_at=now,
            updated_at=now,
            state="done",
            options={"lang": "ja"},
            outputs=outs,
        )
    )


def test_case_job_card_renders_counts_in_every_language(box: dict[str, Any]) -> None:
    jid = _ulid(960)
    _case_done(box["backend"], jid)
    c, csrf = login(box["app"])
    page = c.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="case-counts"' in page and "met 15" in page and "not met 2" in page and "for a human 3" in page
    assert f"/pilot/jobs/{jid}/view/case_GZQO_ja.html" in page
    for lang, needle in (("ja", "該当 15"), ("zh-TW", "符合 15")):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        r = c.get(f"/pilot/jobs/{jid}")
        assert r.status_code == 200 and needle in r.text, lang


# ---------------------------------------------------------------------------------------------- coordinator screen
def _done_screen(backend: FakeBackend, jid: str) -> Job:
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    summary = {
        "ruleset": "GZQO",
        "version": "1.0.0",
        "run_date": "2026-10-05",
        "snapshot": "2026-10-04",
        "practitioner_names": {"DR-LIN": "Dr Lin (DR-LIN)"},
        "scope": {"practitioners": ["DR-LIN"], "departments": ["RHEU"], "window_days": 14, "n_scoped": 61},
        "tiers": {"high": 2, "review": 1, "excluded": 58},
        "listed": 3,
        "referrals": {"RHEU": 3},
        "unknown_by_criterion": {"GZQO-INC-05": 1},
        "judging": {"mode": "single", "judge_model": "j-workhorse", "verifier_model": None, "may_block": False},
    }
    rows = [
        {
            "pid": "a" * 32,
            "tier": "high",
            "next_appointment": "2026-10-07T09:30:00+08:00",
            "practitioner_id": "DR-LIN",
            "department": "RHEU",
            "criteria": [
                {"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": []}},
                {
                    "id": "GZQO-INC-05",
                    "verdict": "pass",
                    "evidence": {
                        "resource_refs": [],
                        "quote": "two flares this spring",
                        "quote_date": "2026-04-02",
                        "confidence": 0.9,
                    },
                },
            ],
            "actions": [],
            "n_unknown": 0,
        },
        {
            "pid": "b" * 32,
            "tier": "review",
            "next_appointment": None,
            "practitioner_id": "DR-LIN",
            "department": "RHEU",
            "criteria": [{"id": "GZQO-INC-05", "verdict": "unknown", "evidence": {"resource_refs": []}}],
            "actions": ["confirm flare dates with patient"],
            "n_unknown": 1,
        },
        {"pid": "c" * 32, "tier": "excluded", "criteria": [], "actions": [], "n_unknown": 0},
    ]
    cl = {
        "ruleset": "GZQO",
        "version": "1.0.0",
        "snapshot": "2026-10-04",
        "scope": {},
        "rows": rows,
        "summary": summary["tiers"],
    }
    files = {
        ("screen_candidates_GZQO_v1.0.0_2026-10-05.json", "aggregate"): json.dumps(summary).encode(),
        ("candidate_list_GZQO_v1.0.0.json", "phi"): json.dumps(cl).encode(),
        ("summary_candidates_GZQO_v1.0.0_2026-10-05.pdf", "aggregate"): b"%PDF-1.4 x",
    }
    outs = []
    for (name, tag), data in files.items():
        backend.objects[f"outputs/{jid}/{name}"] = data
        outs.append(
            JobOutput(
                filename=name,
                sha256=sha256_bytes(data),
                minio_key=f"outputs/{jid}/{name}",
                recipients=["pi@hospa.test"],
                tag=tag,  # type: ignore[arg-type]
            )
        )
    return backend.add_job(
        Job(
            job_id=jid,
            type="SCREEN",
            ruleset="GZQO",
            requested_by="admin@hospa.test",
            received_at=now,
            updated_at=now,
            state="done",
            options={},
            outputs=outs,
        )
    )


def test_screen_job_page_shows_candidates_and_reveals_a_chart_number_once(box: dict[str, Any]) -> None:
    jid = _ulid(970)
    _done_screen(box["backend"], jid)
    c, csrf = login(box["app"])
    page = c.get(f"/pilot/jobs/{jid}").text
    assert (
        'data-testid="screen"' in page
        and "2 patients likely eligible, 1 to review, 58 excluded, of 61 in scope" in page
    )
    assert 'data-testid="screen-rows"' in page and page.count("<tr data-pid=") == 2  # excluded rows are not listed
    assert page.index("a" * 12) < page.index("b" * 12)  # likely eligible first
    assert "two flares this spring" in page and "90 %" in page and "Dr Lin" in page and "confirm flare dates" in page
    assert "read by j-workhorse alone" in page and f'href="/pilot/registry/GZQO#p-{"a" * 32}"' in page
    assert page.count('data-testid="reveal"') == 2 and "MRN-000123" not in page
    r = c.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": csrf, "pid": "a" * 32})
    assert r.status_code == 200 and 'data-testid="mrn"' in r.text and "MRN-000123" in r.text
    assert r.text.count('data-testid="reveal"') == 1  # the other row still has its button
    assert box["backend"].revealed == [(jid, "a" * 32, "console:admin")]
    assert any(rec.event == "console.reveal" for rec in box["backend"].audit(jid))
    r = c.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": csrf, "pid": "b" * 32})
    assert r.status_code == 200 and "no chart number on this box" in r.text
    assert c.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": csrf, "pid": "x"}).status_code == 400
    # viewers: counts, no rows, no reveal
    viewer, vcsrf = login(box["app"], "viewer", VIEWER_PW)
    vpage = viewer.get(f"/pilot/jobs/{jid}").text
    assert (
        'data-testid="screen-viewer"' in vpage
        and 'data-testid="screen-rows"' not in vpage
        and "two flares" not in vpage
    )
    assert viewer.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": vcsrf, "pid": "a" * 32}).status_code == 403
    # Japanese
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    assert "適格の可能性が高い 2 名" in c.get(f"/pilot/jobs/{jid}").text


# ---------------------------------------------------------------------------------------------- models card
def test_overview_shows_models_and_the_never_exclude_fallback(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    page = c.get("/").text
    assert 'data-testid="models"' in page and "j-workhorse" in page
    assert 'data-testid="models-warning"' in page and 'data-testid="models-fallback"' in page
    assert "has only one model" in page
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    assert "モデルが一つしかありません" in c.get("/").text
    c.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/"})
    box["backend"].models_info = {
        **MODELS_INFO,
        "mode": "agreement",
        "verifier_model": "v-verifier",
        "note_block": "both_agree",
        "may_block": True,
    }
    page = c.get("/").text
    assert "v-verifier" in page and "Only when both models agree" in page and 'data-testid="models-warning"' not in page
    box["backend"].models_info = None
    assert "orchestrator is not answering" in c.get("/").text


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


# ---------------------------------------------------------------------------------------------- D-91 CASE
def _done_case(backend: FakeBackend) -> Job:
    jid = _ulid(950)
    now = datetime(2026, 10, 25, 9, 5, tzinfo=UTC)
    rec = {
        "lang": "en",
        "subject": {"pid": "ab" * 16, "in_lake": True, "snapshot": "2026-10-04", "note": ""},
        "counts": {"total": 12, "met": 7, "not_met": 1, "unknown": 2, "human": 2},
        "criteria": [],
    }
    outs = []
    for name, data in (
        (f"case_GZQO_{jid}.html", b"<h1>Eligibility sheet</h1><p>2026-03-12 acute gout flare</p>"),
        (f"case_GZQO_{jid}.json", json.dumps(rec).encode()),
    ):
        key = f"outputs/{jid}/{name}"
        backend.objects[key] = data
        outs.append(JobOutput(filename=name, sha256=sha256_bytes(data), minio_key=key, recipients=[], tag="phi"))
    return backend.add_job(
        Job(
            job_id=jid,
            type="CASE",
            ruleset="GZQO",
            ruleset_version="1.0.0",
            requested_by="admin@hospa.test",
            received_at=now,
            updated_at=now,
            state="done",
            options={"lang": "en"},
            inputs=[],
            outputs=outs,
        )
    )


def test_case_form_becomes_the_case_mail_line(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    page = c.get("/pilot/case").text
    assert 'data-testid="case-submit"' in page and "GZQO" in page and 'data-testid="case-notice"' in page
    r = c.post(
        "/pilot/case",
        data={"csrf": csrf, "ruleset": "gzqo", "mrn": " A1001 ", "lang": "zh-TW"},
        files=[("charts", ("chart.md", b"# summary\n2026-03-12 flare", "text/markdown"))],
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    (req,) = box["backend"].created
    assert req.type == "CASE" and req.ruleset == "GZQO"
    assert req.options == {"mrn": "A1001", "lang": "zh-TW"}
    assert [i.filename for i in req.inputs] == ["chart.md"]
    # no file -> the form again with the message, no job
    r = c.post("/pilot/case", data={"csrf": csrf, "ruleset": "GZQO"})
    assert r.status_code == 422 and 'data-testid="case-error"' in r.text and len(box["backend"].created) == 1
    # a bad chart number or language is refused before anything is stored
    r = c.post(
        "/pilot/case",
        data={"csrf": csrf, "ruleset": "GZQO", "mrn": "A 10/01"},
        files=[("charts", ("c.txt", b"x", "text/plain"))],
    )
    assert r.status_code == 400
    r = c.post(
        "/pilot/case",
        data={"csrf": csrf, "ruleset": "GZQO", "lang": "fr"},
        files=[("charts", ("c.txt", b"x", "text/plain"))],
    )
    assert r.status_code == 400 and len(box["backend"].created) == 1


def test_case_sheet_card_and_phi_view_rules(box: dict[str, Any]) -> None:
    job = _done_case(box["backend"])
    c, _ = login(box["app"])
    page = c.get(f"/pilot/jobs/{job.job_id}").text
    assert 'data-testid="case"' in page and "12 criteria" in page and "met 7" in page and "snapshot 2026-10-04" in page
    sheet = re.search(
        r'data-testid="case-sheet" href="([^"]+)"|href="([^"]+)" target="_blank" rel="noopener" data-testid="case-sheet"',
        page,
    )
    assert sheet
    r = c.get(sheet.group(1) or sheet.group(2))
    assert r.status_code == 200 and "acute gout flare" in r.text
    assert "sandbox" in r.headers.get("content-security-policy", "")
    # the viewer sees the counts but cannot open the sheet (chart text)
    v, _ = login(box["app"], "viewer", VIEWER_PW)
    page = v.get(f"/pilot/jobs/{job.job_id}").text
    assert "12 criteria" in page and 'data-testid="case-sheet"' not in page
    assert v.get(f"/pilot/jobs/{job.job_id}/view/case_GZQO_{job.job_id}.html").status_code == 404
    # a phi output of any other job type is never viewable, even for an administrator
    feas = _done_feas(box["backend"])
    assert c.get(f"/pilot/jobs/{feas.job_id}/view/feasibility_GZQO_v1.0.0_2026-10-04.raw.json").status_code == 404


# ---------------------------------------------------------------------------------------------- D-92 registry
def test_registry_pages_add_promote_export(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    page = c.get("/pilot/registry").text
    assert 'data-testid="registry-summary"' in page and "GZQO" in page
    page = c.get("/pilot/registry/GZQO").text
    assert 'data-testid="registry-empty"' in page and 'data-testid="registry-add"' in page
    r = c.post(
        "/pilot/registry/GZQO",
        data={"csrf": csrf, "mrn": "A1001", "status": "candidate", "reason": "referred by Dr Lin"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = c.get("/pilot/registry/GZQO").text
    assert 'data-testid="registry-rows"' in page and "referred by Dr Lin" in page and "A1001" not in page
    assert 'data-pid="' + "ab" * 16 + '"' in page
    # the row's own status form offers only recorded transitions
    assert '<option value="enrolled"' not in page.split('data-pid="')[1]
    # change the status by pseudonym
    r = c.post(
        "/pilot/registry/GZQO",
        data={"csrf": csrf, "pid": "ab" * 16, "status": "contacted", "reason": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert box["backend"].registry[("GZQO", "ab" * 16)].status == "contacted"
    # a refusal from the orchestrator comes back on the page, not as a crash
    r = c.post("/pilot/registry/GZQO", data={"csrf": csrf, "mrn": "nope", "status": "candidate"})
    assert r.status_code == 422 and 'data-testid="registry-error"' in r.text and "chart number" in r.text
    # promote SCREEN candidates
    r = c.post("/pilot/registry/GZQO/promote", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("?added=2")
    page = c.get(r.headers["location"]).text
    assert 'data-testid="registry-added"' in page and "2 candidates added" in page and "SCREEN run" in page
    counts = re.search(r'data-testid="registry-counts">(.*?)</p>', page, re.S)
    assert counts and "candidate 2" in counts.group(1) and "contacted 1" in counts.group(1)
    # the summary page counts them
    page = c.get("/pilot/registry").text
    assert 'data-testid="registry-summary"' in page
    # export carries chart numbers: requesters only, audited
    r = c.get("/pilot/registry/GZQO/export.xlsx")
    assert (
        r.status_code == 200
        and r.content.startswith(b"PK")
        and "screening_log_GZQO.xlsx" in r.headers["content-disposition"]
    )
    assert c.get("/pilot/registry/BAD").status_code == 400
    events = [e.event for e in read_audit(box["dir"] / "audit")]
    assert events.count("console.registry") == 5  # 2 updates + 1 refused update + promote + export
    assert verify(box["dir"] / "audit").ok


def test_viewer_reads_registry_but_cannot_change_or_export(box: dict[str, Any]) -> None:
    v, csrf = login(box["app"], "viewer", VIEWER_PW)
    assert v.get("/pilot/registry").status_code == 200 and v.get("/pilot/registry/GZQO").status_code == 200
    assert v.post("/pilot/registry/GZQO", data={"csrf": csrf, "mrn": "A1001", "status": "candidate"}).status_code == 403
    assert v.post("/pilot/registry/GZQO/promote", data={"csrf": csrf}).status_code == 403
    assert v.get("/pilot/registry/GZQO/export.xlsx").status_code == 403
    assert v.post("/pilot/case", data={"csrf": csrf, "ruleset": "GZQO"}).status_code == 403
    assert box["backend"].registry == {}


# ---------------------------------------------------------------------------------------------- D-93 roles and SSO
def test_coordinator_requests_and_approves_but_does_not_operate(box: dict[str, Any]) -> None:
    box["users"].create("crc", "coordinator", "crc-password-1234", "crc1@hospa.test")
    c, csrf = login(box["app"], "crc", "crc-password-1234")
    assert "study coordinator" in c.get("/").text
    r = c.post(
        "/pilot/request",
        data={"csrf": csrf, "kind": "FEAS", "ruleset": "GZQO", "lookback": "36"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert box["backend"].created[-1].requested_by == "crc1@hospa.test"
    r = c.post(
        "/pilot/registry/GZQO", data={"csrf": csrf, "mrn": "A1001", "status": "candidate"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert c.post("/ops/ingest", data={"csrf": csrf}).status_code == 403
    assert c.get("/ops/users").status_code == 403
    assert (
        c.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "x", "role": "admin"}).status_code == 403
    )
    assert "/ops/users" not in c.get("/").text  # no link either


def test_users_page_add_reset_disable(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    page = c.get("/ops/users").text
    assert 'data-testid="users-table"' in page and 'data-user="viewer"' in page and "/ops/users" in c.get("/").text
    r = c.post(
        "/ops/users",
        data={
            "csrf": csrf,
            "action": "add",
            "username": "Nurse.Lin",
            "role": "coordinator",
            "mailbox": "lin@hospa.test",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 and "made=nurse.lin" in r.headers["location"]
    page = c.get(r.headers["location"]).text
    pw = re.search(r'data-testid="users-pw">([^<]+)<', page)
    assert pw and len(pw.group(1)) >= 12 and 'data-user="nurse.lin"' in page
    n, _ = login(box["app"], "nurse.lin", pw.group(1))  # the one-time password works once handed over
    assert "study coordinator" in n.get("/").text
    # reset signs the person out everywhere and shows a new password once
    r = c.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "nurse.lin"}, follow_redirects=False)
    assert r.status_code == 303
    assert n.get("/", follow_redirects=False).status_code == 303  # session gone
    pw2 = re.search(r'data-testid="users-pw">([^<]+)<', c.get(r.headers["location"]).text)
    assert pw2 and pw2.group(1) != pw.group(1)
    # cannot disable yourself; can disable others; duplicates and bad roles are refused with a reason
    assert c.post("/ops/users", data={"csrf": csrf, "action": "disable", "username": "admin"}).status_code == 400
    r = c.post("/ops/users", data={"csrf": csrf, "action": "disable", "username": "nurse.lin"}, follow_redirects=False)
    assert r.status_code == 303 and 'data-user="nurse.lin"' not in c.get("/ops/users").text
    assert (
        c.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "viewer", "role": "viewer"}).status_code
        == 400
    )
    assert (
        c.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "z", "role": "root"}).status_code == 400
    )
    events = [e.event for e in read_audit(box["dir"] / "audit")]
    assert events.count("console.user") == 3


SSO_ENV = {
    **PILOT_ENV,
    "TB_CONSOLE_SSO_HEADER": "X-Forwarded-User",
    "TB_CONSOLE_SSO_ROLE_HEADER": "X-Forwarded-Groups",
    "TB_CONSOLE_SSO_TRUSTED_PROXIES": "testclient,127.0.0.1,10.0.0.0/8",
    "TB_CONSOLE_SSO_ROLE_MAP": "trialbox-admins:admin,crc:coordinator",
}


def test_sso_header_signs_in_from_a_trusted_proxy_only(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore(tmp_path / "c.sqlite")
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    app = create_app(
        {**SSO_ENV, "TB_CONSOLE_DIR": str(tmp_path)}, backend=backend, audit=AuditLog(backend.audit_dir), users=users
    )
    # TestClient's peer address is the literal "testclient", so it is listed among the trusted proxies above
    c = TestClient(app, headers={"X-Forwarded-User": "Nurse.Lin@hospa.test", "X-Forwarded-Groups": "staff;crc"})
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 200 and "nurse.lin" in r.text and "study coordinator" in r.text
    assert "tb_console=" in r.headers.get("set-cookie", "")  # a session cookie was set
    assert users.is_sso("nurse.lin") and users.get("nurse.lin").mailbox == "nurse.lin@hospa.test"  # type: ignore[union-attr]
    # the sign-in page sends an SSO user straight in; a local account still works beside it
    assert c.get("/login", follow_redirects=False).status_code == 303
    plain = TestClient(app)
    assert 'data-testid="sso-hint"' in plain.get("/login").text
    local, _ = login(app)
    assert "administrator" in local.get("/").text
    # group -> role mapping, default role for the rest
    a = TestClient(app, headers={"X-Forwarded-User": "boss", "X-Forwarded-Groups": "trialbox-admins"})
    assert "administrator" in a.get("/").text
    v = TestClient(app, headers={"X-Forwarded-User": "someone"})
    assert "viewer" in v.get("/").text
    # an SSO account cannot be given a console password; a local account is never overwritten by the header
    adm_c, csrf = login(app)
    assert adm_c.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "nurse.lin"}).status_code == 400
    spoof = TestClient(app, headers={"X-Forwarded-User": "admin", "X-Forwarded-Groups": "nothing"})
    assert "administrator" in spoof.get("/").text  # the local admin keeps their role (header cannot demote)
    events = [e.event for e in read_audit(tmp_path / "audit")]
    assert events.count("console.login") >= 4


def test_sso_header_ignored_from_an_untrusted_peer(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore(tmp_path / "c.sqlite")
    users.create("admin", "admin", ADMIN_PW)
    env = {**SSO_ENV, "TB_CONSOLE_SSO_TRUSTED_PROXIES": "10.1.2.3", "TB_CONSOLE_DIR": str(tmp_path)}
    app = create_app(env, backend=backend, audit=AuditLog(backend.audit_dir), users=users)
    c = TestClient(app, headers={"X-Forwarded-User": "mallory", "X-Forwarded-Groups": "trialbox-admins"})
    assert c.get("/", follow_redirects=False).status_code == 303  # to /login: the header did nothing
    assert users.get("mallory") is None
    assert "console.sso_rejected" in [e.event for e in read_audit(tmp_path / "audit")]
    with pytest.raises(PilotRefused, match="TRUSTED_PROXIES"):
        create_app(
            {**SSO_ENV, "TB_CONSOLE_SSO_TRUSTED_PROXIES": "", "TB_CONSOLE_DIR": str(tmp_path)},
            backend=backend,
            audit=AuditLog(backend.audit_dir),
        )


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
