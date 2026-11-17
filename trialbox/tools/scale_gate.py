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
import contextlib
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

from tb_llm.outage import MODEL_FAULTS  # noqa: E402
from tb_testkit.scale import (  # noqa: E402
    Check,
    Enforcer,
    Expected,
    PhaseRun,
    SlowModel,
    Stalled,
    Watch,
    compose_caps,
    compose_setting,
    free_port,
    gate_ok,
    gib,
    markdown,
    stall_check,
    verdict,
    wait_http,
)

PROFILES = ("thin", "dense")
REF_DATE = date(2026, 10, 5)  # the synthetic generator's reference day (tools.synth)
SNAPSHOT = "2026-10-04"  # the night before it: the snapshot the night writes
TRIAL = "GZQO"  # the ruleset of hospital_sim and the bench gate
SITE_KEY = b"trialbox-scale-gate-site-key-0123456789"
FULL = 50_000  # the size of the plan's reference site (SPEC §11.3, review §3): the nightly job's size
# the gateway's refusals that are the model's faults (an outage, a restart, a queue), not the call's content: the
# product's own list (T-689, D-456: ``upstream_down`` is the gateway's 5xx or transport error after its own retry), and
# ``upstream_failed``, which before T-689 was how a 502 outage was answered (a call lost to it is lost to the model)
FAULT_REFUSALS = frozenset({*MODEL_FAULTS, "upstream_failed"})
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
    # empty since T-689 (D-456): F-01 (T-690), F-02 (T-691), F-05 (T-692) and F-04 (T-689) were listed until their
    # cards merged; each then passed at 200 and 2,000 patients and its line was removed. A new known failure goes here
    # with its finding and card.
}


#: D-674: the default of ``TB_SCALE_STALL_S``. Not a budget for a part's length: the longest time the gate goes on
#: while NONE of its processes works or writes its log and nothing a wait watches changes
#: (``tb_testkit.scale.stall_check``). The longest quiet interval the gate has by design is the screen waiting
#: through the model stand-in's outage and restart (the nightly job: 40 s and 30 s); ten minutes is an order above
#: that, and a dead part then costs ten of the job's 340 minutes. No quiet interval was measured on a schedule
#: before this card; the report now holds each process's longest one (``longest_quiet_s``), which is what a later
#: default is chosen from.
STALL_S = 600.0
PUBLISH = "site publish and lake rebuild"

#: the gate's report, in the order ``Report.write`` writes it
REPORT_FILES = ("scale_gate.json", "scale_gate.md")


@dataclass
class Params:
    patients: int
    out: Path
    profile: str = "thin"  # TB_SCALE_PROFILE: thin (the generator's own hospital) | dense (about 500 records
    # and 40 notes per patient: tb_testkit.scale.densify)
    enforce: str = ""  # TB_SCALE_ENFORCE: cgroup | measure | "" (the best this host has)
    validate: bool = True  # the HL7 validator in the night (the JVM; StructuralValidator without it)
    latency_s: float = 0.0  # the stand-in's seconds per call
    outage_after: int = 0  # the call from which the stand-in answers 502
    outage_s: float = 0.0  # for this many seconds
    restart_after: int = 0  # the call count after which the stand-in is restarted once (0: never)
    restart_gap_s: float = 0.0  # how long it is down
    outage_status: int = 502  # the status of the outage's answers (a test plays one the product does not wait through)
    lake_timeout_s: float | None = None  # None: the product's LakeHttp default (the limit F-01 is about)
    publish_poll_s: float = 5.0
    backup_quiesce: str = ""  # "" : the box's default (D-455: off); "pause": D-274's pause, to show the gate sees it
    publish_wait_s: float = 6 * 3600.0  # a guard for a hung lake; the CI job's own timeout is the real bound
    stall_s: float = 600.0  # TB_SCALE_STALL_S (STALL_S): no progress for this long ends the gate (0: never)
    language: str = "auto"  # --language (D-987): the notes' language for the cascade, auto by default
    caps: dict[str, int] = field(default_factory=dict)


