"""Public evaluation suites (spec v4 §16, §17.7; S1-13).

Done-when: the GPT-4 reference reproduces accuracy 0.873 and false-block 0.014 exactly (through the gateway, from the
recorded outputs), and ``ingest_fhir_demo`` is green. Results are archived with dataset hashes. The Chia loader stays
a stub until the licence is confirmed. ``ingest_fhir_demo`` skips when the MIMIC demo has not been fetched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.mlbench_tasks.chia import ChiaLicenceUnconfirmed, load_chia
from tools.trialbox import eval as tb_eval
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]
MIMIC = ROOT / ".cache" / "open_data" / "mimic-iv-fhir-demo"


@pytest.mark.req("S1-13", "LLM-30")
def test_judge_public_reproduces_the_gpt4_reference_through_the_gateway(tmp_path: Path) -> None:
    result, path = tb_eval.run_suite("judge_public", tmp_path / "work", tmp_path / "archive")
    assert result["passed"], result
    assert result["reproduced"] == {"accuracy": 0.873, "false_block_rate": 0.014, "false_block_upper95": 0.022}
    assert result["metrics"]["n"] == 1015 and result["metrics"]["valid_rate"] == 1.0
    assert result["gateway"] == {"calls": 1015, "refused": 0, "builds": ["trialbox-stub:unpinned:trialbox-stub-1"]}
    archived = json.loads(path.read_text(encoding="utf-8"))
    assert archived["suite"] == "judge_public" and archived["passed"] is True
    ds = archived["datasets"]
    assert set(ds) == {"eval/criterion_ml/annotations.jsonl", "eval/criterion_ml/notes_en.json"}
    assert all(len(h) == 64 for h in ds.values())
    audit = [
        json.loads(x)
        for f in sorted((tmp_path / "work" / "gateway_audit").glob("*.jsonl"))
        for x in f.read_text().splitlines()
    ]
    assert len(audit) == 1015 and {r["detail"]["class"] for r in audit} == {"D0"}
    assert {r["detail"]["route_id"] for r in audit} == {"dev-stub"}


@pytest.mark.req("S1-13")
def test_recorded_upstream_refuses_unrecorded_requests(tmp_path: Path) -> None:
    from tb_llm import CallLabels, GatewayError, json_schema_format

    gw = tb_eval.stub_gateway(tb_eval.RecordedUpstream({}).client(), tmp_path / "a")
    client = tb_eval.gateway_client(gw, "eval")
    labels = CallLabels("D0", "evaluation", "none", "eval", "judge", "mlbench_judge@1")
    with pytest.raises(GatewayError):
        client.chat(
            [{"role": "user", "content": "x"}], labels, response_format=json_schema_format("j", tb_eval.JUDGE_SCHEMA)
        )


@pytest.mark.req("S1-13", "VV-12", "S1-04")
@pytest.mark.skipif(not (MIMIC / "fhir" / "MimicPatient.ndjson.gz").exists(), reason="MIMIC demo not fetched")
def test_ingest_fhir_demo_is_green_and_archived_with_hashes(tmp_path: Path) -> None:
    result, path = tb_eval.run_suite("ingest_fhir_demo", tmp_path / "work", tmp_path / "archive")
    assert result["passed"], result
    assert result["metrics"] == {
        "outcome": "PUBLISH",
        "blocking_dq_errors": 0,
        "lineage_complete": True,
        "patients": 100,
    }
    fetched = json.loads((MIMIC / "FETCHED.json").read_text(encoding="utf-8"))
    archived = json.loads(path.read_text(encoding="utf-8"))
    assert {k: v for k, v in archived["datasets"].items() if k != "version"} == fetched["files"]


@pytest.mark.req("S1-13")
def test_ingest_fhir_demo_skips_cleanly_without_data(tmp_path: Path) -> None:
    suite = tb_eval.load_suite("ingest_fhir_demo")
    out = tb_eval.run_ingest_fhir_demo(tmp_path, suite, source_dir=tmp_path / "absent")
    assert out["status"] == "skipped" and out["passed"] is None


@pytest.mark.req("S1-13")
def test_chia_loader_is_a_stub_until_the_licence_is_confirmed(tmp_path: Path) -> None:
    with pytest.raises(ChiaLicenceUnconfirmed):
        load_chia(tmp_path)
    result, _ = tb_eval.run_suite("criteria_extract_public", tmp_path, tmp_path / "archive")
    assert result["status"] == "blocked" and "licence" in result["reason"]
    assert list(tmp_path.glob("*.json")) == []  # nothing fetched or written besides the archive


@pytest.mark.req("ENG-16", "S1-13")
def test_suites_refuse_datasets_above_d0_or_unlisted() -> None:
    with pytest.raises(tb_eval.SuiteRefused):
        tb_eval.check_dataset_class("not_a_dataset")
    tb_eval.check_dataset_class("criterion_ml")
    with pytest.raises(tb_eval.SuiteRefused):
        tb_eval.run_suite("no_such_suite", Path("."))
    assert cli(["eval", "no_such_suite"]) == 2
