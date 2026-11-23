"""The performance gate on a runner of another CPU model (rc1 line 1, the nightly's perf-5k).

On 2026-11-20 and 2026-11-22 the gate failed `cascade_s` at +41 % on an AMD runner against a baseline written on an
Intel machine, with no commit to blame (the same code read 16.3 to 19.1 s on one machine in one day). The ruling: when
the runner's CPU model is not the baseline's, the baseline's reference commit is measured on the same runner and the
gate is on the ratio to it. The 20 % tolerance and the floors stay; nothing is re-baselined. Synthetic numbers only."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from tools import bench

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-e2e.yml"
INTEL = {"cpu": "Intel(R) Xeon(R) Processor @ 2.10GHz", "cpus": 4, "mem_gb": 16, "machine": "x86_64"}
AMD = {"cpu": "AMD EPYC 7763 64-Core Processor", "cpus": 4, "mem_gb": 16, "machine": "x86_64"}


def _run(cascade: float, lake: float = 58.0, total: float = 93.0, rss: int = 1871, cal: float = 0.30,
         host: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    return {"patients": 5000, "trial": "GZQO", "passed": True, "failed_checks": [], "calibration_s": cal,
            "host": host or AMD, "commit": "abc",
            "metrics": {"generate_s": 2.5, "lake_s": lake, "cascade_s": cascade, "rest_s": 18.0,
                        "total_s": total, "peak_rss_mb": rss}}  # fmt: skip


BASELINE = {**_run(14.67, cal=0.3241, host=INTEL), "written": "2026-11-10"}


def _cascade(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return next(r for r in rows if r["metric"] == "cascade_s")


def test_a_runner_of_another_cpu_model_is_told_from_the_baselines() -> None:
    assert bench.host_differs(BASELINE, AMD)
    assert not bench.host_differs(BASELINE, INTEL)
    assert not bench.host_differs(BASELINE, {"cpu": ""})  # an unnamed CPU is not "another model"
    assert not bench.host_differs({**BASELINE, "host": {}}, AMD)  # nor is a baseline that names none


def test_the_failure_of_11_22_in_the_baselines_own_numbers_and_the_same_run_on_the_ratio() -> None:
    cur = _run(20.71)  # the run of 2026-11-22: +41 % over a baseline of another machine
    ok, rows = bench.compare(BASELINE, cur)
    assert not ok and not _cascade(rows)["ok"]
    # the reference commit on that same runner took 19.0 s: this run is +9 % over it
    ref = _run(19.0)
    ok, rows = bench.compare(bench.ratio_baseline(BASELINE, ref), cur, ratio=True)
    assert ok and _cascade(rows)["ok"] and _cascade(rows)["scaled_baseline"] == 19.0


def test_a_real_slowdown_still_fails_on_the_ratio() -> None:
    ref = _run(15.0)  # the reference commit, on this runner
    base = bench.ratio_baseline(BASELINE, ref)
    ok, rows = bench.compare(base, _run(19.5), ratio=True)  # +30 % over the reference, and over the 3 s floor
    assert not ok and not _cascade(rows)["ok"]
    ok, rows = bench.compare(base, _run(17.9), ratio=True)  # +19 %: inside the 20 % tolerance
    assert ok
    ok, _ = bench.compare(base, _run(17.9, rss=1871 + 400), ratio=True)  # memory is gated the same way
    assert not ok


def test_the_ratio_is_not_scaled_by_the_calibration() -> None:
    ref = _run(10.0, cal=0.20)
    base = bench.ratio_baseline(BASELINE, ref)
    _, rows = bench.compare(base, _run(10.0, cal=0.60), ratio=True)  # a 3x calibration: the baseline mode would scale
    assert _cascade(rows)["scaled_baseline"] == 10.0
    _, rows = bench.compare(base, _run(10.0, cal=0.60))
    assert _cascade(rows)["scaled_baseline"] == 30.0  # the baseline-mode behaviour is unchanged


def test_the_ratio_baseline_keeps_the_size_and_the_trial_and_says_where_it_came_from() -> None:
    base = bench.ratio_baseline(BASELINE, _run(15.0))
    assert (base["patients"], base["trial"]) == (5000, "GZQO")
    md = bench.gate_markdown(_run(16.0), base, bench.compare(base, _run(16.0), ratio=True)[1], True, ratio=True)
    assert "Ratio mode" in md and "abc" in md and md.count("| cascade_s |") == 1
    assert "Ratio mode" not in bench.gate_markdown(_run(16.0), BASELINE, bench.compare(BASELINE, _run(16.0))[1], True)


def test_the_baseline_names_a_reference_commit_that_exists() -> None:
    doc = json.loads((ROOT / "tools" / "bench_baseline.json").read_text(encoding="utf-8"))
    ref = doc[bench.REF_COMMIT_KEY]
    assert re.fullmatch(r"[0-9a-f]{40}", ref)
    assert doc["metrics"]["cascade_s"] == 14.67  # the baseline's own numbers are not re-baselined


def test_make_passes_the_reference_to_the_gate_only_when_given() -> None:
    def cmd(*extra: str) -> str:
        r = subprocess.run(["make", "-n", "bench-gate", *extra], cwd=ROOT, capture_output=True, text=True, check=False)
        return r.stdout

    assert "--ref" not in cmd()
    assert '--ref "/x/ref.json"' in cmd("BENCH_REF=/x/ref.json")


def test_the_nightly_measures_the_reference_before_the_gate_and_passes_it_on() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.index("--cpu-differs") < text.index("make bench-gate")
    assert 'BENCH_REF="${BENCH_REF:-}"' in text and "BENCH_REF=$RUNNER_TEMP/bench-ref.json" in text
