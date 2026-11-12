"""Role demo box (D-104): the real TrialBox pipeline on the synthetic hospital, in one process, with the console's
report-first pages and one sign-in per role. For trying the product, never for patient data.

    python -m tools.role_demo --dir /tmp/tb-demo --port 8080

What it does:

1. builds the synthetic hospitals (``tools.make_fixtures``) and ingests site A into a local lake;
2. starts the orchestrator and mail gateway in process (the same in-process box the integration tests use), with a
   stub language model;
3. runs the real jobs a site would run: ``FEAS GZQO`` (feasibility report and its profile) and ``SCREEN GZQO``
   (candidate list for the weekly PI list), plus ``MICROBATCH`` for the Monday re-screen;
4. serves the console (pilot workspace, TB_ENV=DEV, data class D0) against that box, with accounts
   ``admin``, ``crc`` (study coordinator), ``pi`` (investigator), ``smo`` (SMO coordinator, GZQO only, account
   ends 2027-03-31), ``cra`` (CRO, aggregate only) and ``viewer``. All share one password: ``TB_DEMO_PASSWORD`` or
   a random one printed at start.

Everything shown is synthetic. GZQO is the repository's gout test study; the AD early-stage ruleset is not in the
repository yet, so the AD-specific report rows (screen-failure default, AD capability list) do not appear here.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from tb_common import service_auth as sa
from tb_common.service_auth import actor_header, auth_headers

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

KEY = b"trialbox-demo-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)  # a Monday, the synthetic reference date


def orch_client(app: Any) -> Any:
    """The demo box's client for the in-process orchestrator. D-114: it authenticates like a real console, with a
    per-process service token on every changing call. D-464 (T-713): outside DEV and TEST the orchestrator admits only
    a caller it can name, and the demo image runs with no ``TB_ENV`` (PRODUCTION by the one rule), so the box gets a
    token registry naming that token as the console's, and the console's actor key, as ``trialbox secrets init``
    writes them on a box (unless a registry is configured already).

    D-437: the process token is the console's, and the console may not call the model gateway as the orchestrator. So
    the box's orchestrator gets its own token too, in the registry and in a 0600 file beside it
    (:func:`service_token_of`); the box's model calls carry that one (``tools.scenarios.gateway_client``)."""
    from fastapi.testclient import TestClient

    tok = os.environ.setdefault("TB_SERVICE_TOKEN", secrets.token_hex(16))
    if not (os.environ.get(sa.REGISTRY_ENV) or "").strip():
        d = Path(tempfile.mkdtemp(prefix="tb-demo-tokens-"))
        reg, keys = d / "tokens.json", d / "actor-keys"
        own = {name: secrets.token_hex(16) for name in OWN_TOKENS}
        services = {"console": sa.token_hash(tok), **{name: sa.token_hash(t) for name, t in own.items()}}
        reg.write_text(json.dumps({"schema": sa.REGISTRY_SCHEMA, "services": services}), encoding="utf-8")
        keys.write_text(sa.actor_key(tok).hex() + "\n", encoding="utf-8")
        for name, t in own.items():
            _token_file(reg, name).write_text(t + "\n", encoding="utf-8")
        for f in (reg, keys, *(_token_file(reg, name) for name in own)):
            f.chmod(0o600)
        os.environ[sa.REGISTRY_ENV] = str(reg)
        os.environ.setdefault(sa.ACTOR_KEYS_ENV, str(keys))
    return TestClient(app, headers=auth_headers())


# the services of the one-process box, besides the console, that call another service under their own name
OWN_TOKENS = ("orchestrator",)


def _token_file(registry: Path, service: str) -> Path:
    return registry.parent / f"{service}.token"


