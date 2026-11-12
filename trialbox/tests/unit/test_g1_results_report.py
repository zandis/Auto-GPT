"""The results reader of lane G (deploy/gcp/results_report.py): a collected results folder -> the results PR's files.

The fixtures under tests/rehearsal/results-fixtures/ are small synthetic folders of the shape a collect leaves
(plan.json, TB_HEAD.json, parts/<tag>.json), with made-up figures and made-up model names.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "rehearsal" / "results-fixtures"
REAL = ROOT / "docs" / "plan" / "measurements" / "g1-2026-11-11"
SETTINGS = [1, 4, 16, 48]
WINDOW = ["--window-patients", "50000", "--studies", "5", "--night-hours", "8"]
FIXTURE_MODEL_NAMES = ("synthetic-judge-fixture", "synthetic-verifier-fixture")

_spec = importlib.util.spec_from_file_location("results_report", ROOT / "deploy" / "gcp" / "results_report.py")
assert _spec is not None and _spec.loader is not None
rr = importlib.util.module_from_spec(_spec)
sys.modules["results_report"] = rr
_spec.loader.exec_module(rr)


def run(folder: Path, out: Path, *args: str) -> tuple[int, str, str, dict]:
    code = rr.main([str(folder), "--out", str(out), *args])
    if code:
        return code, "", "", {}
    return (code, (out / "README.md").read_text("utf-8"), (out / "DEFECTS.md").read_text("utf-8"),
            json.loads((out / "capacity_inputs.json").read_text("utf-8")))  # fmt: skip


def test_complete_run(tmp_path: Path) -> None:
    code, readme, defects, cap = run(FIXTURES / "complete", tmp_path, *WINDOW, "--vm-hours", "2.6")
    assert code == 0
    assert "**Verdict**: **PASSED**" in readme
    assert "9 passed, 0 failed, 0 pending, 0 missing, of 9 planned" in readme
    assert "`20261112T090000Z-0f1e2d3c`" in readme and "`0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c`" in readme
    # hours and cost against the estimate and the cap, all from the plan and the argument
    assert "2.6 h (VM hours given with --vm-hours); estimate 2.9 h; cap 4 h" in readme
    assert "US$21.37 at US$8.22 an hour; estimate US$23.84; cap US$32.88" in readme
    for tag in ("chat-template", "install", "prepare", "scenario-gateway", "scenario-emr-fhir"):
        assert f"| `{tag}` | PASSED |" in readme
    # G-1: both sha256 and the differing tokens
    assert "**Verdict: IDENTICAL**" in readme and "Differing tokens: 0 of 3,120 over 20 prompts" in readme
    assert cap["g1"]["passed_sha256"] == cap["g1"]["folder_sha256"] and len(cap["g1"]["passed_sha256"]) == 64
    # G-3: one row per setting, the list identical, the chosen setting meets the window
    g3 = cap["g3"]["ja"]
    assert [s["in_flight"] for s in g3["settings"]] == SETTINGS
    assert "Candidate list: **IDENTICAL** at 1, 4, 16, 48 in flight." in readme
    assert g3["chosen_in_flight"] == 16 and "**PASS: meets the window.**" in readme
    assert "| 16 | PASSED | 2.42 | 1655.0 | 5.9 | 11.8 | 93.0 | 63600.0 | 97887.0 | 0 | 3 |" in readme
    assert "No part that ran failed" in defects and "### D1." not in defects
    # the capacity inputs: per setting, with the run id and the commit
    assert cap["schema"] == "tb-capacity-inputs/1" and cap["complete"] is True
    assert cap["run_id"] == "20261112T090000Z-0f1e2d3c" and cap["commit"].startswith("0f1e2d3c")
    s16 = g3["settings"][2]
    assert (s16["calls_per_second"], s16["tokens_per_second"], s16["patients"]) == (2.42, 1655.0, 5000)
    assert s16["seconds_per_patient"] == pytest.approx(s16["wall_seconds"] / 5000, abs=1e-4)
    assert s16["model_seconds_per_patient"] == pytest.approx(s16["model_busy_seconds"] / 5000, abs=1e-4)
    assert set(s16["by_role"]) == {"judge", "verifier"}  # roles, never endpoint or model names


def test_threshold_is_computed_from_the_arguments(tmp_path: Path) -> None:
    """Plan v7 section 7.1: with the G1 share of calls (6,704 calls for 50,000 patients) and an 8-hour night,
    50,000 x 5 studies needs 1.66 calls/s and 500,000 x 1 study needs 3.3. The reader computes both."""
    g1_calls = ["--calls-per-patient", str(6704 / 50000)]
    _, _, _, a = run(FIXTURES / "complete", tmp_path / "a", *WINDOW, *g1_calls)
    assert a["g3"]["ja"]["window"]["required_calls_per_second"] == pytest.approx(1.66, abs=0.005)
    _, readme, _, b = run(FIXTURES / "complete", tmp_path / "b", "--window-patients", "500000", "--studies", "1",
                          "--night-hours", "8", *g1_calls)  # fmt: skip
    assert b["g3"]["ja"]["window"]["required_calls_per_second"] == pytest.approx(3.3, abs=0.03)
    assert b["g3"]["ja"]["window"]["status"] == "BELOW" and "**FAIL: below the window.**" in readme
    # a longer night halves the need; a smaller window share raises it
    _, _, _, c = run(FIXTURES / "complete", tmp_path / "c", "--window-patients", "50000", "--studies", "5",
                     "--night-hours", "16", *g1_calls)  # fmt: skip
    assert c["g3"]["ja"]["window"]["required_calls_per_second"] == pytest.approx(1.66 / 2, abs=0.005)
    _, _, _, d = run(FIXTURES / "complete", tmp_path / "d", *WINDOW, *g1_calls, "--window-share", "0.35")
    assert d["g3"]["ja"]["window"]["required_calls_per_second"] == pytest.approx(1.66 * 2, abs=0.01)
    # without studies and night hours there is no verdict, and no made-up figure
    _, readme, _, e = run(FIXTURES / "complete", tmp_path / "e")
    assert e["g3"]["ja"]["window"]["status"] == "NOT COMPUTED" and "Night window: **NOT COMPUTED**" in readme
    assert "required_calls_per_second" not in e["g3"]["ja"]["window"]


def test_window_can_come_from_the_plan(tmp_path: Path) -> None:
    src = tmp_path / "run"
    shutil.copytree(FIXTURES / "complete", src)
    plan = json.loads((src / "plan.json").read_text("utf-8"))
    plan["window"] = {"patients": 50000, "studies": 5, "night_hours": 8}
    (src / "plan.json").write_text(json.dumps(plan), "utf-8")
    _, _, _, cap = run(src, tmp_path / "out")
    assert cap["g3"]["ja"]["window"]["status"] == "MEETS"
    assert cap["g3"]["ja"]["window"]["required_calls_per_second"] == pytest.approx(1.662, abs=0.001)


def test_preempted_after_two_parts(tmp_path: Path) -> None:
    code, readme, defects, cap = run(FIXTURES / "preempted", tmp_path, *WINDOW)
    assert code == 0
    assert "**Verdict**: **INCOMPLETE**" in readme
    assert "2 passed, 0 failed, 1 pending, 6 missing, of 9 planned" in readme
    assert "| `prepare` | PENDING | - | - | - | a half-written result is in the folder |" in readme
    missing = [*(f"hospital-ja@c{n}" for n in SETTINGS), "scenario-gateway", "scenario-emr-fhir"]
    for tag in missing:
        assert f"| `{tag}` | MISSING |" in readme and f"- `{tag}`: MISSING" in defects
        assert cap["parts"][tag] == "MISSING"
    assert cap["complete"] is False and cap["parts"]["prepare"] == "PENDING"
    # every setting of the curve is still a row; nothing is judged or chosen from no data
    assert [s["status"] for s in cap["g3"]["ja"]["settings"]] == ["MISSING"] * 4
    assert cap["g3"]["ja"]["candidate_lists"]["status"] == "NOT JUDGED"
    assert cap["g3"]["ja"]["chosen_in_flight"] is None and cap["g3"]["ja"]["window"]["status"] == "NOT COMPUTED"
    assert "### D1." not in defects  # a part that did not run is not a defect, and not passed


def test_pending_argument_and_report_state(tmp_path: Path) -> None:
    _, readme, _, cap = run(FIXTURES / "preempted", tmp_path / "a", "--pending", "hospital-ja@c1,scenario-gateway")
    assert cap["parts"]["hospital-ja@c1"] == "PENDING" and cap["parts"]["scenario-gateway"] == "PENDING"
    assert cap["parts"]["hospital-ja@c4"] == "MISSING" and "2 passed, 0 failed, 3 pending, 4 missing" in readme
    src = tmp_path / "run"
    shutil.copytree(FIXTURES / "preempted", src)
    (src / "report").mkdir()
    (src / "report" / "report.json").write_text(
        json.dumps(
            {
                "not_started": [
                    {"tag": "hospital-ja@c4", "state": "pending"},
                    {"tag": "hospital-ja@c16", "state": "not run (VM stopped)"},
                ]
            }
        )
    )
    _, readme, _, cap = run(src, tmp_path / "b")
    assert cap["parts"]["hospital-ja@c4"] == "PENDING" and cap["parts"]["hospital-ja@c16"] == "MISSING"
    assert "| `hospital-ja@c16` | MISSING | - | - | - | not run (VM stopped) |" in readme


def test_candidate_list_differs_at_one_setting(tmp_path: Path) -> None:
    code, readme, defects, cap = run(FIXTURES / "list-differs", tmp_path, *WINDOW)
    assert code == 0 and "**Verdict**: **FAILED**" in readme
    assert "**FAIL: the candidate list at 16 in flight differs from the list at 1, 4, 48.**" in readme
    lists = cap["g3"]["ja"]["candidate_lists"]
    assert lists["status"] == "DIFFERENT" and lists["reference_settings"] == [1, 4, 48]
    assert lists["differing"] == [{"in_flight": 16, "candidates": 3, "only_here": 1, "not_here": 1}]
    # the setting with another list is never the chosen one, though it is the fastest
    assert cap["g3"]["ja"]["chosen_in_flight"] == 48
    assert "the candidate list of hospital-ja depends on the calls in flight" in defects
    assert "The list at 16 in flight differs from the list at 1, 4, 48. 1 listed only here, 1 missing here." in defects
    for field in ("- **Cause.**\n", "- **Fix.**\n", "- **Card.**\n"):  # empty, for the integrator
        assert field in defects


def test_chat_template_with_differing_tokens(tmp_path: Path) -> None:
    code, readme, defects, cap = run(FIXTURES / "template-differs", tmp_path, *WINDOW)
    assert code == 0 and "**Verdict**: **FAILED**" in readme
    assert "| `chat-template` | FAILED | 0/3 |" in readme and "**Verdict: DIFFERENT**" in readme
    one = cap["g1"]
    assert one["sha256_equal"] is False and one["passed_sha256"] != one["folder_sha256"]
    assert f"`{one['passed_sha256']}`" in readme and f"`{one['folder_sha256']}`" in readme
    # three listed differences: lengths 158/156 twice (2 tokens each) and one of equal length (1 token)
    assert one["differing_tokens_at_least"] == 5 and one["differing_prompts_listed"] == [2, 7]
    assert "Differing tokens: at least 5 of 3,120 over 20 prompts; differing prompts listed: [2, 7]" in readme
    assert defects.count("### D") == 4  # the three failed checks and the G-1 verdict
    assert "G-1: the passed chat template is not the weights folder's own" in defects
    assert "parts/chat-template.json" in defects


def test_throughput_below_the_window(tmp_path: Path) -> None:
    code, readme, defects, cap = run(FIXTURES / "below-window", tmp_path, *WINDOW)
    assert code == 0 and "**Verdict**: **FAILED**" in readme
    w = cap["g3"]["ja"]["window"]
    assert w["status"] == "BELOW" and w["measured_calls_per_second"] == 1.21 < w["required_calls_per_second"]
    assert "**FAIL: below the window.** Measured 1.21 calls/s; needed 1.662 calls/s." in readme
    assert "G-3: hospital-ja is slower than the night window needs" in defects
    assert "Candidate list: **IDENTICAL**" in readme  # slow, but the list is sound
    # the same run meets a smaller site's window: the verdict follows the arguments
    _, readme, _, cap = run(FIXTURES / "below-window", tmp_path / "small", "--window-patients", "50000", "--studies",
                            "1", "--night-hours", "8")  # fmt: skip
    assert cap["g3"]["ja"]["window"]["status"] == "MEETS" and cap["verdict"] == "PASSED"


def test_breaker_cost_and_failed_part_are_defects(tmp_path: Path) -> None:
    src = tmp_path / "run"
    shutil.copytree(FIXTURES / "complete", src)
    f = src / "parts" / "hospital-ja@c48.json"
    res = json.loads(f.read_text("utf-8"))
    res["throughput"]["breaker_opens"] = {"serving": 2, "verifier": 1}
    f.write_text(json.dumps(res), "utf-8")
    (src / "parts" / "scenario-gateway.json").write_text(json.dumps({
        "stages": [{"name": "scenario-gateway crashed", "ok": False, "seconds": 0,
                    "checks": [["part ran", False, "RuntimeError('synthetic-judge-fixture did not answer')"]]}],
        "not_run": "crashed", "run": res["run"], "wall_seconds": 3.0}), "utf-8")  # fmt: skip
    _, readme, defects, cap = run(src, tmp_path / "out", *WINDOW, "--vm-hours", "5")
    assert "| `scenario-gateway` | FAILED | 0/1 | - | 3.0 | did not run: crashed |" in readme
    assert "**FAIL: over the cap**" in readme and "The run cost more than its cap" in defects
    assert "G-3: the breaker opened at 48 in flight (hospital-ja)" in defects and "3 breaker opening(s)" in defects
    assert "RuntimeError('<judge> did not answer')" in defects  # the role, not the model's name
    assert cap["g3"]["ja"]["settings"][3]["breaker_opens"] == 3 and cap["cost"]["over_cap"] is True


@pytest.mark.parametrize("name", ["complete", "preempted", "list-differs", "template-differs", "below-window"])
def test_no_model_name_in_any_output(tmp_path: Path, name: str) -> None:
    code, *_ = run(FIXTURES / name, tmp_path, *WINDOW)
    assert code == 0
    text = "".join(p.read_text("utf-8") for p in tmp_path.iterdir())
    assert not [m for m in FIXTURE_MODEL_NAMES if m in text]
    assert "judge_model" not in text and "verifier_model" not in text


def test_the_real_partial_run_marks_its_missing_parts(tmp_path: Path) -> None:
    """docs/plan/measurements/g1-2026-11-11: three parts of twenty, part files flat in the folder."""
    code, readme, defects, cap = run(REAL, tmp_path)
    assert code == 0
    assert "2 passed, 1 failed, 0 pending, 17 missing, of 20 planned" in readme
    assert "| `hospital-ja` | FAILED | 210/211 |" in readme
    for tag in ("hospital-zh-TW", "public-ja", "scenario-gateway", "embed", "profile"):
        assert f"| `{tag}` | MISSING |" in readme
    assert cap["run_id"] == "20261111T183639Z-986d91c9" and cap["complete"] is False
    assert 'stage "12 site set-up and data harmonization"' in defects
    models = json.loads((REAL / "hospital-ja.json").read_text("utf-8"))["screen"]["judging"]
    for model in (models["judge_model"], models["verifier_model"]):
        assert model not in readme + defects + json.dumps(cap) and model.split("/")[-1] not in readme + defects


@pytest.mark.parametrize(
    "text", ['{"stages": [', '{"checks": []}', '{"stages": [{"checks": [["only a name"]]}]}', "[]"]
)
def test_a_malformed_part_is_the_only_non_zero_exit(tmp_path: Path, text: str, capsys: pytest.CaptureFixture) -> None:
    src = tmp_path / "run"
    shutil.copytree(FIXTURES / "complete", src)
    (src / "parts" / "install.json").write_text(text, "utf-8")
    assert rr.main([str(src), "--out", str(tmp_path / "out")]) == 2
    assert "install.json" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()  # nothing is written from a folder that cannot be read


def test_a_malformed_plan_and_a_missing_folder(tmp_path: Path) -> None:
    src = tmp_path / "run"
    shutil.copytree(FIXTURES / "complete", src)
    (src / "plan.json").write_text("not json", "utf-8")
    assert rr.main([str(src), "--out", str(tmp_path / "out")]) == 2
    assert rr.main([str(tmp_path / "nowhere"), "--out", str(tmp_path / "out")]) == 2


def test_a_hand_written_readme_is_not_overwritten(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "README.md").write_text("# written by hand\n", "utf-8")
    assert rr.main([str(FIXTURES / "complete"), "--out", str(out)]) == 3
    assert (out / "README.md").read_text("utf-8") == "# written by hand\n"
    assert rr.main([str(FIXTURES / "complete"), "--out", str(out), "--force"]) == 0
    assert rr.main([str(FIXTURES / "complete"), "--out", str(out)]) == 0  # its own README: written again


def test_the_reader_only_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No service, no command, and the results folder is left as it was."""

    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("the reader must not open a socket or run a command")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    src = FIXTURES / "complete"
    before = {p: p.read_bytes() for p in src.rglob("*") if p.is_file()}
    assert rr.main([str(src), "--out", str(tmp_path), *WINDOW]) == 0
    assert {p: p.read_bytes() for p in src.rglob("*") if p.is_file()} == before
    source = (ROOT / "deploy" / "gcp" / "results_report.py").read_text("utf-8")
    for word in ("import subprocess", "import urllib", "import socket", "import requests", "gcloud "):
        assert word not in source


def test_the_command_line_as_documented(tmp_path: Path) -> None:
    done = subprocess.run([sys.executable, "deploy/gcp/results_report.py", str(REAL), "--out", str(tmp_path)],
                          cwd=ROOT, capture_output=True, text=True, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("FAILED: 2 passed, 1 failed, 0 pending, 17 missing; 1 defect(s)")
    assert (tmp_path / "README.md").exists() and (tmp_path / "capacity_inputs.json").exists()
