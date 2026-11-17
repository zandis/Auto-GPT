"""H-23 (D-1137): the size ladder's arithmetic and report shape, on made-up runs (no data, no processes)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import size_ladder as sl

ROOT = Path(__file__).resolve().parents[2]
GIB = 2**30


def _run(patients: int, ingest_s: float, feas: list[float], screen: list[float], repeat: int = 1) -> dict[str, Any]:
    """A measured run as ``measure`` + ``compact`` leave it."""
    lines = []
    for i, (f, s) in enumerate(zip(feas, screen, strict=True)):
        study = sl.study_list(len(feas))[i]
        lines.append({"i": i, "study": study, "kind": "FEAS", "state": "done", "seconds": f, "scoped": patients,
                      "model_calls": 0, "stub_s": 0.0, "rss_peak": (i + 1) * GIB // 4})  # fmt: skip
        lines.append({"i": i, "study": study, "kind": "SCREEN", "state": "done", "seconds": s, "scoped": patients - 1,
                      "model_calls": 10, "stub_s": 0.5, "rss_peak": (i + 1) * GIB // 4})  # fmt: skip
    procs = [
        {"name": "generate", "service": "-", "cap": 0, "rc": 0, "oom": False, "peak": GIB // 8, "seconds": 1.0},
        {
            "name": "ingest (nightly)",
            "service": "adapter",
            "cap": 6 * GIB,
            "rc": 0,
            "oom": False,
            "peak": 2 * GIB,
            "seconds": ingest_s,
        },
        {
            "name": "lake (rebuild, queries)",
            "service": "lake",
            "cap": 8 * GIB,
            "rc": 0,
            "oom": False,
            "peak": GIB,
            "seconds": 99.0,
        },
        {
            "name": "screen (cascade)",
            "service": "orchestrator",
            "cap": 4 * GIB,
            "rc": 0,
            "oom": False,
            "peak": GIB // 2,
            "seconds": 30.0,
        },
    ]
    gate = {
        "ok": True,
        "runs": procs,
        "numbers": {
            "ingest": {"records": patients * 31, "ok": True},
            "publish": {"seconds": 20.0},
            "screen": {"judge_calls": 7},
        },
    }
    jobs = {"orchestrator_cap": 4 * GIB, "lake_cap": 8 * GIB, "lake_peak": GIB, "lines": lines}
    return {"patients": patients, "studies": len(feas), "repeat": repeat, "gate": gate, "jobs": jobs}


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (["5000:20:2"], [sl.Rung(5000, 20, 2)]),
        (["200_000"], [sl.Rung(200_000, 1, 1)]),
        (["50,000:5"], [sl.Rung(50_000, 5, 1)]),
    ],
    ids=["full", "patients-only", "no-repeats"],
)
def test_the_plan_is_read(raw: list[str], want: list[sl.Rung]) -> None:
    assert sl.parse_plan(raw) == want


@pytest.mark.parametrize("raw", ["0:1:1", "5000:x", "5000:1:0"], ids=["zero-patients", "not-a-number", "zero-repeats"])
def test_a_bad_plan_is_refused_by_name(raw: str) -> None:
    with pytest.raises(ValueError, match=raw):
        sl.parse_plan([raw])


def test_the_studies_are_the_shipped_rulesets_cycled() -> None:
    assert sl.study_list(3) == list(sl.STUDIES[:3])
    twenty = sl.study_list(20)
    assert len(twenty) == 20 and twenty[8] == sl.STUDIES[0] and twenty[19] == sl.STUDIES[3]
    for rs in sl.STUDIES:  # each is shipped, with a site profile the test box approves
        assert (ROOT / "rulesets" / rs / "manifest.yaml").exists(), rs
        assert (ROOT / "rulesets" / "profiles" / f"{rs}.yaml").exists(), rs


def test_spread_and_rates() -> None:
    assert sl.spread([10.0, 12.0, 11.0]) == {"median": 11.0, "min": 10.0, "max": 12.0, "spread_pct": 18.2, "n": 3}
    assert sl.spread([5.0])["spread_pct"] == 0.0
    assert sl.spread([])["n"] == 0
    assert sl.per_unit_ms(30.0, 5000) == 6.0
    assert sl.per_unit_ms(1.0, 0) == 0.0
    assert sl.marks(20) == [1, 5, 20] and sl.marks(3) == [1, 3] and sl.marks(1) == [1]


def test_first_slow_is_the_first_size_over_the_factor() -> None:
    flat = {5000: (50.0, 10.0), 20000: (210.0, 10.5), 50000: (550.0, 11.0)}
    assert sl.first_slow(flat) is None
    bent = {5000: (50.0, 10.0), 20000: (220.0, 11.0), 50000: (800.0, 16.0), 100000: (2000.0, 20.0)}
    got = sl.first_slow(bent)
    assert got == {"patients": 50000, "ms_per_unit": 16.0, "lowest_smaller": 10.0, "ratio": 1.6}
    # a short stage is not judged: start-up costs dominate it
    assert sl.first_slow({1000: (1.0, 1.0), 2000: (4.0, 2.0)}) is None
    assert sl.first_slow({5000: (50.0, 10.0)}) is None


def test_stage_rows_and_the_summary() -> None:
    runs = [
        _run(5000, 100.0, [8.0] * 5, [20.0] * 5, repeat=1),
        _run(5000, 110.0, [8.0] * 5, [22.0] * 5, repeat=2),
        _run(50000, 1500.0, [80.0], [400.0]),
    ]
    rows = sl.stage_rows(runs[0])
    stages = [r["stage"] for r in rows]
    assert stages == ["generate", "ingest", "rebuild+publish", "cascade (gate, GZQO)",
                      "FEAS x1", "FEAS x5", "SCREEN x1", "SCREEN x5"]  # fmt: skip
    feas5 = next(r for r in rows if r["stage"] == "FEAS x5")
    assert feas5["seconds"] == 40.0 and feas5["units"] == 25000 and feas5["ms_per_unit"] == 1.6
    assert feas5["peak"] == 5 * GIB // 4 and feas5["cap"] == 4 * GIB and feas5["ok"]
    scr1 = next(r for r in rows if r["stage"] == "SCREEN x1")
    assert scr1["model_calls"] == 10 and scr1["stub_s"] == 0.5 and scr1["scoped"] == 4999
    ingest = next(r for r in rows if r["stage"] == "ingest")
    assert ingest["service"] == "adapter" and ingest["records"] == 155000 and ingest["ms_per_unit"] == 20.0
    assert next(r for r in rows if r["stage"] == "rebuild+publish")["seconds"] == 20.0  # the publish's own time

    s = sl.summarise(runs)
    ing = [t for t in s["table"] if t["stage"] == "ingest"]
    assert [t["patients"] for t in ing] == [5000, 50000]
    assert ing[0]["seconds"] == {"median": 105.0, "min": 100.0, "max": 110.0, "spread_pct": 9.5, "n": 2}
    assert ing[0]["ms_per_unit"] == 21.0 and ing[1]["ms_per_unit"] == 30.0
    assert s["first_slow"]["ingest"] is None  # 30 / 21 = 1.43, under the factor
    assert s["first_slow"]["SCREEN x1"]["patients"] == 50000  # 8.0 against 4.2 ms per patient-study
    assert "FEAS x5" in s["first_slow"] and s["first_slow"]["FEAS x5"] is None  # one size only
    table = sl.markdown_table(s)
    assert table.count("\n") == 2 + len(s["table"])
    assert "| 5,000 | ingest | adapter (6.00) | 105.0; 100.0-110.0; 2 | 2.00 | 21.000 per patient |" in table


def test_a_failed_job_is_shown() -> None:
    run = _run(5000, 100.0, [8.0], [20.0])
    run["jobs"]["lines"][1]["state"] = "failed"
    s = sl.summarise([run])
    assert not next(t for t in s["table"] if t["stage"] == "SCREEN x1")["ok"]
    assert "SCREEN x1 **FAILED**" in sl.markdown_table(s)


def test_the_results_file(tmp_path: Path) -> None:
    rec = _run(5000, 100.0, [8.0], [20.0])
    rec["gate"]["numbers"]["publish"]["ticks"] = ["building"] * 50
    rec["gate"]["rows"] = [{"check": "ingest.night_under_cap", "state": "pass"}]
    rec["jobs"]["tail"] = "a log tail"
    small = sl.compact(rec)
    assert "ticks" not in small["gate"]["numbers"]["publish"] and "tail" not in small["jobs"]
    assert small["gate"]["checks"] == {"ingest.night_under_cap": "pass"}
    out = tmp_path / "ladder.json"
    doc = sl.write_results(out, [small], "2026-11-17T00:00:00+00:00")
    back = json.loads(out.read_text())
    assert back == doc
    assert set(back) == {"schema", "decision", "started", "written", "machine", "studies", "runs", "summary"}
    assert back["schema"] == sl.SCHEMA and back["decision"] == "D-1137"
    assert back["machine"]["cpus"] >= 1
    assert {"table", "first_slow", "slow_factor", "slow_floor_s"} <= set(back["summary"])


def test_the_job_child_is_python() -> None:
    compile(sl.CHILD_JOBS, "<size_ladder jobs>", "exec")


def test_no_zone_no_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TB_TZ", raising=False)
    with pytest.raises(SystemExit):
        sl.main(["--plan", "10", "--work", str(tmp_path / "w"), "--results", str(tmp_path / "r.json")])
    assert not (tmp_path / "w").exists()


def test_the_marks_sort_by_number() -> None:
    s = sl.summarise([_run(5000, 100.0, [8.0] * 20, [20.0] * 20)])
    assert [t["stage"] for t in s["table"]][4:] == [
        "FEAS x1",
        "FEAS x5",
        "FEAS x20",
        "SCREEN x1",
        "SCREEN x5",
        "SCREEN x20",
    ]


def test_a_job_cut_at_the_cap_is_a_failed_row() -> None:
    run = _run(50000, 800.0, [312.0], [1.0])
    run["jobs"]["lines"] = run["jobs"]["lines"][:1]  # the FEAS line only: the SCREEN never printed
    run["jobs"].update(orchestrator_oom=True, orchestrator_rc=-9, orchestrator_s=544.6, orchestrator_peak=4 * GIB + 1)
    cut = next(r for r in sl.stage_rows(run) if r["stage"] == "SCREEN x1")
    assert cut["ok"] is False and cut["seconds"] == 232.6 and cut["peak"] == 4 * GIB + 1
    assert cut["cut"] == "GZQO: killed at the cap" and cut["units"] == 50000
    assert "SCREEN x1 **FAILED**" in sl.markdown_table(sl.summarise([run]))
    assert sl.cut_job({"orchestrator_rc": 0, "lines": []}) is None


def test_a_stage_killed_at_its_cap_is_not_judged_slow() -> None:
    fast = _run(5000, 100.0, [8.0], [20.0])
    killed = _run(50000, 1000.0, [80.0], [200.0])
    killed["gate"]["runs"][3].update(rc=-9, oom=True, seconds=3000.0)  # the cascade: 60 ms a patient, against 6
    s = sl.summarise([fast, killed])
    assert not next(t for t in s["table"] if t["stage"] == "cascade (gate, GZQO)" and t["patients"] == 50000)["ok"]
    assert s["first_slow"]["cascade (gate, GZQO)"] is None
