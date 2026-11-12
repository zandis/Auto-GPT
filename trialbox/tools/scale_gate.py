"""The scale gate (T-687, D-471; OD-10 of TB-PLAN-06.1): the night of a hospital at full size, each part in its own
process under the memory cap of the compose service that runs it in production, with a slow model that fails.

The scale review of 2026-11-11 (§1) found one bug class: fixed limits and whole-hospital work in one process, which
development and CI never met because they ran 500 to 5,000 synthetic patients, on the instant stub, in one process,
without the caps (``tools/hospital_sim.py scale`` ran 50,000 that way and passed). This gate runs the same product
code, split as the containers split it:

1. ``generate``: the synthetic hospital (``tools.synth``; every patient fictional), no cap (it is the test's input);
2. ``ingest``: the adapter's night (``adapter.pipeline.run_ingest``, the HL7 validator when the JVM is there) under
   the ``adapter`` cap. When it fails, the back-fill path (``adapter.backfill``, streaming) writes the same snapshot
   under the same cap so that the later parts still run, and the report says so;
3. ``rebuild`` and ``publish``: the lake service (``lake.app``) under the ``lake`` cap; the site publish
   (``sitesetup.SiteSetup.flush`` with the product's ``LakeHttp`` client) ticks as the orchestrator's scheduler does
   until the publish is recorded, or a second rebuild of the snapshot starts (F-01's loop), or the lake dies;
4. ``screen``: the cascade S0 to S5 (``matching.cascade.run_cascade``) under the ``orchestrator`` cap, reading the
   lake service over HTTP and judging through the real gateway over real HTTP to the slow stand-in
   (``tb_testkit.scale.SlowModel``: seconds per call, an outage of 502 answers, one restart of the server);
5. ``backup``: the nightly backup's own steps (``tools.trialbox.backup_schedule.ComposeOps.make_backup`` and
   ``nightly``) with a runner that plays compose: the db container's snapshot script runs for real against the run's
   PostgreSQL; ``ps``, ``pause`` and the backup container are recorded.

Each check is listed in :data:`CHECKS`; today's failures are strict expected failures by finding and card
(:data:`EXPECTED`): ``tests/perf/test_scale_gate.py`` (nightly, 50,000) and ``tests/unit/test_scale_gate_logic.py``
(every pull request, a small size). Remove a line of :data:`EXPECTED` in the card that fixes it.

    TB_ENV=DEV PYTHONPATH=libs:services:. python -m tools.scale_gate --patients 300 --out build/scale
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services", "."):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from tb_testkit.scale import (  # noqa: E402
    Check,
    Enforcer,
    Expected,
    PhaseRun,
    SlowModel,
    compose_caps,
    compose_setting,
    free_port,
    gate_ok,
    gib,
    markdown,
    verdict,
    wait_http,
)

REF_DATE = date(2026, 10, 5)  # the synthetic generator's reference day (tools.synth)
SNAPSHOT = "2026-10-04"  # the night before it: the snapshot the night writes
TRIAL = "GZQO"  # the ruleset of hospital_sim and the bench gate
SITE_KEY = b"trialbox-scale-gate-site-key-0123456789"
FULL = 50_000  # the size of the plan's reference site (SPEC §11.3, review §3): the nightly job's size
# the gateway's refusals that are the model's faults (an outage, a restart, a stall), not the call's content
FAULT_REFUSALS = frozenset({"model_asleep", "model_busy", "model_unavailable", "upstream_failed"})
# the compose service whose cap each part runs under (deploy/docker-compose.yml)
SERVICE = {"ingest": "adapter", "rebuild": "lake", "screen": "orchestrator", "backup": "db", "generate": "-"}

CHECKS = {
    "ingest.night_under_cap": "the night's ingest ends under the adapter's cap",
    "rebuild.under_cap": "the lake's rebuild of the snapshot ends under the lake's cap",
    "publish.recorded_once": "the site publish over that rebuild is recorded, with one rebuild of the snapshot",
    "screen.ends_under_cap": "the screen (the cascade S0 to S5) ends under the orchestrator's cap",
    "screen.model_faults_seen": "the stand-in's outage and its restart both happened during the screen",
    "screen.outage_no_unknown": "no judge call of the screen was lost to the outage or the restart",
    "backup.ends": "the nightly backup ends and is written",
    "backup.no_pause": "the backup holds no service still while it reads",
}

# Today's failures: strict expected failures (D-460). A check here must fail from ``from_patients`` up, and passes
# below it. The card that fixes one removes its line; until then a pass turns the gate red ("FIXED").
EXPECTED: dict[str, Expected] = {
    # F-04: when T-689 (#309) lands, the gateway answers the stand-in's 502 outage with its new code `upstream_down`:
    # add it to FAULT_REFUSALS (the model's faults) and remove this line if the screen then loses no call
    "screen.outage_no_unknown": Expected(
        ("F-04",),
        "T-689",
        0,
        "a refused call is tried once at once and then lost as unknown; reproduced at 200 patients with a 1 s outage",
    ),
}


@dataclass
class Params:
    patients: int
    out: Path
    enforce: str = ""  # TB_SCALE_ENFORCE: cgroup | measure | "" (the best this host has)
    validate: bool = True  # the HL7 validator in the night (the JVM; StructuralValidator without it)
    latency_s: float = 0.0  # the stand-in's seconds per call
    outage_after: int = 0  # the call from which the stand-in answers 502
    outage_s: float = 0.0  # for this many seconds
    restart_after: int = 0  # the call count after which the stand-in is restarted once (0: never)
    restart_gap_s: float = 0.0  # how long it is down
    lake_timeout_s: float | None = None  # None: the product's LakeHttp default (the limit F-01 is about)
    publish_poll_s: float = 5.0
    backup_quiesce: str = ""  # "" : the box's default (D-455: off); "pause": D-274's pause, to show the gate sees it
    publish_wait_s: float = 6 * 3600.0  # a guard for a hung lake; the CI job's own timeout is the real bound
    caps: dict[str, int] = field(default_factory=dict)


@dataclass
class Report:
    params: Params
    mode: str
    runs: list[PhaseRun] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)

    def check(self, cid: str, passed: bool | None, detail: str, blocked_by: str = "") -> None:
        assert cid in CHECKS, cid
        self.checks.append(Check(cid, passed, detail, blocked_by))

    def rows(self) -> list[dict[str, Any]]:
        return verdict(self.checks, EXPECTED, self.params.patients)

    def ok(self) -> bool:
        return gate_ok(self.rows())

    def markdown(self) -> str:
        p = self.params
        caps = ", ".join(f"{SERVICE[k]} {gib(p.caps[SERVICE[k]])}" for k in ("ingest", "rebuild", "screen"))
        head = [
            f"{p.patients:,} synthetic patients; caps from deploy/docker-compose.yml: {caps}; "
            f"enforcement: {self.mode}.",
            f"Model stand-in: {p.latency_s} s per call, 502 for {p.outage_s} s from call {p.outage_after}, "
            f"restart after call {p.restart_after or 'never'}.",
            *(f"Note: {n}" for n in self.notes),
        ]
        return markdown(self.rows(), head, self.runs)

    def to_json(self) -> dict[str, Any]:
        return {
            "patients": self.params.patients,
            "mode": self.mode,
            "ok": self.ok(),
            "rows": self.rows(),
            "notes": self.notes,
            "numbers": self.numbers,
            "runs": [
                {
                    "name": r.name,
                    "service": r.service,
                    "cap": r.cap,
                    "rc": r.rc,
                    "oom": r.oom,
                    "peak": r.peak,
                    "seconds": round(r.seconds, 1),
                }
                for r in self.runs
            ],
        }


# ------------------------------------------------------------------------------------------------ the processes
CHILD_GENERATE = r"""
import sys
from datetime import date
from pathlib import Path
from tools.make_fixtures import write_site
from tools.synth.generator import generate
n, out, ref = int(sys.argv[1]), Path(sys.argv[2]), date.fromisoformat(sys.argv[3])
write_site(generate(42, "DEMO-A", ref, n, "1"), out)
"""

CHILD_INGEST = r"""
import json, sys, time
from pathlib import Path
from adapter.pipeline import AdapterConfig, run_ingest
from adapter.validate.validator import Hl7Validator, StructuralValidator

