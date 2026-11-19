import json
import os
import subprocess
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import httpx
import pytest
from orchestrator import canary_gate, selftest
from orchestrator.scenarios import screen as screen_module
from tb_common.config import site_tz
from tb_common.llm import LlmClient
from tb_llm import CallLabels, GatewayClient

from tools import japanese_context_rehearsal as rehearsal
from tools import pglocal
from tools.japanese_context import Arm, Counts, ObservedGateway, Provenance, call_scope

PROVENANCE = Provenance(42, 2500, "a" * 64, "b" * 64)
RESULT = SimpleNamespace(judging={}, cascade={})


def screen_with(monkeypatch, work, action, gateway=None):
    arm = Arm("ballast", PROVENANCE)
    if gateway is None:
        gateway = SimpleNamespace(model="test", base_url="in-process", context=lambda: 8192)
    monkeypatch.setattr(screen_module, "run_screen", action)
    rehearsal.screen(work, None, SimpleNamespace(id="synthetic"), arm, gateway, gateway)
    return arm


def test_wake_reads_only_reviewed_cases(tmp_path, monkeypatch):
    cases = selftest.load_cases(rehearsal.ROOT / "services/orchestrator/canary/judge_canary.jsonl")
    cases[0]["excerpts"][0]["text"] = "PLANTED SITE CANARY"
    for case in cases:
        case["excerpts"] = cases[0]["excerpts"]
    site = tmp_path / "site.jsonl"
    site.write_text("\n".join(map(json.dumps, cases)))
    monkeypatch.setenv("TB_CANARY_CASES", str(site))
    # selftest binds the shell override in its default argument at import.
    monkeypatch.setattr(selftest.load_cases, "__defaults__", (site,))
    observed = []

    def run(*_):
        observed.extend(canary_gate.wake_cases())
        return RESULT

    screen_with(monkeypatch, tmp_path, run)
    assert len(observed) == 6
    assert "PLANTED SITE CANARY" not in json.dumps(observed)


def test_screen_loads_current_pair_canary(tmp_path, monkeypatch):
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    monkeypatch.setenv("TB_ORCH_DIR", str(tmp_path))
    monkeypatch.setenv("TB_CANARY_GATE", "on")
    monkeypatch.setattr(canary_gate, "GATE", canary_gate.Gate())
    (tmp_path / "selftest.json").write_text(json.dumps({"ok": True, "pair": {"correct": 54}}))
    policies = []

    def run(*_):
        policies.append(canary_gate.check()[:2])
        return RESULT

    screen_with(monkeypatch, tmp_path, run)
    assert policies == [(True, "ok")]


@pytest.mark.parametrize("refreshed", [None, 32768])
def test_lost_or_changed_context_invalidates_observations(tmp_path, monkeypatch, refreshed):
    contexts = iter([8192, 8192, refreshed, refreshed])
    gateway = SimpleNamespace(model="test", base_url="in-process", context=lambda: next(contexts))
    monkeypatch.setattr(LlmClient, "CONTEXT_TTL_S", 0)

    def run(ctx, *_):
        for client in (ctx.services.llm, ctx.services.verifier):
            client.context_tokens()
        return RESULT

    arm = screen_with(monkeypatch, tmp_path, run, gateway)
    arm.counts = Counts(1, 0, 900, 20)
    assert not arm.complete
    assert not arm.contexts_verified


def test_dropped_completion_cannot_hide_a_model_execution():
    requests = []

    def respond(request):
        requests.append(request.method)
        if len(requests) == 1:
            raise httpx.RemoteProtocolError("synthetic response dropped")
        return httpx.Response(
            200, json={"tb": {"alias": "judge"}, "usage": {"prompt_tokens": 900, "completion_tokens": 20}}
        )

    arm = Arm("ballast", PROVENANCE, finished=True, contexts_verified=True)
    labels = CallLabels("D3", "screening", "o6-synthetic", "s3_note_judgement", "judge", "judge@4")
    with httpx.Client(transport=httpx.MockTransport(respond)) as http, call_scope("judge", 1):
        gateway = GatewayClient("http://test.invalid/v1", "orchestrator", http=http, model="judge")
        observed = ObservedGateway(gateway, arm, "judge", labels.study_id, Lock())
        observed.complete({"response_format": {"type": "json_schema"}}, labels)
    assert arm.counts.judge_calls == 1
    assert arm.counts.missing_judge_calls == 1
    assert arm.counts.judge_calls + arm.counts.missing_judge_calls == len(requests)
    assert not arm.complete


