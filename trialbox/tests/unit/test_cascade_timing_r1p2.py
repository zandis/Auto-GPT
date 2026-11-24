"""R1-P2 (lane DB, the integrator's go 7119172890): the cascade's stage clock, off by default.

* off (the default): no timing on the result, no timing file, and the traces, the stage log, the manifest, the review
  queue and the final list are byte for byte those of a run with the clock on;
* on: each stage's wall seconds, with the patients and pairs of the stages in the stage log, and the run's wall
  seconds; ``write_outputs`` adds ``cascade_timing.json`` with its own writes timed; counts and seconds only, never a
  patient;
* a SCREEN whose card is time-shared runs a judge pass and a verifier pass: their timings are summed into one;
* the flag ``screen.timing`` is declared off, never seeded from a file, and named on ``/ops/flags`` in three
  languages;
* the model servers' prefill and decode counters are read beside the others, and only when a server has them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from console import i18n_flags
from lake.client import LakeLocal
from matching.cascade import write_outputs
from orchestrator.scenarios.screen_cascade import TIMING_FLAG, merged_timing
from tb_common import flags

from tests.judge_kit import ScriptedJudge, note_lake, quoting, ruleset
from tests.unit.test_cascade_exclusion_rules import CODED, FLARE, INC, PATIENTS, SNAP, _run
from tools import run_metrics as rm

OUTPUTS = (
    "cascade_traces.jsonl",
    "review_queue.jsonl",
    "final_list.json",
    "cascade_log.jsonl",
    "cascade_manifest.json",
)
STAGES = {"S0", "S1", "S2", "S2b", "sample", "S3", "S4", "tiers", "S5"}


@pytest.fixture(scope="module")
def timed_lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    return note_lake(tmp_path_factory.mktemp("cascade-timing"), PATIENTS, SNAP, CODED)


def _go(lake: Any, **kw: Any) -> Any:
    return _run(lake, ruleset([INC]), ["P-HIT", "P-QUIET"], ScriptedJudge(quoting("pass", FLARE)), **kw)


def test_with_timing_off_every_output_is_byte_for_byte_that_of_a_timed_run(timed_lake: Any, tmp_path: Path) -> None:
    off, on = _go(timed_lake), _go(timed_lake, timing=True)
    assert off.timing is None and on.timing is not None
    a, b = write_outputs(off, tmp_path / "off"), write_outputs(on, tmp_path / "on")
    assert "timing" not in a and not (tmp_path / "off" / "cascade_timing.json").exists()
    for name in OUTPUTS:
        assert (tmp_path / "off" / name).read_bytes() == (tmp_path / "on" / name).read_bytes(), name
    assert b["timing"] == tmp_path / "on" / "cascade_timing.json"


def test_with_timing_on_each_stage_has_its_seconds_and_its_patients(timed_lake: Any, tmp_path: Path) -> None:
    res = _go(timed_lake, timing=True)
    t = res.timing
    assert set(t["stages"]) == STAGES and t["rounds"] == 1 and t["timing"] == "R1-P2"
    assert all(row["seconds"] >= 0 for row in t["stages"].values())
    log = {s.stage: s for s in res.stages}
    for stage in ("S0", "S1", "S2", "S2b", "S3", "S4", "S5"):
        row = t["stages"][stage]
        assert (row["patients_in"], row["patients_out"], row["pairs_in"]) == (
            log[stage].patients_in,
            log[stage].patients_out,
            log[stage].pairs_in,
        )
    assert "patients_in" not in t["stages"]["sample"]  # not a stage of the stage log: seconds only
    assert t["wall_seconds"] >= max(row["seconds"] for row in t["stages"].values())
    write_outputs(res, tmp_path)
    doc = json.loads((tmp_path / "cascade_timing.json").read_text(encoding="utf-8"))
    assert set(doc["stages"]) == STAGES | {"writes"} and doc["stages"]["writes"]["seconds"] >= 0
    assert "P-HIT" not in json.dumps(doc) and "P-QUIET" not in json.dumps(doc)  # counts and seconds only


def test_the_rounds_of_a_time_shared_card_are_summed_into_one_timing() -> None:
    judge = {
        "timing": "R1-P2",
        "rounds": 1,
        "wall_seconds": 10.0,
        "stages": {"S1": {"seconds": 2.0, "patients_in": 600}, "S3": {"seconds": 7.0}},
    }
    verifier = {
        "timing": "R1-P2",
        "rounds": 1,
        "wall_seconds": 5.0,
        "stages": {"S1": {"seconds": 2.0, "patients_in": 600}, "S4": {"seconds": 3.0}},
    }
    m = merged_timing([judge, verifier])
    assert m is not None and m["rounds"] == 2 and m["wall_seconds"] == 15.0
    assert m["stages"] == {"S1": {"seconds": 4.0, "patients_in": 600}, "S3": {"seconds": 7.0}, "S4": {"seconds": 3.0}}
    assert merged_timing([]) is None


def test_the_flag_is_declared_off_never_seeded_from_a_file_and_named_in_three_languages() -> None:
    d = flags.DECLARED[TIMING_FLAG]
    assert (d.values, d.default, d.seed_env) == (("off", "on"), "off", None)
    key = f"flags.desc.{TIMING_FLAG}"
    for table in (i18n_flags.EN, i18n_flags.JA, i18n_flags.ZH):
        assert table[key]


def test_the_servers_prefill_and_decode_are_read_only_when_they_have_them() -> None:
    before = "vllm:request_prefill_time_seconds_sum 1.0\nvllm:request_prefill_time_seconds_count 10\n"
    after = (
        "vllm:request_prefill_time_seconds_sum 5.0\nvllm:request_prefill_time_seconds_count 30\n"
        "vllm:request_decode_time_seconds_sum 12.0\nvllm:request_decode_time_seconds_count 20\n"
    )
    d = rm.metrics_delta(before, after)
    assert d["prefill_mean_s"] == 0.2 and d["decode_mean_s"] == 0.6
    plain = rm.metrics_delta("vllm:request_success_total 1\n", "vllm:request_success_total 3\n")
    assert "prefill_mean_s" not in plain and "decode_mean_s" not in plain  # none made up


def test_the_flag_is_read_and_a_run_publishes_its_timing_only_when_it_was_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from orchestrator.scenarios import screen_cascade

    monkeypatch.setattr(flags, "read", lambda name, url=None: None)
    assert screen_cascade.screen_timing_on() is False  # no row, or no store: off
    monkeypatch.setattr(flags, "read", lambda name, url=None: "on" if name == TIMING_FLAG else None)
    assert screen_cascade.screen_timing_on() is True
    published: list[tuple[str, bytes, str]] = []
    ctx = SimpleNamespace(publish=lambda name, body, label, to: published.append((name, body, label)))
    rs = ruleset([INC])
    assert screen_cascade.publish_timing(ctx, rs, "2026-10-05", []) is None and published == []  # off: no file
    one = {"timing": "R1-P2", "rounds": 1, "wall_seconds": 3.0, "stages": {"S0": {"seconds": 1.0, "patients_in": 2}}}
    name = screen_cascade.publish_timing(ctx, rs, "2026-10-05", [one])
    ((got, body, label),) = published
    assert got == name == f"cascade_timing_{rs.id}_v{rs.version}.json" and label == "aggregate"
    doc = json.loads(body)
    assert (doc["ruleset"], doc["snapshot"], doc["wall_seconds"], doc["stages"]["S0"]["patients_in"]) == (
        rs.id,
        "2026-10-05",
        3.0,
        2,
    )
