"""NEW-LIFE-3 and NEW-LIFE-4 (D-642; deep review 2026-11-12, LIFE-003 and LIFE-004): the weekly run re-checks by
rule, not by a model's flag, and excluded patients come back.

* LIFE-003: the weekly re-check re-evaluated only the criteria the model had flagged ``time_sensitive``. RA-JAK has
  none, so its re-check evaluated nothing: a pool patient with sepsis last week stayed on the clinic list. Every
  structured or mixed criterion is now re-checked (the compiled SQL decides them), and a flagged note criterion.
* LIFE-004: a patient a SCREEN (or an earlier weekly run) excluded was never looked at again until a person ran
  SCREEN. The weekly run now screens them again while they are in the study's scope: after the re-checks and the
  new patients, inside the night budget, the one looked at longest ago first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from orchestrator.scenarios import microbatch
from orchestrator.scenarios.evaluate import PatientVerdicts
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence

from tests.unit.test_microbatch_cadence import FRI, GZQO, WED, _Box, _new, _verdicts

ROOT = Path(__file__).resolve().parents[2]
RECORD = "new_screened_GZQO_v" + GZQO.version + ".json"
THU = "2026-10-08T09:00:00+09:00"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    monkeypatch.delenv("TB_SCREEN_JUDGE", raising=False)


# ------------------------------------------------------------------------------------------------ LIFE-003
@pytest.mark.parametrize("rid", ["RA-JAK", "GZQO", "AD-MAB", "RA-BIO"])
def test_every_criterion_the_sql_decides_is_re_checked_whatever_the_models_flag(rid: str) -> None:
    rs = Ruleset.load(ROOT / "rulesets" / rid)
    ids = microbatch.recheck_ids(rs)
    coded = {c.id for c in rs.active() if c.class_ in ("structured", "mixed") and c.kind in ("inclusion", "exclusion")}
    flagged = {c.id for c in rs.active() if c.time_sensitive and c.kind in ("inclusion", "exclusion")}
    assert coded and coded <= ids and flagged <= ids
    assert ids <= coded | flagged  # a note or human criterion nobody flagged is not asked again every week


def test_ra_jak_has_no_flag_and_its_re_check_is_not_empty() -> None:
    """The review's case: all 16 RA-JAK criteria carry ``time_sensitive: false``, "serious infection in the last 30
    days" among them."""
    rs = Ruleset.load(ROOT / "rulesets" / "RA-JAK")
    assert not any(c.time_sensitive for c in rs.active())
    infection = [c.id for c in rs.active() if "Serious infection" in c.text and c.kind == "exclusion"]
    assert infection == ["RA-JAK-EXC-05"] and "RA-JAK-EXC-05" in microbatch.recheck_ids(rs)


class _Changing(_Box):
    """A box whose re-check finds ``fails`` now failing for every re-checked patient."""

    fails: tuple[str, ...] = ()

    def evaluate_scope(self, ctx: Any, rs: Any, run_date: Any, snap: str, scoped: list[Any], **kw: Any) -> Any:
        self.only = set(kw["only"])
        self.evaluated.append([s.pid for s in scoped])
        fresh = [
            CriterionVerdict(id=cid, verdict="fail", evidence=Evidence(resource_refs=["Condition/c1"]))
            for cid in self.fails
        ]
        return {s.pid: PatientVerdicts(s.pid, fresh, "excluded", [], 0) for s in scoped}


def test_a_new_coded_exclusion_takes_a_pool_patient_off_the_weeks_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """A criterion the model did not flag: its new answer is a change on the weekly list and the row is excluded."""
    unflagged = next(
        c.id for c in GZQO.active() if c.class_ == "structured" and c.kind == "exclusion" and not c.time_sensitive
    )
    box = _Changing(pool=["P1"], booked={"P1": FRI}, scope=[])
    box.fails = (unflagged,)
    out = box.go(monkeypatch)
    assert unflagged in box.only and box.evaluated == [["P1"]]
    cl = json.loads(box.published["candidate_list_GZQO_v" + GZQO.version + ".json"])
    assert cl["rows"] == [] and cl["summary"]["excluded"] == 1  # no longer listed
    assert "Verdict changes: 1" in out.summary_md and "time-sensitive" not in out.summary_md


