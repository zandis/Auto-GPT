"""Card H-36 (lane H, 2026-11-17): where a set's time went, protocol by protocol, in two stored runs of it.

``tools.public_accuracy.timing`` reads each run's driver log, progress, raw traces and SCREEN reports and puts the two
runs side by side. The runs here are made up, in the records' real shape (launch P3's ``built/gold`` and ``work/``):
synthetic trials, job ids and figures, no patient data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import timing

pytestmark = pytest.mark.nodb

TRIALS = ("NCT90000001", "NCT90000002", "NCT90000003")


def _run(root: Path, prefix: str, approve_s: float, *, cut: int = 0, extra_judge: int = 0) -> Path:
    """A made-up set: three protocols sent at 10:00:00, 10:01:00 and 10:02:00; the last ``cut`` never run."""
    d = root / prefix
    (d / "built" / "gold").mkdir(parents=True)
    (d / "work" / "screen").mkdir(parents=True)
    (d / "built" / "gold" / "ids.json").write_text(json.dumps({"set": "made"}), encoding="utf-8")
    progress: dict[str, Any] = {}
    log: list[str] = []
    traces: list[dict[str, Any]] = []
    for i, t in enumerate(TRIALS):
        rid = f"{prefix}{t}"
        if i >= len(TRIALS) - cut:
            progress[rid] = {"ruleset": rid, "attempt": 1, "outcome": "not_run_time_budget", "finished": True}
            continue
        ids = {typ: f"{prefix}-{typ}-{i}" for typ in timing.TYPES}
        progress[rid] = {
            "ruleset": rid,
            "feas_job": ids["FEAS"],
            "approve_job": ids["APPROVE"],
            "screen_job": ids["SCREEN"],
            "outcome": "screened",
            "screen_metrics": {"llm_calls": 2, "tokens_in": 500, "tokens_out": 50, "wall_seconds": 5.0},
        }
        for typ, wall in (("FEAS", 30.0), ("APPROVE", approve_s), ("SCREEN", 5.0)):
            log.append(f"+ mail-gateway onbox send 10:0{i}:00")
            log.append(json.dumps({"folder": "Processed", "action": "job", "job": ids[typ], "reason": ""}))
            log.append(f"+ mail-gateway onbox wait 10:0{i}:01")
            log.append(f"job {ids[typ]} compiling")
            log.append(
                json.dumps(
                    {
                        "job": ids[typ],
                        "type": typ,
                        "ruleset": rid.upper(),
                        "state": "done",
                        "metrics": {"llm_calls": 0, "wall_seconds": wall},
                        "waited": "ended",
                    }
                )
            )
        for prompt, job, alias in (
            ("ir_extract@4", "FEAS", "j-workhorse"),
            ("concept_map@2", "FEAS", "j-workhorse"),
            ("judge@5", "SCREEN", "j-workhorse"),
            ("judge@5", "SCREEN", "v-verifier"),
        ):
            traces.append(
                {
                    "attributes": {
                        "tb.prompt": prompt,
                        "tb.model_alias": alias,
                        "tb.study_id": ids[job],
                        "tb.cache": "miss",
                    },
                    "prompt": [{"role": "user", "content": "made up"}],
                }
            )
        for _ in range(extra_judge):  # a schema repair: its prompt holds an earlier answer
            traces.append(
                {
                    "attributes": {
                        "tb.prompt": "judge@5",
                        "tb.model_alias": "j-workhorse",
                        "tb.study_id": ids["SCREEN"],
                        "tb.cache": "hit",
                    },
                    "prompt": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "{}"}],
                }
            )
        screen = {
            "cascade": {
                "metrics": {"pairs_judged": {"S3": 1, "S4": 0}},
                "judged_store": {"on": True, "read": 0, "live": 2},
            }
        }
        (d / "work" / "screen" / f"{rid}.json").write_text(json.dumps(screen), encoding="utf-8")
    (d / "work" / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    (d / "work" / "box-calls.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    (d / "work" / "raw-traces.json").write_text(
        json.dumps({"since": "x", "calls": len(traces), "traces": traces}), encoding="utf-8"
    )
    return d


def test_trial_drops_the_runs_prefix() -> None:
    assert timing.trial("Sm4NCT00002897") == "NCT00002897"
    assert timing.trial("Gm3TCGA-BRCA") == "TCGA-BRCA"
    assert timing.trial("Mm4JMED-DM") == "JMED-DM"


def test_two_runs_side_by_side(tmp_path: Path) -> None:
    before = _run(tmp_path, "Sm3", approve_s=30.0)
    after = _run(tmp_path, "Sm4", approve_s=70.0, cut=1, extra_judge=1)
    r = timing.compare(before, after)
    assert r["protocols_both"] == 2
    assert [row["trial"] for row in r["rows"]] == list(TRIALS[:2])
    t = r["totals"]
    assert t["wall_APPROVE"] == {"before": 60.0, "after": 140.0}
    assert t["wall_FEAS"] == {"before": 60.0, "after": 60.0}
    assert t["calls_judge"] == {"before": 4.0, "after": 6.0}
    assert t["calls_judge:v-verifier"] == {"before": 2.0, "after": 2.0}
    assert t["calls_repair"] == {"before": 0.0, "after": 2.0}
    assert t["calls_cache_hit"] == {"before": 0.0, "after": 2.0}
    assert t["tokens_in"] == {"before": 1000.0, "after": 1000.0}
    assert t["store_live"] == {"before": 4.0, "after": 4.0}
    assert r["difference_quantiles_s"]["APPROVE"]["median"] == 40.0
    assert r["difference_quantiles_s"]["SCREEN"]["max"] == 0.0
    assert r["cut"] == {"before": [], "after": ["NCT90000003"]}
    assert r["order"]["before"] == list(TRIALS)
    assert r["after_cut_is_before_tail"] is True


def test_in_flight_counts_overlapping_jobs(tmp_path: Path) -> None:
    d = _run(tmp_path, "Sm4", approve_s=150.0)
    f = timing.in_flight(d)
    # three approvals of 150 s sent a minute apart: 2 overlap from 10:01 to 10:02:30, 3 from 10:02 to 10:02:30
    assert f["span_s"] == 270
    assert f["approve_share"]["3+"] == round(100 * 30 / 270)
    assert f["mean"]["APPROVE"] == round(450 / 270, 2)


def test_main_writes_json_and_refuses_an_unknown_set(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = _run(tmp_path, "Sm3", approve_s=30.0)
    after = _run(tmp_path, "Sm4", approve_s=70.0)
    out = tmp_path / "t.json"
    assert timing.main([str(before), str(after), "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["protocols_both"] == 3
    assert "It says where the time is, not why" in capsys.readouterr().out
    assert timing.main([str(before), str(after), "--set", "other"]) == 2