@pytest.fixture
def fake_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    monkeypatch.setenv("TB_GATEWAY_URL", "http://site.invalid/v1")
    monkeypatch.setattr(rehearsal, "fixture", lambda *_: (PROVENANCE, tmp_path, None))
    monkeypatch.setattr(rehearsal, "ballast_holder", lambda: "holder")
    monkeypatch.setattr(pglocal, "ensure", lambda _: "scratch-db")
    monkeypatch.setattr(pglocal, "remove", lambda _: None)


@pytest.mark.parametrize("setting", ["omop", "timezone", "audit"])
def test_scratch_ingest_environment(tmp_path, monkeypatch, fake_capture, setting):
    from omop.schema import db_url

    monkeypatch.setattr(rehearsal, "validation_gateway", lambda: "http://synthetic.invalid/v1")
    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    monkeypatch.setenv("TB_OMOP_DB_URL", "site-db")
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "site-audit"))
    monkeypatch.setenv("TB_AUDIT_WRITER", "file")
    monkeypatch.delenv("TB_TZ", raising=False)
    seen = []

    def ingest(work, _):
        if setting == "omop":
            seen.append(db_url() == "scratch-db")
        elif setting == "timezone":
            seen.append(site_tz() == "Asia/Tokyo")
        else:
            seen.append(Path(os.environ["TB_AUDIT_DIR"]).is_relative_to(work))
        raise RuntimeError

    monkeypatch.setattr(rehearsal, "ingest", ingest)
    rehearsal.capture(tmp_path, "ballast", 42)
    assert seen == [True]
    assert os.environ["TB_OMOP_DB_URL"] == "site-db"
    assert "TB_TZ" not in os.environ
    assert os.environ["TB_AUDIT_DIR"] == str(tmp_path / "site-audit")


def test_site_gateway_cannot_receive_calls_or_swap(tmp_path, monkeypatch, fake_capture):
    from tools import ballast

    seen = []
    monkeypatch.setattr(ballast, "run_cmd", lambda *_: "")
    monkeypatch.setattr(rehearsal, "ingest", lambda *_: None)

    def run(work, lake, rules, arm, judge, verifier):
        seen.extend((judge.base_url, verifier.base_url, os.environ["TB_GATEWAY_URL"]))

    monkeypatch.setattr(rehearsal, "screen", run)
    assert not rehearsal.capture(tmp_path, "ballast", 42).complete
    assert not seen


def test_documented_commands_with_activated_python(tmp_path):
    doc = (rehearsal.ROOT / "docs/plan/measurements/japanese-context-o6.md").read_text()
    commands = doc.split("```sh\n")[1].split("```")[0]
    (tmp_path / "o6-results").mkdir()
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\necho "$*" >> calls\n')
    python.chmod(0o755)
    (tmp_path / "python3").symlink_to(python)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]}
    env.pop("TB_PY", None)
    subprocess.run(["sh", "-ec", commands], env=env, cwd=tmp_path, check=True)
    assert len((tmp_path / "calls").read_text().splitlines()) == 5


@pytest.mark.parametrize("profile", ["ballast", "head-box"])
def test_local_gateway_is_shared_with_gpu_controls(tmp_path, monkeypatch, fake_capture, profile):
    from tools import ballast

    monkeypatch.setenv("HTTP_PROXY", "http://site.invalid")
    monkeypatch.setattr(rehearsal, "ballast_holder", lambda: "holder" if profile == "ballast" else "")
    monkeypatch.setattr(rehearsal, "ingest", lambda *_: None)
    monkeypatch.setattr(ballast, "run_cmd", lambda cmd: "127.0.0.1" if cmd[:3] == list(rehearsal.LOCAL_DOCKER) else "")
    seen = []

    def run(work, lake, rules, arm, judge, verifier):
        from orchestrator.twophase import GatewaySwap

        swap = GatewaySwap.from_env()
        try:
            seen.append((judge.base_url, verifier.base_url, swap.url if swap else None, os.environ["no_proxy"]))
        finally:
            if swap:
                swap.http.close()
        arm.contexts_verified = arm.finished = True
        arm.counts = Counts(1, 1, 900, 20, verifier_calls=1)

    monkeypatch.setattr(rehearsal, "screen", run)
    assert rehearsal.capture(tmp_path, profile, 42).complete
    url = rehearsal.validation_gateway()
    assert seen == [(url, url, url if profile == "ballast" else None, "*")]
    assert os.environ["TB_GATEWAY_URL"] == "http://site.invalid/v1"


def test_missing_pair_canary_prevents_qualified_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("TB_CANARY_GATE", "on")
    monkeypatch.setenv("TB_ORCH_DIR", str(tmp_path))
    arm = screen_with(monkeypatch, tmp_path, lambda *_: pytest.fail("SCREEN used an unqualified pair"))
    assert not arm.finished