# ------------------------------------------------------------------------------------------------ LIFE-004
def test_a_patient_excluded_at_screen_and_still_in_scope_is_screened_again(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _Box(
        pool=["P-POOL"],
        booked={},
        scope=[_new("P-POOL", None), _new("X-IN", FRI), _new("N-NEW", FRI)],
        excluded_at_screen=("X-IN", "X-GONE"),  # X-GONE left the scope: nobody screens it
    )
    out = box.go(monkeypatch)
    assert box.screened == ["N-NEW", "X-IN"]  # the new patient first, then the one who comes back
    assert "X-IN" in box.persisted  # listed again: in the pool
    record = json.loads(box.published[RECORD])
    assert record["pids"] == ["N-NEW", "X-IN"] and record["again"] == {"X-IN": WED.isoformat()}
    ev = box.budget_event()
    assert (ev["excluded_rescreened"], ev["excluded_back"], ev["excluded_carried"]) == (1, 1, 0)
    assert "excluded patients screened again: 1" in out.summary_md and "back on the list: 1" in out.summary_md
    assert box.delivered == [["N-NEW", "X-IN"]]  # both have a visit in the window: on the week's list


def test_a_patient_an_earlier_weekly_run_excluded_comes_back_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """In the earlier record and not in the pool: that run screened and excluded it."""
    box = _Box(pool=["P-POOL"], booked={}, scope=[_new("P-A", FRI), _new("P-POOL", None)])
    box.store["k-prev"] = json.dumps({"pids": ["P-A", "P-POOL"]}).encode()
    box.job.options = {"seen_from": "k-excl,k-prev"}
    box.go(monkeypatch)
    assert box.screened == ["P-A"]  # P-POOL is in the pool: re-checked there, not screened again


def test_the_night_budget_holds_and_the_one_looked_at_longest_ago_goes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    excluded = ("X1", "X2", "X3")
    box = _Box(
        pool=["P1"],
        booked={"P1": FRI},
        scope=[_new("N0", FRI), *(_new(x, None) for x in excluded)],
        excluded_at_screen=excluded,
        budget=4,
    )
    box.store["k-prev"] = json.dumps({"pids": ["X1"], "again": {"X1": "2026-09-30", "X3": "2026-09-23"}}).encode()
    box.job.options = {"seen_from": "k-excl,k-prev"}
    out = box.go(monkeypatch)
    assert box.evaluated == [["P1"]]  # the re-check first
    assert box.screened == ["N0", "X2", "X3"]  # then the new one; then never looked at again, then the oldest look
    ev = box.budget_event()
    assert ev["excluded_rescreened"] == 2 and ev["excluded_carried"] == 1 and ev["new_carried"] == 0
    record = json.loads(box.published[RECORD])
    assert record["again"] == {"X1": "2026-09-30", "X2": WED.isoformat(), "X3": WED.isoformat()}
    assert "1 excluded patients carried over" in out.summary_md
    assert box.job.metrics.patients_scoped == 4


def test_after_an_ingest_and_with_incident_0_nobody_comes_back(monkeypatch: pytest.MonkeyPatch) -> None:
    for options in ({"trigger": "ingest"}, {"incident": "0"}):
        box = _Box(pool=["P1"], booked={}, scope=[_new("X1", FRI)], excluded_at_screen=("X1",), options=options)
        box.go(monkeypatch)
        assert box.screened == []


def test_one_who_stays_excluded_is_not_listed_and_is_recorded_as_looked_at(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StillOut(_Box):
        def run_screen(self, ctx: Any, rs: Any, run_date: Any, snapshot: str, select: Any = None) -> Any:
            got = super().run_screen(ctx, rs, run_date, snapshot, select)
            got.rows = [r.model_copy(update={"tier": "excluded"}) for r in got.rows]
            return got

    box = _StillOut(pool=["P1"], booked={}, scope=[_new("X1", FRI)], excluded_at_screen=("X1",))
    out = box.go(monkeypatch)
    assert box.screened == ["X1"] and "X1" not in box.persisted
    assert json.loads(box.published[RECORD])["again"] == {"X1": WED.isoformat()}
    assert "back on the list: 0" in out.summary_md and box.budget_event()["excluded_back"] == 0


def test_a_resumed_job_screens_again_the_one_it_brought_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """As for its own new patients (D-397): the row this job wrote for a patient SCREEN had excluded is not the
    pool's, so a resumed job and a re-run make the same list."""
    from datetime import timedelta

    from tests.unit.test_microbatch_cadence import RECEIVED, _pool_row

    box = _Box(
        pool=["P1"], booked={}, scope=[_new("X1", FRI)], excluded_at_screen=("X1",),
        options={"seen_from": "k-excl", "night_left": "-1"},
    )  # fmt: skip
    box.pool.append(_pool_row("X1") | {"job_id": "J-MB", "added_at": (RECEIVED + timedelta(minutes=5)).isoformat()})
    box.go(monkeypatch)
    assert box.screened == ["X1"]


def test_the_stand_in_verdicts_of_this_file_are_the_cadence_tests_own() -> None:
    assert {v.id for v in _verdicts()} == {c.id for c in GZQO.active()}


# ------------------------------------------------------------------------------------------------ review of #422
def test_a_resumed_job_of_a_later_week_also_screens_again_the_one_it_brought_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M1: after one weekly run screened X1 again, X1 is in the record's ``pids``; the next week's job, resumed
    after it wrote X1's pool row, counted that row as the pool's: nobody "came back", ``again`` kept the old day."""
    from datetime import timedelta

    from tests.unit.test_microbatch_cadence import RECEIVED, _pool_row

    def box() -> _Box:
        b = _Box(pool=["P1"], booked={}, scope=[_new("X1", FRI)], excluded_at_screen=("X1",),
                 options={"seen_from": "k-excl,k-prev", "night_left": "-1"})  # fmt: skip
        b.store["k-prev"] = json.dumps({"pids": ["X1"], "again": {"X1": "2026-09-30"}, "out": ["X1"]}).encode()
        return b

    first = box()
    first.go(monkeypatch)
    resumed = box()
    resumed.pool.append(_pool_row("X1") | {"job_id": "J-MB", "added_at": (RECEIVED + timedelta(minutes=5)).isoformat()})
    resumed.go(monkeypatch)
    assert first.screened == resumed.screened == ["X1"]
    record = json.loads(resumed.published[RECORD])
    assert record["again"] == {"X1": WED.isoformat()} and record["out"] == []  # listed now: no longer out
    assert resumed.budget_event()["excluded_back"] == first.budget_event()["excluded_back"] == 1


def test_the_record_says_whom_the_weekly_run_did_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    class _HalfOut(_Box):
        def run_screen(self, ctx: Any, rs: Any, run_date: Any, snapshot: str, select: Any = None) -> Any:
            got = super().run_screen(ctx, rs, run_date, snapshot, select)
            got.rows = [r.model_copy(update={"tier": "excluded"}) if r.pid != "N1" else r for r in got.rows]
            return got

    box = _HalfOut(pool=["P1"], booked={}, scope=[_new("N1", FRI), _new("N2", FRI), _new("X1", FRI)],
                   excluded_at_screen=("X1",))  # fmt: skip
    box.go(monkeypatch)
    record = json.loads(box.published[RECORD])
    assert record["pids"] == ["N1", "N2", "X1"] and record["out"] == ["N2", "X1"]


class _NotAsked(_Box):
    """A box whose re-check could not ask the model: ``cid`` comes back unknown with ``reason``."""

    cid = ""
    reason = "not_evaluated"

    def evaluate_scope(self, ctx: Any, rs: Any, run_date: Any, snap: str, scoped: list[Any], **kw: Any) -> Any:
        self.evaluated.append([s.pid for s in scoped])
        fresh = [
            CriterionVerdict(id=self.cid, verdict="unknown", evidence=Evidence(resource_refs=[], reason=self.reason))
        ]
        return {s.pid: PatientVerdicts(s.pid, fresh, "review", [], 1) for s in scoped}


@pytest.mark.parametrize("reason", ["not_evaluated", "model_down"])
def test_a_model_that_was_not_asked_does_not_replace_a_stored_answer(
    monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    """M2: every mixed criterion is now re-checked, and one the codes do not settle asks the model. Under a hold,
    with no judge or with the model down the answer is "unknown: not evaluated": it said nothing about the patient,
    so the stored answer stands and nothing is reported as a change."""
    mixed = next(
        c.id for c in GZQO.active() if c.class_ == "structured" and c.kind == "exclusion"
    )  # any re-checked one
    box = _NotAsked(pool=["P1"], booked={"P1": FRI}, scope=[])
    box.cid, box.reason = mixed, reason
    out = box.go(monkeypatch)
    cl = json.loads(box.published["candidate_list_GZQO_v" + GZQO.version + ".json"])
    stored = next(v for v in cl["rows"][0]["criteria"] if v["id"] == mixed)
    assert stored["verdict"] == "pass" and cl["rows"][0]["tier"] == "high"
    assert "Verdict changes: 0" in out.summary_md


def test_an_unknown_the_data_gives_still_replaces_a_stored_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only "nobody was asked" is ignored: an unknown that says something (a data gap) is the new answer."""
    coded = next(c.id for c in GZQO.active() if c.class_ == "structured" and c.kind == "inclusion")
    box = _NotAsked(pool=["P1"], booked={"P1": FRI}, scope=[])
    box.cid, box.reason = coded, "data_gap"
    out = box.go(monkeypatch)
    assert "Verdict changes: 1" in out.summary_md


def test_a_pool_row_that_is_excluded_comes_back_too_and_is_listed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: a re-check or a version re-screen leaves an excluded row in the pool. "Not in the pool" missed it, so
    that patient was never screened again in full. He is now; one who is listed again has one row on the list."""
    box = _Box(pool=["P1", "P-OUT"], booked={"P-OUT": FRI}, scope=[_new("P-OUT", FRI), _new("P1", None)], options={})
    out_row = next(p for p in box.pool if p["pid"] == "P-OUT")
    out_row["tier"] = "excluded"
    fail = next(c.id for c in GZQO.active() if c.class_ == "structured" and c.kind == "exclusion")
    for v in out_row["verdicts"]:
        if v["id"] == fail:
            v["verdict"], v["final"] = "fail", True

    def nothing_new(ctx: Any, rs: Any, run_date: Any, snap: str, scoped: list[Any], **kw: Any) -> Any:
        box.evaluated.append([s.pid for s in scoped])
        return {}

    box.evaluate_scope = nothing_new  # type: ignore[method-assign]
    box.go(monkeypatch)
    assert box.screened == ["P-OUT"]  # P1 is listed: not screened again
    cl = json.loads(box.published["candidate_list_GZQO_v" + GZQO.version + ".json"])
    assert sorted(r["pid"] for r in cl["rows"]) == ["P-OUT", "P1"] and cl["summary"]["excluded"] == 0
    assert box.delivered == [["P-OUT"]] and box.budget_event()["excluded_back"] == 1
