"""OPT-1 §6 item 2: the night report and the run ledger (the night's audit event) say how long each stage took and how much memory the process
had peaked at when it ended, so a slowdown or a memory climb is seen on the night it happens (prof16 had to wrap 32
phases by hand to find it). Names, seconds and megabytes only. Synthetic data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest
from adapter.stage_times import Stages

from tests.unit.test_dataflow_lake_p0 import _cfg, _Lakes
from tests.unit.test_night_runs import _feed


@pytest.mark.nodb
def test_each_stage_is_timed_and_a_stage_entered_twice_adds_up() -> None:
    now, rss = [0.0], iter([100.0, 250.5, 250.5, 400.0])
    at = Stages("start", clock=lambda: now[0], rss=lambda: next(rss))
    now[0] = 1.0
    at["step"] = "read"
    now[0] = 11.0
    at["step"] = "delta check"
    now[0] = 12.0
    at["step"] = "read"  # entered again: adds to its first 10 s
    now[0] = 14.5
    at["table"] = "lab"  # not a stage: nothing closes
    assert at == {"step": "read", "table": "lab"}
    assert at.summary() == {
        "start": {"seconds": 1.0, "peak_rss_mb": 100.0},
        "read": {"seconds": 12.5, "peak_rss_mb": 400.0},
        "delta check": {"seconds": 1.0, "peak_rss_mb": 250.5},
    }


@pytest.mark.nodb
def test_a_platform_that_cannot_say_its_memory_gives_none_never_zero() -> None:
    at = Stages("start", clock=iter([0.0, 2.0]).__next__, rss=lambda: None)
    assert at.summary() == {"start": {"seconds": 2.0, "peak_rss_mb": None}}


def test_the_night_report_and_the_ledger_carry_the_stages(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    rep = run_ingest(cfg, "csv", _feed(tmp_path / "f"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed and rep.stages is not None
    assert {"read", "validate", "report"} <= set(rep.stages)
    assert all(s.seconds >= 0 and (s.peak_rss_mb or 0) > 0 for s in rep.stages.values())  # Linux: memory is known
    rss = [s.peak_rss_mb for s in rep.stages.values() if s.peak_rss_mb is not None]
    assert max(rss) == rep.stages["report"].peak_rss_mb  # a high-water mark: the last stage holds the peak
    written = json.loads((snapshot_dir(cfg.lake_dir, "2026-10-01") / "ingest_report.json").read_text("utf-8"))
    assert set(written["stages"]["read"]) == {"seconds", "peak_rss_mb"}  # no other key: nothing from a row
    events = [
        json.loads(x) for f in sorted((tmp_path / "audit").glob("*.jsonl")) for x in f.read_text("utf-8").splitlines()
    ]
    (done,) = [e for e in events if e["event"] == "ingest.done"]
    assert done["detail"]["stages"] == written["stages"]  # the run ledger says what the report says