@dataclass
class Report:
    params: Params
    mode: str
    runs: list[PhaseRun] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    profile_facts: dict[str, Any] = field(default_factory=dict)  # the dense profile's own numbers
    numbers: dict[str, Any] = field(default_factory=dict)
    #: NEW-B-33 (D-674): the part the gate is in ("" once it has ended). The report is written before every part,
    #: so a gate that is cut (a time limit, a kill, a runner that goes away) leaves what it measured till then.
    unfinished: str = ""

    def progress(self, part: str) -> None:
        """The gate enters ``part``: write the report of what is measured so far, marked NOT FINISHED."""
        self.unfinished = part
        self.write()

    def write(self) -> None:
        """Both report files, each replaced whole: a cut in the middle of a write leaves the report before it."""
        out = self.params.out
        out.mkdir(parents=True, exist_ok=True)
        texts = (json.dumps(self.to_json(), indent=1), self.markdown())
        for name, text in zip(REPORT_FILES, texts, strict=True):
            tmp = out / f".{name}.tmp"
            try:
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(out / name)
            finally:
                tmp.unlink(missing_ok=True)

    def check(self, cid: str, passed: bool | None, detail: str, blocked_by: str = "") -> None:
        assert cid in CHECKS, cid
        self.checks.append(Check(cid, passed, detail, blocked_by))

    def rows(self) -> list[dict[str, Any]]:
        return verdict(self.checks, EXPECTED, self.params.patients)

    def ok(self) -> bool:
        return not self.unfinished and gate_ok(self.rows())

    def markdown(self) -> str:
        p = self.params
        caps = ", ".join(f"{SERVICE[k]} {gib(p.caps[SERVICE[k]])}" for k in ("ingest", "rebuild", "screen"))
        head = [
            f"{p.patients:,} synthetic patients ({p.profile} profile); caps from deploy/docker-compose.yml: {caps}; "
            f"enforcement: {self.mode}.",
            f"Model stand-in: {p.latency_s} s per call, 502 for {p.outage_s} s from call {p.outage_after}, "
            f"restart after call {p.restart_after or 'never'}.",
            *(f"Note: {n}" for n in self.notes),
        ]
        if not self.unfinished:
            return markdown(self.rows(), head, self.runs)
        head.append(
            f"**NOT FINISHED: {self.unfinished}.** This report was written when the gate entered that part. If it "
            "is the last report of a run, the gate ended there: cut (a time limit, a kill), or by an error of its "
            "own, which a note above then names. The rows below are what was measured till then; a check without "
            "a row was not made (some are made only at the end of their part); a process shown as still running "
            "has no result and no peak yet."
        )
        body = markdown(self.rows(), head, self.runs).rstrip("\n").split("\n")
        body[-1] = f"Gate: NOT FINISHED (in: {self.unfinished})."
        return "\n".join(body) + "\n"

    def to_json(self) -> dict[str, Any]:
        return {
            "patients": self.params.patients,
            "profile": self.params.profile,
            "profile_facts": self.profile_facts,
            "mode": self.mode,
            "ok": self.ok(),
            "unfinished": self.unfinished,
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
                    "longest_quiet_s": round(r.quiet_max_s, 1),
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
n, out, ref, profile = int(sys.argv[1]), Path(sys.argv[2]), date.fromisoformat(sys.argv[3]), sys.argv[4]
if profile == "dense":  # T-687, the dense profile: the generator's hospital, thickened to a real chart's size
    import json
    from tb_testkit.scale import densify
    thin = out.with_name(out.name + "-thin")
    write_site(generate(42, "DEMO-A", ref, n, "1"), thin)
    print(json.dumps(densify(thin, out)))
else:
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
# D-539: the build is a process of its own and does not get the line above; it reads the environment, so the limit
# the service derives from the cap is handed on as the setting a box would have
os.environ.setdefault("TB_LAKE_MEMORY_LIMIT", store.memory_limit())
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

lake_url, stub_url, trial, snap, run_date, work, lang_arg = sys.argv[1:8]
for name in ("gateway", "httpx"):
    logging.getLogger(name).setLevel(logging.WARNING)
# the gateway as its container runs it: the real policy, breakers and budgets, the stand-in over real HTTP
gw = Gateway(RoutingPolicy.load(), Registry.load(), AuditLog(Path(work) / "audit"),
             GatewayConfig(topology=Topology.A, environment=Environment.TEST), guard=Guard.from_settings(),
             env={**os.environ, "TB_EP_STUB_URL": stub_url})
client = GatewayClient("http://tb-gateway/v1", "orchestrator", http=TestClient(create_app(gw)))
judge = GatewayJudge(client)
rs = load_trial(trial)
from matching.notelang import cascade_languages
language, notes_language = cascade_languages(lang_arg, "zh-TW")  # D-987: the synthetic site writes zh-TW notes
cfg = CascadeConfig(study_id=trial, run_date=date.fromisoformat(run_date), lookback_months=36,
                    language=language, notes_language=notes_language,
                    notes_class="D0", purpose="feasibility", step_id=f"scale:{trial}", sample_per_stratum=200,
                    snapshot=snap)
t0 = time.perf_counter()
res = run_cascade(LakeHttp(lake_url), rs, cfg, judge=judge, embedder=HashEmbedder())
print(json.dumps({"seconds": round(time.perf_counter() - t0, 1), "judge_calls": judge.calls,
                  "refusals": dict(Counter(judge.refusals)),
                  "n_after": dict(res.metrics.n_after)}))
"""


def latency_share(calls: int, latency_s: float, screen_s: float, night_s: float) -> str:
    """D-973: the stand-in's waiting (calls x seconds per call) as a share of the screen and of the night up to the
    screen's end (the parts before it and the screen); empty without a latency or calls. An upper bound: calls that
    overlap wait at the same time."""
    if latency_s <= 0 or calls <= 0:
        return ""
    wait = calls * latency_s

    def pct(total: float) -> str:
        return f"{100 * wait / total:.0f} %" if total > 0 else "n/a"

    return (
        f"Model stand-in waiting: {calls:,} calls x {latency_s:g} s = {wait:,.0f} s, {pct(screen_s)} of the screen's "
        f"{screen_s:,.0f} s and {pct(night_s)} of the night's {night_s:,.0f} s up to the screen's end (an upper bound: "
        "calls that overlap wait at the same time)."
    )


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
    for name in REPORT_FILES:  # D-674: an earlier run's report goes before anything here can fail
        (p.out / name).unlink(missing_ok=True)
    p.caps = p.caps or compose_caps()
    enf = Enforcer.detect(p.enforce)
    enf.stall_s = p.stall_s
    rep = Report(p, enf.mode)
    try:
        _parts(p, rep, enf)
    except BaseException as exc:
        # D-674: the gate ended on an error of its own, or was cut where the cut raises here (a time limit's signal,
        # an interrupt). The processes it started are stopped by now and have their results: write once more
        rep.notes.append(f"the gate ended by {type(exc).__name__} in: {rep.unfinished or 'its last lines'}")
        if isinstance(exc, Stalled):
            rep.notes.append(str(exc))  # which part made no progress, for how long, and what was last seen
        with contextlib.suppress(Exception):
            rep.write()
        raise
    rep.unfinished = ""
    rep.write()
    return rep


def _parts(p: Params, rep: Report, enf: Enforcer) -> None:
    work = p.out / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    logs = p.out / "logs"
    db_url = _db_url(work)
    token = secrets.token_hex(16)  # the box's service token for this run (the lake checks it on every change)
    big = max(p.caps.values())

    # 1. the input
    rep.progress("generate")  # D-674: also replaces an earlier run's report in this folder
    site = work / "site"
    gen = enf.run(
        "generate",
        "-",
        big * 4,
        [sys.executable, "-c", CHILD_GENERATE, str(p.patients), str(site), REF_DATE.isoformat(), p.profile],
        _env(),
        ROOT,
        logs / "generate.log",
    )
    gen.mode, gen.cap = "uncapped", 0
    rep.runs.append(gen)
    if gen.rc != 0:
        raise RuntimeError(f"the synthetic hospital could not be generated: {gen.tail}")
    if p.profile == "dense":
        facts = _last_json(gen.tail) or {}
        rep.profile_facts = facts
        rep.notes.append(
            f"dense profile: {facts.get('records_per_patient')} records and {facts.get('notes_per_patient')} notes "
            f"per patient ({facts.get('records', 0):,} records, {facts.get('notes', 0):,} notes)"
        )

    # 2. the night's ingest under the adapter's cap
    mapping = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
    args = [str(site), str(work), str(mapping), SNAPSHOT, "1" if p.validate else "0", SITE_KEY.decode()]
    env = _env(TB_DB_URL=db_url)
    xmx = compose_setting("adapter", "TB_VALIDATOR_XMX")  # the validator's heap inside the adapter's cap, as composed
    if xmx:
        env["TB_VALIDATOR_XMX"] = xmx
    rep.progress("ingest (nightly)")
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
        rep.progress("ingest (back-fill, to feed the rest)")
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
    rep.progress("backup (nightly steps)")
    _backup(p, rep, work, db_url)


def _db_url(work: Path) -> str:
    from tools import pglocal

    return pglocal.for_work(work)


def _lake_parts(p: Params, rep: Report, enf: Enforcer, work: Path, logs: Path, token: str) -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = _env(
        TB_LAKE_DIR=str(work / "lake"),
        TB_LAKE_EMBEDDER="hash",
        TB_LAKE_BUILD="process",  # D-539: as a box runs it, whatever this process's environment says
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
        rep.progress(PUBLISH)
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
        if not built and not lake_died and _build_interrupted(url, token):
            # D-539: under a cgroup the kernel kills the build's process alone and the service lives; that is the
            # rebuild not ending under the cap, as the service's death was before the build had its own process
            rep.check(
                "rebuild.under_cap",
                False,
                f"the lake's build process was killed during the rebuild (cap {gib(p.caps['lake'])}); the service "
                "lived",
            )
            lake_died = True  # no second verdict on this check below
        if not built:
            for cid in ("screen.ends_under_cap", "screen.model_faults_seen", "screen.outage_no_unknown"):
                rep.check(cid, None, "the lake has no built snapshot", blocked_by="rebuild")
            return
        rep.progress("screen (cascade)")
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


def _build_interrupted(url: str, token: str) -> bool:
    """Whether the rebuild job of the gate's snapshot ended without an answer (its process was killed)."""
    import httpx
    from tb_common.service_auth import TOKEN_HEADER

    try:
        r = httpx.get(f"{url}/rebuild/{SNAPSHOT}", headers={TOKEN_HEADER: token}, timeout=30)
        return bool(r.json().get("state") == "interrupted")
    except Exception:
        return False


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
    moved = Watch()  # D-674: what the publish's ticks say, how many rebuilds started, whether it is recorded
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
        # D-674: a publish that does not move while the lake does no work ends the gate, not the job's own limit
        moved.seen((ticks[-1], lake.started, st.pub is not None))
        stall_check(PUBLISH, p.stall_s, moved)
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
            moved.seen(("waiting for the lake to serve", SNAPSHOT))
            stall_check(PUBLISH, p.stall_s, moved)
            time.sleep(p.publish_poll_s)
        return False
    return True


def _screen(
    p: Params, rep: Report, enf: Enforcer, work: Path, logs: Path, lake_url: str, lake_alive: Any, token: str
) -> None:
    model = SlowModel(work / "stub", p.latency_s, p.outage_after, p.outage_s, p.restart_gap_s, p.outage_status)
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
                p.language,
            ],
            _env(TB_SERVICE_TOKEN=token),
            ROOT,
            logs / "screen.log",
            watch=model.log_bytes,  # D-674: every call the stand-in sees is the screen's progress
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
        "stand_in_outage_answers": model.refused(),
        "stand_in_restarts": model.restarts,
    }
    # D-973: how much of the screen and of the night was the stand-in's waiting (D-537 asked for the scale gate's
    # latency share)
    share = latency_share(model.calls(), p.latency_s, sc.seconds, sum(r.seconds for r in rep.runs))
    if share:
        rep.notes.append(share)
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
    faults = f"{model.refused()} outage answers ({model.outage_status}), {model.restarts} restart(s)"
    detail = f"{faults} in {model.calls()} calls"
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
def limit_s() -> float:
    """NEW-B-33 (D-674): the time limit of the gate's test, in seconds: ``TB_SCALE_LIMIT_S``, else 0, which is "no
    limit" to pytest-timeout. Not the suite's default (900 s per test): the gate is one fixture that runs a whole
    night, and a night is measured, not budgeted. The nightly job's own ``timeout-minutes`` ends a hang; a person
    who wants a bound on their own machine sets the variable."""
    raw = os.environ.get("TB_SCALE_LIMIT_S", "").strip()
    if not raw:
        return 0.0
    try:
        limit = float(raw)
    except ValueError:
        limit = -1.0
    if limit < 0:
        raise ValueError(f"TB_SCALE_LIMIT_S={raw!r}: give a number of seconds, or leave it empty for no limit")
    return limit


