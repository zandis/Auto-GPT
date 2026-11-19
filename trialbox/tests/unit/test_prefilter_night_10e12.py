"""10E-12 (D-1259): the pre-filter record of a nightly job and the per-study per-night report built from it.

Invented nights only (synthetic pseudonyms). The rules (lane H's counting, PR #639, 2026-11-19):

* a patient evaluated twice in a night is counted once, at the last evaluation;
* the stages add up to "in scope";
* the jobs of one night are summed; another night, another study, a job not done or of another type is not;
* a night with no job has no report (None, never a funnel of zeros);
* the job writes counts only: no patient id in its record;
* anything mailed or exported takes complementary suppression (``funnel_drops_publishable``).
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.scenarios import microbatch
from orchestrator.scenarios.evaluate import PatientVerdicts, row
from tb_common import prefilter
from tb_common.smallcell import funnel_drops_publishable
from tb_contracts import CriterionVerdict, Evidence, JobMetrics, PrefilterRecord

from tests.unit.test_microbatch_cadence import FRI, WED, _Box, _new

CODED = "GZQO-EXC-01"  # a structured exclusion the weekly re-check answers again
NOTE = "GZQO-INC-05"  # a note inclusion


def _rec(trigger: str = "weekly", **c: int) -> PrefilterRecord:
    counts = {s: c.get(s, 0) for s in prefilter.STAGES}
    return PrefilterRecord(trigger=trigger, in_scope=sum(counts.values()), **counts)  # type: ignore[arg-type]


def _job(rec: PrefilterRecord | None, *, rs: str = "GZQO", day: date = WED, state: str = "done",
         type_: str = "MICROBATCH") -> Any:  # fmt: skip
    return SimpleNamespace(
        type=type_, state=state, ruleset=rs, run_date=day, metrics=JobMetrics(patients_scoped=0, prefilter=rec)
    )


# ------------------------------------------------------------------------------------------- the tally (one job)
def test_a_patient_evaluated_twice_is_counted_once_at_the_last() -> None:
    t = prefilter.Tally()
    t.evaluated("P1", "coded_excluded")  # the re-check excluded them
    t.evaluated("P1", "listed")  # screened again later the same job: listed
    t.passed(["P1"], "carried")  # a later step that did not evaluate them changes nothing
    t.passed(["P2"], "not_due")
    t.passed(["P2"], "carried")  # two stages without an evaluation: the later stands
    assert t.counts() == {**dict.fromkeys(prefilter.STAGES, 0), "listed": 1, "carried": 1}
    assert t.record("weekly").in_scope == 2


def test_an_evaluation_stage_is_never_given_without_an_evaluation() -> None:
    with pytest.raises(ValueError):
        prefilter.Tally().passed(["P1"], "listed")
    with pytest.raises(ValueError):
        prefilter.Tally().evaluated("P1", "carried")


@pytest.mark.parametrize(
    ("kw", "stage"),
    [
        ({"consent_out": True, "at_index": True, "coded_fail": True, "listed": True, "model_read": True}, "opted_out"),
        ({"consent_out": False, "at_index": False, "coded_fail": False, "listed": True, "model_read": False},
         "opted_out"),
        ({"consent_out": False, "at_index": True, "coded_fail": True, "listed": False, "model_read": True},
         "coded_excluded"),
        ({"consent_out": False, "at_index": True, "coded_fail": False, "listed": True, "model_read": True}, "listed"),
        ({"consent_out": False, "at_index": True, "coded_fail": False, "listed": False, "model_read": False},
         "no_model"),
        ({"consent_out": False, "at_index": True, "coded_fail": False, "listed": False, "model_read": True},
         "model_not_listed"),
    ],
)  # fmt: skip
def test_the_funnel_order_of_an_evaluated_patient(kw: dict[str, bool], stage: str) -> None:
    assert prefilter.evaluated_stage(**kw) == stage


# ------------------------------------------------------------------------------------------- the night (records)
def test_two_jobs_of_one_night_are_summed_and_the_stages_add_up() -> None:
    weekly = _rec(opted_out=2, not_due=40, carried=7, coded_excluded=30, no_model=5, model_not_listed=6, listed=10)
    ingest = _rec("ingest", not_due=12, coded_excluded=3, listed=1)
    jobs = [
        _job(weekly),
        _job(ingest),
        _job(_rec(listed=99), day=date(2026, 10, 6)),  # another night
        _job(_rec(listed=99), rs="ABCD"),  # another study
        _job(_rec(listed=99), state="running"),  # not finished
        _job(_rec(listed=99), type_="SCREEN"),  # not a nightly job
        _job(None),  # a job of the night from before the record: nothing to add
    ]
    f = prefilter.night_funnel(jobs, "gzqo", WED)
    assert f is not None and f.jobs == 2
    assert f.drops == {
        "opted_out": 2, "not_due": 52, "carried": 7, "coded_excluded": 33, "no_model": 5, "model_not_listed": 6,
        "listed": 11,
    }  # fmt: skip
    assert f.in_scope == weekly.in_scope + ingest.in_scope == sum(f.drops.values()) == 116
    assert f.remaining == [116, 114, 62, 55, 22, 17, 11] and f.listed == 11
    for i, s in enumerate(prefilter.STAGES[:-1]):
        assert f.remaining[i] - f.remaining[i + 1] == f.drops[s]


def test_a_night_with_no_job_has_no_report() -> None:
    assert prefilter.night_funnel([], "GZQO", WED) is None
    assert prefilter.night_funnel([_job(_rec(listed=3), day=date(2026, 10, 6))], "GZQO", WED) is None
    assert prefilter.night_funnel([_job(None)], "GZQO", WED) is None


def test_what_is_mailed_or_exported_takes_complementary_suppression() -> None:
    f = prefilter.night_funnel([_job(_rec(not_due=40, carried=2, coded_excluded=30, listed=10))], "GZQO", WED)
    assert f is not None
    assert prefilter.publishable(f) == funnel_drops_publishable(f.remaining)
    shown = prefilter.publishable(f)
    assert shown[prefilter.STAGES.index("carried") + 1] is False  # a drop of 2 is withheld ...
    assert shown.count(False) >= 3  # ... with a neighbour (and the pool, which has no drop)


def test_the_record_holds_counts_only() -> None:
    props = PrefilterRecord.model_json_schema()["properties"]
    assert set(props) == {"trigger", "in_scope", *prefilter.STAGES}
    assert all(props[k]["type"] == "integer" for k in ("in_scope", *prefilter.STAGES))


# ------------------------------------------------------------------------------------------- the job writes it
def _v(cid: str, verdict: str, reason: str) -> CriterionVerdict:
    conf = 0.9 if reason == "note" else None
    return CriterionVerdict(
        id=cid, verdict=verdict, evidence=Evidence(resource_refs=[], reason=reason, confidence=conf)
    )  # type: ignore[arg-type]


class _Night(_Box):
    """The cadence box with a re-check that excludes some pool rows and a screen that answers per patient."""

    recheck_fail: tuple[str, ...] = ()
    answers: dict[str, tuple[str, list[CriterionVerdict]]] = {}  # noqa: RUF012

    def evaluate_scope(self, ctx: Any, rs: Any, run_date: date, snap: str, scoped: list[Any], **kw: Any) -> Any:
        self.evaluated.append([s.pid for s in scoped])
        return {
            s.pid: PatientVerdicts(
                s.pid, [_v(CODED, "fail", "coded")] if s.pid in self.recheck_fail else [], "high", [], 0
            )
            for s in scoped
        }

    def run_screen(self, ctx: Any, rs: Any, run_date: date, snapshot: str, select: Any = None, scope: Any = None
                   ) -> Any:  # fmt: skip
        picked = select(list(self.scope if scope is None else scope))
        self.screened += [s.pid for s in picked]
        results = {s.pid: PatientVerdicts(s.pid, self.answers[s.pid][1], self.answers[s.pid][0], [], 0) for s in picked}
        stamp = "2026-10-07T03:00:00+09:00"
        rows = [row(results[s.pid], s.next_appointment, "D1", "RHEU", stamp) for s in picked]
        return SimpleNamespace(scoped=picked, rows=rows, judging=None, results=results)

    def go(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        monkeypatch.setattr(microbatch.answer_store, "record", lambda *a, **kw: 0)
        return super().go(monkeypatch)


def test_a_weekly_job_writes_one_record_each_patient_once(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _Night(
        pool=["P-LIST", "P-BACK", "P-FAR"],
        booked={"P-LIST": FRI, "P-BACK": FRI},  # P-FAR has no visit in the window: not due
        scope=[
            _new("P-LIST", FRI),  # in the pool and not excluded: counted with the pool
            _new("P-BACK", FRI),  # re-checked, excluded by the codes, screened again the same job: listed
            _new("P-CODED", FRI), _new("P-NOMODEL", FRI), _new("P-READ", FRI), _new("P-IDX", FRI),
            _new("P-MODEL", FRI),
        ],
    )  # fmt: skip
    box.recheck_fail = ("P-BACK",)
    box.removed = ["P-OPT"]  # on the register: the scope query's patient the register removed
    unknown = [_v(NOTE, "unknown", "not_evaluated")]
    box.answers = {
        "P-CODED": ("excluded", [_v(CODED, "fail", "coded")]),
        "P-NOMODEL": ("excluded", unknown),  # past the codes, nobody read their notes, not listed
        "P-READ": ("excluded", [_v(NOTE, "fail", "note")]),  # the model read their notes: not listed
        "P-MODEL": ("high", [_v(NOTE, "pass", "note")]),
        "P-IDX": ("review", [_v(NOTE, "unknown", "not_in_snapshot"), _v(CODED, "unknown", "not_in_snapshot")]),
        "P-BACK": ("high", [_v(NOTE, "pass", "note")]),
    }
    box.go(monkeypatch)
    rec = box.job.metrics.prefilter
    assert rec is not None and rec.trigger == "weekly"
    assert rec.model_dump() == {
        "trigger": "weekly", "in_scope": 9, "opted_out": 2, "not_due": 1, "carried": 0, "coded_excluded": 1,
        "no_model": 1, "model_not_listed": 1, "listed": 3,
    }  # fmt: skip
    assert rec.in_scope == sum(getattr(rec, s) for s in prefilter.STAGES)
    assert "P-BACK" in box.screened and box.evaluated == [["P-BACK", "P-LIST"]]  # evaluated twice, counted once
    # counts only: no pseudonym anywhere in the stored metrics
    assert "P-" not in json.dumps(box.job.metrics.model_dump(mode="json"))


def test_the_budget_carries_and_the_ingest_run_counts_the_pool_as_not_in_its_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = _Night(
        pool=["P-POOL"],
        booked={"P-POOL": FRI},
        scope=[_new("P-POOL", FRI), _new("P-N1", FRI), _new("P-N2", FRI), _new("P-LATE", None)],
        options={"trigger": "ingest"},
        budget=1,
    )
    box.answers = {p: ("high", [_v(NOTE, "pass", "note")]) for p in ("P-N1", "P-N2")}
    box.go(monkeypatch)
    rec = box.job.metrics.prefilter
    assert rec is not None and rec.trigger == "ingest"
    # the scope: P-POOL already screened and P-LATE with no visit in the window are not due on an after-ingest run;
    # the budget of one takes P-N1 (the nearest), P-N2 waits
    assert (rec.in_scope, rec.not_due, rec.carried, rec.listed) == (4, 2, 1, 1)
    assert box.evaluated == []  # the after-ingest run re-checks nobody
