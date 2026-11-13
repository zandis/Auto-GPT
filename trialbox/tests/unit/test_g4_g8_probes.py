"""The cloud driver's parts for the review's GPU tests G-4, G-5, G-7 and G-8 (plan v7 §7.1; ``tools.g_probes``).

G-4 the structured-output backend and guided decoding on and off; G-5 real against estimated token counts; G-7 the
clipped note against the whole note (LLM-001); G-8 public protocols compiled with the production judge. No GPU, no
cloud: pure functions, the driver's ``--dry-run`` and the stand-ins (``tools.vllm_standin``, ``llm_stub``)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tools import complete_run as cr
from tools import g_probes as gp
from tools import vllm_standin as vs

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
KEY = "rehearsal-key-0123456789"
PARTS = ["g4-decoding", "g5-tokens", "g7-clipped", "g8-protocols"]


# ---------------------------------------------------------------- the plan, the estimate, the driver
def _ns(**kw: Any) -> argparse.Namespace:
    base: dict[str, Any] = {"langs": ["ja"], "scenarios": ["gateway"], "skip": [], "only": [], "llm_concurrency": ""}
    return argparse.Namespace(**{**base, **kw})


def test_each_probe_is_a_part_named_only_by_only() -> None:
    assert set(PARTS) <= set(cr.PARTS) and set(PARTS) <= set(cr.MODEL_PARTS) and set(PARTS) <= set(cr.NO_CONSOLE)
    assert not set(PARTS) & {cr._tag(*p) for p in cr.plan(_ns())}  # never in the complete run by default
    tags = [cr._tag(*p) for p in cr.plan(_ns(only=["g5-tokens", "g8-protocols"]))]
    assert tags == ["g5-tokens", "g8-protocols"]


def test_the_estimate_has_a_row_per_probe_derived_from_g1s_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_G8_PROTOCOLS_DIR", str(tmp_path / "none"))  # a folder with no protocol: G-8's row says so
    e = cr.restrict(cr.estimate(5000), PARTS)
    rows = {r["tags"][0]: r for r in e["rows"] if r["tags"]}
    assert list(rows) == PARTS
    rate = cr.G1_CALLS_PER_SECOND
    assert rows["g4-decoding"]["model_items"] == 2 * gp.DECODING_ROUNDS * 16  # the record's 16 slots, both ways
    assert rows["g4-decoding"]["seconds"] == pytest.approx(gp.PART_START_SECONDS + 128 / rate, abs=0.1)
    assert rows["g5-tokens"]["model_items"] == 800 and rows["g7-clipped"]["model_items"] == 16
    assert "no fixture: not run" in rows["g8-protocols"]["scenario"]
    monkeypatch.delenv("TB_G8_PROTOCOLS_DIR")  # master's own folder: lane A's two public protocols (train 6)
    with_fixtures = {r["tags"][0]: r for r in cr.restrict(cr.estimate(5000), PARTS)["rows"] if r["tags"]}
    assert "2 public protocol(s)" in with_fixtures["g8-protocols"]["scenario"]
    assert e["hours"] == pytest.approx(0.5 + sum(r["seconds"] for r in rows.values()) / 3600, abs=0.02)
    with pytest.raises(ValueError, match="no such part"):
        cr.restrict(cr.estimate(5000), ["g6-night"])


def test_a_protocol_folder_sizes_the_g8_row(tmp_path: Path) -> None:
    (tmp_path / "ra.txt").write_text("Inclusion Criteria:\n* Adult\n* RA\n\nExclusion Criteria:\n* TB\n", "utf-8")
    (tmp_path / "skip.pdf").write_bytes(b"%PDF")
    row = gp.estimate_rows(["g8-protocols"], 16, tmp_path)[0]
    from tb_llm.timeouts import UPSTREAM_READ_S

    assert row["model_items"] == 5 and "1 public protocol" in row["scenario"]
    assert row["seconds"] == pytest.approx(gp.PART_START_SECONDS + UPSTREAM_READ_S + 5 / cr.G1_CALLS_PER_SECOND, 0.1)


def test_the_dry_run_plans_the_probes_on_one_spot_vm(tmp_path: Path) -> None:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"),
               TB_RUN_ID="R")  # fmt: skip
    for k in ("TB_ZONES", "TB_ESTIMATE_LLM_SPEEDUP", "TB_PROVISIONING"):
        env.pop(k, None)
    env["TB_G8_PROTOCOLS_DIR"] = str(tmp_path / "none")  # no protocol there: the plan's figures do not move with master
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--patients", "5000", "--only", ",".join(PARTS)],
                       cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    plan = json.loads((tmp_path / "out" / "plan.json").read_text(encoding="utf-8"))
    rows = [r["scenario"] for r in plan["rows"] if r["tags"]]
    assert [x.split(" ", 1)[0] for x in rows] == ["G-4", "G-5", "G-7", "G-8"] and "no fixture: not run" in rows[3]
    assert "0.97" in r.stdout and "g4-decoding" in r.stdout
    meta = next(ln for ln in r.stdout.splitlines() if "add-metadata" in ln and "tb-run-id=" in ln)
    assert sorted(meta.split("tb-only=")[1].split(",")[0].split()) == sorted(PARTS)
    sched = next(ln for ln in r.stdout.splitlines() if "set-scheduling" in ln and "max-run-duration=" in ln)
    assert "--provisioning-model=SPOT" in sched and "--max-run-duration=2h" in sched  # 0.97 h x 1.3
    report = next(ln for ln in r.stdout.splitlines() if "--report-only" in ln)
    assert all(p in report for p in PARTS)


def test_a_part_runs_through_the_drivers_part_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``part g8-protocols`` with no fixture folder: a result that says why it did not run, never a crash."""
    monkeypatch.setenv("TB_G8_PROTOCOLS_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(cr, "shoot", lambda items, *a, **k: {it["name"]: {"ok": True} for it in items})
    rc = cr.main(["part", "g8-protocols", "--dir", str(tmp_path), "--shots", str(tmp_path / "s"), "--run-id", "R"])
    res = json.loads((tmp_path / "parts" / "g8-protocols.json").read_text(encoding="utf-8"))
    assert rc == 1 and res["not_run"] == "no fixture on master"
    assert "no fixture on master: not run" in res["stages"][0]["name"]
    assert res["protocols"]["result"] == "no fixture on master: not run"


# ---------------------------------------------------------------- shared pure helpers
def test_percentiles_and_ratios() -> None:
    assert gp.percentile([], 50) is None and gp.percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert gp.percentile(list(range(1, 101)), 95) == 95.0 and gp.percentile([1.0, 9.0], 100) == 9.0
    s = gp.ratio_stats([(110, 100), (90, 100), (None, 100), (5, 0)])
    assert s == {"n": 2, "missing": 2, "p50": 0.9, "p95": 1.1, "max": 1.1, "mean": 1.0}


def test_the_synthetic_excerpts_are_fixed_cjk_and_of_many_sizes() -> None:
    for lang in ("ja", "zh-TW"):
        xs = gp.synthetic_excerpts(lang)
        assert len(xs) == gp.N_EXCERPTS == 200 and xs == gp.synthetic_excerpts(lang)
        assert len({len(x) for x in xs}) > 50 and max(map(len, xs)) > 5 * min(map(len, xs))
    assert gp.synthetic_excerpts("ja")[:5] != gp.synthetic_excerpts("zh-TW")[:5]
    assert any("結核" in x for x in gp.synthetic_excerpts("ja"))  # the imaging sentences are in the pool


# ---------------------------------------------------------------- G-4
def test_the_backend_is_read_from_the_server_then_the_record() -> None:
    info = "VllmConfig(model='m', structured_outputs_config=StructuredOutputsConfig(backend='xgrammar', x=1))"
    assert gp.backend_from_server_info(info) == "xgrammar"
    assert gp.backend_from_server_info('{"guided_decoding_backend": "outlines"}') == "outlines"
    assert gp.backend_from_server_info("") is None
    got = gp.backend_of({"structured_outputs_backend": "auto"}, info)
    assert got["backend"] == "xgrammar" and got["named"] and "server_info" in got["from"]
    auto = gp.backend_of({"structured_outputs_backend": "auto"})
    assert auto["backend"] == "auto" and not auto["named"] and "not named" in auto["note"]
    assert gp.backend_of({})["backend"] is None


def test_decoding_summary_and_the_profile() -> None:
    res: list[dict[str, Any]] = [{"status": 200, "seconds": 1.0, "in_schema": True, "completion_tokens": 50},
                                 {"status": 200, "seconds": 3.0, "in_schema": False, "completion_tokens": 70},
                                 {"status": 0, "seconds": 0.1, "error": "refused"}]  # fmt: skip
    s = gp.decoding_summary(res, 2.0)
    assert (s["calls"], s["answered"], s["errors"], s["schema_failures"]) == (3, 2, 1, 1)
    assert s["calls_per_second"] == 1.0 and s["p50_s"] == 1.0 and s["p95_s"] == 3.0 and s["completion_tokens"] == 120
    on = {"calls_per_second": 2.0, "schema_failures": 0, "errors": 0}
    assert gp.faster_setting(on, {"calls_per_second": 3.0, "schema_failures": 0, "errors": 0}) == "guided decoding off"
    assert gp.faster_setting(on, {"calls_per_second": 3.0, "schema_failures": 1, "errors": 0}) == "guided decoding on"
    assert gp.faster_setting(on, {"calls_per_second": 1.0, "schema_failures": 0, "errors": 0}) == "guided decoding on"
    assert gp.n_decoding_prompts(16) == 64 and gp.n_decoding_prompts(0) == gp.DECODING_ROUNDS


def test_an_answer_is_checked_against_the_judge_schema() -> None:
    from tb_common.llm import load_prompt

    schema = load_prompt("judge", "PRODUCTION").meta.output_schema
    good = {"verdict": "unknown", "confidence": 0.0, "quote": None, "quote_date": None, "reason": "not in the note"}
    assert gp.answer_in_schema(json.dumps(good), schema)
    assert gp.answer_in_schema("```json\n" + json.dumps(good) + "\n```", schema)
    assert not gp.answer_in_schema("The patient has gout.", schema)
    assert not gp.answer_in_schema(json.dumps({**good, "verdict": "maybe"}), schema)
    assert not gp.answer_in_schema(None, schema) and not gp.answer_in_schema("[1]", schema)


@pytest.fixture()
def standin() -> Any:
    s, _, _ = vs.build(["--model=/models/judge", "--served-model-name=local/judge", "--api-key", KEY], {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), vs.make_handler(s))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield s, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_g4_against_the_stand_in(standin: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s, base = standin
    monkeypatch.setattr(cr, "JUDGE", "local/judge")
    monkeypatch.setenv("TB_GPU_KEY", KEY)
    res = gp.run_g4(argparse.Namespace(dir=tmp_path, live_record=None, judge_url=f"{base}/v1"))
    checks = {c[0]: c[1] for st in res["stages"] for c in st["checks"]}
    assert all(checks.values()), checks
    b = res["decoding"]
    assert b["backend"]["backend"] == "auto" and "serving record" in b["backend"]["from"]  # the vendor record
    assert b["prompts"] == 64 and b["in_flight"] == 16
    assert b["guided_on"]["answered"] == b["guided_off"]["answered"] == 64
    assert b["guided_on"]["schema_failures"] == 0 and b["eager"]["result"].startswith("needs a restart: not run")
    assert s.stats()["counts"] == {"200": 128}
    assert gp.run_g4(argparse.Namespace(dir=tmp_path, live_record=None, judge_url=""))["not_run"] == "no judge server"


def test_each_schema_failure_keeps_why_it_stopped_its_tokens_and_its_opening() -> None:
    """2026-11-13: G-4 counted the answers outside the schema and nothing else, so a cut at max_tokens could not be
    told from a fenced or wordy answer."""
    long = "x" * 500
    res: list[dict[str, Any]] = [{"status": 200, "seconds": 1.0, "in_schema": True, "finish_reason": "stop",
                                  "completion_tokens": 40, "content": None}]  # fmt: skip
    res += [{"status": 200, "seconds": 1.0, "in_schema": False, "finish_reason": "length", "completion_tokens": 512,
             "content": long} for _ in range(gp.SCHEMA_FAILURE_EXAMPLES + 2)]  # fmt: skip
    res.append({"status": 200, "seconds": 1.0, "in_schema": False, "finish_reason": "stop", "completion_tokens": 60,
                "content": "Here is the answer: {...}"})  # fmt: skip
    s = gp.decoding_summary(res, 1.0)
    assert s["schema_failures"] == gp.SCHEMA_FAILURE_EXAMPLES + 3
    assert s["schema_failures_by_finish_reason"] == {"length": gp.SCHEMA_FAILURE_EXAMPLES + 2, "stop": 1}
    ex = s["schema_failure_examples"]
    assert len(ex) == gp.SCHEMA_FAILURE_EXAMPLES  # capped per setting
    assert ex[0] == {"finish_reason": "length", "completion_tokens": 512, "content_head": "x" * gp.EXAMPLE_CHARS}
    assert gp.EXAMPLE_CHARS == 200
    clean = gp.decoding_summary(res[:1], 1.0)
    assert clean["schema_failure_examples"] == [] and clean["schema_failures_by_finish_reason"] == {}


def test_g4_records_the_failures_of_each_setting(standin: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guided off answers wrapped in a fence with prose and cut at max_tokens (finish_reason length): each kept as an
    example of its setting; guided on, in the schema, keeps none."""
    _, base = standin
    monkeypatch.setattr(cr, "JUDGE", "local/judge")
    monkeypatch.setenv("TB_GPU_KEY", KEY)
    real = gp.post_json

    def post(url: str, body: dict[str, Any], *a: Any, **kw: Any) -> tuple[int, Any]:
        status, got = real(url, body, *a, **kw)
        if url.endswith("/chat/completions") and "response_format" not in body and isinstance(got, dict):
            choice = got["choices"][0]
            choice["message"]["content"] = "Sure, here it is:\n```json\n" + choice["message"]["content"][:20]
            choice["finish_reason"] = "length"
        return status, got

    monkeypatch.setattr(gp, "post_json", post)
    b = gp.run_g4(argparse.Namespace(dir=tmp_path, live_record=None, judge_url=f"{base}/v1"))["decoding"]
    on, off = b["guided_on"], b["guided_off"]
    assert on["schema_failures"] == 0 and on["schema_failure_examples"] == []
    assert off["schema_failures"] == 64 and off["schema_failures_by_finish_reason"] == {"length": 64}
    ex = off["schema_failure_examples"]
    assert len(ex) == gp.SCHEMA_FAILURE_EXAMPLES and ex[0]["finish_reason"] == "length"
    assert ex[0]["content_head"].startswith("Sure, here it is:\n```json\n") and len(ex[0]["content_head"]) <= 200
    assert isinstance(ex[0]["completion_tokens"], int)
    text = "\n".join(gp.report_lines({"parts": [{"tag": "g4-decoding", "decoding": b}]}))
    assert "guided off: answers outside the schema by finish_reason: length 64" in text
    assert "- length, " in text and "\\u0060\\u0060\\u0060json" in text and "guided on: answers" not in text


# ---------------------------------------------------------------- G-5
def test_token_summary_fits_or_names_the_safety_it_needs() -> None:
    rows = {"ja": [{"real": 105, "budget": 100, "cascade": 100}, {"real": 50, "budget": 50, "cascade": 40}]}
    s = gp.token_summary(rows, {"ja": [(220, 200)]}, 0.85)
    per = s["per_language"]["ja"]
    assert per["budget"]["max"] == 1.05 and per["cascade"]["max"] == 1.25 and per["prompt"]["max"] == 1.1
    assert s["max_ratio"] == 1.25 and not s["fits"]  # 1.25 x 1.05 > 1 / 0.85
    assert s["safety_from_measurement"] == pytest.approx(1 / (1.25 * 1.05), abs=1e-4)
    ok = gp.token_summary({"ja": [{"real": 100, "budget": 100, "cascade": 100}]}, {}, 0.85)
    assert ok["fits"] and ok["safety_from_measurement"] == 0.85


def test_g5_against_the_stand_in(standin: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, base = standin
    monkeypatch.setattr(cr, "JUDGE", "local/judge")
    res = gp.run_g5(argparse.Namespace(dir=tmp_path, live_record=None, judge_url=f"{base}/v1"))
    t = res["tokens"]
    assert t["counted"] == {"ja": 200, "zh-TW": 200} and t["excerpts"] == {"ja": 200, "zh-TW": 200}
    ja = t["per_language"]["ja"]
    assert ja["budget"]["n"] == 200 and ja["prompt"]["n"] == 200
    # the stand-in counts one token per character: the budget's CJK rule of one per character is close to it
    assert 0.8 < ja["budget"]["p50"] <= 1.2
    checks = [c for st in res["stages"] for c in st["checks"]]
    assert checks[0][1] and len(checks) == 2


# ---------------------------------------------------------------- G-7
def test_the_two_llm001_notes_are_clipped_by_the_products_own_clip() -> None:
    cases = gp.clip_cases()
    assert [c["lang"] for c in cases] == ["ja", "zh-TW"]
    for c in cases:
        v = gp.clipped_view(c)
        assert v["clipped"] and v["chars_shown"] < v["chars_whole"] and v["evidence"] == ["肺結核。"]
        assert "肺結核。" in v["excerpts"][0]["text"] and isinstance(v["left_out"], int)


def test_the_final_outcome_follows_the_cascades_rule() -> None:
    f = gp.final_outcome
    assert f("pass", 0.9, True, 0, 0.75) == "not met (final)"  # condition present on an exclusion: out
    assert f("pass", 0.9, True, 1, 0.75) == "review"  # a note left out: not final
    assert f("pass", 0.5, True, 0, 0.75) == "review" and f("pass", 0.9, False, 0, 0.75) == "review"
    assert f("fail", 0.9, True, 0, 0.75) == "met" and f("unknown", 0.0, False, 0, 0.75) == "review"
    assert f("pass", 0.9, True, 0, 0.75, "inclusion") == "met"
    cases = [{"id": "a", "clipped": True, "clipped_view": {"final": "not met (final)"}},
             {"id": "b", "clipped": False, "clipped_view": {"final": "not met (final)"}},
             {"id": "c", "clipped": True, "clipped_view": {"final": "review"}}]  # fmt: skip
    assert gp.clipped_finals(cases) == ["a"]


def _stub_clients() -> tuple[Any, Any]:
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub
    from tb_common.llm import LlmClient

    out = []
    for name in ("stub", "stub-verifier"):
        c = LlmClient("http://stub/v1", name)
        c.http = TestClient(stub)
        out.append(c)
    return out[0], out[1]


def test_g7_records_every_view_and_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cr, "_models", lambda a: _stub_clients())
    res = gp.run_g7(argparse.Namespace(dir=tmp_path))
    b = res["clipped"]
    assert [c["id"] for c in b["cases"]] == [c["id"] for c in gp.clip_cases()]
    for c in b["cases"]:
        for v in ("clipped_view", "whole_view"):
            assert {"judge", "verifier", "pair", "final", "left_out"} <= set(c[v])
    checks = {c[0]: c[1] for st in res["stages"] for c in st["checks"]}
    assert checks["0 exclusions on a clipped note (no final not met from a clipped note)"] == (
        not b["final_not_met_from_clipped_note"]
    )
    monkeypatch.setattr(cr, "_models", lambda a: (None, None))
    assert gp.run_g7(argparse.Namespace(dir=tmp_path))["not_run"] == "no model pair"


# ---------------------------------------------------------------- G-8
AD_TEXT = """Inclusion Criteria:

* Age 50 to 90 years.
* Meets one of the following:
  * Mild cognitive impairment due to Alzheimer's disease.
  * Mild Alzheimer's disease dementia.
* Amyloid positive on PET or CSF.

Exclusion Criteria:

* Any medical condition other than Alzheimer's disease that may account for the cognitive decline.
* Participants in the open-label extension must have completed the core study.
"""


def test_alternative_groups_and_extension_lines_are_found() -> None:
    groups = gp.alternative_groups(AD_TEXT)
    assert groups == [{"opener": "* Meets one of the following:",
                       "members": ["Mild cognitive impairment due to Alzheimer's disease.",
                                   "Mild Alzheimer's disease dementia."]}]  # fmt: skip
    crit = [
        {"id": "X-INC-01", "class": "structured", "text": "Mild cognitive impairment due to Alzheimer's disease.",
         "needs_review": False, "time_sensitive": False, "active": True},
        {"id": "X-INC-02", "class": "structured", "text": "Mild Alzheimer's disease dementia.",
         "needs_review": False, "time_sensitive": True, "active": True},
        {"id": "X-EXC-02", "class": "human", "text": "Participants in the open-label extension must have completed "
         "the core study.", "needs_review": False, "time_sensitive": False, "active": True},
    ]  # fmt: skip
    f = gp.protocol_findings(crit, [], AD_TEXT)
    assert f["class_split"] == {"structured": 2, "human": 1} and f["time_sensitive"] == ["X-INC-02"]
    assert f["extension_active_without_warning"] == ["X-EXC-02"]
    assert f["alternative_groups"][0]["flattened_to_and"] and f["alternative_groups"][0]["criteria"] == [
        "X-INC-01", "X-INC-02"]  # fmt: skip
    crit[2]["needs_review"] = True
    named = gp.protocol_findings(crit, ["X-INC-01 and X-INC-02 are alternatives (OR)"], AD_TEXT)
    assert not named["extension_active_without_warning"] and not named["alternative_groups"][0]["flattened_to_and"]


def test_public_protocols_are_read_from_json_or_text(tmp_path: Path) -> None:
    j = gp.read_protocol(ROOT / "tests" / "fixtures" / "open_data" / "ctgov_NCT02568722.json")
    assert j["id"] == "NCT02568722" and "Inclusion" in j["text"] and j["conditions"] == ["Acute Kidney Injury"]
    (tmp_path / "early-ad.txt").write_text(AD_TEXT, encoding="utf-8")
    t = gp.read_protocol(tmp_path / "early-ad.txt")
    assert t["id"] == "early-ad" and t["text"] == AD_TEXT
    assert gp.protocol_files(tmp_path) == [tmp_path / "early-ad.txt"] and gp.protocol_files(tmp_path / "x") == []
    assert gp.protocols_dir({}) == ROOT / "tests" / "fixtures" / "public_protocols"
    assert gp.protocols_dir({"TB_G8_PROTOCOLS_DIR": str(tmp_path)}) == tmp_path
    on_master = gp.protocol_files(gp.protocols_dir({}))  # lane A's two public protocols (train 6): RA, early AD
    assert [f.name for f in on_master] == ["NCT02629159.json", "NCT03887455.json"]
    assert all(gp.read_protocol(f)["text"].lstrip().lower().startswith(("inclusion", "core study")) for f in on_master)


def test_g8_compiles_a_folder_with_the_judge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "protocols"
    folder.mkdir()
    (folder / "early-ad.txt").write_text(AD_TEXT, encoding="utf-8")
    monkeypatch.setenv("TB_G8_PROTOCOLS_DIR", str(folder))
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    monkeypatch.setattr(cr, "_models", lambda a: _stub_clients())
    res = gp.run_g8(argparse.Namespace(dir=tmp_path / "run"))
    p = res["protocols"]["protocols"][0]
    assert "error" not in p, p
    assert p["criteria"] >= 4 and sum(p["class_split"].values()) == p["criteria"]
    assert {"id", "kind", "class", "needs_review", "time_sensitive"} <= set(p["per_criterion"][0])
    names = [c[0] for st in res["stages"] for c in st["checks"]]
    assert names[0] == "1 protocol(s) compiled with the production judge" and len(names) == 3
    monkeypatch.setattr(cr, "_models", lambda a: (None, None))
    assert gp.run_g8(argparse.Namespace(dir=tmp_path / "run"))["not_run"] == "no model pair"


# ---------------------------------------------------------------- the report
def test_the_report_has_a_section_per_probe() -> None:
    on = {"calls": 64, "answered": 64, "calls_per_second": 3.2, "p50_s": 1.0, "p95_s": 2.0, "schema_failures": 0}
    rows = [
        {"tag": "g4-decoding", "decoding": {"backend": {"backend": "xgrammar", "from": "x"}, "guided_on": on,
                                            "guided_off": {**on, "schema_failures": 2}, "profile": "guided decoding on",
                                            "in_flight": 16, "prompts": 64,
                                            "eager": {"result": "needs a restart: not run", "enforce_eager": True}}},
        {"tag": "g5-tokens", "tokens": gp.token_summary({"ja": [{"real": 9, "budget": 10, "cascade": 10}]}, {}, 0.85)},
        {"tag": "g8-protocols", "not_run": "no fixture on master", "protocols": {"protocols": []}},
        {"tag": "hospital-ja"},
    ]  # fmt: skip
    text = "\n".join(gp.report_lines({"parts": rows}))
    assert "### G-4 (g4-decoding)" in text and "**xgrammar**" in text and "| guided off | 64 | 64 | 3.2" in text
    assert "### G-5 (g5-tokens)" in text and "**fits**" in text
    assert "### G-8 (g8-protocols)" in text and "Not run: no fixture on master." in text
    assert "### G-7" not in text and gp.report_lines({"parts": [{"tag": "hospital-ja"}]}) == []