def service_token_of(service: str) -> str:
    """The token :func:`orch_client` made for ``service`` of this process's box; "" when the process has no such box
    (no registry, or a registry :func:`orch_client` did not write), and then the caller sends what
    ``service_auth.auth_headers`` gives."""
    reg = (os.environ.get(sa.REGISTRY_ENV) or "").strip()
    if not reg or service not in OWN_TOKENS:
        return ""
    try:
        return _token_file(Path(reg), service).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class InprocBackend:
    """``console.backend.Backend`` over an in-process box: jobs and registry through the orchestrator's own HTTP
    routes (FastAPI test client), objects from its store."""

    def __init__(self, box: Any, client: Any, rulesets_dir: Path) -> None:
        self.box, self.c, self.rulesets_dir = box, client, rulesets_dir
        self.cfg = box.orch.cfg  # the site time zone for user-facing times (console.timefmt)

    # jobs
    def list_jobs(self, limit: int = 100) -> list[Any]:
        from tb_contracts import Job

        return [Job.model_validate(j) for j in self.c.get(f"/jobs?limit={limit}").json()]

    def get_job(self, job_id: str) -> Any:
        from tb_contracts import Job

        r = self.c.get(f"/jobs/{job_id}")
        return Job.model_validate(r.json()) if r.status_code == 200 else None

    def create_job(self, req: Any, by: str = "", role: str = "") -> Any:
        from console.backend import Refused
        from tb_contracts import Job, dump

        # D-146 (review J-01): as the HTTP backend does, the signed-in person and role travel signed
        r = self.c.post("/jobs", json=dump(req), headers=actor_header(by, role=role) if by and role else {})
        if r.status_code != 200:
            try:
                detail = str(r.json().get("detail"))
            except (ValueError, AttributeError):
                detail = r.text
            raise Refused(detail[:300])
        job = Job.model_validate(r.json())
        self.box.orch.drain()
        return self.get_job(job.job_id) or job

    def retry_scheduled_job(self, job_id: str, *, reply_to: str, by: str, role: str) -> Any:
        from console.backend import Refused
        from tb_contracts import Job

        # T-746 (D-474): as the HTTP backend does: the job's id and the reply mailbox, the person and role signed
        r = self.c.post(f"/jobs/{job_id}/retry", json={"reply_to": reply_to}, headers=actor_header(by, role=role))
        if r.status_code != 200:
            raise Refused(r.text[:300])
        job = Job.model_validate(r.json())
        self.box.orch.drain()
        return self.get_job(job.job_id) or job

    def cancel_job(self, job_id: str, by: str) -> Any:
        from console.backend import Refused
        from tb_contracts import Job

        r = self.c.post(f"/jobs/{job_id}/cancel", params={"by": by}, headers=actor_header(by))
        if r.status_code != 200:
            raise Refused(r.text[:300])
        return Job.model_validate(r.json())

    def put_input(self, job_id: str, filename: str, data: bytes, content_type: str) -> Any:
        from tb_common.crypto import sha256_bytes
        from tb_contracts import JobFile

        key = f"attachments/{job_id}/{filename}"
        self.box.store.put(key, data, content_type)
        return JobFile(filename=filename, sha256=sha256_bytes(data), minio_key=key, content_type=content_type)

    def get_object(self, key: str) -> bytes:
        return bytes(self.box.store.get(key))

    def thread(self, job_id: str) -> list[Any]:
        return []

    def audit(self, job_id: str | None = None, limit: int = 200) -> list[Any]:
        from console.backend import read_audit

        return read_audit(self.box.audit_dir, job_id, limit)

    def rulesets(self) -> list[Any]:
        from console.backend import ruleset_infos

        return ruleset_infos(self.rulesets_dir)

    def criteria(self, ruleset: str) -> list[dict[str, str]]:
        from console.backend import criteria_of

        return criteria_of(self.rulesets_dir, ruleset)

    def health(self) -> list[Any]:
        from console.backend import Health

        return [
            Health("orchestrator", True, "in process (demo)"),
            Health("lake", True, "synthetic site A"),
            Health("mail-gateway", True, "in process, no outside mail"),
        ]

    def models(self) -> dict[str, Any] | None:
        r = self.c.get("/models")
        return r.json() if r.status_code == 200 else None

    def run_canary(self) -> bool:
        return bool(self.c.post("/models/canary").status_code == 200)

    def ruleset_detail(self, ruleset: str) -> dict[str, Any] | None:
        r = self.c.get(f"/rulesets/{ruleset}")
        return r.json() if r.status_code == 200 else None

    def ingest(self) -> dict[str, Any]:
        return {"passed": True, "note": "demo: data is loaded once at start"}

    def send_test_mail(self, sender: str, to: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> str:
        return str(self.box.mail(subject, tuple(files), sender=sender))

    # registry
    def _call(self, method: str, path: str, body: Any = None) -> Any:
        from console.backend import Refused
        from tb_contracts import dump

        r = self.c.get(path) if method == "GET" else self.c.post(path, json=dump(body) if body is not None else None)
        if r.status_code in (400, 404, 422):
            raise Refused(str(r.json().get("detail")))
        return r.json()

    def registry_summaries(self) -> list[Any]:
        from tb_contracts import RegistrySummary

        return [RegistrySummary.model_validate(s) for s in self._call("GET", "/registry")]

    def registry_rows(self, ruleset: str) -> list[Any]:
        from tb_contracts import RegistryEntry

        return [RegistryEntry.model_validate(r) for r in self._call("GET", f"/registry/{ruleset}")]

    def registry_update(self, ruleset: str, upd: Any) -> Any:
        from tb_contracts import RegistryEntry

        return RegistryEntry.model_validate(self._call("POST", f"/registry/{ruleset}", upd))

    def registry_promote(self, ruleset: str, req: Any) -> int:
        return int(self._call("POST", f"/registry/{ruleset}/promote", req)["added"])

    def registry_export(self, ruleset: str, by: str, role: str = "", scope: str = "") -> bytes:
        from console.backend import Refused

        r = self.c.get(f"/registry/{ruleset}/export.xlsx", headers=actor_header(by, role=role, scope=scope))
        if r.status_code != 200:
            raise Refused(r.text[:200])
        return bytes(r.content)

    def reveal(self, job_id: str, pid: str, by: str, role: str = "", scope: str = "", purpose: str = "",
               reason: str = "") -> str | None:  # fmt: skip
        from console.backend import Refused

        # T-103 (D-438): the purpose and reason travel to the orchestrator's record, as from HttpBackend
        body = {"pid": pid, **({"purpose": purpose} if purpose else {}), **({"reason": reason} if reason else {})}
        r = self.c.post(f"/jobs/{job_id}/reveal", json=body, headers=actor_header(by, role=role, scope=scope))
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise Refused(r.text[:200])
        return str(r.json().get("mrn") or "") or None

    def study_api(self, method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        from console.backend import problem_of

        kw: dict[str, Any] = {"headers": headers} if headers else {}
        r = self.c.request(method, path, json=body, **kw) if body is not None else self.c.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    def send_notice(self, kind: str, to: list[str], subject: str, body_md: str, by: str) -> str:
        from console.backend import Refused

        body = {"kind": kind, "to": to, "subject": subject, "body_md": body_md}
        r = self.c.post("/notices", json=body, headers=actor_header(by))
        if r.status_code != 200:
            raise Refused(r.text[:200])
        return str(r.json().get("message_id") or "")


def build(work: Path) -> tuple[Any, Any, Path]:
    from orchestrator import app as orch_app

    from tests.inproc_box import ingest_site, make_box
    from tools.make_fixtures import main as make_fixtures

    synth = work / "synth"
    if not (synth / "site-a").exists():
        assert make_fixtures(["--out", str(synth), "--sites", "a"]) == 0
    sec = work / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(synth / "site-a", work / "lake", sec, "2026-10-04")
    box = make_box(work / "box", work / "lake", sec, RUN)
    orch_app._orch = box.orch  # the orchestrator's routes now serve this box
    from rc_sim.app import register_inproc

    register_inproc()  # S36 accepts inproc://rc-sim, the REDCap simulator of the demo image (FR-RC-17a, D-109)
    client = orch_client(orch_app.app)
    for subject in ("FEAS GZQO", "SCREEN GZQO version=1.0.0", "MICROBATCH GZQO"):
        box.mail(subject)
        box.orch.drain()
    return box, client, work / "box" / "repo"


def seed_activity(work: Path, bk: InprocBackend) -> None:
    """A few weeks of made-up site activity so the workbench opens in a working state (D-105): PI decisions on the
    weekly list and coordinator progress in the registry. Synthetic, like everything in the demo."""
    import json
    from datetime import UTC, datetime, timedelta

    from console.sitestore import Mark, SiteStore
    from tb_contracts import RegistryPromote, RegistryUpdate

    jobs = [
        j for j in bk.list_jobs() if j.ruleset == "GZQO" and j.type in ("SCREEN", "MICROBATCH") and j.state == "done"
    ]
    if not jobs:
        return
    job = max(jobs, key=lambda j: j.received_at)
    out = next((o for o in job.outputs or [] if o.filename.startswith("candidate_list_")), None)
    if out is None:
        return
    rows = [r for r in json.loads(bk.get_object(out.minio_key))["rows"] if r.get("tier") in ("high", "review")]
    pids = [str(r["pid"]) for r in rows]
    if len(pids) < 6:
        return
    store = SiteStore()  # the trial database of this run (TB_DB_URL, set by make_box)
    now = datetime.now(UTC)

    def at(days: int) -> str:
        return (now - timedelta(days=days)).isoformat()

    marks = [
        Mark(pids[0], "approach", None, None, "pi", at(3), job.job_id),
        Mark(pids[1], "approach", None, "Ask about flare dates at the visit", "pi", at(1), job.job_id),
        Mark(pids[2], "need_info", None, "Was the last flare treated elsewhere?", "pi", at(2), job.job_id),
        Mark(pids[3], "not_suitable", "comorbidity", None, "pi", at(4), job.job_id),
        Mark(pids[4], "approach", None, None, "pi", at(10), job.job_id),
        Mark(pids[5], "approach", None, None, "pi", at(12), job.job_id),
    ]
    for m in marks:
        store.mark("GZQO", m)
    try:
        bk.registry_promote("GZQO", RegistryPromote(by="crc"))
        bk.registry_update("GZQO", RegistryUpdate(pid=pids[4], status="contacted", by="crc"))
        bk.registry_update("GZQO", RegistryUpdate(pid=pids[5], status="consented", by="crc"))
    except Exception as exc:
        print(f"demo registry seed skipped: {exc}")


def main(argv: list[str] | None = None) -> int:
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR") or scratch_root() / "tb-role-demo"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--fresh", action="store_true", help="delete --dir first")
    a = ap.parse_args(argv)
    if a.fresh and a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True, exist_ok=True)
    box, client, repo = build(a.dir)

    import uvicorn
    from console.app import create_app
    from console.auth import UserStore
    from tb_common.audit import AuditLog

    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    users = UserStore()  # schema auth of the trial database (TB_DB_URL, set by make_box)
    accounts = [
        ("admin", "admin", {}),
        ("crc", "coordinator", {}),
        ("pi", "investigator", {}),
        ("smo", "coordinator", {"affiliation": "smo", "studies": "GZQO", "expires": "2027-03-31"}),
        ("cra", "cro", {"affiliation": "cro", "studies": "GZQO,GOUT-COH"}),  # D-380: names its studies
        ("viewer", "viewer", {}),
    ]
    for name, role, scope in accounts:
        if users.get(name) is None:
            users.create(name, role, password, f"{name}@hospa.test")  # type: ignore[arg-type]
        else:
            users.set_password(name, password)
        if scope:
            users.set_scope(name, **scope)
    from tools.feas_demo import seed_pi

    seed_pi()  # D-380: the demo investigator is each study's logged PI
    seed_activity(a.dir, InprocBackend(box, client, repo))
    env = {
        "TB_ENV": "DEV",
        "TB_CONSOLE_PILOT": "1",
        "TB_DATA_CLASS": "D0",
        "TB_CONSOLE_DIR": str(a.dir / "console"),
        "TB_CONSOLE_ADMIN_EMAIL": "admin@hospa.test",
        "TB_CONSOLE_SECURE_COOKIE": os.environ.get("TB_CONSOLE_SECURE_COOKIE", "0"),
    }
    app = create_app(env, backend=InprocBackend(box, client, repo), audit=AuditLog(box.audit_dir), users=users)
    print(f"TrialBox role demo on http://{a.host}:{a.port}  accounts: {', '.join(n for n, _, _ in accounts)}")
    if not os.environ.get("TB_DEMO_PASSWORD"):
        print(f"password (all accounts): {password}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
