"""`trialbox eval qualify` and the qualification record (T-012a, D-313): every step runs against the stub through an
in-process gateway; a record missing or failing any step is `failed`; a record of another profile, an edited record
and synthetic weights for PRODUCTION are refused.

No GPU, no network: the gateway and ``services/llm_stub`` run in this process.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import yaml

from tools import qualify as q

FAST = {"repeat_items": 20}


def _ctx(opts: q.Options, tmp_path: Path, builds: dict[str, q.Build] | None = None) -> q.Ctx:
    """A context for a step that calls no model."""
    return q.Ctx(opts, cast(q.Target, None), builds or {}, cast(q.QClient, None), cast(q.QClient, None), tmp_path,
                 io.StringIO())  # fmt: skip


def _opts(**over: Any) -> q.Options:
    base: dict[str, Any] = {"profile": "ci", "stub": True, "operator": "test", "sources": ("synthetic",), **FAST}
    base.update(over)
    return q.Options(**base)


@pytest.fixture(scope="module")
def record() -> dict[str, Any]:
    """One full stub qualification, shared by the tests that only read it (about half a minute)."""
    return q.qualify(_opts())


# ------------------------------------------------------------------------------------------------ the stub run
@pytest.mark.req("MOD-8")
def test_every_step_runs_against_the_stub_and_the_record_passes(record: dict[str, Any]) -> None:
    assert list(record["steps"]) == list(q.STEPS)
    bad = {k: v["reason"] for k, v in record["steps"].items() if v["status"] != "passed"}
    assert bad == {}
    assert record["status"] == "passed" and record["failed_steps"] == []
    assert record["profile"] == "ci" and record["stub"] is True
    assert {b["weights_sha256"] for b in record["builds"].values()} == {"synthetic"}
    assert record["qualifies_production"] is False  # synthetic weights never qualify a PRODUCTION champion


def test_the_record_validates_against_its_schema(record: dict[str, Any]) -> None:
    assert q.schema_problems(record) == []
    assert q.check_record(record, profile="ci") == []


def test_the_canary_step_reports_the_stubs_known_result_by_name(record: dict[str, Any]) -> None:
    c = record["steps"]["canary"]
    assert c["status"] == "passed"
    assert "trialbox-stub-1" in c["reason"] and "known canary result" in c["reason"]
    assert c["detail"]["models"]["judge"]["model"] == "trialbox-stub-1"
    assert c["detail"]["stub_known_result"] == q.STUB_CANARY


def test_steps_record_their_numbers(record: dict[str, Any]) -> None:
    s = record["steps"]
    assert s["schema"]["detail"]["valid"] == s["schema"]["detail"]["sent"] > 10
    assert s["schema"]["detail"]["not_probed_on_stub"] == ["profile_summary@1"]
    assert s["pair_gate"]["detail"]["exclusions"] >= 20 and s["pair_gate"]["detail"]["wrong_exclusions"] == 0
    assert s["determinism"]["detail"]["changed_exclusions"] == 0 and s["determinism"]["detail"]["cache_hits"] == 0
    tp = s["throughput"]["detail"]
    # the stub answers in well under a millisecond on a fast host, and the times are rounded to 1 ms: a time may be
    # 0.0, so the check is that the numbers are there and ordered, not that they are positive (ENG-027, T-653)
    per = tp["seconds_per_criterion_check"]
    assert tp["seconds_per_note_stage_patient"]["n"] > 0 and per["n"] > 0 and per["p95"] >= per["p50"] >= 0
    assert s["planted_defect"]["detail"]["gate_passed"] is False
    assert s["log_marker"]["detail"]["found_in"] == []
    assert {r["result"] for r in s["longest_prompt"]["detail"]["roles"].values()} == {"answered"}
    assert {s[n]["detail"]["mode"] for n in q.EVIDENCE_STEPS} == {"wiring"}


def test_the_record_holds_no_note_text(record: dict[str, Any]) -> None:
    text = json.dumps(record, ensure_ascii=False)
    assert "痛風" not in text and "gout" not in text.lower()


# ------------------------------------------------------------------------------------------------ status rules
@pytest.mark.parametrize("step", q.STEPS)
def test_a_failed_step_fails_the_record_by_name(record: dict[str, Any], step: str) -> None:
    doc = copy.deepcopy(record)
    doc["steps"][step]["status"] = "failed"
    doc = q.finalize(doc)
    assert doc["status"] == "failed" and doc["failed_steps"] == [step] and not doc["qualifies_production"]
    assert any(step in p for p in q.check_record(doc))


@pytest.mark.parametrize("step", ["schema", "goldens", "planted_defect"])
def test_a_record_missing_a_step_is_failed(record: dict[str, Any], step: str) -> None:
    doc = copy.deepcopy(record)
    del doc["steps"][step]
    doc = q.finalize(doc)
    assert doc["status"] == "failed" and doc["failed_steps"] == [step]


def test_a_step_that_raises_is_failed_with_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(ctx: q.Ctx) -> q.StepResult:
        raise RuntimeError("upstream exploded")

    monkeypatch.setitem(q.STEP_FUNCS, "licence", boom)
    doc = q.qualify(_opts(), steps=("licence",))
    assert doc["steps"]["licence"] == {**doc["steps"]["licence"], "status": "failed"}
    assert "RuntimeError" in doc["steps"]["licence"]["reason"]
    assert doc["status"] == "failed" and "licence" in doc["failed_steps"] and "pin" in doc["failed_steps"]


def test_a_forged_status_is_refused(record: dict[str, Any]) -> None:
    doc = copy.deepcopy(record)
    doc["steps"]["pair_gate"]["status"] = "failed"
    doc["status"], doc["failed_steps"] = "passed", []  # a hand edit, with the sha recomputed to match
    doc["sha256"] = hashlib.sha256(q.canonical(doc)).hexdigest()
    assert "the status does not follow from the steps" in q.check_record(doc)


def test_an_edited_record_is_refused(record: dict[str, Any]) -> None:
    doc = copy.deepcopy(record)
    doc["builds"]["judge"]["build_id"] = "another-build"
    assert q.check_record(doc) == ["the record's sha256 does not match its body (edited after it was written)"]


def test_a_record_of_another_profile_does_not_qualify_this_one(record: dict[str, Any]) -> None:
    assert any("profile ci, not rtxpro6000" in p for p in q.check_record(record, profile="rtxpro6000"))
    assert any("does not name build" in p for p in q.check_record(record, build_id="qwen3.5-9b-rtxpro6000"))


def test_synthetic_weights_cannot_qualify_production(record: dict[str, Any]) -> None:
    assert q.check_record(record) == []
    assert any("PRODUCTION" in p for p in q.check_record(record, environment="PRODUCTION"))


def test_a_record_that_breaks_the_schema_is_refused(record: dict[str, Any]) -> None:
    doc = copy.deepcopy(record)
    doc["steps"]["pin"]["status"] = "skipped"
    assert any("skipped" in p for p in q.check_record(doc))


# ------------------------------------------------------------------------------------------------ steps that fail
def test_stub_mode_is_for_profile_ci_only() -> None:
    with pytest.raises(q.QualifyError, match="profile ci only"):
        q.qualify(_opts(profile="rtxpro6000"))


def test_a_real_profile_needs_pinned_weights_and_a_verified_licence(tmp_path: Path) -> None:
    """The registry's real builds have no weight hash and an unverified licence today (LLM-007, LLM-012)."""
    doc = q.qualify(_opts(profile="rtxpro6000", stub=False), q.stub_target(tmp_path), steps=("pin", "licence"))
    pin, lic = doc["steps"]["pin"], doc["steps"]["licence"]
    assert pin["status"] == "failed" and "no pinned weight hash" in pin["reason"]
    assert lic["status"] == "failed" and "licence not verified" in lic["reason"] and "--model-dir" in lic["reason"]


