"""The scenario matrix and the fail-safe cloud run (TB-PLAN-04 step 9, D-141): the pieces that need no box.

The scenarios themselves run in ``python -m tools.complete_run`` (the local done-check); these tests hold the
generators' truth, the recounts, the scoring, the estimate, the resume rule and the cloud scripts' safety."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools import complete_run as cr
from tools import scenarios as sc
from tools import synth_charts as ch

ROOT = Path(__file__).resolve().parents[2]


def test_charts_have_truth_and_traps_in_both_languages() -> None:
    ppl = ch.patients(40)
    langs = {p.lang for p in ppl}
    assert langs == {"ja", "zh-TW"}
    traps = {t for p in ppl for c in p.charts for t in c.traps}
    assert {"negated malignancy", "family history", "ruled-out gout"} <= traps
    for p in ppl:
        assert p.chart_no.startswith("3") and p.chart_no not in "".join(f.value for f in p.facts())
        assert any(f.domain == "birth_date" for f in p.facts())
        for c in p.charts:  # every true fact's value or date is in its chart's text
            for f in c.facts:
                if f.domain == "observation":
                    assert f.value in c.text
        past = [f for f in p.facts() if f.domain == "condition" and f.code in ("C16.9", "C50.919")]
        for f in past:  # past history is dated on its own day, not the visit's
            assert f.day < p.charts[0].facts[-1].day or f.day[:4] <= "2024"


def test_the_stub_reads_the_charts_without_falling_into_the_traps() -> None:
    """The stub stands in for the model locally; on these charts it must reach the floors, or the local run would
    pass on a reader that cannot tell a negation or a relative's disease from the patient's."""
    from llm_stub.handlers import chart_facts
    from sitesetup import charts

    ppl = ch.patients(60, seed=3)
    truth = {p.chart_no: p.facts() for p in ppl}
    got: dict[str, list[dict[str, Any]]] = {}

    class Llm:
        def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
            return chart_facts({"chart": variables["text"]})

    for p in ppl:
        for c in p.charts:
            facts, _ = charts.extract(Llm(), c.text, c.lang)
            got.setdefault(p.chart_no, []).extend(facts)
    s = ch.score(truth, got)
    assert s["precision"] >= sc.FLOORS["precision"] and s["recall"] >= sc.FLOORS["recall"], s


def test_score_counts_wrong_and_missed_facts() -> None:
    t = {"p": [ch.Fact("condition", "M10.9", "2026-10-01"), ch.Fact("observation", "3084-1", "2026-10-01", "8.1")]}
    got = {
        "p": [
            {"domain": "condition", "code": "M10.9", "day": "2026-10-01"},
            {"domain": "condition", "code": "C50.919", "day": "2026-10-01"},
        ]
    }
    s = ch.score(t, got)
    assert (s["matched"], s["proposed"], s["truth"]) == (1, 2, 2)
    assert s["precision"] == 0.5 and s["recall"] == 0.5 and s["wrong"] and s["missed"]


def test_expected_state_is_the_site_study_by_hand() -> None:
    adult = "1960-01-01"
    assert sc.expected_state(sc.Truth(adult, {"M10.9"}, [("2026-10-01", 8.0)])) == "ready"
    assert sc.expected_state(sc.Truth(adult, {"M10.9"}, [("2026-10-01", 6.0)])) == "not_eligible"
    assert sc.expected_state(sc.Truth(adult, {"M10.9"}, [("2024-01-01", 9.0)])) == "needs"  # outside the year
    assert sc.expected_state(sc.Truth(adult, {"M10.9", "C16.9"}, [("2026-10-01", 9.0)])) == "not_eligible"
    # SCR-01: a basal cell skin carcinoma and a Merkel cell carcinoma are malignancies; a history code is unknown
    assert sc.expected_state(sc.Truth(adult, {"M10.9", "C44.91"}, [("2026-10-01", 9.0)])) == "not_eligible"
    assert sc.expected_state(sc.Truth(adult, {"M10.9", "C4A.0"}, [("2026-10-01", 9.0)])) == "not_eligible"
    assert sc.expected_state(sc.Truth(adult, {"M10.9", "Z85.3"}, [("2026-10-01", 9.0)])) == "needs"
    assert sc.expected_state(sc.Truth("2015-01-01", {"M10.9"}, [("2026-10-01", 9.0)])) == "not_eligible"
    assert sc.expected_state(sc.Truth("", {"M10.9"}, [("2026-10-01", 9.0)])) == "needs"


def test_dump_and_sheets_carry_their_truth(tmp_path: Path) -> None:
    data, truth, info = sc.dump(40)
    text = data.decode("cp932")
    assert info["patients"] == 40 and len(truth) == 40 and "患者番号" in text and info["undated"]
    for no in info["undated"]:
        assert any(c.startswith("C") for c in truth[no].dx)


def test_flagged_labs_keep_the_true_number(tmp_path: Path) -> None:
    f = tmp_path / "lab.csv"
    f.write_text(
        "lab_no,mrn,local_code,item_name,result_value,unit,sample_datetime\n"
        "L1,1,UA,Uric acid,8.4,mg/dL,2026-09-01 10:00:00\nL2,1,UA,Uric acid,7.9,mg/dL,2026-10-01 10:00:00\n"
        "L3,2,UA,Uric acid,6.1,mg/dL,2026-10-02 10:00:00\n",
        encoding="utf-8",
    )
    out = sc.flag_labs([f], ["1", "2"])
    rows = f.read_text(encoding="utf-8").splitlines()
    assert out["1"] == ("7.9 H", 7.9) and "7.9 H" in rows[2] and "8.4" in rows[1]  # only the latest one
    assert out["2"][0].startswith(">") and out["2"][1] >= 7.2


def test_model_exclusions_are_checked_against_the_note_truth() -> None:
    v = SimpleNamespace
    results = {
        "a": v(tier="excluded", actions=[], verdicts=[v(id="GZQO-EXC-11", verdict="fail")]),
        "b": v(tier="excluded", actions=[], verdicts=[v(id="GZQO-INC-05", verdict="fail")]),
        "c": v(tier="excluded", actions=[], verdicts=[v(id="GZQO-INC-02", verdict="fail")]),  # coded: not a model's
        "d": v(tier="review", actions=[], verdicts=[]),
        "e": v(
            tier="excluded",
            actions=["contact: deny (FHIR Consent) — never listed"],
            verdicts=[v(id="GZQO-EXC-11", verdict="fail")],
        ),
    }
    truth = {"a": {"GZQO-EXC-11": "yes"}, "b": {"GZQO-INC-05": "yes"}, "d": {"GZQO-EXC-11": "yes"}}
    x = sc.model_exclusions(results, truth)
    assert (x["excluded_by_models"], x["true"], x["false"], x["missed_true"]) == (2, 1, 1, 1)


def test_estimate_for_50000_patients_has_every_scenario_and_a_cap() -> None:
    e = cr.estimate(50000)
    names = {r["scenario"] for r in e["rows"]}
    assert {"db-csv (ja)", "db-csv (zh-TW)", *sc.SCENARIOS} <= names
    assert abs(sum(r["hours"] for r in e["rows"]) - e["hours"]) < 0.1
    assert e["cap_hours"] >= e["hours"] * 1.3 and e["cap_hours"] == int(e["cap_hours"])
    assert abs(e["usd"] - e["hours"] * cr.ON_DEMAND_PRICE_PER_HOUR) < 0.05  # one VM with the hospitals (D-468)
    assert "hard cap" in cr.print_estimate(e)


def test_resume_keeps_only_passed_parts(tmp_path: Path) -> None:
    good = {"stages": [{"checks": [["x", True, ""]]}]}
    bad = {"stages": [{"checks": [["x", False, ""]]}]}
    assert cr._passed(good) and not cr._passed(bad) and not cr._passed({"stages": []})
    assert cr._tag("scenario", "ja", "it-dump") == "scenario-it-dump" and cr._tag("hospital", "ja") == "hospital-ja"


def test_report_only_builds_the_report_from_part_files(tmp_path: Path) -> None:
    (tmp_path / "parts").mkdir()
    part = {
        "stages": [{"name": "s", "ok": True, "seconds": 1, "checks": [["c", True, ""]]}],
        "wall_seconds": 2,
        "scenario": {"input": "x", "model_calls": 3},
        "findings": [{"id": "B-03", "what": "w", "expected": "e", "got": "g", "holds": False}],
    }
    (tmp_path / "parts" / "scenario-it-dump.json").write_text(json.dumps(part), encoding="utf-8")
    a = argparse.Namespace(
        dir=tmp_path,
        langs=["ja"],
        skip=[],
        only=["scenario-it-dump"],
        scenarios=[],
        model="stub",
        direct=False,
        ocr="fake",
        patients=5000,
    )
    assert cr.report_only(a) == 1  # a scenario without a screenshot is not a complete report
    md = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "### it-dump" in md and "Model calls: 3" in md and "| B-03 |" in md


# ------------------------------------------------------------------------------------------------ the cloud scripts
GCP = ROOT / "deploy" / "gcp"


def _fake_gcloud(tmp_path: Path, fail_first: bool) -> Path:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls.log"
    script = f"""#!/bin/sh