mode, feed, work, mapping, snap, validate = sys.argv[1:7]
work = Path(work)
(work / "sec").mkdir(parents=True, exist_ok=True)
(work / "sec" / "site_hmac.key").write_bytes(sys.argv[7].encode())
cfg = AdapterConfig(lake_dir=work / "lake", secrets_dir=work / "sec", mapping_path=Path(mapping), site_id="DEMO-A")
val = (Hl7Validator.from_env() or StructuralValidator()) if validate == "1" else None
t0 = time.perf_counter()
if mode == "backfill":
    from adapter.backfill import backfill
    rep = backfill(cfg, "csv", feed, snapshot=snap, validate=validate == "1", validator=val, rebuild_lake=False)
    ok, counts = rep.state == "published", rep.counts
else:
    rep = run_ingest(cfg, "csv", feed, snapshot=snap, load_fhir=False, rebuild_lake=False,
                     validate=validate == "1", validator=val)
    ok, counts = rep.passed, rep.counts
print(json.dumps({"ok": ok, "records": sum(counts.values()), "seconds": round(time.perf_counter() - t0, 1),
                  "validator": type(val).__name__ if val else "off"}))
"""

# the lake service as its container runs it; the container's cap is what lake.store sizes DuckDB from (it reads the
# cgroup root, which is the container's own cgroup there, and the host's here): the cap is handed to that function
CHILD_LAKE = r"""
import os, sys
import uvicorn
from lake import store
cap = int(os.environ["TB_SCALE_CAP_BYTES"])
store._cgroup_memory_max = lambda: cap
uvicorn.run("lake.app:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
"""

CHILD_SCREEN = r"""
import json, logging, os, sys, time
from collections import Counter
from datetime import date
from pathlib import Path
from fastapi.testclient import TestClient
from embed_service.embedder import HashEmbedder
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from lake.client import LakeHttp
from matching.cascade import CascadeConfig, run_cascade
from matching.cascade.judge import GatewayJudge
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology
from tb_llm import GatewayClient
from tools.cascade_e2e import load_trial

lake_url, stub_url, trial, snap, run_date, work = sys.argv[1:7]
for name in ("gateway", "httpx"):
    logging.getLogger(name).setLevel(logging.WARNING)
# the gateway as its container runs it: the real policy, breakers and budgets, the stand-in over real HTTP
gw = Gateway(RoutingPolicy.load(), Registry.load(), AuditLog(Path(work) / "audit"),
             GatewayConfig(topology=Topology.A, environment=Environment.TEST), guard=Guard.from_settings(),
             env={**os.environ, "TB_EP_STUB_URL": stub_url})
client = GatewayClient("http://tb-gateway/v1", "orchestrator", http=TestClient(create_app(gw)))
judge = GatewayJudge(client)
rs = load_trial(trial)
cfg = CascadeConfig(study_id=trial, run_date=date.fromisoformat(run_date), lookback_months=36,
                    notes_class="D0", purpose="feasibility", step_id=f"scale:{trial}", sample_per_stratum=200,
                    snapshot=snap)
t0 = time.perf_counter()
res = run_cascade(LakeHttp(lake_url), rs, cfg, judge=judge, embedder=HashEmbedder())
print(json.dumps({"seconds": round(time.perf_counter() - t0, 1), "judge_calls": judge.calls,
                  "refusals": dict(Counter(judge.refusals)),
                  "n_after": dict(res.metrics.n_after)}))
"""


def _env(**extra: str) -> dict[str, str]:
    env = {**os.environ, "PYTHONPATH": "libs:services:.", "TB_ENV": os.environ.get("TB_ENV", "DEV")}
    env.update(extra)
    return env


def _last_json(text: str) -> dict[str, Any] | None:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                out: dict[str, Any] = json.loads(line)
                return out
            except json.JSONDecodeError:
                return None
    return None


def _over(run: PhaseRun) -> str:
    if run.oom:
        return f"killed at the {run.service} cap of {gib(run.cap)} after {run.seconds:.0f} s"
    if run.rc:
        return f"exit {run.rc}: {run.tail[-400:]}"
    if run.peak > run.cap:
        return f"peak {gib(run.peak)} over the {run.service} cap of {gib(run.cap)}"
    return ""


# ------------------------------------------------------------------------------------------------ the gate
def run(p: Params) -> Report:
    p.caps = p.caps or compose_caps()
    enf = Enforcer.detect(p.enforce)
    rep = Report(p, enf.mode)
    work = p.out / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    logs = p.out / "logs"
    db_url = _db_url(work)
    token = secrets.token_hex(16)  # the box's service token for this run (the lake checks it on every change)
    big = max(p.caps.values())

    # 1. the input
    site = work / "site"
    gen = enf.run(
        "generate",
        "-",
        big * 4,
        [sys.executable, "-c", CHILD_GENERATE, str(p.patients), str(site), REF_DATE.isoformat()],
        _env(),
        ROOT,
        logs / "generate.log",
    )
    gen.mode, gen.cap = "uncapped", 0
    rep.runs.append(gen)
    if gen.rc != 0:
        raise RuntimeError(f"the synthetic hospital could not be generated: {gen.tail}")

    # 2. the night's ingest under the adapter's cap
    mapping = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
    args = [str(site), str(work), str(mapping), SNAPSHOT, "1" if p.validate else "0", SITE_KEY.decode()]
    env = _env(TB_DB_URL=db_url)
    xmx = compose_setting("adapter", "TB_VALIDATOR_XMX")  # the validator's heap inside the adapter's cap, as composed
    if xmx:
        env["TB_VALIDATOR_XMX"] = xmx
    ing = enf.run(
        "ingest (nightly)",
        "adapter",
        p.caps["adapter"],
        [sys.executable, "-c", CHILD_INGEST, "nightly", *args],
        env,
        ROOT,
        logs / "ingest.log",
    )
    rep.runs.append(ing)
    got = _last_json(ing.tail) or {}
    rep.numbers["ingest"] = got
    why = _over(ing) or ("" if got.get("ok") else f"the night was not published: {got}")
    rep.check("ingest.night_under_cap", not why, why or f"{got.get('records', 0):,} records, peak {gib(ing.peak)}")
    nd = work / "lake" / "ndjson" / SNAPSHOT
    if why:
        shutil.rmtree(work / "lake", ignore_errors=True)
        bf = enf.run(
            "ingest (back-fill, to feed the rest)",
            "adapter",
            p.caps["adapter"],
            [sys.executable, "-c", CHILD_INGEST, "backfill", *args],
            env,
            ROOT,
            logs / "backfill.log",
        )
        rep.runs.append(bf)
        rep.notes.append(
            f"the night failed; the snapshot for the later parts came from the back-fill path ({bf.summary()})"
        )
    if not nd.is_dir():
        for cid in (
            "rebuild.under_cap",
            "publish.recorded_once",
            "screen.ends_under_cap",
            "screen.model_faults_seen",
            "screen.outage_no_unknown",
        ):
            rep.check(cid, None, "no snapshot was written", blocked_by="ingest")
    else:
        _lake_parts(p, rep, enf, work, logs, token)
    _backup(p, rep, work, db_url)
    (p.out / "scale_gate.json").write_text(json.dumps(rep.to_json(), indent=1), encoding="utf-8")
    (p.out / "scale_gate.md").write_text(rep.markdown(), encoding="utf-8")
    return rep


def _db_url(work: Path) -> str:
    from tools import pglocal

    return pglocal.for_work(work)


def _lake_parts(p: Params, rep: Report, enf: Enforcer, work: Path, logs: Path, token: str) -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = _env(
        TB_LAKE_DIR=str(work / "lake"),
        TB_LAKE_EMBEDDER="hash",
        TB_SERVICE_TOKEN=token,
        TB_SCALE_CAP_BYTES=str(p.caps["lake"]),
    )
    with enf.start(
        "lake (rebuild, queries)",
        "lake",
        p.caps["lake"],
        [sys.executable, "-c", CHILD_LAKE, str(port)],
        env,
        ROOT,
        logs / "lake.log",
    ) as (proc, lake_run):
        rep.runs.append(lake_run)

        def alive() -> bool:
            return proc.poll() is None

        if not wait_http(f"{url}/healthz", 120, alive):
            rep.check("rebuild.under_cap", False, f"the lake service did not start: {lake_run.tail[-400:]}")
            for cid in (
                "publish.recorded_once",
                "screen.ends_under_cap",
                "screen.model_faults_seen",
                "screen.outage_no_unknown",
            ):
                rep.check(cid, None, "the lake service did not start", blocked_by="rebuild")
            return
        built = _publish(p, rep, url, alive, token)
        lake_died = not alive()
        if lake_died:
            rc = proc.returncode
            why = (
                f"the lake was killed at its cap of {gib(p.caps['lake'])}"
                if lake_run.mode == "measure" or rc in (-9, 137)
                else f"the lake exited {rc}"
            )
            rep.check("rebuild.under_cap", False, f"{why} during the rebuild")
            built = False
        if not built:
            for cid in ("screen.ends_under_cap", "screen.model_faults_seen", "screen.outage_no_unknown"):
                rep.check(cid, None, "the lake has no built snapshot", blocked_by="rebuild")
            return
        _screen(p, rep, enf, work, logs, url, alive, token)
    if not lake_died:  # the lake lived to the end: its whole run's peak against its cap
        why = _over(lake_run)
        rep.check("rebuild.under_cap", not why, why or f"peak {gib(lake_run.peak)} (rebuild and the screen's queries)")


class _Store:
    """The site set-up's store for the main workspace: one confirmed fact, and the publish record (the gate reads
    only whether the publish was recorded)."""

    def __init__(self) -> None:
        self.pub: dict[str, Any] | None = None

    def facts(self, ws: str, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "pid": "scale-gate",
                "domain": "condition",
                "term": "gout",
                "code": "M10.1",
                "system": "http://hl7.org/fhir/sid/icd-10",
                "value": "",
                "unit": "",
                "day": "2026-10-01",
                "status": "coded",
                "local_code": "",
                "local_system": "",
                "quote": "",
                "input_id": 1,
            }
        ]

    def mapping(self, ws: str) -> dict[Any, Any]:
        return {}

    def inputs(self, ws: str, kind: str) -> list[dict[str, Any]]:
        return []

    def published(self, ws: str) -> dict[str, Any] | None:
        return self.pub

    def set_published(self, ws: str, at: str, snapshot: str, digest: str, counts: dict[str, int]) -> None:
        self.pub = {"snapshot": snapshot, "digest": digest, "counts": counts}


class _CountingLake:
    """The product's ``LakeHttp``; counts the rebuilds the lake started (a 409 "already building" started none)."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.started = inner, 0
        self.errors: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def holds(self) -> dict[str, str]:
        out: dict[str, str] = self.inner.holds() if hasattr(self.inner, "holds") else {}
        return out

    def rebuild(self, snapshot: str, allow_empty: bool = False) -> dict[str, Any]:
        return self._count(lambda: self.inner.rebuild(snapshot))

    def start_rebuild(self, snapshot: str, allow_empty: bool = False) -> dict[str, Any]:
        """T-690 (D-472): the publish starts the rebuild as a job and follows it; a start counts as one rebuild."""
        return self._count(lambda: self.inner.start_rebuild(snapshot))

    def _count(self, call: Any) -> dict[str, Any]:
        import httpx

        try:
            out: dict[str, Any] = call()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:  # 409: busy, already building: no rebuild started
                self.started += 1
            self.errors.append(f"{exc.response.status_code}")
            raise
        except Exception as exc:
            if not _busy(exc):
                self.started += 1
            self.errors.append(type(exc).__name__)
            raise
        self.started += 1
        return out