def test_a_weight_folder_without_a_licence_file_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builds = q.profile_builds("rtxpro6000")
    for b in builds.values():
        b.licence = {"name": "Apache-2.0", "verified": True}
    (tmp_path / "j").mkdir()
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "LICENSE").write_text("licence text\n", encoding="utf-8")
    dirs = {"judge": tmp_path / "j", "verifier": tmp_path / "v"}
    ctx = _ctx(_opts(profile="rtxpro6000", stub=False, model_dirs=dirs), tmp_path, builds)
    r = q.step_licence(ctx)
    assert r.status == "failed" and r.reason.endswith("no licence file in the weight folder")
    assert r.detail["verifier"]["file"] == "LICENSE" and r.detail["judge"]["file"] is None


@pytest.mark.parametrize("context", [8192, 16384, 32768])
def test_the_longest_prompt_is_sized_to_the_profiles_context(monkeypatch: pytest.MonkeyPatch, context: int) -> None:
    """T-603: the judge's full record and the chart are sized from the context, so the longest prompt fits each
    profile (8k: the RTX 5090; 16k: the Spark; 32k: the RTX PRO 6000)."""
    real = q.profile_builds

    def sized(profile: str, doc: Any = None) -> dict[str, q.Build]:
        out = real(profile, doc)
        out["judge"].context_length = context
        return out

    monkeypatch.setattr(q, "profile_builds", sized)
    s = q.qualify(_opts(), steps=("longest_prompt",))["steps"]["longest_prompt"]
    assert s["status"] == "passed", s
    assert all(r["tokens_needed"] <= context for r in s["detail"]["roles"].values()), s["detail"]


