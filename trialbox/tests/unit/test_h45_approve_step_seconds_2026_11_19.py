"""Card H-45: the seconds of each step of ``Compiler.approve`` and of the orchestrator's APPROVE job, in the job's
``metrics.step_seconds`` (fixed names, numbers only), adding up to its wall seconds, and read back by
``python -m tools.public_accuracy.approve_profile --steps``. Stand-ins only: the stub model, no FHIR server, a fake
compiler for the orchestrator's side; the slow steps are sleeps planted in the stand-ins, never in product code."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.service import CompileFailed, Compiler
from orchestrator.clients import StepFailed
from orchestrator.core import Orchestrator, Services
from orchestrator.db import JobDB
from orchestrator.scenarios import approve as approve_scenario
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.fhir import FhirEvalError
from tb_common.objstore import FsStore
from tb_common.steptime import APPROVE_STEPS, COMPILER_STEPS, ORCH_STEPS, StepClock
from tb_contracts import ApproveRequest, ApproveResult, JobCreate, JobFile, JobMetrics, SendRequest, SendResult

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401 - env is a fixture
from tools.public_accuracy import approve_profile

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "plan" / "measurements" / "approve-profile-2026-11-19.md"
SLOW = 0.3


def _numbers_only(steps: dict[str, Any]) -> None:
    assert steps and set(steps) <= set(APPROVE_STEPS), set(steps) - set(APPROVE_STEPS)
    assert all(type(v) is float for v in steps.values()), steps
    assert not [v for k, v in steps.items() if not k.endswith("unaccounted") and v < 0]


# --- the names --------------------------------------------------------------------------------------------------


def test_the_step_names_are_exactly_the_documented_set() -> None:
    text = DOC.read_text(encoding="utf-8")
    section = text[text.index("## What the next launch records") :]
    documented = set(re.findall(r"`((?:orch|compiler)\.[a-z_]+)`", section))
    assert documented == set(APPROVE_STEPS)
    assert len(APPROVE_STEPS) == len(set(APPROVE_STEPS))
    assert all(re.fullmatch(r"(orch|compiler)\.[a-z_]+", k) for k in APPROVE_STEPS)


def test_the_clock_adds_up_to_its_total() -> None:
    clock = StepClock()
    clock.lap("orch.target")
    time.sleep(0.05)
    clock.mark()  # the sleep is between steps: the remainder's
    time.sleep(0.02)
    clock.lap("orch.state")
    out = clock.closed("orch.unaccounted", total=1.0)
    assert out["orch.state"] >= 0.02 and out["orch.unaccounted"] == pytest.approx(
        1.0 - sum(clock.seconds.values()), abs=1e-3
    )
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-3)


# --- Compiler.approve ---------------------------------------------------------------------------------------------


class Fhir:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def load(self, libraries: list[dict[str, Any]], valuesets: Any) -> None:
        if self.error is not None:
            raise self.error


def test_compiler_records_its_steps_and_they_add_up(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    res = _compile(env)
    env["deps"].fhir = Fhir()
    real = Compiler.build_artifacts

    def slow_build(self: Compiler, *a: Any, **kw: Any) -> Any:  # the stand-in's sleep, not the product's
        time.sleep(SLOW)
        return real(self, *a, **kw)

    monkeypatch.setattr(Compiler, "build_artifacts", slow_build)
    decisions = _decisions(env["store"], res.review_xlsx_key)
    t0 = time.perf_counter()
    out = _approve(env, decisions)
    wall = time.perf_counter() - t0
    assert out.status == "approved"
    steps = out.step_seconds or {}
    _numbers_only(steps)
    assert set(steps) <= set(COMPILER_STEPS)
    for k in ("compiler.draft_read", "compiler.refresh_installed", "compiler.build_artifacts",
              "compiler.equivalence", "compiler.fhir_load", "compiler.repo_write", "compiler.repo_tag",
              "compiler.repo_promote", "compiler.audit_done", "compiler.unaccounted"):  # fmt: skip
        assert k in steps, k
    assert steps["compiler.build_artifacts"] >= SLOW
    # the planted sleep lands under its own name, nowhere else (a loaded machine may make another step slower still)
    assert sum(v for k, v in steps.items() if k != "compiler.build_artifacts") < wall - SLOW + 0.05
    assert sum(steps.values()) == pytest.approx(wall, abs=0.05)
    assert 0 <= steps["compiler.unaccounted"] < 0.2


def test_a_failing_compiler_step_leaves_the_steps_before_it(env: dict[str, Any]) -> None:  # noqa: F811
    res = _compile(env)
    env["deps"].fhir = Fhir(FhirEvalError("PUT Library/x: 422 refused"))
    with pytest.raises(CompileFailed) as exc:
        _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert exc.value.step == "approve"  # the failure as before
    steps = exc.value.step_seconds  # type: ignore[attr-defined]
    _numbers_only(steps)
    assert {"compiler.draft_read", "compiler.build_artifacts", "compiler.files", "compiler.fhir_load"} <= set(steps)
    assert "compiler.repo_write" not in steps and "compiler.audit_done" not in steps


# --- the orchestrator's APPROVE job -------------------------------------------------------------------------------


class FakeMail:
    def send(self, req: SendRequest) -> SendResult:
        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=False)


class FakeCompiler:
    """Sleeps ``SLOW`` and says ``compiler.build_artifacts`` took ``SLOW - 0.05`` of it; or fails."""

    def __init__(self, fail: bool = False, steps: bool = True) -> None:
        self.fail, self.steps = fail, steps

    def approve(self, req: ApproveRequest) -> ApproveResult:
        time.sleep(SLOW)
        if self.fail:
            raise StepFailed("approve", "the compiler refused", "criteria-compiler HTTP 422")
        named = {"compiler.build_artifacts": SLOW - 0.05, "compiler.unaccounted": 0.001} if self.steps else None
        return ApproveResult(ruleset=req.ruleset, version=req.version, status="rejected", round=1, step_seconds=named)


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    def slow_parse(data: bytes) -> tuple[list[Any], dict[str, Any]]:  # the stand-in's sleep
        time.sleep(0.1)
        return [], {}

    monkeypatch.setattr("criteria_compiler.review.parse_review_xlsx", slow_parse)

    def build(compiler: FakeCompiler, earlier: float = 0.0, raise_done_once: bool = False) -> tuple[Orchestrator, str]:
        cfg = Config(env=load_env(dotenv=tmp_path / "x.env", environ={}),
                     settings=load_settings(ROOT / "deploy/settings.example.yaml"))  # fmt: skip
        store = FsStore(tmp_path / "obj")
        services = Services(lake=None, parser=None, compiler=compiler, mail=FakeMail())  # type: ignore[arg-type]
        orch = Orchestrator(cfg, JobDB(), store, AuditLog(tmp_path / "audit"), services,
                            {"APPROVE": approve_scenario.run}, tmp_path / "rulesets", tmp_path,
                            today=lambda: date(2026, 10, 5), workers=0, async_notify=False)  # fmt: skip
        data = b"PK made-up workbook"
        store.put("attachments/A/review.xlsx", data, "application/octet-stream")
        f = JobFile(filename="review.xlsx", sha256=hashlib.sha256(data).hexdigest(),
                    minio_key="attachments/A/review.xlsx")  # fmt: skip
        job = orch.create(JobCreate(type="APPROVE", ruleset="GZQO", requested_by="crc1@hospa.test",
                                    options={"version": "1.0.0"}, inputs=[f]))  # fmt: skip
        if earlier:  # a run before a restart left its wall seconds on the record
            orch.db.put(job.model_copy(update={"metrics": JobMetrics(wall_seconds=earlier)}))
        if raise_done_once:  # the success path's final write fails once; the failure path writes the job
            real, failed = orch.set_state, []

            def set_state(j: Any, state: str, **kw: Any) -> Any:
                if state == "done" and not failed:
                    failed.append(state)
                    raise RuntimeError("the database went away")
                return real(j, state, **kw)

            monkeypatch.setattr(orch, "set_state", set_state)
        orch.drain()
        return orch, job.job_id

    return build


def test_the_approve_job_records_its_steps_adding_up_to_its_wall(box: Any) -> None:
    orch, jid = box(FakeCompiler())
    job = orch.db.get(jid)
    assert job is not None and job.state == "done" and job.metrics is not None
    steps = job.metrics.step_seconds or {}
    _numbers_only(steps)
    for k in ("orch.target", "orch.state", "orch.read_workbook", "orch.parse_review", "orch.compiler_transport",
              "compiler.build_artifacts", "compiler.unaccounted", "orch.fail_awaiting", "orch.deliver",
              "orch.unaccounted"):  # fmt: skip
        assert k in steps, k
    assert "orch.compiler_call" not in steps
    assert steps["orch.parse_review"] >= 0.1  # the slow stand-in under its own name
    assert steps["compiler.build_artifacts"] == pytest.approx(SLOW - 0.05)
    assert steps["orch.compiler_transport"] == pytest.approx(0.05 - 0.001, abs=0.04)
    assert sum(steps.values()) == pytest.approx(job.metrics.wall_seconds, abs=0.002)
    assert 0 <= steps["orch.unaccounted"] < 0.25
    assert set(ORCH_STEPS) & set(steps) and json.loads(json.dumps(steps)) == steps


def test_a_compiler_without_steps_is_one_call(box: Any) -> None:
    orch, jid = box(FakeCompiler(steps=False))
    steps = orch.db.get(jid).metrics.step_seconds
    assert steps["orch.compiler_call"] >= SLOW and "orch.compiler_transport" not in steps
    assert not [k for k in steps if k.startswith("compiler.")]


def test_a_failing_compiler_call_leaves_the_earlier_steps_on_the_failed_job(box: Any) -> None:
    orch, jid = box(FakeCompiler(fail=True))
    job = orch.db.get(jid)
    assert job is not None and job.state == "failed" and job.error is not None
    assert job.error.step == "approve" and job.error.message == "the compiler refused"  # the failure as before
    steps = job.metrics.step_seconds if job.metrics else None
    assert steps is not None
    _numbers_only(steps)
    assert {"orch.target", "orch.state", "orch.read_workbook", "orch.parse_review", "orch.compiler_call",
            "orch.unaccounted"} == set(steps)  # fmt: skip
    assert steps["orch.compiler_call"] >= SLOW and steps["orch.parse_review"] >= 0.1


def test_other_jobs_record_no_steps(tmp_path: Path) -> None:
    from orchestrator.core import Ctx, Outcome

    def feas(ctx: Ctx) -> Outcome:
        ctx.state("running")
        return Outcome(summary_md="ok")

    cfg = Config(env=load_env(dotenv=tmp_path / "x.env", environ={}),
                 settings=load_settings(ROOT / "deploy/settings.example.yaml"))  # fmt: skip
    services = Services(lake=None, parser=None, compiler=None, mail=FakeMail())  # type: ignore[arg-type]
    orch = Orchestrator(cfg, JobDB(), FsStore(tmp_path / "obj"), AuditLog(tmp_path / "audit"), services,
                        {"FEAS": feas}, tmp_path / "rulesets", tmp_path, today=lambda: date(2026, 10, 5),
                        workers=0, async_notify=False)  # fmt: skip
    job = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="crc1@hospa.test"))
    orch.drain()
    got = orch.db.get(job.job_id)
    assert got is not None and got.state == "done" and got.metrics is not None
    assert got.metrics.step_seconds is None and "step_seconds" not in got.model_dump_json(exclude_none=True)


# --- the reader ---------------------------------------------------------------------------------------------------


def test_the_reader_prints_the_step_table_from_stored_records(box: Any, tmp_path: Path, capsys: Any) -> None:
    orch, jid = box(FakeCompiler())
    job = orch.db.get(jid)
    assert job is not None
    rec = json.loads(job.model_dump_json(by_alias=True, exclude_none=True))
    log = tmp_path / "box-calls.log"
    log.write_text("+ 2026-11-19 send 10:00:00\n" + json.dumps({"job": jid, **rec}) + "\nnot json\n", encoding="utf-8")
    out = tmp_path / "steps.json"
    assert approve_profile.main(["--steps", str(log), "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "orch.parse_review" in printed and "compiler.build_artifacts" in printed
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["approve_jobs"] == 1 and r["steps_differ_from_wall"] == []
    assert [x["step"] for x in r["rows"]] == [k for k in APPROVE_STEPS if k in (job.metrics.step_seconds or {})]
    assert sum(x["share"] for x in r["rows"]) == pytest.approx(1.0, abs=0.01)


def test_the_reader_refuses_records_without_steps(tmp_path: Path) -> None:
    p = tmp_path / "job.json"
    p.write_text(json.dumps({"job_id": "J", "type": "APPROVE", "metrics": {"wall_seconds": 3.0}}), encoding="utf-8")
    assert approve_profile.main(["--steps", str(p)]) == 2


def test_the_reader_drops_anything_but_known_names_and_numbers(tmp_path: Path) -> None:
    p = tmp_path / "job.json"
    rec = {"job_id": "J", "type": "APPROVE", "state": "done",
           "metrics": {"wall_seconds": 2.0, "step_seconds": {"orch.target": 1.5, "orch.unaccounted": 0.5,
                                                             "made.up": 9.0, "compiler.files": "text"}}}  # fmt: skip
    p.write_text(json.dumps(rec), encoding="utf-8")
    jobs = approve_profile.approve_jobs([p])
    assert jobs[0]["steps"] == {"orch.target": 1.5, "orch.unaccounted": 0.5}
    assert approve_profile.step_table(jobs)["steps_differ_from_wall"] == []


# --- a restart, and a failed final write (the lead's review) ------------------------------------------------------


def test_a_restarted_job_counts_its_earlier_runs_once_and_adds_up_to_wall(box: Any) -> None:
    orch, jid = box(FakeCompiler(), earlier=20.0)
    job = orch.db.get(jid)
    assert job is not None and job.state == "done" and job.metrics is not None
    steps = job.metrics.step_seconds or {}
    _numbers_only(steps)
    assert steps["orch.earlier_runs"] == 20.0 and job.metrics.wall_seconds > 20.0
    assert sum(steps.values()) == pytest.approx(job.metrics.wall_seconds, abs=0.002)
    assert 0 <= steps["orch.unaccounted"] < 0.25


def test_a_failed_final_write_after_a_restart_still_counts_the_earlier_runs_once(box: Any) -> None:
    orch, jid = box(FakeCompiler(), earlier=20.0, raise_done_once=True)
    job = orch.db.get(jid)
    assert job is not None and job.state == "failed" and job.metrics is not None
    steps = job.metrics.step_seconds or {}
    _numbers_only(steps)
    assert steps["orch.earlier_runs"] == 20.0  # once, not twice
    assert steps["orch.unaccounted"] >= 0 and all(v >= 0 for v in steps.values())
    assert 20.0 < sum(steps.values()) < 20.0 + 5.0


def test_closing_the_clock_twice_gives_the_same_steps() -> None:
    clock = StepClock()
    clock.add("orch.target", 0.5)
    a = clock.closed("orch.unaccounted", total=30.0, extra={"orch.earlier_runs": 20.0})
    b = clock.closed("orch.unaccounted", total=30.0, extra={"orch.earlier_runs": 20.0})
    assert a == b == {"orch.target": 0.5, "orch.earlier_runs": 20.0, "orch.unaccounted": 9.5}
    assert clock.seconds == {"orch.target": 0.5}


# --- the real route shape -----------------------------------------------------------------------------------------


def test_the_compiler_route_and_the_orchestrators_client_carry_step_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    from criteria_compiler import app as capp
    from fastapi.testclient import TestClient
    from orchestrator.clients import CompilerHttp

    sent = {"compiler.build_artifacts": 1.25, "compiler.unaccounted": 0.5}

    class Answer:
        def approve(self, req: ApproveRequest) -> ApproveResult:
            return ApproveResult(ruleset=req.ruleset, version=req.version, status="rejected", round=1,
                                 step_seconds=sent)  # fmt: skip

    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(capp, "compiler", Answer)
    client = CompilerHttp("http://testserver")
    client.c.client = TestClient(capp.app)
    got = client.approve(ApproveRequest(ruleset="GZQO", version="1.0.0", by="crc1@hospa.test", decisions=[]))
    assert got.status == "rejected" and got.step_seconds == sent