def _busy(exc: Exception) -> bool:
    try:
        from lake.store import LakeBusy
    except ImportError:  # pragma: no cover - an older lake
        return False
    return isinstance(exc, LakeBusy)


def _publish(p: Params, rep: Report, url: str, alive: Any, token: str) -> bool:
    """The site publish ticks as the orchestrator's scheduler does (``_flush_main``: every tick, errors logged and
    tried again on the next) until it is recorded, a second rebuild of the snapshot starts, or the lake dies."""
    from lake.client import LakeHttp
    from sitesetup.service import SiteSetup
    from tb_common.audit import AuditLog
    from tb_common.service_auth import TOKEN_HEADER

    inner = LakeHttp(url) if p.lake_timeout_s is None else LakeHttp(url, timeout=p.lake_timeout_s)
    inner.client.headers[TOKEN_HEADER] = token  # this run's token, without changing this process's environment
    lake = _CountingLake(inner)
    st = _Store()
    work = p.out / "work"
    svc = SiteSetup(
        st,  # type: ignore[arg-type]
        work / "setup",
        lake,
        None,
        AuditLog(work / "setup-audit"),
        lambda: datetime(2026, 10, 5, tzinfo=UTC),
        lambda: date.fromisoformat(SNAPSHOT),
        lambda: SITE_KEY,
    )
    t0 = time.monotonic()
    ticks: list[str] = []
    first: float | None = None
    while time.monotonic() - t0 < p.publish_wait_s and alive():
        try:
            out = svc.flush("main")
            ticks.append("building" if out.get("building") else "pending" if out.get("pending") else "done")
        except Exception as exc:  # the scheduler logs and tries again next tick
            ticks.append(type(exc).__name__)
        if first is None:
            first = time.monotonic() - t0
        if st.pub is not None or lake.started >= 2:
            break
        time.sleep(p.publish_poll_s)
    took = time.monotonic() - t0
    snap_built = False
    if alive():
        try:
            snap_built = inner.snapshot() == SNAPSHOT
        except Exception:
            snap_built = False
    rep.numbers["publish"] = {
        "ticks": ticks,
        "rebuilds_started": lake.started,
        "seconds": round(took, 1),
        "first_answer_s": round(first or 0, 1),
        "client_timeout_s": inner.client.timeout.read,
    }
    if not alive():
        # the lake's death is the rebuild's failure (its cap, F-05), not the publish's: blocked by it, never a pass
        rep.check("publish.recorded_once", None, f"the lake died during the publish (ticks {ticks[-5:]})", "rebuild")
        return False
    ok = st.pub is not None and lake.started == 1
    detail = (
        f"recorded after {took:.0f} s with one rebuild"
        if ok
        else f"recorded={st.pub is not None}, rebuilds started {lake.started}, ticks {ticks[-6:]}, first answer "
        f"after {first or 0:.1f} s against the client's {inner.client.timeout.read:.1f} s"
    )
    rep.check("publish.recorded_once", ok, detail)
    if not snap_built:  # wait for the build that runs, so the screen reads it
        end = time.monotonic() + p.publish_wait_s
        while alive() and time.monotonic() < end:
            try:
                if inner.snapshot() == SNAPSHOT:
                    return True
            except Exception:
                pass
            time.sleep(p.publish_poll_s)
        return False
    return True


