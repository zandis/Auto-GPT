"""Isolated fixture and SCREEN call capture for O-6."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
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
            env=SimpleNamespace(tz="Asia/Tokyo"),
            settings=load_settings(ROOT / "deploy" / "settings.example.yaml"),
        ),
    )
    with (
        patch.object(_Run, "_ask", observe_route),
        patch.dict(os.environ, {"TB_SCREEN_PIPELINE": "cascade", "TB_SCREEN_JUDGE": "agreement"}),
    ):
        result = run_screen(ctx, rules, RUN_DATE, SNAPSHOT)
    arm.finished = not ((result.judging or {}).get("failures") or (result.cascade or {}).get("budget", {}).get("hit"))


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


def ballast_holder() -> str:
    from tools.ballast import CONTAINER, run_cmd

    return run_cmd(["docker", "ps", "--no-trunc", "--format", "{{.ID}}", "--filter", f"name=^{CONTAINER}$"]).strip()


def capture(folder: Path, profile: str, seed: int) -> Arm:
    from tb_llm import GatewayClient

    from tools import pglocal

    if seed < 0:
        raise ValueError
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{profile}.json"
    arm = Arm(profile)
    arm.write(path)
    if os.environ.get("TB_ENV") != "VALIDATION":
        return arm
    with TemporaryDirectory(prefix=".o6-", dir=folder) as scratch:
        work = Path(scratch)
        try:
            arm.provenance, feed, rules = fixture(work, seed, PATIENTS)
            arm.write(path)
            holder = ballast_holder()
            if bool(holder) != (profile == "ballast"):
                return arm
            judge = GatewayClient(os.environ.get("TB_GATEWAY_URL", ""), "orchestrator", model="j-workhorse")
            verifier = GatewayClient(judge.base_url, judge.caller, http=judge.http, model="v-verifier")
            try:
                with patch.dict(os.environ):
                    os.environ["TB_DB_URL"] = pglocal.ensure(work / "pg")
                    os.environ.pop("TB_DATA_CLASS", None)
                    os.environ["TB_MODEL_SWAP"] = "sleep" if profile == "ballast" else "off"
                    os.environ["TB_SERVICE_NAME"] = "orchestrator"
                    lake = ingest(work, feed)
                    screen(work, lake, rules, arm, judge, verifier)
                    arm.finished = arm.finished and ballast_holder() == holder
            finally:
                judge.http.close()
        except (Exception, KeyboardInterrupt):
            # An interrupted or failed capture can still file the numeric observations collected so far.
            arm.finished = False
        finally:
            arm.write(path)
            pglocal.remove(work / "pg")
    return arm
