"""M8: the timing record sums to the wall time and the bench rows of the speed line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orchestrator.scenarios import screen_cascade

from tools import speed_rows as sr

pytestmark = pytest.mark.nodb
STAGES = {"S1": {"seconds": 120.0, "patients": 50000}, "S2b": {"seconds": 40.0, "rows": 9000}, "S3": {"seconds": 400.0}}


def test_the_record_adds_up_to_the_wall_and_names_what_it_cannot() -> None:
    rows = sr.timing_record(600.0, STAGES, 50000)
    assert [r["stage"] for r in rows] == ["S1", "S2b", "S3", "unaccounted"]
    assert sum(r["seconds"] for r in rows) == pytest.approx(600.0)
    assert rows[-1]["seconds"] == pytest.approx(40.0) and rows[1]["rows"] == 9000 and rows[2]["patients"] == 50000


def test_the_stages_explain_the_wall_within_five_percent() -> None:
    assert sr.explains_wall(sr.timing_record(565.0, STAGES, 1), 565.0)  # 25 s of 565 left over: 4.4 %
    assert not sr.explains_wall(sr.timing_record(600.0, STAGES, 1), 600.0)  # 40 s of 600: 6.7 %
    assert not sr.explains_wall(sr.timing_record(500.0, STAGES, 1), 500.0)  # a clock past the wall is a fault
    assert not sr.explains_wall([], 0.0)


def test_the_largest_stage_and_its_share() -> None:
    assert sr.largest(sr.timing_record(600.0, STAGES, 1)) == ("S3", 66.7)
    assert sr.largest([]) == ("unknown", 0.0)


def test_the_bench_rows_say_unknown_for_what_was_not_measured() -> None:
    rows = sr.timing_record(600.0, STAGES, 50000)
    got = sr.bench_rows("GZQO", 600.0, 50000, None, "unknown", rows)
    assert got == [
        "GZQO\tscreen_now_seconds=600.0",
        "GZQO\tper_1000_patients_seconds=12.0",
        "GZQO\tpeak_memory_gb=unknown",
        "GZQO\tequal_to_night=unknown",
        "GZQO\tlargest_stage=S3 share=66.7",
    ]
    assert "per_1000_patients_seconds=unknown" in sr.bench_rows("X", 0.0, 0, 1.0, "PASS", rows)[1]


def test_the_command_reads_a_timing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"ruleset": "GZQO", "wall_seconds": 565.0, "stages": STAGES}), encoding="utf-8")
    assert sr.main(["--timing", str(f), "--patients", "50000", "--peak-gb", "31.24", "--equal-to-night", "PASS"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[2] == "GZQO\tpeak_memory_gb=31.2" and json.loads(out[5])["explains_wall"] is True


def test_a_run_with_no_stage_clock_says_the_largest_stage_is_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    assert sr.main(["--wall", "300", "--ruleset", "GZQO", "--patients", "1000"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "GZQO\tper_1000_patients_seconds=300.0" and out[4] == "GZQO\tlargest_stage=unknown share=0.0"
    assert json.loads(out[5])["explains_wall"] is False


def test_the_jobs_wall_stands_in_for_the_stage_clocks_total(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"ruleset": "GZQO", "wall_seconds": 560.0, "stages": STAGES}), encoding="utf-8")
    assert sr.main(["--timing", str(f), "--wall", "700", "--patients", "50000"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "GZQO\tscreen_now_seconds=700.0" and json.loads(out[5])["explains_wall"] is False  # 140 s unnamed


def test_the_environment_switches_the_stage_clock_on_and_only_on(monkeypatch: pytest.MonkeyPatch) -> None:
    import tb_common.flags as flags

    monkeypatch.setattr(flags, "read", lambda name, url=None: "off")
    monkeypatch.delenv(screen_cascade.TIMING_ENV, raising=False)
    assert screen_cascade.screen_timing_on() is False
    monkeypatch.setenv(screen_cascade.TIMING_ENV, "off")
    assert screen_cascade.screen_timing_on() is False
    monkeypatch.setenv(screen_cascade.TIMING_ENV, "on")
    assert screen_cascade.screen_timing_on() is True
