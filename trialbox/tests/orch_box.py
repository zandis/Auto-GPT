"""T-714 (D-482; trust review TR-7): a box whose orchestrator is the real one, for tests of what crosses the
console's boundary.

``orch_box`` (the fixture, registered in ``tests/conftest.py``) gives:

* the real orchestrator app (``orchestrator.app.app``: ``make_app``, the token middleware, the route gate of D-464,
  every router) serving a real ``Orchestrator`` over an ingested synthetic lake (``tests.inproc_box.make_box``);
* the production configuration of trust: ``TB_ENV=VALIDATION`` (rc1 makes no list in PRODUCTION; see ``build``), a
  token registry with every service's own token, the actor-keys file (``tests.service_tokens``);
* the console's real backend (``console.backend.HttpBackend``) with its orchestrator client bound to that app: the
  console's own code builds every request, signs every assertion and reads every refusal;
* a finished screening job of ``GZQO`` with real listed pseudonyms, and the chart numbers of the synthetic site.

Nothing here answers for the orchestrator: a console call that signs the wrong role, the wrong study or none is
refused by the real route. Synthetic data only.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from console.backend import HttpBackend
from fastapi.testclient import TestClient
from tb_common import service_auth as sa
from tb_common.config import Config, load_env
from tb_common.crypto import pid_for_mrn
from tb_contracts import Job, JobCreate

from tests.inproc_box import Box, ingest_site, make_box
from tests.rulesets_guard import approve_at_site
from tests.service_tokens import per_service_tokens, token_of

KEY = b"trialbox-test-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)  # a Monday, the synthetic reference date
SNAPSHOT = "2026-10-04"
STUDY = "GZQO"


class BoxBackend(HttpBackend):
    """The console's own backend on the box. The only additions are what a test needs because the box has no worker
    thread: the orchestrator's queue is drained after a job is started. Requests, headers and refusals are
    ``HttpBackend``'s."""

    def __init__(self, ob: OrchBox) -> None:
        env = load_env(dotenv=ob.work / "none.env", environ={"TB_RULESETS_DIR": str(ob.work / "box" / "repo"),
                                                             "TB_SECRETS_DIR": str(ob.work / "sec")})  # fmt: skip
        super().__init__(Config(env=env, settings=ob.box.orch.cfg.settings), ob.box.store, ob.box.orch.audit)
        self.orch.client = ob.client("console")  # the real app, the console's own token
        self.ob = ob

    def create_job(self, req: JobCreate, by: str = "", role: str = "") -> Job:
        job = super().create_job(req, by, role)
        self.ob.box.orch.drain()
        return self.get_job(job.job_id) or job


@dataclass
class OrchBox:
    box: Box
    app: Any
    work: Path
    mrn: dict[str, str]  # pseudonym -> chart number of every synthetic patient of the site
    _screen: Job | None = field(default=None, repr=False)

    def client(self, service: str | None = "console") -> TestClient:
        """A client that sends ``service``'s own token (None: no token at all)."""
        headers = {sa.TOKEN_HEADER: token_of(service)} if service else {}
        return TestClient(self.app, headers=headers, raise_server_exceptions=False)

    def read(self, path: str) -> Any:
        """A patient read as a coordinator of the study, for a test that checks what was stored: since NEW-SEC-1
        (D-717) such a read takes a verified claim (``phi.view`` on the path's study; none for ``/setup/``)."""
        from tests.actor3 import signed

        study = "" if path.startswith("/setup/") else path.split("?", 1)[0].split("/")[2].upper()
        headers = signed("phi.view", study, "GET", path, sub="console:test-reader", role="coordinator")
        return self.client("console").get(path, headers=headers)

    def backend(self) -> BoxBackend:
        return BoxBackend(self)

    def screen(self) -> Job:
        """The box's finished ``SCREEN GZQO`` job (started by mail once, as a coordinator's request)."""
        if self._screen is None:
            assert self.box.mail(f"SCREEN {STUDY} version=1.0.0") == "Processed"
            self.box.orch.drain()
            job = self.box.orch.db.find(type_="SCREEN")[0]
            assert job.state == "done", job.error
            self._screen = job
        return self._screen

    def listed(self, job: Job | None = None) -> list[str]:
        """The pseudonyms the job listed, in list order."""
        job = job or self.screen()
        out = next(o for o in job.outputs or [] if o.filename.startswith("candidate_list_"))
        return [str(r["pid"]) for r in json.loads(self.box.store.get(out.minio_key))["rows"]]

    def events(self, kind: str) -> list[dict[str, Any]]:
        """The audit records of one event name, oldest first (the console and the orchestrator write one chain)."""
        out = []
        for path in sorted(self.box.audit_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                if rec.get("event") == kind:
                    out.append(rec)
        return out


def build(work: Path, synth_dir: Path, monkeypatch: pytest.MonkeyPatch) -> OrchBox:
    from orchestrator import app as oapp

    sec = work / "sec"
    sec.mkdir(parents=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(synth_dir / "site-a", work / "lake", sec, SNAPSHOT)
    box = make_box(work / "box", work / "lake", sec, RUN)
    per_service_tokens(work, monkeypatch)  # the registry, the actor keys; this process signs as the console
    # D-640: a PRODUCTION box runs no seeded example; this one's studies are approved the site's way
    approve_at_site(box.orch.rulesets_dir)
    # R22-34 (D-1072; the integrator's go, comment 7079138866): VALIDATION, the strict environment in which rc1 still
    # makes a list; PRODUCTION refuses this box's SCREEN (tests/console/test_rc1_orch_box.py). This returns to
    # PRODUCTION the day the rc1 refusals are lifted for a pilot.
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    monkeypatch.setattr(oapp, "_orch", box.orch)  # the app's routes serve this box
    monkeypatch.setattr(oapp, "REVEALS", oapp.RevealLimit())  # the caps count from zero in every test
    monkeypatch.setattr(oapp, "EXPORTS", oapp.RevealLimit("TB_EXPORT_MAX_PER_HOUR", 10))
    monkeypatch.setattr(
        oapp, "REVEALS_SERVICE", oapp.RevealLimit("TB_REVEAL_MAX_PER_HOUR_PER_SERVICE", 600, "reveal_service")
    )
    monkeypatch.setattr(
        oapp, "EXPORTS_SERVICE", oapp.RevealLimit("TB_EXPORT_MAX_PER_HOUR_PER_SERVICE", 60, "export_service")
    )
    with (synth_dir / "site-a" / "patient.csv").open(encoding="utf-8") as fh:
        mrn = {pid_for_mrn(KEY, r["mrn"]): r["mrn"] for r in csv.DictReader(fh)}
    return OrchBox(box=box, app=oapp.app, work=work, mrn=mrn)