def _screen(
    p: Params, rep: Report, enf: Enforcer, work: Path, logs: Path, lake_url: str, lake_alive: Any, token: str
) -> None:
    model = SlowModel(work / "stub", p.latency_s, p.outage_after, p.outage_s, p.restart_gap_s)
    model.start()
    done = threading.Event()
    watcher = model.restart_after(p.restart_after, done) if p.restart_after else None
    try:
        sc = enf.run(
            "screen (cascade)",
            "orchestrator",
            p.caps["orchestrator"],
            [
                sys.executable,
                "-c",
                CHILD_SCREEN,
                lake_url,
                model.url,
                TRIAL,
                SNAPSHOT,
                REF_DATE.isoformat(),
                str(work / "screen"),
            ],
            _env(TB_SERVICE_TOKEN=token),
            ROOT,
            logs / "screen.log",
        )
    finally:
        done.set()
        if watcher is not None:
            watcher.join(timeout=60)
        model.stop()
    rep.runs.append(sc)
    got = _last_json(sc.tail) or {}
    rep.numbers["screen"] = {
        **got,
        "stand_in_calls": model.calls(),
        "stand_in_502": model.refused(),
        "stand_in_restarts": model.restarts,
    }
    why = _over(sc)
    if why and not lake_alive():
        why += " (the lake died under it)"
    rep.check(
        "screen.ends_under_cap",
        not why,
        why or f"{got.get('judge_calls', 0)} judge calls in {sc.seconds:.0f} s, peak {gib(sc.peak)}",
    )
    if why:
        rep.check("screen.model_faults_seen", None, "the screen did not end", blocked_by="screen")
        rep.check("screen.outage_no_unknown", None, "the screen did not end", blocked_by="screen")
        return
    refusals: dict[str, int] = got.get("refusals") or {}
    lost = sum(n for r, n in refusals.items() if r in FAULT_REFUSALS)
    other = {r: n for r, n in refusals.items() if r not in FAULT_REFUSALS}
    calls = int(got.get("judge_calls", 0))
    rest = f"; {sum(other.values())} other refusals, not the model's faults: {other}" if other else ""
    if not (model.refused() or model.restarts):  # nothing to survive: the check was not exercised, never a pass
        rep.check(
            "screen.outage_no_unknown",
            None,
            "no outage or restart reached the stand-in (none configured, or the screen made too few calls)" + rest,
            blocked_by="the stand-in's faults",
        )
    else:
        rep.check(
            "screen.outage_no_unknown",
            lost == 0,
            (
                f"{lost} of {calls} judge calls lost to the model's faults ({refusals})"
                if lost
                else f"none of {calls} judge calls lost"
            )
            + rest,
        )
    want_outage, want_restart = p.outage_s > 0, p.restart_after > 0
    seen = (not want_outage or model.refused() > 0) and (not want_restart or model.restarts == 1)
    detail = f"{model.refused()} answers of 502, {model.restarts} restart(s) in {model.calls()} calls"
    if not seen and lost:  # the job lost its calls (the breaker answers for the model): the later fault is not met
        rep.check("screen.model_faults_seen", None, detail, blocked_by="screen.outage_no_unknown")
    else:
        why = (
            ""
            if seen
            else ": the screen made too few calls for the faults; lower TB_SCALE_OUTAGE_AFTER / _RESTART_AFTER"
        )
        rep.check("screen.model_faults_seen", seen, detail + why)


