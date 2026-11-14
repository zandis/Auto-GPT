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
from orchestrator.scenarios import microbatch, screen
from tb_common.config import ConfigError, load_env

from tests.unit.test_microbatch_cadence import FRI, _Box, _new, _pool_row

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


# ------------------------------------------------------------------------------------------- review of D-646
def test_an_allowance_too_small_to_keep_a_place_says_so_and_not_that_the_setting_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quarter of 3 is no whole place: nothing is kept, and the summary must not blame a setting of 0."""
    box = _box(pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=[_new("X1", None), _new("X2", None)],
               excluded_at_screen=("X1", "X2"), budget=3)  # fmt: skip
    out = box.go(monkeypatch)
    ev = box.budget_event()
    assert (ev["excluded_kept"], ev["excluded_percent"], ev["excluded_full_pass_runs"]) == (0, 25, None)
    assert "is 0" not in out.summary_md and "too small to keep a place" in out.summary_md


def test_a_resumed_job_keeps_the_places_its_first_run_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """The count is of the pool's stored tiers, which the job's own re-check rewrites: counted again on a resume
    it kept another number, and the resumed job re-checked other patients (D-642, D-458: the same list)."""
    scope = [_new("P1", FRI), _new("X1", None)]
    first = _box(50, pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=scope, excluded_at_screen=("X1",), budget=4)
    first.go(monkeypatch)
    assert first.job.options["excluded_kept"] == "1" and first.evaluated == [["P1", "P2", "P3"]]
    resumed = _box(50, pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=scope, excluded_at_screen=("X1",),
                   budget=4, options=dict(first.job.options))  # fmt: skip
    resumed.pool[0] = _pool_row("P1") | {"tier": "excluded"}  # as the first run's re-check could have left it
    resumed.go(monkeypatch)
    assert resumed.evaluated == first.evaluated and resumed.budget_event()["excluded_kept"] == 1


def test_the_full_pass_figure_is_left_out_where_the_count_behind_it_is_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The summary is an aggregate output: "a full pass takes 3 runs" at one place a run says three are in scope."""
    from tb_common import smallcell

    box = _box(pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=[_new(f"X{i}", None) for i in range(3)],
               excluded_at_screen=("X0", "X1", "X2"), budget=4)  # fmt: skip
    monkeypatch.setattr(microbatch, "suppress", lambda n, cell: smallcell.suppress(n, 5))
    out = box.go(monkeypatch)
    assert "in scope" in out.summary_md and "weekly runs" not in out.summary_md
    assert box.budget_event()["excluded_full_pass_runs"] == 3  # the audit keeps the figure


def test_the_weekly_run_hands_the_screen_the_scope_it_counted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _box(pool=["P1"], booked={}, scope=[_new("X1", None)], excluded_at_screen=("X1",), budget=4)
    box.go(monkeypatch)
    assert [s.pid for s in box.scope_given] == ["X1"]


def test_a_screen_given_its_scope_does_not_ask_the_lake_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real seam: ``screen_scope`` is the scope query with the register applied, and ``run_screen(scope=...)``
    takes it as it is."""
    from types import SimpleNamespace

    from tests.unit.test_microbatch_cadence import GZQO, WED

    asked: list[str] = []

    def lake(*a: Any) -> list[Any]:
        asked.append("lake")
        return [_new("A", None), _new("B", None)]

    ctx = SimpleNamespace(job=SimpleNamespace(options={}), metrics=lambda **kw: None)
    monkeypatch.setattr(screen, "practitioners_of", lambda ctx, rs: ["D1"])
    monkeypatch.setattr(screen, "scope_patients", lake)
    monkeypatch.setattr(screen, "drop_opted_out", lambda ctx, scoped: [s for s in scoped if s.pid != "B"])
    monkeypatch.setattr(screen, "judge_for", lambda ctx, rs: None)
    got = screen.screen_scope(ctx, GZQO, WED, "2026-10-06")  # type: ignore[arg-type]
    assert [s.pid for s in got] == ["A"] and asked == ["lake"]
    seen: list[list[str]] = []

    def nobody(scoped: list[Any]) -> list[Any]:
        seen.append([s.pid for s in scoped])
        return []

    screen.run_screen(ctx, GZQO, WED, "2026-10-06", select=nobody, scope=got)  # type: ignore[arg-type]
    assert seen == [["A"]] and asked == ["lake"]  # the scope as handed in; no second query
    screen.run_screen(ctx, GZQO, WED, "2026-10-06", select=nobody)  # type: ignore[arg-type]
    assert seen == [["A"], ["A"]] and asked == ["lake", "lake"]  # without it: asked, and the register applied


# ------------------------------------------------------------------------------- the full-pass figure (lane C2's finding)
class _SomeTurnExcluded(_Box):
    """A box whose re-check finds an exclusion criterion failing for ``turn``: those pool rows are excluded as the
    run leaves them, so they wait with the excluded patients, though nobody had counted them before the run."""

    turn: tuple[str, ...] = ()

    def evaluate_scope(self, ctx: Any, rs: Any, run_date: Any, snap: str, scoped: list[Any], **kw: Any) -> Any:
        from orchestrator.scenarios.evaluate import PatientVerdicts
        from tb_contracts import CriterionVerdict, Evidence

        from tests.unit.test_microbatch_cadence import GZQO

        cid = next(c.id for c in GZQO.active() if c.class_ == "structured" and c.kind == "exclusion")
        self.evaluated.append([s.pid for s in scoped])
        out = {}
        for s in scoped:
            fails = [CriterionVerdict(id=cid, verdict="fail", evidence=Evidence(resource_refs=["Condition/c1"]))]
            out[s.pid] = PatientVerdicts(s.pid, fails if s.pid in self.turn else [], "excluded", [], 0)
        return out


def _turned(before: int, turn: int) -> _SomeTurnExcluded:
    """Allowance 40 (a quarter is 10 places); ``before`` excluded patients counted at the start, ``turn`` pool
    patients that the run's own re-check excludes."""
    pool = [f"P{i:02d}" for i in range(20)]
    new = [_new(f"N{i:02d}", FRI) for i in range(30)]
    old = tuple(f"X{i}" for i in range(before))
    box = _SomeTurnExcluded(
        pool=pool, booked=dict.fromkeys(pool, FRI), budget=40, excluded_at_screen=old,
        scope=[*new, *(_new(x, None) for x in old), *(_new(p, FRI) for p in pool[:turn])],
    )  # fmt: skip
    box.turn = tuple(pool[:turn])
    return box


