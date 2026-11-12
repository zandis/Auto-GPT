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

from tools import licence_register
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
    assert s["schema"]["detail"]["not_probed_on_stub"] == ["profile_summary@2"]
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


def test_a_real_profile_needs_pinned_weights_and_a_licence_file(tmp_path: Path) -> None:
    """The registry's real builds name the release they expect (T-012b, LLM-007): that is the weight hash in the
    record, and the stub's answers do not carry it, so the pin step fails. Their licences are verified against the
    register (T-617b), but no weight folder was given to show the licence file."""
    doc = q.qualify(_opts(profile="rtxpro6000", stub=False), q.stub_target(tmp_path), steps=("pin", "licence"))
    pin, lic = doc["steps"]["pin"], doc["steps"]["licence"]
    reg = {b["build_id"]: b for b in q.registry_doc()["builds"]}
    for b in doc["builds"].values():
        assert b["weights_sha256"] == reg[b["build_id"]]["expected"]["manifest_sha256"]
        assert b["revision"] == reg[b["build_id"]]["expected"]["revision"]
    assert pin["status"] == "failed" and "no pinned weight hash" not in pin["reason"]
    assert lic["status"] == "failed" and "licence not verified" not in lic["reason"] and "--model-dir" in lic["reason"]
    assert lic["detail"]["judge"]["register"] == "model-gemma-4-26b-a4b-nvfp4"
    assert lic["detail"]["verifier"]["register"] == "model-qwen3.5-9b-awq-4bit"


def test_a_build_with_no_licence_file_is_refused_and_the_text_must_be_the_checked_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-617b: `qualify` refuses a weight folder with no licence file; a licence file that is not the text the
    register row checked is refused too; the register's own text passes. HW-004 (D-565): the judge's source has no
    licence file, so its register row is checked and its folder is not."""
    builds = q.profile_builds("rtxpro6000")
    for role in ("judge", "verifier"):
        (tmp_path / role).mkdir()
    dirs = {"judge": tmp_path / "judge", "verifier": tmp_path / "verifier"}
    ctx = _ctx(_opts(profile="rtxpro6000", stub=False, model_dirs=dirs), tmp_path, builds)
    r = q.step_licence(ctx)
    assert r.status == "failed" and r.reason.count("no licence file in the weight folder") == 1
    assert r.reason.startswith(f"{builds['verifier'].build_id}: no licence file in the weight folder")
    assert r.detail["judge"]["file"] == q.NONE_IN_SOURCE_FILE

    (dirs["judge"] / "LICENSE").write_text("Apache License 2.0 text\n", encoding="utf-8")
    (dirs["verifier"] / "LICENSE").write_text("some other text\n", encoding="utf-8")
    r = q.step_licence(ctx)
    assert r.status == "failed" and "not the text checked in register row model-qwen3.5-9b-awq-4bit" in r.reason
    # the judge's source has no licence file (D-565): its folder is not read by this step; a file put there is
    # the pin's to refuse (the manifest is every visible file)
    assert "gemma" not in r.reason

    sha = hashlib.sha256(b"some other text\n").hexdigest()
    rows = [
        replace(row, raw={**row.raw, "text_sha256": sha}) if row.id == "model-qwen3.5-9b-awq-4bit" else row
        for row in licence_register.load()
    ]
    monkeypatch.setattr(licence_register, "load", lambda: rows)
    r = q.step_licence(ctx)
    assert r.status == "passed", r.reason
    assert r.detail["verifier"] == {**r.detail["verifier"], "file": "LICENSE", "file_sha256": sha}


def test_a_verified_licence_needs_its_register_row(tmp_path: Path) -> None:
    builds = q.profile_builds("rtxpro6000")
    builds["judge"].licence = {"name": "Apache-2.0", "spdx": "Apache-2.0", "verified": True}
    builds["verifier"].licence = {**builds["verifier"].licence, "spdx": "MIT"}
    r = q.step_licence(_ctx(_opts(profile="rtxpro6000", stub=False), tmp_path, builds))
    assert "licence verified without a register row" in r.reason
    assert "spdx 'MIT' is not row model-qwen3.5-9b-awq-4bit's 'Apache-2.0'" in r.reason


def test_a_weight_folder_without_a_licence_file_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builds = q.profile_builds("rtxpro6000")  # both licences verified against docs/licences/register.csv
    (tmp_path / "j").mkdir()
    (tmp_path / "v").mkdir()
    dirs = {"judge": tmp_path / "j", "verifier": tmp_path / "v"}
    ctx = _ctx(_opts(profile="rtxpro6000", stub=False, model_dirs=dirs), tmp_path, builds)
    r = q.step_licence(ctx)
    # the verifier's registry row names a licence file ({path, sha256}): a folder without one fails, as before
    assert builds["verifier"].licence_file["path"] == "LICENSE"
    assert r.status == "failed" and r.reason == f"{builds['verifier'].build_id}: no licence file in the weight folder"
    assert r.detail["verifier"]["file"] is None
    (tmp_path / "v" / "LICENSE").write_text("licence text\n", encoding="utf-8")
    monkeypatch.setattr(licence_register, "load", lambda: [replace(x, raw={**x.raw, "text_sha256": ""}) for x in ROWS])
    r = q.step_licence(ctx)
    assert r.status == "passed" and r.detail["verifier"]["file"] == "LICENSE"


ROWS = licence_register.load()


def _judge_ctx(tmp_path: Path, with_dirs: bool = True) -> tuple[Any, dict[str, q.Build]]:
    """The rtxpro6000 pair with the verifier's licence file in place: what is left is the judge's."""
    builds = q.profile_builds("rtxpro6000")
    root = tmp_path / "models"
    dirs = {"judge": root / "gemma-folder", "verifier": root / "qwen-folder"}
    for d in dirs.values():
        d.mkdir(parents=True)
    (dirs["verifier"] / "LICENSE").write_text("licence text\n", encoding="utf-8")
    opts = _opts(profile="rtxpro6000", stub=False, model_dirs=dirs if with_dirs else {"verifier": dirs["verifier"]})
    return _ctx(opts, tmp_path, builds), builds


def _rows(**judge: str) -> list[Any]:
    """The register without the verifier's text hash (its file here is a test's), the judge's row changed."""
    out = []
    for x in ROWS:
        raw = {**x.raw, "text_sha256": ""} if x.id == "model-qwen3.5-9b-awq-4bit" else dict(x.raw)
        if x.id == "model-gemma-4-26b-a4b-nvfp4":
            raw.update(judge)
        out.append(replace(x, raw=raw))
    return out