# ------------------------------------------------------------------------------------------------ the backup
class ComposeStandIn:
    """The compose commands of the nightly backup, played on this host: the db container's snapshot script runs for
    real with the local ``psql`` against the run's database; ``ps`` answers the compose file's services; ``pause``,
    ``unpause`` and the backup container are recorded (the container writes a file, as ``FakeBox`` in the unit tests);
    every command is timed."""

    def __init__(self, db_url: str, spool: Path) -> None:
        from tb_common.db import split_url

        self.dsn, self.prefix = split_url(db_url)
        self.spool = spool
        self.log: list[tuple[float, float, list[str]]] = []
        self.db = ""

    def services(self) -> list[str]:
        import yaml

        doc = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")) or {}
        return sorted(n for n, s in (doc.get("services") or {}).items() if not (s or {}).get("profiles"))

    def __call__(
        self,
        argv: list[str],
        stdin_file: Path | None = None,
        stdout_file: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        from tools.trialbox import backup_schedule as bs

        t0 = time.monotonic()
        out = ""
        joined = " ".join(argv)
        try:
            if "psql" in joined and stdin_file is not None:
                self.db = argv[-1].split("/")[-1].removesuffix(".sql")
                self.spool.mkdir(parents=True, exist_ok=True)
                refdata = f"{self.prefix}refdata" if self.db == "trialbox_wf" else None
                script = bs.snapshot_script(
                    str(self.spool), self.db, "pg_dump", f'--dbname "{self.dsn}"', [f"{self.prefix}*"], refdata
                )
                f = self.spool / f"{self.db}.sql"
                f.write_text(script, encoding="utf-8")
                subprocess.run(
                    ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "--dbname", self.dsn, "-f", str(f)],
                    check=True,
                    capture_output=True,
                    timeout=timeout,
                )
                f.unlink()
            elif "psql" in argv and "-c" in argv:  # the backup's catalogue questions to the db container (D-455)
                out = self._query(argv[argv.index("-c") + 1])
            elif len(argv) >= 3 and argv[-3] == "cp":
                dest = Path(argv[-1])
                for x in self.spool.glob(f"{self.db}.*"):
                    shutil.copy2(x, dest / x.name)
            elif "rm" in argv and "-rf" in argv:
                shutil.rmtree(self.spool, ignore_errors=True)
            elif "ps" in argv and "--services" in argv:
                out = "\n".join(self.services()) + "\n"
            elif argv[:2] == ["docker", "run"]:
                for i, a in enumerate(argv):
                    if a == "-v" and ":/backup/" in argv[i + 1]:
                        host = Path(argv[i + 1].split(":")[0])
                        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                        f = host / f"trialbox-SCALE-{stamp}{bs.SUFFIX}"
                        f.write_bytes(b"scale gate: the backup container is not run here")
                        bs.sidecar(f).write_text(f"{'0' * 64}  {f.name}\n")
        finally:
            self.log.append((t0, time.monotonic(), list(argv)))
        return out

    def _query(self, sql: str) -> str:
        """A database's size is the run's own schemas (what its snapshot reads here); the run has no orchestrator, so
        no job runs (the count is 0, the list empty)."""
        if "orch.jobs" in sql:
            return "" if "job_id" in sql else "0\n"
        if "pg_database_size" in sql:
            size = (
                "SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0)::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname LIKE %s AND c.relkind = 'r'"
            )
            import psycopg

            with psycopg.connect(self.dsn) as conn:
                row = conn.execute(size, (f"{self.prefix}%",)).fetchone()
            return f"{int(row[0]) if row else 0}\n"
        raise RuntimeError(f"the compose stand-in has no answer for: {sql[:80]}")

    def paused_window(self) -> tuple[list[str], float, float]:
        """The services paused, how long, and how much of the dump ran while they were."""
        paused: list[str] = []
        t_pause = t_unpause = None
        for t0, t1, a in self.log:
            if "pause" in a:
                paused, t_pause = a[a.index("pause") + 1 :], t1
            elif "unpause" in a:
                t_unpause = t0
        if t_pause is None:
            return [], 0.0, 0.0
        end = t_unpause if t_unpause is not None else time.monotonic()
        dump = sum(min(t1, end) - max(t0, t_pause) for t0, t1, a in self.log if "psql" in " ".join(a) and t1 > t_pause)
        return paused, end - t_pause, max(0.0, dump)


