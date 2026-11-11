"""T-653 (ENG-017, ENG-026, ENG-027, ENG-028, ENG-030, ENG-031): the test suite's own hygiene. Pure tests run with no
PostgreSQL; a cluster that cannot start stops the run with one message; the nightly compose job allows no skip; the
jars are a prerequisite of `make test`; the performance gate fails a regression of more than 20 %; the nightly
workflow runs on a schedule and by hand."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import bench

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-e2e.yml"


def _pytest(args: list[str], env: dict[str, str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "TB_TEST_DB_URL", "TB_STRICT"))}
    base.update(PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")), **env)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "0", *args],
                          cwd=cwd, env=base, capture_output=True, text=True, timeout=600, check=False)  # fmt: skip


# ------------------------------------------------------------------------------------------- no PostgreSQL (ENG-028)
def test_a_pure_module_runs_with_no_postgresql_at_all() -> None:
    """The review's acceptance: tests/unit/test_one_engine.py runs with no server binaries (TB_PG_BIN points nowhere,
    no TB_TEST_DB_URL)."""
    r = _pytest(["-m", "nodb", "tests/unit/test_one_engine.py"], {"TB_PG_BIN": "/nonexistent"})
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert re.search(r"\b\d+ passed\b", r.stdout) and "error" not in r.stdout.splitlines()[-1]


def test_a_database_test_without_a_cluster_stops_the_run_with_one_message(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "test_needs_db.py").write_text(
        "def test_one(db_url):\n    assert db_url\n\n\ndef test_two(db_url):\n    assert db_url\n", encoding="utf-8"
    )
    r = _pytest([str(probe), "-p", "tests.conftest", "--rootdir", str(probe), "-c", os.devnull],
                {"TB_PG_BIN": "/nonexistent", "TB_TEST_ROOT": str(tmp_path / "root")})  # fmt: skip
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert out.count("the test PostgreSQL cluster cannot start") >= 1 and "Interrupted" in out
    assert "test_two" not in out.split("short test summary info")[-1]  # stopped after the first test


def test_a_nodb_test_gets_a_database_url_that_refuses() -> None:
    from tests import conftest

    assert conftest.NODB_URL.startswith("postgresql://127.0.0.1:1/")
    assert all((ROOT / m).is_file() for m in conftest.PURE_MODULES)
    assert "tests/unit/test_one_engine.py" in conftest.PURE_MODULES


@pytest.mark.nodb
def test_the_marker_sets_the_refusing_url() -> None:
    from tests import conftest

    assert os.environ["TB_DB_URL"] == conftest.NODB_URL


# ------------------------------------------------------------------------------------- strict skips (ENG-017 nightly)
@pytest.mark.parametrize("strict", [False, True])
def test_a_skip_fails_only_under_strict_skips(tmp_path: Path, strict: bool) -> None:
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "test_skips.py").write_text(
        "import pytest\n\n\n@pytest.mark.nodb\ndef test_skipped():\n    pytest.skip('compose test stack not running')\n"
        "\n\n@pytest.mark.nodb\n@pytest.mark.xfail(reason='known')\ndef test_xfail():\n    assert False\n",
        encoding="utf-8",
    )
    env = {"TB_PG_BIN": "/nonexistent", "TB_TEST_ROOT": str(tmp_path / "root")}
    if strict:
        env["TB_STRICT_SKIPS"] = "1"
    r = _pytest([str(probe), "-p", "tests.conftest", "--rootdir", str(probe), "-c", os.devnull, "-rA"], env)
    if strict:
        assert r.returncode == 1 and "1 failed" in r.stdout and "1 xfailed" in r.stdout, r.stdout[-1500:]
        assert "TB_STRICT_SKIPS=1" in r.stdout and "compose test stack not running" in r.stdout
    else:
        assert r.returncode == 0 and "1 skipped" in r.stdout and "1 xfailed" in r.stdout, r.stdout[-1500:]


# ------------------------------------------------------------------------------------------ make test (ENG-026, 031)
def _target(name: str) -> str:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(name)}:(.*)$", text, re.M)
    assert m, name
    return m.group(1)


def test_the_jars_are_a_prerequisite_of_make_test() -> None:
    assert "$(JVM_DEPS)" in _target("test") and "$(JVM_DEPS)" in _target("test-random")
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "JVM_DEPS := .cache/jvm/.fetched" in text
    assert re.search(r"^\$\(JVM_DEPS\): tools/fetch_jvm_deps\.sh \$\(TRANSLATOR_POM\)$", text, re.M)
    assert re.search(r"^jvm-deps:\n\ttools/fetch_jvm_deps\.sh\n\t@touch \$\(JVM_DEPS\)$", text, re.M)


def test_the_random_order_run_has_no_network() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^SOCKET \?= pytest-socket==\d+\.\d+\.\d+$", text, re.M)
    assert "--allow-hosts=127.0.0.1,::1 --allow-unix-socket" in text
    locked = text[text.index("test-random-locked:") :].split("\n\n", 1)[0]
    assert "$(NO_NETWORK)" in locked and "$(NO_NETWORK_ARGS)" in locked and "-p randomly" in locked


# ------------------------------------------------------------------------------------------ the nightly (ENG-017, 030)
def test_the_nightly_runs_on_a_schedule_and_by_hand_with_every_job() -> None:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)  # YAML 1.1 reads the key `on` as True
    assert on["schedule"] and "workflow_dispatch" in on
    assert {"random-order", "perf-5k"} <= set(wf["jobs"]["nightly"]["strategy"]["matrix"]["run"])
    runs = "\n".join(str(s.get("run", "")) for s in wf["jobs"]["compose"]["steps"])
    for step in ("make images", "make up-test", "make test-compose", "make walk", "make poc", "test_console_poc.py"):
        assert step in runs, step
    assert "TB_STRICT_SKIPS=1" in runs and "TB_STRICT_SKIPS=1" in _target_body("test-compose")
    nightly = "\n".join(str(s.get("run", "")) for s in wf["jobs"]["nightly"]["steps"])
    assert "make bench-gate" in nightly and "make test-random" in nightly


def _target_body(name: str) -> str:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return text[text.index(f"\n{name}:") :].split("\n\n", 1)[0]


# ------------------------------------------------------------------------------------------- the perf gate (ENG-030)
def _run(**metrics: float) -> dict[str, Any]:
    base = {"generate_s": 2.0, "lake_s": 30.0, "cascade_s": 40.0, "rest_s": 10.0, "total_s": 82.0,
            "peak_rss_mb": 1800}  # fmt: skip
    return {"patients": 5000, "trial": "GZQO", "passed": True, "calibration_s": 1.0, "metrics": {**base, **metrics}}


def test_the_gate_passes_the_baseline_itself_and_small_noise() -> None:
    ok, rows = bench.compare(_run(), _run())
    assert ok and all(r["ok"] for r in rows) and {r["metric"] for r in rows} == set(_run()["metrics"])
    ok, _ = bench.compare(_run(), _run(lake_s=32.5))  # +8 %
    assert ok
    ok, _ = bench.compare(_run(), _run(rest_s=30.0, generate_s=9.0))  # short phases: reported, not gated
    assert ok
    ok, _ = bench.compare(_run(), _run(cascade_s=47.9))  # +19.75 %
    assert ok


def test_a_regression_of_more_than_twenty_percent_fails() -> None:
    ok, rows = bench.compare(_run(), _run(cascade_s=48.5, total_s=90.5))  # +21 % and 8.5 s
    bad = {r["metric"] for r in rows if not r["ok"]}
    assert not ok and bad == {"cascade_s"}
    ok, rows = bench.compare(_run(), _run(total_s=99.0))  # the whole run +21 %
    assert not ok and [r["metric"] for r in rows if not r["ok"]] == ["total_s"]
    ok, rows = bench.compare(_run(), _run(peak_rss_mb=2200))  # +22 %, 400 MB
    assert not ok and [r["metric"] for r in rows if not r["ok"]] == ["peak_rss_mb"]


def test_a_slower_host_scales_the_times_but_not_the_memory_and_is_clamped() -> None:
    slow = _run(cascade_s=70.0, lake_s=52.0, total_s=140.0, rest_s=16.0, generate_s=3.5)
    slow["calibration_s"] = 1.8  # this host is 1.8 times slower on the fixed loop
    ok, rows = bench.compare(_run(), slow)
    assert ok, rows
    assert next(r for r in rows if r["metric"] == "cascade_s")["scaled_baseline"] == 72.0
    far = _run(cascade_s=400.0)
    far["calibration_s"] = 10.0  # clamped at 3x: a host that far off needs its own baseline
    ok, rows = bench.compare(_run(), far)
    assert not ok and next(r for r in rows if r["metric"] == "cascade_s")["scaled_baseline"] == 120.0
    fast = _run(cascade_s=48.5)
    fast["calibration_s"] = 0.5  # a faster reading never lowers the bar: a quiet moment is not a faster host
    ok, rows = bench.compare(_run(), fast)
    assert not ok and next(r for r in rows if r["metric"] == "cascade_s")["scaled_baseline"] == 40.0
    ok, _ = bench.compare(_run(), {**fast, "metrics": _run(cascade_s=44.0)["metrics"]})
    assert ok


def test_a_run_whose_own_checks_failed_fails_and_another_size_is_refused() -> None:
    cur = _run()
    cur["passed"] = False
    assert bench.compare(_run(), cur)[0] is False
    other = _run()
    other["patients"] = 2000
    with pytest.raises(ValueError, match="not comparable"):
        bench.compare(_run(), other)
    missing = _run()
    del missing["metrics"]["lake_s"]
    assert bench.compare(_run(), missing)[0] is False


def test_the_report_names_the_verdict_and_every_metric() -> None:
    cur = {**_run(cascade_s=60.0), "host": {"cpu": "x", "machine": "x86_64", "cpus": 4, "mem_gb": 16}}
    base = {**_run(), "written": "2026-11-10", "host": {"cpu": "y"}}
    ok, rows = bench.compare(base, cur)
    md = bench.gate_markdown(cur, base, rows, ok)
    assert "FAIL" in md and "| cascade_s | 40.0 | 40.0 | 60.0 | +50.0 % | NO |" in md and "| lake_s |" in md
    assert "| rest_s | 10.0 | 10.0 | 10.0 | +0.0 % | not gated |" in md


def test_each_metric_is_the_best_of_the_runs() -> None:
    a, b = _run(cascade_s=50.0, lake_s=29.0), _run(cascade_s=41.0, lake_s=33.0)
    b["passed"], b["failed_checks"] = False, ["x"]
    a["failed_checks"] = []
    best = bench.best_of([a, b])
    assert best["metrics"]["cascade_s"] == 41.0 and best["metrics"]["lake_s"] == 29.0 and best["runs"] == 2
    assert best["passed"] is False and best["failed_checks"] == ["x"]


def test_the_calibration_is_a_positive_time() -> None:
    assert 0 < bench.calibrate(rounds=1) < 60


def test_the_committed_baseline_is_the_stub_at_5000_patients() -> None:
    doc = json.loads(bench.BASELINE.read_text(encoding="utf-8"))
    assert (doc["patients"], doc["trial"], doc["passed"]) == (5000, "GZQO", True)
    assert {"generate_s", "lake_s", "cascade_s", "rest_s", "total_s", "peak_rss_mb"} == set(doc["metrics"])
    assert doc["calibration_s"] > 0 and doc["host"]["cpus"] and doc["written"]
    assert bench.compare(doc, doc)[0]


def test_the_baseline_can_be_adopted_from_a_nightly_report(tmp_path: Path) -> None:
    report = tmp_path / "bench_gate.json"
    cur = {**_run(), "failed_checks": [], "host": {"cpu": "runner"}, "commit": "abc"}
    report.write_text(json.dumps({"passed": True, "current": cur}), encoding="utf-8")
    out = tmp_path / "baseline.json"
    assert bench.main(["--gate", "--adopt", str(report), "--baseline", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["metrics"] == cur["metrics"] and doc["host"] == {"cpu": "runner"} and doc["adopted_from"] == report.name
    report.write_text(json.dumps({"passed": False, "current": {**cur, "passed": False}}), encoding="utf-8")
    assert bench.main(["--gate", "--adopt", str(report), "--baseline", str(out)]) == 1