def test_the_longest_prompt_must_fit_the_profiles_context(monkeypatch: pytest.MonkeyPatch) -> None:
    real, longest = q.profile_builds, q.longest_prompts

    def small(profile: str, doc: Any = None) -> dict[str, q.Build]:
        out = real(profile, doc)
        out["judge"].context_length = 8192  # the RTX 5090 profile
        return out

    monkeypatch.setattr(q, "profile_builds", small)
    monkeypatch.setattr(q, "longest_prompts", lambda context=None: longest(None))  # sizing removed: 28,000 tokens
    s = q.qualify(_opts(), steps=("longest_prompt",))["steps"]["longest_prompt"]
    assert s["status"] == "failed" and "judge: the longest prompt needs about" in s["reason"]
    assert s["detail"]["roles"]["judge"]["result"] == "too_long"


def test_a_missing_schema_probe_fails_the_schema_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = yaml.safe_load(q.PROBES.read_text(encoding="utf-8"))
    del doc["probes"]["judge"]
    probes = tmp_path / "probes.yaml"
    probes.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(q, "PROBES", probes)
    s = q.qualify(_opts(), steps=("schema",))["steps"]["schema"]
    assert s["status"] == "failed" and s["detail"]["probes"]["judge@4"] == "no_probe"


def test_a_schema_violation_fails_the_schema_step(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub

    inner = TestClient(stub)

    def handler(req: httpx.Request) -> httpx.Response:
        r = inner.post(str(req.url.path), content=req.content, headers=dict(req.headers))
        doc = r.json()
        if req.headers.get("x-tb-prompt-id") == "concept_map":
            doc["choices"][0]["message"]["content"] = json.dumps({"choices": "not a list", "extra": 1})
        return httpx.Response(r.status_code, json=doc)

    up = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://llm-stub:8000")
    s = q.qualify(_opts(), q.stub_target(tmp_path, up), steps=("schema",))["steps"]["schema"]
    assert s["status"] == "failed" and s["detail"]["probes"]["concept_map@1"] == "invalid"


def test_a_server_that_logs_prompts_fails_the_log_marker_step(tmp_path: Path) -> None:
    """A model server that writes request bodies to its log (vLLM with request logging on) is caught (LLM-042)."""
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub

    inner = TestClient(stub)
    log = tmp_path / "vllm.log"
    log.write_text("server started\n", encoding="utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        with log.open("a", encoding="utf-8") as fh:
            fh.write("Received request: " + req.content.decode("utf-8") + "\n")
        r = inner.post(str(req.url.path), content=req.content, headers=dict(req.headers))
        return httpx.Response(r.status_code, json=r.json())

    up = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://llm-stub:8000")
    s = q.qualify(_opts(server_logs=[log]), q.stub_target(tmp_path, up), steps=("log_marker",))["steps"]["log_marker"]
    assert s["status"] == "failed" and s["detail"]["found_in"] == ["server_log:vllm.log"]


def test_changed_exclusions_between_two_runs_fail_determinism(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import judge_bakeoff as jb

    runs = iter(["fail", "pass"])

    def flaky(judge: Any, verifier: Any, items: list[Any], workers: int) -> list[Any]:
        e = next(runs)
        return [jb.Row(it.id, it.source, it.cluster, "", it.kind, it.gold, True, predicate=e, eligibility=e)
                for it in items]  # fmt: skip

    monkeypatch.setattr(q, "run_pair", flaky)
    s = q.qualify(_opts(repeat_items=5), steps=("determinism",))["steps"]["determinism"]
    assert s["status"] == "failed" and s["detail"]["changed_exclusions"] == 5


def test_a_defect_the_gate_cannot_see_fails_the_planted_defect_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(q.QClient, "defect", False, raising=False)
    orig = q.QClient.__init__

    def no_defect(self: q.QClient, gateway: Any, **kw: Any) -> None:
        orig(self, gateway, **{**kw, "defect": False})

    monkeypatch.setattr(q.QClient, "__init__", no_defect)
    s = q.qualify(_opts(), steps=("canary", "planted_defect"))["steps"]["planted_defect"]
    assert s["status"] == "failed" and "planted defect" in s["reason"] and s["detail"]["gate_passed"] is True


# ------------------------------------------------------------------------------------------------ evidence steps
def _evidence(tmp_path: Path, **doc: Any) -> Path:
    p = tmp_path / "goldens.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_evidence_at_this_head_passes_and_from_another_head_fails(tmp_path: Path) -> None:
    head, _ = q.git_head()
    real = _opts(stub=False, profile="rtxpro6000")
    ev = {"goldens": _evidence(tmp_path, passed=True, head=head)}
    good = q.step_evidence("goldens")(_ctx(replace(real, evidence=ev), tmp_path))
    assert good.status == "passed" and good.detail["mode"] == "evidence" and len(good.detail["sha256"]) == 64
    for doc, why in (
        ({"passed": True, "head": "0" * 40}, "not this HEAD"),
        ({"passed": False, "head": head}, "does not say passed"),
        ({"ok": True}, "names no git HEAD"),
    ):
        r = q.step_evidence("goldens")(_ctx(replace(real, evidence={"goldens": _evidence(tmp_path, **doc)}), tmp_path))
        assert r.status == "failed" and why in r.reason
    none = q.step_evidence("n12")(_ctx(real, tmp_path))
    assert none.status == "failed" and "--evidence n12=" in none.reason


# ------------------------------------------------------------------------------------------------ the command
def test_the_trialbox_command_checks_a_record(record: dict[str, Any], tmp_path: Path, capsys: Any) -> None:
    from tools.trialbox.__main__ import main

    path = q.write_record(record, tmp_path)
    assert main(["eval", "qualify", "--check", str(path), "--profile", "ci"]) == 0
    assert "qualifies" in capsys.readouterr().out
    assert main(["eval", "qualify", "--check", str(path), "--environment", "PRODUCTION"]) == 1
    assert main(["eval", "qualify", "--profile", "rtxpro6000"]) == 2  # no gateway, no --stub


def test_the_trialbox_command_writes_a_stub_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from tools.trialbox.__main__ import main

    monkeypatch.setattr(q, "STEPS", ("pin", "serving_record"))  # read at call time: these two are then required
    rc = main(["eval", "qualify", "--profile", "ci", "--stub", "--out", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["status"] == "passed"
    doc = json.loads(Path(out["record"]).read_text(encoding="utf-8"))
    assert set(doc["steps"]) == {"pin", "serving_record"} and q.schema_problems(doc) == []