def _backup(p: Params, rep: Report, work: Path, db_url: str) -> None:
    from tools.trialbox import backup as bk
    from tools.trialbox import backup_schedule as bs

    deploy = work / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    volumes = work / "docker-volumes"  # the box's volumes, walked by the backup (D-455): none made here
    volumes.mkdir()
    (deploy / ".env").write_text(f"TB_SITE_ID=SCALE\nTB_DOCKER_VOLUMES={volumes}\n", encoding="utf-8")
    pub = work / "keys" / "box.pub"
    bk.keygen(work / "keys" / "box.key", pub)
    target = work / "backup-target"
    target.mkdir()
    cfg = bs.Config(deploy=deploy, targets=[target], public_key=pub, production=False, keep=3, site="SCALE", mailto="")
    if p.backup_quiesce:
        cfg.quiesce = p.backup_quiesce
    box = ComposeStandIn(db_url, work / "db-spool")
    ops = bs.ComposeOps(deploy, box)
    events: list[str] = []
    t0 = time.monotonic()
    res = bs.nightly(
        cfg,
        ops.make_backup(cfg),
        lambda e, d: events.append(e),
        now=datetime.now(UTC),
        classify=lambda t: bs.Target(str(t), "network share", True),
    )
    took = time.monotonic() - t0
    paused, held, under = box.paused_window()
    rep.numbers["backup"] = {
        "ok": res["ok"],
        "seconds": round(took, 1),
        "paused": paused,
        "held_s": round(held, 1),
        "dump_s_while_paused": round(under, 1),
        "errors": res.get("errors", []),
    }
    rep.runs.append(PhaseRun("backup (nightly steps)", "db", p.caps["db"], "host", 0 if res["ok"] else 1, took))
    rep.check("backup.ends", bool(res["ok"]), f"written in {took:.0f} s" if res["ok"] else f"{res.get('errors')}")
    rep.check(
        "backup.no_pause",
        not paused,
        "no service paused"
        if not paused
        else f"{len(paused)} services paused for {held:.1f} s, {under:.1f} s of it the dump of this "
        f"{p.patients:,}-patient database; a box's 20 to 50 GB database is a pause of 30 to 75 minutes",
    )