def test_hw004_a_source_with_no_licence_file_is_checked_against_its_register_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The judge's source repository holds no licence file and its expected manifest is every visible file of that
    source: a licence file put into the folder breaks the pin. The step reads the register row, not the folder."""
    monkeypatch.setattr(licence_register, "load", _rows)
    ctx, builds = _judge_ctx(tmp_path)
    assert builds["judge"].licence_file == "none-in-source"
    r = q.step_licence(ctx)
    assert r.status == "passed", r.reason
    assert r.detail["judge"] == {
        "name": builds["judge"].licence["name"], "verified": True, "register": "model-gemma-4-26b-a4b-nvfp4",
        "file": "none in source (register row)", "text": None,
    }  # fmt: skip
    ctx, _ = _judge_ctx(tmp_path / "second", with_dirs=False)
    r = q.step_licence(ctx)  # and no weight folder is needed to check this build's licence
    assert r.status == "passed", r.reason


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"version": "revision 0000000000000000000000000000000000000000"}, "does not name the build's revision"),
        ({"evidence": "read on the publisher's page"}, "names no source URL"),
        ({"status": "pending"}, "not cleared"),
    ],
)
def test_hw004_the_register_row_must_be_cleared_and_name_the_revision_and_a_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, str], said: str
) -> None:
    rows = _rows(**change)
    if "status" in change:
        rows = [replace(x, status="pending") if x.id == "model-gemma-4-26b-a4b-nvfp4" else x for x in rows]
    monkeypatch.setattr(licence_register, "load", lambda: rows)
    ctx, builds = _judge_ctx(tmp_path)
    r = q.step_licence(ctx)
    assert r.status == "failed" and said in r.reason and builds["judge"].build_id in r.reason, r.reason


def test_hw004_the_licence_text_rides_beside_the_weight_folder_and_must_be_the_checked_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beside the folder, outside the manifest, as the chat template: <models root>/licences/<folder>/LICENSE."""
    ctx, _ = _judge_ctx(tmp_path)
    beside = tmp_path / "models" / "licences" / "gemma-folder"
    beside.mkdir(parents=True)
    (beside / "LICENSE").write_text("Apache License 2.0 text\n", encoding="utf-8")
    sha = hashlib.sha256(b"Apache License 2.0 text\n").hexdigest()
    monkeypatch.setattr(licence_register, "load", _rows)  # the committed row holds no text hash: recorded
    r = q.step_licence(ctx)
    assert r.status == "passed", r.reason
    assert r.detail["judge"]["text"] == "licences/gemma-folder/LICENSE" and r.detail["judge"]["text_sha256"] == sha
    assert not (tmp_path / "models" / "gemma-folder" / "LICENSE").exists()  # the weight folder stays as published
    monkeypatch.setattr(licence_register, "load", lambda: _rows(text_sha256=sha))
    assert q.step_licence(ctx).status == "passed"
    monkeypatch.setattr(licence_register, "load", lambda: _rows(text_sha256="0" * 64))
    r = q.step_licence(ctx)
    assert r.status == "failed" and "is not the text checked in register row model-gemma-4-26b-a4b-nvfp4" in r.reason