def test_the_full_pass_figure_is_never_one_run_while_somebody_is_carried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lane C2's finding: the figure came from the nominal share (a quarter of 40 is 10) and the five in scope,
    so it said "1 run" while three of the five were carried: two were kept places for (the two counted before the
    run), three more became excluded by the run's own re-check."""
    box = _turned(2, 3)
    out = box.go(monkeypatch)
    ev = box.budget_event()
    assert (ev["excluded_kept"], ev["excluded_in_scope"], ev["excluded_rescreened"], ev["excluded_carried"]) == (
        2,
        5,
        2,
        3,
    )
    # the next run counts all five at its start and keeps five places: the pass ends in the second run
    assert ev["excluded_full_pass_runs"] == 2
    assert "a full pass takes 2 weekly runs" in out.summary_md


def test_the_full_pass_figure_is_what_a_run_keeps_once_they_are_counted_not_what_tonight_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The review of the first fix: divided by tonight's kept places it said "7 runs" for seven in scope with one
    kept, where the next run keeps seven; and at a small-cell threshold of 5 the figure 3 beside "5 in scope" gave
    away that exactly two had been counted before the run."""
    from tb_common import smallcell

    box = _turned(1, 6)
    out = box.go(monkeypatch)
    ev = box.budget_event()
    assert (ev["excluded_kept"], ev["excluded_in_scope"], ev["excluded_carried"]) == (1, 7, 6)
    assert ev["excluded_full_pass_runs"] == 2 and "a full pass takes 2 weekly runs" in out.summary_md
    box = _turned(2, 3)
    monkeypatch.setattr(microbatch, "suppress", lambda n, cell: smallcell.suppress(n, 5))
    out = box.go(monkeypatch)
    assert "<5 of 5 in scope" in out.summary_md and "a full pass takes 2 weekly runs" in out.summary_md
    assert "none was counted" not in out.summary_md


def test_the_full_pass_figure_follows_from_how_the_night_went(monkeypatch: pytest.MonkeyPatch) -> None:
    # nobody in scope: there is no pass to speak of
    box = _box(pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=[], excluded_at_screen=("X-GONE",), budget=4)
    box.go(monkeypatch)
    assert box.budget_event()["excluded_full_pass_runs"] is None
    # nobody carried: the pass was made tonight, whatever the share (also a share of 0, with room left over)
    box = _box(0, pool=["P1"], booked={}, scope=[_new("X1", None)], excluded_at_screen=("X1",), budget=4)
    box.go(monkeypatch)
    ev = box.budget_event()
    assert (ev["excluded_rescreened"], ev["excluded_carried"], ev["excluded_full_pass_runs"]) == (1, 0, 1)
    # three in scope, one place kept, and the others left room for all three: one run, as the figures beside it say
    xs = [_new(f"X{i}", None) for i in range(3)]
    box = _box(pool=["P1"], booked={}, scope=xs, excluded_at_screen=("X0", "X1", "X2"), budget=4)
    box.go(monkeypatch)
    ev = box.budget_event()
    assert (ev["excluded_kept"], ev["excluded_rescreened"], ev["excluded_carried"]) == (1, 3, 0)
    assert ev["excluded_full_pass_runs"] == 1
    # somebody carried and no share kept: no run is sure to reach them
    box = _box(0, pool=POOL, booked=dict.fromkeys(POOL, FRI), scope=xs, excluded_at_screen=("X0", "X1", "X2"), budget=4)
    box.go(monkeypatch)
    ev = box.budget_event()
    assert ev["excluded_carried"] > 0 and ev["excluded_full_pass_runs"] is None