# ------------------------------------------------------------------------------------------------ the command
def params_from_env(out: Path, patients: int | None = None) -> Params:
    """The gate's settings from ``TB_SCALE_*`` (the nightly job's values are in trialbox-e2e.yml)."""
    e = os.environ

    def f(name: str, default: float) -> float:
        raw = e.get(name, "")
        return float(raw) if raw.strip() else default

    lt = e.get("TB_SCALE_LAKE_TIMEOUT_S", "").strip()
    return Params(
        patients=patients or int(f("TB_SCALE_PATIENTS", 300)),
        out=out,
        enforce=e.get("TB_SCALE_ENFORCE", ""),
        validate=e.get("TB_SCALE_VALIDATE", "1") != "0",
        latency_s=f("TB_SCALE_LATENCY_S", 0.0),
        outage_after=int(f("TB_SCALE_OUTAGE_AFTER", 0)),
        outage_s=f("TB_SCALE_OUTAGE_S", 0.0),
        restart_after=int(f("TB_SCALE_RESTART_AFTER", 0)),
        restart_gap_s=f("TB_SCALE_RESTART_GAP_S", 0.0),
        lake_timeout_s=float(lt) if lt else None,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--patients", type=int)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "scale-gate")
    a = ap.parse_args(argv)
    rep = run(params_from_env(a.out, a.patients))
    sys.stdout.write(rep.markdown())
    return 0 if rep.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
