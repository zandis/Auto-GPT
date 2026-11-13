"""A share of a study's night allowance is kept for its excluded patients (D-646; the owner's ruling of 2026-11-13).

D-642 screens excluded patients again after the re-checks and the new patients, inside the night budget. Measured
(the weekly load of D-642): when the pool's re-checks and the new patients fill a study's allowance, the excluded
patients are never reached. ``TB_MICROBATCH_EXCLUDED_PERCENT`` (default 25) of the job's allowance is kept for them:
only as much as there are excluded patients in scope, so nothing is held back for nobody.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from orchestrator.scenarios import microbatch
from tb_common.config import ConfigError, load_env

from tests.unit.test_microbatch_cadence import FRI, _Box, _new

POOL = ["P1", "P2", "P3", "P4"]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    monkeypatch.delenv("TB_SCREEN_JUDGE", raising=False)


def _box(percent: int | None = None, **kw: Any) -> _Box:
    box = _Box(**kw)
    if percent is not None:
        box.ctx.cfg.env.microbatch_excluded_percent = percent
    return box


def test_re_checks_that_fill_the_allowance_no_longer_starve_the_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _box(pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=[_new("X1", None), _new("X2", None)],
               excluded_at_screen=("X1", "X2"), budget=4)  # fmt: skip
    out = box.go(monkeypatch)
    assert box.evaluated == [["P1", "P2", "P3"]]  # three of the four re-checks: one place is kept
    assert box.screened == ["X1"]
    ev = box.budget_event()
    assert (ev["recheck_carried"], ev["excluded_rescreened"], ev["excluded_carried"]) == (1, 1, 1)
    assert (ev["excluded_kept"], ev["excluded_in_scope"], ev["excluded_percent"]) == (1, 2, 25)
    assert ev["excluded_full_pass_runs"] == 2  # two in scope, one place a run
    assert "screened again: 1 of 2 in scope" in out.summary_md and "2 weekly runs" in out.summary_md
    assert box.job.metrics.patients_scoped == 4  # the allowance is spent, not exceeded


def test_new_patients_that_fill_the_allowance_do_not_starve_them_either(monkeypatch: pytest.MonkeyPatch) -> None:
    new = [_new(f"N{i}", FRI) for i in range(6)]
    box = _box(pool=["P1"], booked={}, scope=[*new, _new("X1", None)], excluded_at_screen=("X1",), budget=4)
    box.go(monkeypatch)
    assert box.screened == ["N0", "N1", "N2", "X1"]
    ev = box.budget_event()
    assert (ev["new_screened"], ev["new_carried"], ev["excluded_rescreened"]) == (3, 3, 1)


def test_nothing_is_kept_when_no_excluded_patient_is_in_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _box(pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=[], excluded_at_screen=("X-GONE",), budget=4)
    box.go(monkeypatch)
    assert box.evaluated == [POOL]  # X-GONE left the scope: the re-checks have the whole allowance
    ev = box.budget_event()
    assert (ev["excluded_kept"], ev["excluded_in_scope"], ev["recheck_carried"]) == (0, 0, 0)


def test_no_more_is_kept_than_there_are_excluded_patients(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = [f"P{i}" for i in range(8)]
    box = _box(pool=pool, booked=dict.fromkeys(pool, FRI), scope=[_new("X1", None)], excluded_at_screen=("X1",),
               budget=8)  # fmt: skip
    box.go(monkeypatch)
    assert len(box.evaluated[0]) == 7 and box.screened == ["X1"]  # a quarter of 8 is 2; one is in scope: 1 kept


def test_a_place_the_excluded_do_not_use_goes_to_a_waiting_new_patient(monkeypatch: pytest.MonkeyPatch) -> None:
    """The count before the run is of the stored lists; the run's own re-check can take one off it. A place kept
    and then not needed is not left idle while a new patient waits."""
    new = [_new(f"N{i}", FRI) for i in range(6)]
    box = _box(pool=["P1"], booked={}, scope=[*new, _new("X1", None)], excluded_at_screen=("X1",), budget=4)
    seen = microbatch.read_sources

    def gone_since(ctx: Any, keys: list[str]) -> Any:  # the second reading (inside the screen) no longer has X1
        gone_since.calls += 1  # type: ignore[attr-defined]
        src = seen(ctx, keys)
        if gone_since.calls > 1:  # type: ignore[attr-defined]
            src.excluded.discard("X1")
        return src

    gone_since.calls = 0  # type: ignore[attr-defined]
    monkeypatch.setattr(microbatch, "read_sources", gone_since)
    box.go(monkeypatch)
    assert len(box.screened) == 4  # X1 now reads as new, or its place goes to N3: four screened, none idle


@pytest.mark.parametrize("percent", [0])
def test_a_share_of_zero_is_the_order_of_d642(monkeypatch: pytest.MonkeyPatch, percent: int) -> None:
    box = _box(percent, pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=[_new("X1", None)],
               excluded_at_screen=("X1",), budget=4)  # fmt: skip
    box.go(monkeypatch)
    assert box.evaluated == [POOL] and box.screened == []
    assert box.budget_event()["excluded_full_pass_runs"] is None  # nothing kept: no run reaches them for sure


def test_without_a_night_budget_everybody_is_reached_in_one_run(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _box(pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=[_new("X1", None), _new("X2", None)],
               excluded_at_screen=("X1", "X2"), budget=0)  # fmt: skip
    box.go(monkeypatch)
    assert box.evaluated == [POOL] and box.screened == ["X1", "X2"]
    assert box.budget_event()["excluded_full_pass_runs"] == 1


def test_the_after_ingest_run_keeps_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    new = [_new(f"N{i}", FRI) for i in range(6)]
    box = _box(pool=["P1"], booked={}, scope=[*new, _new("X1", None)], excluded_at_screen=("X1",), budget=4,
               options={"trigger": "ingest"})  # fmt: skip
    box.go(monkeypatch)
    assert box.screened == ["N0", "N1", "N2", "N3"]  # it brings nobody back (D-642), so it keeps no place


def test_the_setting_is_a_declared_percentage() -> None:
    none = Path("/nonexistent")
    assert load_env(dotenv=none, environ={}).microbatch_excluded_percent == 25
    assert load_env(dotenv=none, environ={"TB_MICROBATCH_EXCLUDED_PERCENT": "40"}).microbatch_excluded_percent == 40
    for bad in ("-1", "101"):
        with pytest.raises(ConfigError, match="TB_MICROBATCH_EXCLUDED_PERCENT"):
            load_env(dotenv=none, environ={"TB_MICROBATCH_EXCLUDED_PERCENT": bad})
    json.dumps(microbatch.DEFAULT_EXCLUDED_PERCENT)  # the scenario's own default exists and is the config's
    assert microbatch.DEFAULT_EXCLUDED_PERCENT == 25
