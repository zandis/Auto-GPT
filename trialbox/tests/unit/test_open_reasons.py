"""F17 5a, 5b: every open criterion of a night carries a reason code that says where the cause is (a site gap, a part of
the box, a person's decision) and which site view or field it names; the night counts the patients whose coded records
are complete. Counts only: no patient id in anything stored. Synthetic data only."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common import open_reasons, prefilter
from tb_common.reasons import CODES, Reason
from tb_contracts import CriterionVerdict, Evidence, JobMetrics, NightOpen, OpenReason, PrefilterRecord


def _c(cid: str, cls: str = "structured", domain: str | None = "observation") -> Any:
    logic = (
        SimpleNamespace(domain=domain)
        if domain
        else SimpleNamespace(op="and", args=[SimpleNamespace(op="not", args=[])])
    )
    return SimpleNamespace(id=cid, class_=cls, logic=logic)


def _v(cid: str, verdict: str, reason: str | None = None, **ev: Any) -> CriterionVerdict:
    return CriterionVerdict(id=cid, verdict=verdict, evidence=Evidence(reason=reason, **ev) if reason or ev else None)  # type: ignore[arg-type]


BY_ID = {
    "S-1": _c("S-1"),
    "S-2": _c("S-2", domain="medication"),
    "N-1": _c("N-1", "note", None),
    "H-1": _c("H-1", "human", None),
}


def test_every_reason_is_in_exactly_one_class() -> None:
    classes = [open_reasons.DECIDED, open_reasons.SITE_GAP, open_reasons.PRODUCT, open_reasons.PERSON]
    assert sum(len(c) for c in classes) == len(set().union(*classes)) == len(Reason)
    assert {r.value for r in set().union(*classes)} == CODES
    assert open_reasons.kind_of("no_notes") == "site_gap" and open_reasons.kind_of("order_dates_missing") == "product"
    assert open_reasons.kind_of("disagree") == "person" and open_reasons.kind_of("coded") == "decided"
    assert open_reasons.kind_of(open_reasons.NO_REASON) == "product"  # an open answer that says nothing is a defect
    assert open_reasons.kind_of("a_code_nobody_knows") == "product"


def test_where_names_the_view_the_reason_is_about() -> None:
    w = open_reasons.where
    assert w("no_notes", BY_ID["S-1"]) == "notes"
    assert w("data_gap", BY_ID["S-1"]) == "observation"
    assert w("no_record_of_kind", BY_ID["S-2"]) == "medication"
    assert w("data_gap", BY_ID["N-1"]) == "notes"  # the model reads the notes
    assert w("data_gap", _c("X-1", domain=None)) == "records"  # no atom domain: no single view
    assert w("unit_mismatch", BY_ID["S-1"]) == "product" and w("human", BY_ID["H-1"]) == "person"
    nested = SimpleNamespace(
        class_="structured", logic=SimpleNamespace(op="and", args=[SimpleNamespace(domain="condition")])
    )
    assert w("data_gap", nested) == "condition"


def test_coded_complete_needs_a_coded_yes_no_no_and_only_site_gaps_open() -> None:
    f = open_reasons.facts_of
    ok = f(BY_ID, [_v("S-1", "pass", "coded"), _v("N-1", "unknown", "no_notes")])
    assert ok.coded_complete and ok.opens == (("N-1", "no_notes", "notes"),)
    gap = f(BY_ID, [_v("S-1", "pass", "coded"), _v("S-2", "unknown", "no_record_of_kind")])
    assert gap.coded_complete and gap.opens == (("S-2", "no_record_of_kind", "medication"),)
    assert not f(BY_ID, [_v("S-1", "pass", "coded"), _v("S-2", "unknown", "order_dates_missing")]).coded_complete
    assert not f(BY_ID, [_v("S-1", "pass", "coded"), _v("H-1", "pending_human", "human")]).coded_complete
    assert not f(BY_ID, [_v("S-1", "pass", "coded"), _v("S-2", "fail", "coded")]).coded_complete
    assert not f(BY_ID, [_v("S-1", "unknown", "data_gap"), _v("S-2", "unknown", "data_gap")]).coded_complete  # no yes
    assert not f(BY_ID, [_v("S-1", "pass", "coded"), _v("N-1", "pass", "note")]).coded_complete  # a model's yes
    mixed = {"M-1": _c("M-1", "mixed")}
    assert f(mixed, [_v("M-1", "pass", "coded")]).coded_complete
    assert not f(mixed, [_v("M-1", "pass", "note", confidence=0.9)]).coded_complete  # decided by the model
    silent = f(BY_ID, [_v("S-1", "pass", "coded"), _v("S-2", "unknown")])
    assert not silent.coded_complete and silent.opens == (("S-2", "no_reason", "product"),)
    assert f(BY_ID, [_v("Z-9", "unknown", "data_gap")]).opens == ()  # not a criterion of the ruleset


def _facts(*verdicts: CriterionVerdict) -> open_reasons.Facts:
    return open_reasons.facts_of(BY_ID, verdicts)


def test_the_tally_counts_only_patients_past_the_coded_filter_and_the_last_evaluation_stands() -> None:
    gap = _facts(_v("S-1", "pass", "coded"), _v("N-1", "unknown", "no_notes"))
    t = prefilter.Tally()
    t.evaluated("P-1", "listed", gap)
    t.evaluated("P-2", "no_model", gap)
    t.evaluated("P-3", "coded_excluded", gap)  # excluded by the codes: not counted
    t.evaluated("P-4", "opted_out", gap)
    t.evaluated("P-5", "model_not_listed", _facts(_v("S-1", "pass", "coded"), _v("S-2", "unknown", "unit_mismatch")))
    t.evaluated("P-6", "listed", gap)
    t.evaluated("P-6", "coded_excluded", gap)  # re-evaluated: the stage and the facts of the last one
    t.evaluated("P-7", "listed")  # no facts given
    no = t.night_open()
    assert no.coded_complete == 2
    rows = {(o.criterion, o.reason, o.where): o.count for o in no.open_reasons}
    assert rows == {("N-1", "no_notes", "notes"): 2, ("S-2", "unit_mismatch", "product"): 1}
    assert t.counts()["listed"] == 2 and prefilter.adds_up(t.record("weekly"))  # the funnel itself is untouched
    assert "P-" not in json.dumps(no.model_dump(mode="json"))  # counts only


def _job(rid: str, night: date, no: NightOpen | None, **stages: int) -> Any:
    counts = {s: stages.get(s, 0) for s in prefilter.STAGES}
    rec = PrefilterRecord(trigger="weekly", in_scope=sum(counts.values()), **counts)
    return SimpleNamespace(
        type="MICROBATCH", state="done", ruleset=rid, run_date=night, metrics=JobMetrics(prefilter=rec, night_open=no)
    )


def test_the_night_sums_the_jobs_open_reasons_and_says_nothing_when_no_job_wrote_them() -> None:
    night = date(2026, 10, 5)
    a = NightOpen(
        coded_complete=3, open_reasons=[OpenReason(criterion="N-1", reason="no_notes", where="notes", count=3)]
    )
    b = NightOpen(
        coded_complete=1,
        open_reasons=[
            OpenReason(criterion="N-1", reason="no_notes", where="notes", count=1),
            OpenReason(criterion="S-2", reason="data_gap", where="medication", count=2),
        ],
    )
    f = prefilter.night_funnel([_job("GZQO", night, a, listed=3), _job("GZQO", night, b, listed=1)], "gzqo", night)
    assert f is not None and f.coded_complete == 4
    assert f.open_reasons == (("N-1", "no_notes", "notes", 4), ("S-2", "data_gap", "medication", 2))
    old = prefilter.night_funnel([_job("GZQO", night, None, listed=3)], "GZQO", night)
    assert old is not None and old.coded_complete is None and old.open_reasons == ()  # a job from before: no figure
    mixed = prefilter.night_funnel(
        [_job("GZQO", night, None, listed=3), _job("GZQO", night, a, listed=3)], "GZQO", night
    )
    assert mixed is not None and mixed.coded_complete == 3


def test_a_night_open_record_with_a_bad_count_is_refused() -> None:
    with pytest.raises(ValueError, match="count"):
        OpenReason(criterion="N-1", reason="no_notes", where="notes", count=0)


def test_a_weekly_job_writes_night_open_beside_its_record_counts_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_microbatch_cadence import FRI, _new
    from tests.unit.test_prefilter_night_10e12 import CODED, NOTE, _Night, _v

    box = _Night(
        pool=["P-LIST", "P-BACK", "P-FAR"],
        booked={"P-LIST": FRI, "P-BACK": FRI},
        scope=[
            _new("P-LIST", FRI),
            _new("P-BACK", FRI),
            _new("P-CODED", FRI),
            _new("P-NOMODEL", FRI),
            _new("P-READ", FRI),
        ],
    )
    box.recheck_fail = ("P-BACK",)
    box.answers = {
        "P-CODED": ("excluded", [_v(CODED, "fail", "coded")]),
        "P-NOMODEL": ("excluded", [_v(CODED, "pass", "coded"), _v(NOTE, "unknown", "no_notes")]),  # coded-complete
        "P-READ": ("excluded", [_v(NOTE, "fail", "note")]),
        "P-BACK": ("high", [_v(NOTE, "pass", "note")]),
    }
    box.go(monkeypatch)
    no = box.job.metrics.night_open
    assert no is not None and no.coded_complete == 1
    rows = {(o.criterion, o.reason, o.where): o.count for o in no.open_reasons}
    assert rows[(NOTE, "no_notes", "notes")] == 1
    assert all(w in open_reasons.WHERES and c.startswith("GZQO-") for c, _, w in rows)  # every open one is named
    assert "P-" not in json.dumps(box.job.metrics.model_dump(mode="json"))
