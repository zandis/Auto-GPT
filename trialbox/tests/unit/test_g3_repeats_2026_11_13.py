"""B5 (2026-11-13): ``--repeats N`` runs each ``--llm-concurrency`` setting N times, each its own part
``hospital-<lang>@c<N>#r<k>``, every (setting, repeat) pair in the order the recorded seed gives. The estimate, the cap,
the plan, the report's G-3 table (mean, min and max of the main SCREEN's calls/s per setting) and the results reader
understand the tags. A restart of the model servers between settings is not in scope, and the texts say so. Each test
failed before the change. No cloud: pure functions, the driver's ``--dry-run``, the reader on a synthetic folder."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import complete_run as cr
from tools import run_metrics as rm

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
FIXTURES = ROOT / "tests" / "rehearsal" / "results-fixtures"


def _ns(**kw: Any) -> argparse.Namespace:
    base: dict[str, Any] = {"langs": ["ja"], "scenarios": ["gateway"], "skip": [], "only": [], "llm_concurrency": ""}
    return argparse.Namespace(**{**base, **kw})


def test_every_setting_and_repeat_is_a_part_in_the_seeded_order() -> None:
    runs = cr.hospital_variants((1, 4, 16), 3, seed=7)
    assert sorted(runs) == sorted(f"c{n}#r{k}" for n in (1, 4, 16) for k in (1, 2, 3))  # each pair once
    assert runs == cr.hospital_variants((1, 4, 16), 3, seed=7) != cr.hospital_variants((1, 4, 16), 3, seed=8)
    assert runs != [f"c{n}#r{k}" for k in (1, 2, 3) for n in (1, 4, 16)]  # shuffled across all pairs, not per round
    assert cr.hospital_variants((1, 4, 16), 3) == [f"c{n}#r{k}" for k in (1, 2, 3) for n in (1, 4, 16)]  # no seed
    assert cr.hospital_variants((16,), 2, seed=1) in (["c16#r1", "c16#r2"], ["c16#r2", "c16#r1"])
    # one run per setting: as before (the tags hospital-ja@c<N>, or hospital-ja alone)
    assert cr.hospital_variants((1, 4), 1, seed=7) == ["c1", "c4"] and cr.hospital_variants((16,)) == [""]
    assert (
        cr.setting_tag("hospital-ja@c16#r2") == "hospital-ja@c16" and cr.base_tag("hospital-ja@c16#r2") == "hospital-ja"
    )
    assert cr.variant_concurrency("c16#r2") == 16 == cr.variant_concurrency("c16")


def test_the_plan_runs_the_repeats_and_only_names_a_setting(tmp_path: Path) -> None:
    a = _ns(llm_concurrency="1,16", repeats=2, order_seed=7)
    tags = [cr._tag(*p) for p in cr.plan(a)]
    hosp = [t for t in tags if t.startswith("hospital-")]
    assert hosp == [f"hospital-ja@{v}" for v in cr.hospital_variants((1, 16), 2, 7)] and len(hosp) == 4
    a.only = ["hospital-ja@c16"]  # a setting: every repeat of it
    assert [cr._tag(*p) for p in cr.plan(a)] == [t for t in hosp if t.startswith("hospital-ja@c16#")]
    a.only = ["hospital-ja@c16#r2"]
    assert [cr._tag(*p) for p in cr.plan(a)] == ["hospital-ja@c16#r2"]
    ns = _ns(dir=tmp_path, patients=500, model="stub", ocr="fake", run_id="R", direct=False, live_record=None,
             resume=False, keep_work=False, lc=(1, 16))  # fmt: skip
    cmd = cr._cmd(ns, "hospital", "ja", "c16#r2", tmp_path)
    assert cmd[cmd.index("--variant") + 1] == "c16#r2" and cmd[cmd.index("--llm-concurrency") + 1] == "16"
    assert cr._tag("hospital", "ja", "c16#r2") == "hospital-ja@c16#r2"


def test_the_estimate_and_the_cap_count_every_repeat(capsys: pytest.CaptureFixture[str]) -> None:
    e = cr.restrict(cr.estimate(5000, llm_concurrency=(1, 16), repeats=2, order_seed=7), ["hospital-ja"])
    tags = [t for r in e["rows"] for t in r["tags"]]
    assert sorted(tags) == sorted(f"hospital-ja@c{n}#r{k}" for n in (1, 16) for k in (1, 2))
    one = cr.restrict(cr.estimate(5000, llm_concurrency=(1, 16)), ["hospital-ja"])
    assert e["hours"] == pytest.approx(0.5 + 2 * (one["hours"] - 0.5), abs=0.02) and e["repeats"] == 2
    assert e["cap_hours"] >= 1.3 * e["hours"]
    assert {r["scenario"] for r in e["rows"] if r["tags"]} >= {"db-csv (ja, 16 in flight, repeat 2)"}
    assert cr.restrict(cr.estimate(5000, llm_concurrency=(1, 16), repeats=2), ["hospital-ja@c16"])["rows"][-1][
        "tags"] == ["hospital-ja@c16#r2"]  # fmt: skip
    assert cr.main(["--estimate", "--patients", "5000", "--only", "hospital-ja", "--llm-concurrency", "1,16",
                    "--repeats", "2", "--order-seed", "7", "--json"]) == 0  # fmt: skip
    doc = json.loads(capsys.readouterr().out)
    assert doc["repeats"] == 2 and doc["llm_concurrency"] == [1, 16]  # the given order: the VM shuffles the pairs
    assert doc["llm_concurrency_order"] == {"seed": 7, "given": [1, 16], "runs": cr.hospital_variants((1, 16), 2, 7)}
    text = cr.print_estimate(doc)
    assert "the hospital part runs 2 times per value, each its own part (hospital-<lang>@c<N>#r<k>)" in text
    assert "order: every (setting, repeat) pair randomised with seed 7" in text
    assert f"run order: {' '.join(cr.hospital_variants((1, 16), 2, 7))}" in text
    assert "the model servers are not restarted between settings or repeats (not in scope)" in text
    with pytest.raises(SystemExit):
        cr.main(["--estimate", "--repeats", "0"])


def test_a_restarted_shard_knows_the_repeats(tmp_path: Path) -> None:
    doc = cr.restrict(cr.estimate(5000, llm_concurrency=(16,), repeats=2), ["hospital-ja"])
    doc["plan"] = cr.shard_plan(doc, 1)
    now = cr.shard_now(doc, 1, [tmp_path], "R", "")
    assert sorted(now["left"]) == sorted(["prepare", "hospital-ja@c16#r1", "hospital-ja@c16#r2"])


def _hosp(tag: str, cps: float | None, n: int) -> dict[str, Any]:
    return {"part": "hospital", "lang": "ja", "tag": tag, "llm_concurrency": n,
            "throughput": {"calls": 600, "calls_per_second": 1.0},
            "throughput_screen": {"calls": 244, "calls_per_second": cps} if cps is not None else None,
            "stages": [{"name": "s", "ok": True, "seconds": 1, "checks": [["c", True, ""]]}],
            "seconds_total": 1}  # fmt: skip


def test_the_report_shows_each_settings_mean_min_and_max() -> None:
    rows = [_hosp("hospital-ja@c16#r1", 4.4, 16), _hosp("hospital-ja@c1#r1", 0.38, 1), _hosp("hospital-ja@c16#r2", 4.6, 16),
            _hosp("hospital-ja@c1#r2", 0.4, 1), _hosp("hospital-ja@c4", 1.4, 4)]  # fmt: skip
    s = rm.repeat_summary(rows)
    assert [(x["llm_concurrency"], x["repeats"], x["mean"], x["min"], x["max"]) for x in s] == [
        (1, 2, 0.39, 0.38, 0.4), (16, 2, 4.5, 4.4, 4.6)]  # fmt: skip
    rep = {"throughput": rm.curve(rows), "parts": rows, "repeats": s}
    text = "\n".join(cr._throughput_section(rep))
    assert "| hospital | in flight | repeats | measured | main SCREEN calls/s mean | min | max |" in text
    assert "| ja | 16 | 2 | 2 | 4.5 | 4.4 | 4.6 |" in text and "| ja | 1 | 2 | 2 | 0.39 | 0.38 | 0.4 |" in text
    assert "not restarted between settings or repeats (not in scope)" in text
    assert rm.repeat_summary([_hosp("hospital-ja@c4", 1.4, 4)]) == []  # no repeat: no such table
    assert rm.repeat_summary([_hosp("hospital-ja@c4#r1", None, 4)])[0]["mean"] is None  # not measured: not in it


def _reader() -> Any:
    spec = importlib.util.spec_from_file_location("results_report_b5", GCP / "results_report.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["results_report_b5"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_results_reader_understands_the_repeat_tags(tmp_path: Path) -> None:
    rr = _reader()
    folder = tmp_path / "run"
    shutil.copytree(FIXTURES / "complete", folder)
    parts = folder / "parts"
    src = json.loads((parts / "hospital-ja@c16.json").read_text(encoding="utf-8"))
    (parts / "hospital-ja@c16.json").unlink()
    for k, cps in ((1, 5.2), (2, 4.8), (3, 5.0)):
        doc = json.loads(json.dumps(src))
        doc["throughput"]["calls_per_second"] = cps
        (parts / f"hospital-ja@c16#r{k}.json").write_text(json.dumps(doc), encoding="utf-8")
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    for s in plan["plan"]["shards"]:
        s["tags"] = [t for t in s["tags"] if t != "hospital-ja@c16"] + [f"hospital-ja@c16#r{k}" for k in (1, 2, 3)]
    (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    out = tmp_path / "out"
    assert rr.main([str(folder), "--out", str(out), "--window-patients", "50000", "--studies", "5",
                    "--night-hours", "8"]) == 0  # fmt: skip
    cap = json.loads((out / "capacity_inputs.json").read_text(encoding="utf-8"))
    g3 = cap["g3"]["ja"]
    assert [(s["in_flight"], s["repeat"]) for s in g3["settings"]] == [(1, None), (4, None), (16, 1), (16, 2), (16, 3),
                                                                       (48, None)]  # fmt: skip
    assert g3["repeats"] == [{"in_flight": 16, "repeats": 3, "measured": 3, "mean": 5.0, "min": 4.8, "max": 5.2}]
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "| 16 | 3 | 3 | 5.0 | 4.8 | 5.2 |" in readme and "| 16#r2 | PASSED |" in readme
    assert "The model servers were not restarted between settings or repeats (not in scope)." in readme
    assert "Candidate list: **IDENTICAL** at 1, 4, 16#r1, 16#r2, 16#r3, 48 in flight." in readme
    for k in (1, 2, 3):
        assert f"| `hospital-ja@c16#r{k}` | PASSED |" in readme


def test_the_driver_passes_the_repeats_and_their_seed_to_the_vm(tmp_path: Path) -> None:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"),
               TB_RUN_ID="R")  # fmt: skip
    for k in ("TB_ZONES", "TB_ESTIMATE_LLM_SPEEDUP", "TB_PROVISIONING"):
        env.pop(k, None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--patients", "5000", "--only", "hospital-ja",
                        "--llm-concurrency", "1,16", "--repeats", "2", "--order-seed", "7"], cwd=ROOT, env=env,
                       capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    meta = next(ln for ln in r.stdout.splitlines() if "add-metadata" in ln and "tb-run-id=" in ln)
    assert "tb-llm-concurrency=1 16,tb-repeats=2,tb-order-seed=7," in meta
    assert sorted(meta.split("tb-only=")[1].split(",")[0].split()) == sorted(
        ["prepare", "hospital-ja@c1#r1", "hospital-ja@c1#r2", "hospital-ja@c16#r1", "hospital-ja@c16#r2"]
    )
    report = next(ln for ln in r.stdout.splitlines() if "--report-only" in ln)
    assert "--llm-concurrency 1 16 --repeats 2 --order-seed 7" in report
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert '--repeats "$REPEATS"' in vm and '${ORDER_SEED:+--order-seed "$ORDER_SEED"}' in vm
    one = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--patients", "5000", "--only", "hospital-ja"],
                         cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    assert "tb-repeats=1,tb-order-seed=none," in one.stdout  # a stale seed on the VM's metadata is overwritten
    bad = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--repeats", "0"], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=False, timeout=60)  # fmt: skip
    assert bad.returncode == 2 and "--repeats: a whole number from 1" in bad.stderr