echo "$@" >> {log}
if [ "$1" = auth ] && [ "$2" = activate-service-account ]; then exit 0; fi
if [ -f {tmp_path}/failed ] || [ "{int(fail_first)}" = 0 ]; then echo TERMINATED; exit 0; fi
touch {tmp_path}/failed
echo "ERROR: (gcloud.compute.instances.describe) There was a problem refreshing your current auth tokens: invalid_grant" >&2
exit 1
"""
    (bin_ / "gcloud").write_text(script, encoding="utf-8")
    (bin_ / "gcloud").chmod(stat.S_IRWXU)
    return bin_


def _gc(tmp_path: Path, fail_first: bool) -> subprocess.CompletedProcess[str]:
    key = tmp_path / "key.json"
    key.write_text('{"private_key": "SECRET-KEY-MATERIAL"}', encoding="utf-8")
    env = dict(os.environ, PATH=f"{_fake_gcloud(tmp_path, fail_first)}:{os.environ['PATH']}", TB_SA_KEY_FILE=str(key))
    cmd = f". {GCP / 'gcloud-auth.sh'}; gc compute instances describe vm '--format=value(status)'"
    return subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, check=False)


def test_gc_reactivates_once_on_an_auth_error_and_never_prints_the_key(tmp_path: Path) -> None:
    r = _gc(tmp_path, fail_first=True)
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
    assert r.returncode == 0 and r.stdout.strip() == "TERMINATED"
    assert [c.split()[:2] for c in calls] == [
        ["compute", "instances"],
        ["auth", "activate-service-account"],
        ["compute", "instances"],
    ]
    assert "SECRET-KEY-MATERIAL" not in r.stdout + r.stderr


def test_gc_passes_other_errors_through(tmp_path: Path) -> None:
    r = _gc(tmp_path, fail_first=False)
    assert r.returncode == 0 and "activate" not in (tmp_path / "calls.log").read_text(encoding="utf-8")


def test_driver_sets_the_cloud_cap_before_the_start(tmp_path: Path) -> None:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))
    r = subprocess.run(
        [str(GCP / "complete-run.sh"), "--dry-run", "--patients", "50000"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    out = r.stdout
    assert r.returncode == 0, r.stderr[-800:]
    cap = out.index("set-scheduling tb-gpu-sim --zone asia-east1-a --max-run-duration=")
    assert "--instance-termination-action=STOP" in out and cap < out.index("instances start tb-gpu-sim")
    assert out.index("auth print-access-token") < cap  # the credential is probed before anything costs money
    assert "tb-idle-minutes=20" in out and "complete-run-vm.sh" in out


def test_vm_script_stops_itself_and_never_traces_the_key() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert "set -x" not in vm.replace("no `set -x`", "")
    assert "systemd-run --unit tb-hard-cap" in vm and "systemd-run --unit tb-watchdog" in vm
    assert vm.index("tb-watchdog") < vm.index("gcloud secrets versions access")  # the nets are up before anything else
    assert "--resume" in vm and "--ocr tesseract" in vm and "tesseract-ocr-jpn tesseract-ocr-chi-tra" in vm
    for name in ("gpu-sim-startup.sh", "gpu-fit-test.sh", "gpu-pro6000-run.sh", "gpu-swap-run.sh"):  # review A-12
        text = (GCP / name).read_text(encoding="utf-8")
        assert not [ln for ln in text.splitlines() if ln.strip() == "set -x"], name