def params_from_env(
    out: Path, patients: int | None = None, profile: str | None = None, language: str = "auto"
) -> Params:
    """The gate's settings from ``TB_SCALE_*`` (the nightly job's values are in trialbox-e2e.yml)."""
    e = os.environ

    def f(name: str, default: float) -> float:
        raw = e.get(name, "")
        return float(raw) if raw.strip() else default

    lt = e.get("TB_SCALE_LAKE_TIMEOUT_S", "").strip()
    stall = f("TB_SCALE_STALL_S", STALL_S)
    if stall < 0:
        raise ValueError(f"TB_SCALE_STALL_S={stall:g}: give a number of seconds, or 0 for no stall cut")
    return Params(
        patients=patients or int(f("TB_SCALE_PATIENTS", 300)),
        out=out,
        profile=profile or e.get("TB_SCALE_PROFILE", "").strip() or "thin",
        enforce=e.get("TB_SCALE_ENFORCE", ""),
        validate=e.get("TB_SCALE_VALIDATE", "1") != "0",
        latency_s=f("TB_SCALE_LATENCY_S", 0.0),
        outage_after=int(f("TB_SCALE_OUTAGE_AFTER", 0)),
        outage_s=f("TB_SCALE_OUTAGE_S", 0.0),
        restart_after=int(f("TB_SCALE_RESTART_AFTER", 0)),
        restart_gap_s=f("TB_SCALE_RESTART_GAP_S", 0.0),
        lake_timeout_s=float(lt) if lt else None,
        stall_s=stall,
        language=language,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--patients", type=int)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "scale-gate")
    ap.add_argument(
        "--profile", choices=PROFILES, help="thin (default) or dense: about 500 records, 40 notes per patient"
    )
    ap.add_argument(
        "--language", default="auto", help="the notes' language: auto (read per patient), en, zh-TW, ja (D-987)"
    )
    a = ap.parse_args(argv)
    rep = run(params_from_env(a.out, a.patients, a.profile, a.language))
    sys.stdout.write(rep.markdown())
    return 0 if rep.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
