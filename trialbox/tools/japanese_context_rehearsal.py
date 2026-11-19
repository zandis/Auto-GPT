"""Isolated fixture and SCREEN call capture for O-6."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from functools import partial
from ipaddress import IPv4Address
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from tools.japanese_context import MIX, PROFILES, Arm, ObservedGateway, Provenance, call_scope

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = date(2026, 11, 1)
SNAPSHOT = (REFERENCE - timedelta(days=1)).isoformat()
RUN_DATE = REFERENCE + timedelta(days=1)
PATIENTS = 2500


def fixture(work: Path, seed: int, patients: int) -> tuple[Provenance, Path, Any]:
    from tb_common.ruleset import Ruleset

    from tools.synth_hospital import manifest, parse_lang_mix, run

    generated = run(
        work / "synth",
        sites=f"jp-a:JP:{patients}",
        seed=seed,
        ref_date=REFERENCE,
        lang_mix=parse_lang_mix([MIX]),
    )
    if not generated.passed:
        raise ValueError
    rules_dir = ROOT / "rulesets" / "GZQO"
    rules_digest = hashlib.sha256(json.dumps(manifest(rules_dir), sort_keys=True).encode()).hexdigest()
    provenance = Provenance(seed, patients, generated.summary["digest"], rules_digest)
    return provenance, generated.sites[0].out, Ruleset.load(rules_dir)


def screen(work: Path, lake: Any, rules: Any, arm: Arm, judge_gateway: Any, verifier_gateway: Any) -> None:
    from matching.cascade.engine import _Run
    from orchestrator import canary_gate, selftest
    from orchestrator.scenarios.screen import run_screen
    from tb_common.audit import AuditLog
    from tb_common.config import load_settings
    from tb_common.llm import LlmClient

    lock = Lock()
    job_id = "o6-synthetic"
    clients = [
        LlmClient(gateway.base_url, gateway.model or role, gateway=ObservedGateway(gateway, arm, role, job_id, lock))
        for role, gateway in (("judge", judge_gateway), ("verifier", verifier_gateway))
    ]
    expected = PROFILES[arm.profile]
    arm.contexts_verified = all(client.context_tokens() == expected for client in clients)
    if not arm.contexts_verified:
        return

    cascade_ask = _Run._ask

    def observe_route(engine, role, route, trace):
        with call_scope(role, route.left_out):
            return cascade_ask(engine, role, route, trace)

    ctx = SimpleNamespace(
        job=SimpleNamespace(
            job_id=job_id,
            ruleset=rules.id,
            options={"scope": "hospital"},
            metrics=None,
            received_at=datetime.combine(RUN_DATE, datetime.min.time(), UTC),
        ),
        today=lambda: RUN_DATE,
        metrics=lambda **_: None,
        orch=SimpleNamespace(audit=AuditLog(work / "audit")),
        services=SimpleNamespace(lake=lake, fhir=None, llm=clients[0], verifier=clients[1]),
        cfg=SimpleNamespace(
            env=SimpleNamespace(tz="Asia/Tokyo", data_dir=os.environ.get("TB_DATA_DIR") or "/data"),
            settings=load_settings(ROOT / "deploy" / "settings.example.yaml"),
        ),
    )
    gate = canary_gate.Gate()
    gate.configure(selftest.orch_data_dir(ctx.cfg))
    if not gate.check()[0]:
        return
    cases = selftest.load_cases(ROOT / "services/orchestrator/canary/judge_canary.jsonl")
    with (
        patch.object(canary_gate, "GATE", gate),
        patch.object(canary_gate, "wake_cases", partial(canary_gate.wake_cases, cases)),
        patch.object(_Run, "_ask", observe_route),
        patch.dict(os.environ, {"TB_SCREEN_PIPELINE": "cascade", "TB_SCREEN_JUDGE": "agreement"}),
    ):
        result = run_screen(ctx, rules, RUN_DATE, SNAPSHOT)
    arm.finished = gate.check()[0] and not (
        (result.judging or {}).get("failures") or (result.cascade or {}).get("budget", {}).get("hit")
    )


def ingest(work: Path, feed: Path) -> Any:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from tb_common.kek import create_key_file

    from tests.inproc_box import ingest_site
    from tools.scenarios import secrets_dir

    lake_dir = work / "lake"
    sec = secrets_dir(work)
    create_key_file(sec / "pid_map.key")
    report = ingest_site(feed, lake_dir, sec, SNAPSHOT, site_id="JP-A")
    if not report.passed:
        raise ValueError
    return LakeLocal(lake_dir, HashEmbedder(), tz="Asia/Tokyo")


# Ballast and gateway must belong to the same local Docker daemon.
LOCAL_DOCKER = ("docker", "--host", "unix:///var/run/docker.sock")


def ballast_holder() -> str:
    from tools.ballast import CONTAINER, run_cmd

    return run_cmd(
        [*LOCAL_DOCKER, "ps", "--no-trunc", "--format", "{{.ID}}", "--filter", f"name=^{CONTAINER}$"]
    ).strip()


def validation_gateway() -> str:
    from tools.ballast import run_cmd

    # Docker returns only the running validation service's local network address.
    template = (
        '{{if and .State.Running (eq (index .Config.Labels "com.docker.compose.service") "gateway")}}'
        '{{range .Config.Env}}{{if eq . "TB_ENV=VALIDATION"}}'
        '{{(index $.NetworkSettings.Networks "trialbox-net").IPAddress}}{{end}}{{end}}{{end}}'
    )
    addr = run_cmd([*LOCAL_DOCKER, "inspect", "--format", template, "trialbox-gateway-1"]).strip()
    return f"http://{IPv4Address(addr)}:8020/v1"


def _collect(work: Path, seed: int, arm: Arm) -> None:
    from tb_llm import GatewayClient

    from tools import pglocal

    arm.provenance, feed, rules = fixture(work, seed, PATIENTS)
    holder = ballast_holder()
    if bool(holder) != (arm.profile == "ballast"):
        return
    url = validation_gateway()
    # Only the service credential, canary location/age, local PG tools and profile concurrency
    # are inputs from the box. The fixture, lake, adapter, audit and all database clients use scratch.
    keep = {
        "TB_SERVICE_TOKEN",
        "TB_SERVICE_TOKEN_FILE",
        "TB_CANARY_MAX_AGE_H",
        "TB_PG_BIN",
        "TB_SCREEN_LLM_CONCURRENCY",
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PG", "LLM_")) or k in keep}
    orch_dir = os.environ.get("TB_ORCH_DIR") or str(Path(os.environ.get("TB_DATA_DIR") or "/data") / "orchestrator")
    env.update(
        TB_ENV="VALIDATION",
        TB_SERVICE_NAME="orchestrator",
        TB_GATEWAY_URL=url,
        TB_MODEL_SWAP="sleep" if arm.profile == "ballast" else "off",
        TB_CANARY_GATE="on",
        TB_ORCH_DIR=orch_dir,
        TB_DATA_DIR=str(work),
        TB_AUDIT_WRITER="file",
        TB_AUDIT_DIR=str(work / "audit"),
        TB_TZ="Asia/Tokyo",
        NO_PROXY="*",
        no_proxy="*",
    )
    with patch.dict(os.environ, env, clear=True):
        os.environ["TB_DB_URL"] = pglocal.ensure(work / "pg")
        judge = GatewayClient(url, "orchestrator", model="j-workhorse")
        try:
            verifier = GatewayClient(url, judge.caller, http=judge.http, model="v-verifier")
            lake = ingest(work, feed)
            screen(work, lake, rules, arm, judge, verifier)
            arm.finished = arm.finished and ballast_holder() == holder and validation_gateway() == url
        finally:
            judge.http.close()


def capture(folder: Path, profile: str, seed: int) -> Arm:
    from tools import pglocal

    if seed < 0 or profile not in PROFILES:
        raise ValueError
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{profile}.json"
    arm = Arm(profile)
    if os.environ.get("TB_ENV") == "VALIDATION":
        with TemporaryDirectory(prefix=".o6-", dir=folder) as scratch:
            work = Path(scratch)
            try:
                _collect(work, seed, arm)
            except (Exception, KeyboardInterrupt):
                arm.finished = False
            finally:
                pglocal.remove(work / "pg")
    # Publish once. Concurrent or interrupted retries cannot replace a complete capture with a partial one.
    with (folder / ".capture.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if arm.complete or not Arm.read(path, profile).complete:
            arm.write(path)
        else:
            arm.write(folder / f"{profile}.incomplete.json")
    return arm
