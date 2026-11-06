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
import os
import secrets
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

KEY = b"trialbox-demo-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)  # a Monday, the synthetic reference date


class InprocBackend:
    """``console.backend.Backend`` over an in-process box: jobs and registry through the orchestrator's own HTTP
    routes (FastAPI test client), objects from its store."""

    def __init__(self, box: Any, client: Any, rulesets_dir: Path) -> None:
        self.box, self.c, self.rulesets_dir = box, client, rulesets_dir

    # jobs
    def list_jobs(self, limit: int = 100) -> list[Any]:
        from tb_contracts import Job

        return [Job.model_validate(j) for j in self.c.get(f"/jobs?limit={limit}").json()]

    def get_job(self, job_id: str) -> Any:
        from tb_contracts import Job

        r = self.c.get(f"/jobs/{job_id}")
        return Job.model_validate(r.json()) if r.status_code == 200 else None

    def create_job(self, req: Any) -> Any:
        from console.backend import Refused
        from tb_contracts import Job, dump

        r = self.c.post("/jobs", json=dump(req))
        if r.status_code != 200:
            raise Refused(r.text[:300])
        job = Job.model_validate(r.json())
        self.box.orch.drain()
        return self.get_job(job.job_id) or job

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

    def registry_export(self, ruleset: str) -> bytes:
        return bytes(self.c.get(f"/registry/{ruleset}/export.xlsx").content)

    def reveal(self, job_id: str, pid: str, by: str) -> str | None:
        from console.backend import Refused

        r = self.c.post(f"/jobs/{job_id}/reveal", json={"pid": pid, "by": by})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise Refused(r.text[:200])
        return str(r.json().get("mrn") or "") or None


def build(work: Path) -> tuple[Any, Any, Path]:
    from fastapi.testclient import TestClient
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
    client = TestClient(orch_app.app)
    for subject in ("FEAS GZQO", "SCREEN GZQO version=1.0.0", "MICROBATCH GZQO"):
        box.mail(subject)
        box.orch.drain()
    return box, client, work / "box" / "repo"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR", "/tmp/tb-role-demo")))
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
    users = UserStore(a.dir / "console" / "console.sqlite")
    accounts = [
        ("admin", "admin", {}),
        ("crc", "coordinator", {}),
        ("pi", "investigator", {}),
        ("smo", "coordinator", {"affiliation": "smo", "studies": "GZQO", "expires": "2027-03-31"}),
        ("cra", "cro", {"affiliation": "cro"}),
        ("viewer", "viewer", {}),
    ]
    for name, role, scope in accounts:
        if users.get(name) is None:
            users.create(name, role, password, f"{name}@hospa.test")  # type: ignore[arg-type]
        else:
            users.set_password(name, password)
        if scope:
            users.set_scope(name, **scope)
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
