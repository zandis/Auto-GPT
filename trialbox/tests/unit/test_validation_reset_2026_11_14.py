"""Lane G's validation reset (2026-11-14): a paid run that would not be evidence of the shipped product is refused
unless the operator says so, and then its plan and report say why (tools/product_evidence.py,
docs/plan/measurements/validation-reset-2026-11-14.md)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from tools import complete_run as cr
from tools import product_evidence as pe

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
REH = ROOT / "tests" / "rehearsal"
COMPOSE = (ROOT / "deploy" / "docker-compose.rtxpro6000.yml").read_text(encoding="utf-8")
REGISTRY = {"builds": [
    {"build_id": "gemma-4-26b-a4b-it-rtxpro6000", "expected": {"revision": "a" * 40}},
    {"build_id": "qwen3.5-9b-rtxpro6000", "expected": {"revision": "b" * 40}},
]}  # fmt: skip
SHIPPED_IMAGE = pe._IMAGE.findall(pe._code(COMPOSE))[0]


def _plan(tmp: Path, tags: list[str]) -> Path:
    p = tmp / "plan.json"
    p.write_text(json.dumps({"patients": 500, "plan": {"vms": 1, "shards": [{"shard": 1, "tags": tags}]}}), "utf-8")
    return p


# ------------------------------------------------------------------------------------------------ what it reads
def test_the_shipped_image_is_pinned_by_digest() -> None:
    assert "@sha256:" in SHIPPED_IMAGE


def test_the_vm_script_of_this_tree_differs_from_the_shipped_compose_in_all_three() -> None:
    diffs = pe.tree_serving_differences()
    assert [d.split(":")[0] for d in diffs] == ["chat template", "vLLM image", "weights"], diffs


def test_a_vm_script_that_serves_as_the_box_does_has_no_difference() -> None:
    vm = (f"VLLM={SHIPPED_IMAGE}\n"
          f"start judge --chat-template /models/t.jinja --revision {'a' * 40}\n"
          f"start verifier --revision {'b' * 40}\n")  # fmt: skip
    assert pe.serving_differences(vm, COMPOSE, REGISTRY) == []


def test_a_flag_named_only_in_a_comment_does_not_count() -> None:
    vm = f"# --chat-template is what the box passes\nVLLM={SHIPPED_IMAGE}\n# {'a' * 40} {'b' * 40}\n"
    got = pe.serving_differences(vm, COMPOSE, REGISTRY)
    assert [d.split(":")[0] for d in got] == ["chat template", "weights"]
    # --default-chat-template-kwargs (the verifier's thinking switch) is not --chat-template
    kw = f"VLLM={SHIPPED_IMAGE}\nstart verifier --default-chat-template-kwargs x {'a' * 40} {'b' * 40}\n"
    assert [d.split(":")[0] for d in pe.serving_differences(kw, COMPOSE, REGISTRY)] == ["chat template"]


def test_a_missing_revision_in_the_registry_is_a_difference() -> None:
    vm = f"VLLM={SHIPPED_IMAGE}\nstart judge --chat-template x\n"
    got = pe.serving_differences(vm, COMPOSE, {"builds": []})
    assert got and "none in the registry" in got[0]


def test_the_parts_that_are_not_the_product_path() -> None:
    got = pe.not_product_parts(["hospital-ja", "scenario-public-trec", "scenario-public-mimic", "scenario-public-trec"])
    assert [g.split(":")[0] for g in got] == ["scenario-public-trec", "scenario-public-mimic"]
    assert "mlbench" in got[0] and "stub" in got[1]
    assert pe.not_product_parts(["hospital-ja", "public-ja", "scenario-public-medtxt"]) == []


# ------------------------------------------------------------------------------------------------ the launch gate
def test_the_gate_refuses_and_changes_nothing(tmp_path: Path) -> None:
    p = _plan(tmp_path, ["hospital-ja"])
    before = p.read_text(encoding="utf-8")
    assert pe.launch_gate(p, accept=False) == 8
    assert p.read_text(encoding="utf-8") == before


def test_with_the_flag_the_plan_records_every_reason(tmp_path: Path) -> None:
    p = _plan(tmp_path, ["hospital-ja", "scenario-public-trec"])
    assert pe.launch_gate(p, accept=True) == 0
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["product_evidence"] is False
    assert any(r.startswith("serving: chat template") for r in doc["not_product_evidence"])
    assert any(r.startswith("part scenario-public-trec") for r in doc["not_product_evidence"])


def test_a_dry_run_says_and_writes_nothing(tmp_path: Path, capsys: object) -> None:
    p = _plan(tmp_path, ["scenario-public-mimic"])
    before = p.read_text(encoding="utf-8")
    assert pe.launch_gate(p, accept=False, dry=True) == 0
    assert p.read_text(encoding="utf-8") == before


def test_a_shipped_serving_and_product_parts_pass_the_gate(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    for rel, text in ((pe.VM_SCRIPT, f"VLLM={SHIPPED_IMAGE}\n--chat-template x {'a' * 40} {'b' * 40}\n"),
                      (pe.COMPOSE, COMPOSE), (pe.REGISTRY, json.dumps(REGISTRY))):  # fmt: skip
        f = root / rel.relative_to(pe.ROOT)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    p = _plan(tmp_path, ["hospital-ja", "public-ja"])
    assert pe.launch_gate(p, accept=False, root=root) == 0
    assert json.loads(p.read_text(encoding="utf-8"))["product_evidence"] is True
    # the same plan with a non-product part is refused
    assert pe.launch_gate(_plan(tmp_path, ["scenario-public-trec"]), accept=False, root=root) == 8


def test_the_cli_refuses_with_exit_8(tmp_path: Path) -> None:
    p = _plan(tmp_path, ["hospital-ja"])
    env = dict(os.environ, PYTHONPATH="libs:services:.")
    r = subprocess.run([sys.executable, "-m", "tools.complete_run", "--launch-gate", str(p)], cwd=ROOT, env=env,
                       capture_output=True, text=True, check=False, timeout=120)  # fmt: skip
    assert r.returncode == 8 and "refused" in r.stdout, r.stdout + r.stderr
    r = subprocess.run([sys.executable, "-m", "tools.complete_run", "--launch-gate", str(p), "--not-product-evidence"],
                       cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=120)  # fmt: skip
    assert r.returncode == 0 and "NOT product evidence" in r.stdout


def test_the_driver_refuses_a_paid_launch_before_any_upload_or_start(tmp_path: Path) -> None:
    """The real driver against the rehearsal's gcloud (nothing touches GCP): no --not-product-evidence, exit 8,
    no VM started, no metadata written."""
    state = tmp_path / "state"
    for d in ("metadata", "knobs/metadata", "bucket", "secrets/tb-gpu-door", "units"):  # as the rehearsal's state
        (state / d).mkdir(parents=True, exist_ok=True)
    (state / "status").write_text("TERMINATED\n", encoding="utf-8")
    (tmp_path / "gc").mkdir()
    env = dict(os.environ, PATH=f"{REH / 'driver-shims'}:{os.environ['PATH']}", TB_REH_STATE=str(state),
               TB_REH_CONTAINER="tb-no-such-container", CLOUDSDK_CONFIG=str(tmp_path / "gc"),
               TB_SA_KEY_FILE="/dev/null", TB_COMPLETE_DIR=str(tmp_path / "out"),
               PY=str(ROOT / ".venv" / "bin" / "python"), TB_DOOR_DIRECT="1", TB_LOCK_DIR=str(tmp_path / "locks"),
               GC_TIMEOUT_S="20")  # fmt: skip
    for k in (
        "TB_ZONES",
        "TB_BUCKET",
        "TB_RUN_ID",
        "TB_DRIVER_LOCK_HELD",
        "TB_DRIVER_CHILD",
        "TB_NOT_PRODUCT_EVIDENCE",
    ):
        env.pop(k, None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--patients", "500", "--only", "scenario-gateway", "--no-wait"],
                       cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    calls = (state / "gcloud.log").read_text(encoding="utf-8") if (state / "gcloud.log").exists() else ""
    assert r.returncode == 8, r.stdout[-1500:] + r.stderr[-800:]
    assert "refused: this run would not be evidence of the shipped product" in r.stdout
    assert "instances start" not in calls and "add-metadata" not in calls and "storage cp" not in calls


def test_the_dry_run_says_what_a_launch_would_refuse(tmp_path: Path) -> None:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))
    env.pop("TB_ZONES", None)
    env.pop("TB_NOT_PRODUCT_EVIDENCE", None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--patients", "500", "--only",
                        "scenario-public-mimic"], cwd=ROOT, env=env, capture_output=True, text=True, check=False,
                       timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    assert "a launch would refuse here without --not-product-evidence" in r.stdout
    assert "part scenario-public-mimic" in r.stdout


# ------------------------------------------------------------------------------------------------ the reports
def test_the_run_report_names_why_it_is_not_product_evidence(tmp_path: Path) -> None:
    (tmp_path / "plan.json").write_text(
        json.dumps({"product_evidence": False, "not_product_evidence": ["serving: chat template: x"]}), "utf-8"
    )
    row = {"part": "scenario", "lang": "ja", "tag": "scenario-public-trec", "seconds_total": 1,
           "stages": [{"name": "s", "ok": True, "seconds": 1, "checks": [["c", True, ""]]}]}  # fmt: skip
    a = argparse.Namespace(model="pair", direct=False, ocr="fake", patients=500, langs=["ja"], dir=tmp_path,
                           planned_from=None)  # fmt: skip
    rep = cr.report(a, [row], {"head": "0" * 40, "subject": "s", "dirty": False}, datetime.now(UTC))
    assert rep["not_product_evidence"][0] == "serving: chat template: x"
    assert any(x.startswith("part scenario-public-trec") for x in rep["not_product_evidence"])
    assert "**Not evidence of the shipped product**" in cr.markdown(rep)
    # a plan from before the reset says nothing: not product evidence by default
    (tmp_path / "plan.json").write_text("{}", "utf-8")
    assert "not recorded as the shipped" in cr.report(a, [row], {"head": "0" * 40, "subject": "s", "dirty": False},
                                                      datetime.now(UTC))["not_product_evidence"][0]  # fmt: skip


def test_the_results_reader_marks_every_old_folder_not_product_evidence(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("results_report_reset", GCP / "results_report.py")
    assert spec is not None and spec.loader is not None
    rr = importlib.util.module_from_spec(spec)
    sys.modules["results_report_reset"] = rr
    spec.loader.exec_module(rr)
    folder = ROOT / "docs" / "plan" / "measurements" / "g1-2026-11-11"
    assert rr.main([str(folder), "--out", str(tmp_path)]) == 0
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    cap = json.loads((tmp_path / "capacity_inputs.json").read_text(encoding="utf-8"))
    assert "**Product evidence: NO.**" in readme and "T-667, T-637" not in readme
    assert cap["product_evidence"] is False and cap["not_product_evidence"]
    assert rr.not_product({"report": {}, "plan": {"product_evidence": True}}) == []