def test_hw004_the_register_and_the_decision_no_longer_send_the_text_into_the_weight_folder() -> None:
    row = next(x for x in ROWS if x.id == "model-gemma-4-26b-a4b-nvfp4")
    assert "in the weight folder" not in row.raw["evidence"] and "beside the weight folder" in row.raw["evidence"]
    assert row.raw["version"].endswith(str(q.profile_builds("rtxpro6000")["judge"].revision))


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
    assert s["status"] == "failed" and s["detail"]["probes"]["judge@5"] == "no_probe"


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
    assert s["status"] == "failed" and s["detail"]["probes"]["concept_map@2"] == "invalid"


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


# ------------------------------------------------------------------------- HW-004: the review of PR #355
@pytest.mark.parametrize(
    "version",
    [
        "NOT a19cfe00be84568a6867111c9a68c9c44fdcffe6; revision 1111111111111111111111111111111111111111",
        "revision a19cfe00be84568a6867111c9a68c9c44fdcffe6ff",
        "revision a19cfe0",
    ],
)
def test_hw004_review_the_row_names_exactly_one_full_revision_and_it_is_the_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    """MED-1: the revision was looked for as a substring of the row's version."""
    monkeypatch.setattr(licence_register, "load", lambda: _rows(version=version))
    ctx, _ = _judge_ctx(tmp_path)
    r = q.step_licence(ctx)
    assert r.status == "failed" and "does not name the build's revision" in r.reason


def test_hw004_review_a_short_build_revision_never_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(licence_register, "load", _rows)
    ctx, builds = _judge_ctx(tmp_path)
    builds["judge"].revision = "a"
    assert "does not name the build's revision" in q.step_licence(ctx).reason


def test_hw004_review_an_empty_text_beside_the_folder_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MED-2: with no text hash in the row, an empty file was recorded as the licence text."""
    monkeypatch.setattr(licence_register, "load", _rows)
    ctx, _ = _judge_ctx(tmp_path)
    beside = tmp_path / "models" / "licences" / "gemma-folder"
    beside.mkdir(parents=True)
    (beside / "LICENSE").write_text(" \n", encoding="utf-8")
    r = q.step_licence(ctx)
    assert r.status == "failed" and "the licence text beside the weight folder is empty" in r.reason


def test_hw004_review_the_folder_is_resolved_and_a_cache_snapshot_has_no_beside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LOW: a link to the weight folder used the link's name. MED-3: beside a Hugging Face cache snapshot is the
    `snapshots` folder, where a `licences` folder would be read as a snapshot (tools/serving_config.py)."""
    monkeypatch.setattr(licence_register, "load", _rows)
    ctx, _ = _judge_ctx(tmp_path)
    beside = tmp_path / "models" / "licences" / "gemma-folder"
    beside.mkdir(parents=True)
    (beside / "LICENSE").write_text("Apache License 2.0 text\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "models" / "gemma-folder")
    ctx.opts.model_dirs["judge"] = link
    r = q.step_licence(ctx)
    assert r.status == "passed" and r.detail["judge"]["text"] == "licences/gemma-folder/LICENSE"

    snap = tmp_path / "hub" / "models--x--y" / "snapshots" / "a19c"
    snap.mkdir(parents=True)
    (snap.parent / "licences" / "a19c").mkdir(parents=True)
    (snap.parent / "licences" / "a19c" / "LICENSE").write_text("text\n", encoding="utf-8")
    ctx.opts.model_dirs["judge"] = snap
    r = q.step_licence(ctx)
    assert r.status == "passed" and r.detail["judge"]["text"] is None  # not looked for there


def test_hw004_review_the_detail_always_has_the_text_key_and_the_pages_say_where_the_text_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [x for x in _rows() if x.id != "model-gemma-4-26b-a4b-nvfp4"]
    monkeypatch.setattr(licence_register, "load", lambda: rows)
    ctx, _ = _judge_ctx(tmp_path)
    r = q.step_licence(ctx)
    assert r.status == "failed" and r.detail["judge"]["text"] is None
    page = (q.ROOT / "docs" / "runbook" / "11-qualify.md").read_text(encoding="utf-8")
    assert "licences/<folder>/LICENSE" in page and "none-in-source" in page
    assert "licences/<weight folder" in (q.__doc__ or "")
