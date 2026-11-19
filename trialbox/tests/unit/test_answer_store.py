"""D-1360 (plan 10 card 10A-4, commitment C-5): the answer store.

* a run's answers are stored one per patient, criterion and ruleset version, with the reason code, the rung (the
  cascade's stage), the basis, the quote and its date; the flip date waits for criterion model v3;
* the latest answer stands: a later or same index date replaces it, an older run's never does;
* a patient on the opt-out register is neither written nor read; a register that does not answer means no write and
  no read; one who opts out while the run writes loses the rows at once; the opt-out worker deletes the rest;
* rows go with their snapshot under the site's retention (D-452);
* MICROBATCH tells a patient listed again what changed against the stored answers; CASE shows each criterion's last
  screened answer beside its own, for a patient in the hospital data only, and its own answer is not changed;
* class D3: in the erasure registry's owed tables, the opt-out worker's clear, the record inventory, the restore
  drill and the support bundle's exclusions.

Synthetic pseudonyms and criteria; no patient data.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from matching.cascade.model import Outcome, PatientTrace
from orchestrator import answer_store
from orchestrator.db import JobDB
from orchestrator.reports import case_html
from orchestrator.scenarios.case import Subject, with_last_screening
from orchestrator.scenarios.evaluate import PatientVerdicts
from orchestrator.scenarios.microbatch import answers_changed
from orchestrator.scenarios.screen_cascade import verdicts_of
from tb_contracts import CandidateRow, CriterionVerdict, Evidence

from tests.judge_kit import AGE, note_criterion, ruleset

ROOT = Path(__file__).resolve().parents[2]
A, B = "0ca5381cfa6bdf1c22961d65579f93b3", "1afe78d42518132b113c5858cedcbb54"
SNAP = "2026-11-02"
INC = note_criterion("T-INC-02", "inclusion", "Gout flare in the past year", "Did the patient have a gout flare?")


@pytest.fixture
def db() -> JobDB:
    d = JobDB()
    with d.tx() as con:
        con.execute("DELETE FROM answers")
    return d


def _ctx(db: JobDB, register: frozenset[str] | None = frozenset(), job: str = "01JOB", today: str = SNAP) -> Any:
    def now() -> frozenset[str]:
        if register is None:
            raise RuntimeError("the register did not answer")
        return register

    return SimpleNamespace(
        orch=SimpleNamespace(db=db, _now=lambda: SimpleNamespace(isoformat=lambda: f"{today}T09:00:00+00:00")),
        decision=SimpleNamespace(register_now=now),
        job=SimpleNamespace(job_id=job),
        today=lambda: date.fromisoformat(today),
        cfg=SimpleNamespace(settings=SimpleNamespace(retention=SimpleNamespace(nightly_snapshots=3,
                                                                               month_end_snapshots_months=36))),
    )  # fmt: skip


def _v(
    cid: str,
    verdict: str,
    quote: str | None = None,
    basis: str | None = None,
    final: bool | None = None,
    reason: str = "R1",
) -> CriterionVerdict:
    return CriterionVerdict(
        id=cid,
        verdict=verdict,  # type: ignore[arg-type]
        evidence=Evidence(resource_refs=[], quote=quote, quote_date="2026-10-01" if quote else None, reason=reason),
        basis=basis,  # type: ignore[arg-type]
        final=final,
        prov=[],
    )


def _pv(pid: str, *vs: CriterionVerdict, rungs: dict[str, str] | None = None) -> PatientVerdicts:
    return PatientVerdicts(pid, list(vs), "review", [], 0, rungs or {})


def test_a_runs_answers_are_stored_one_per_patient_and_criterion(db: JobDB) -> None:
    res = {A: _pv(A, _v("T-INC-01", "pass", basis="coded"), _v("T-INC-02", "pass", "Gout flare", "pair"),
                  rungs={"T-INC-01": "S1", "T-INC-02": "S3"}),
           B: _pv(B, _v("T-INC-01", "fail", basis="coded"), rungs={"T-INC-01": "S1"})}  # fmt: skip
    assert answer_store.record(_ctx(db), "T", "1.0.0", res, date(2026, 11, 2), SNAP) == 3
    got = answer_store.last(_ctx(db), A, "T", "1.0.0")
    assert {k: (r["status"], r["rung"], r["basis"], r["quote"], r["quote_date"]) for k, r in got.items()} == {
        "T-INC-01": ("pass", "S1", "coded", None, None),
        "T-INC-02": ("pass", "S3", "pair", "Gout flare", "2026-10-01"),
    }
    r = got["T-INC-02"]
    assert (r["reason"], r["flip_date"], r["index_date"], r["snapshot"], r["job_id"]) == (
        "R1", None, "2026-11-02", SNAP, "01JOB")  # fmt: skip
    assert answer_store.last(_ctx(db), A, "T", "2.0.0") == {}  # another version has its own answers
    assert answer_store.last(_ctx(db), None, "T", "1.0.0") == {}


def test_the_latest_answer_stands_and_an_older_run_never_replaces_it(db: JobDB) -> None:
    answer_store.record(_ctx(db, job="J2"), "T", "1.0.0", {A: _pv(A, _v("T-INC-02", "fail"))}, date(2026, 11, 9), SNAP)
    answer_store.record(_ctx(db, job="J1"), "T", "1.0.0", {A: _pv(A, _v("T-INC-02", "pass"))}, date(2026, 11, 2), SNAP)
    r = answer_store.last(_ctx(db), A, "T", "1.0.0")["T-INC-02"]
    assert (r["status"], r["job_id"]) == ("fail", "J2")
    answer_store.record(_ctx(db, job="J3"), "T", "1.0.0", {A: _pv(A, _v("T-INC-02", "unknown"))}, date(2026, 11, 9),
                        SNAP)  # fmt: skip
    assert answer_store.last(_ctx(db), A, "T", "1.0.0")["T-INC-02"]["job_id"] == "J3"


def test_an_opted_out_patient_is_neither_written_nor_read(db: JobDB) -> None:
    res = {A: _pv(A, _v("T-INC-01", "pass")), B: _pv(B, _v("T-INC-01", "pass"))}
    assert answer_store.record(_ctx(db, frozenset({B})), "T", "1.0.0", res, date(2026, 11, 2), SNAP) == 1
    assert answer_store.last(_ctx(db), B, "T", "1.0.0") == {}
    assert answer_store.last(_ctx(db, frozenset({A})), A, "T", "1.0.0") == {}  # on the register now: not read
    assert answer_store.last_of(_ctx(db, frozenset({A})), [A, B], "T", "1.0.0") == {B: {}}
    # the register does not answer: no write, no read (fail closed)
    assert answer_store.record(_ctx(db, None), "T", "1.0.0", res, date(2026, 11, 3), SNAP) == 0
    assert answer_store.last(_ctx(db, None), A, "T", "1.0.0") == {}
    assert answer_store.last_of(_ctx(db, None), [A], "T", "1.0.0") == {}
    assert db.answer_store_drop_pids([A]) == 1 and db.answer_store_count() == 0  # the opt-out worker's clear


def test_one_who_opts_out_while_the_run_writes_loses_the_rows_at_once(db: JobDB) -> None:
    calls = {"n": 0}

    def now() -> frozenset[str]:
        calls["n"] += 1
        return frozenset() if calls["n"] == 1 else frozenset({A})  # A opts out between the read and the write

    ctx = _ctx(db)
    ctx.decision.register_now = now
    res = {A: _pv(A, _v("T-INC-01", "pass")), B: _pv(B, _v("T-INC-01", "pass"))}
    assert answer_store.record(ctx, "T", "1.0.0", res, date(2026, 11, 2), SNAP) == 1
    assert db.answer_store_of(A, "T", "1.0.0") == [] and len(db.answer_store_of(B, "T", "1.0.0")) == 1


def test_rows_go_with_their_snapshot_under_the_sites_retention(db: JobDB) -> None:
    old = "2026-01-05"
    answer_store.record(_ctx(db, today=old), "T", "1.0.0", {A: _pv(A, _v("T-INC-01", "pass"))}, date(2026, 1, 5), old)
    assert db.answer_store_snapshots() == [old]
    answer_store.record(_ctx(db), "T", "1.0.0", {B: _pv(B, _v("T-INC-01", "pass"))}, date(2026, 11, 2), SNAP)
    assert db.answer_store_snapshots() == [SNAP]  # January 5 is neither a recent night nor a month's end: it is gone


def test_a_fault_of_the_store_is_never_the_runs(db: JobDB) -> None:
    class Broken:
        def answer_store_put(self, rows: Any) -> None:
            raise RuntimeError("the store refused")

        def answer_store_of(self, *a: Any) -> Any:
            raise RuntimeError("the store refused")

    ctx = _ctx(db)
    ctx.orch.db = Broken()
    assert answer_store.record(ctx, "T", "1.0.0", {A: _pv(A, _v("T-INC-01", "pass"))}, date(2026, 11, 2), SNAP) == 0
    assert answer_store.last(ctx, A, "T", "1.0.0") == {}
    # the review of D-1360 (H1): a job's stand-in with no clock, no job, no settings, or results that are not
    # verdicts: still never the run's
    bare = SimpleNamespace(orch=SimpleNamespace(db=db), decision=SimpleNamespace(register_now=frozenset))
    assert answer_store.record(bare, "T", "1.0.0", {A: _pv(A, _v("T-INC-01", "pass"))}, date(2026, 11, 2), SNAP) == 0
    assert answer_store.record(_ctx(db), "T", "1.0.0", {A: object()}, date(2026, 11, 2), SNAP) == 0
    assert answer_store.record(SimpleNamespace(), "T", "1.0.0", {}, date(2026, 11, 2), SNAP) == 0
    clockless = _ctx(db)
    del clockless.orch._now
    del clockless.cfg
    assert answer_store.record(clockless, "T", "1.0.0", {A: _pv(A, _v("T-INC-01", "pass"))}, date(2026, 11, 2),
                               SNAP) == 1  # fmt: skip


def test_the_cascade_gives_the_rung_of_each_answer() -> None:
    rs = ruleset([AGE, INC])
    t = PatientTrace(A, date(2026, 11, 2), tier="potential:uncertain")
    t.outcomes = {
        "T-INC-01": Outcome("T-INC-01", "pass", "S1"),
        "T-INC-02": Outcome("T-INC-02", "unknown", "S3", unknown_kind="uncertain"),
    }
    pv = verdicts_of(rs, t)
    assert pv.rungs == {"T-INC-01": "S1", "T-INC-02": "S3"}
    (row,) = [r for r in answer_store.rows_of("T", "1.0.0", {A: pv}, date(2026, 11, 2), SNAP, "J", "now")
              if r[3] == "T-INC-02"]  # fmt: skip
    assert row[6] == "S3" and row[4] == "unknown"


def _row(pid: str, *vs: CriterionVerdict) -> CandidateRow:
    return CandidateRow(pid=pid, tier="review", criteria=list(vs), actions=[], n_unknown=0)


def test_microbatch_tells_a_patient_listed_again_what_changed(db: JobDB) -> None:
    answer_store.record(_ctx(db), "T", "1.0.0", {A: _pv(A, _v("T-INC-01", "pass"), _v("T-INC-02", "fail"))},
                        date(2026, 10, 26), SNAP)  # fmt: skip
    rs = SimpleNamespace(id="T", version="1.0.0")
    rows = [_row(A, _v("T-INC-01", "pass"), _v("T-INC-02", "pass", "Gout flare"), _v("T-INC-03", "unknown")),
            _row(B, _v("T-INC-02", "pass"))]  # fmt: skip
    got = answers_changed(_ctx(db), rs, rows, [])  # type: ignore[arg-type]
    assert [(c.pid, c.criterion_id, c.before, c.after, c.quote) for c in got] == [
        (A, "T-INC-02", "fail", "pass", "Gout flare")]  # fmt: skip
    from orchestrator.reports.candidate_xlsx import Change

    assert answers_changed(_ctx(db), rs, rows, [Change(A, "T-INC-02", "fail", "pass")]) == []  # type: ignore[arg-type]
    assert answers_changed(_ctx(db, frozenset({A})), rs, rows, []) == []  # type: ignore[arg-type]


def test_case_shows_the_last_screening_beside_its_own_answer(db: JobDB) -> None:
    answer_store.record(_ctx(db), "T", "1.0.0", {A: _pv(A, _v("T-INC-02", "pass", basis="pair"),
                                                        rungs={"T-INC-02": "S3"})}, date(2026, 10, 26), SNAP)  # fmt: skip
    rs = SimpleNamespace(id="T", version="1.0.0")
    rows: list[dict[str, Any]] = [
        {"id": "T-INC-02", "kind": "inclusion", "text": "Gout flare", "verdict": "unknown", "source": "chart"},
        {"id": "T-INC-01", "kind": "inclusion", "text": "Age", "verdict": "pass", "source": "lake"},
    ]
    in_lake = Subject(pid=A, in_lake=True, snapshot=SNAP, note="")
    assert with_last_screening(_ctx(db), rs, in_lake, rows) == 1  # type: ignore[arg-type]
    assert rows[0]["last_screening"] == {"shown": "pass", "held_back": None, "status": "pass", "basis": "pair",
                                         "final": None, "rung": "S3", "index_date": "2026-10-26"}  # fmt: skip
    assert rows[0]["verdict"] == "unknown" and rows[1]["last_screening"] is None  # its own answer is not changed
    html = case_html._row(rows[0], "en")
    assert "Last screening, 2026-10-26: " in html
    assert "前回スクリーニング（2026-10-26）" in case_html._row(rows[0], "ja")
    chart_only = Subject(pid=A, in_lake=False, snapshot=None, note="not in the hospital data")
    assert with_last_screening(_ctx(db), rs, chart_only, rows) == 0  # type: ignore[arg-type]
    assert rows[0]["last_screening"] is None


def test_the_store_is_class_d3_and_erased_with_the_patient() -> None:
    from datacore.optout_worker import OWED_TABLES
    from tb_common import erasure

    assert erasure.entries()["orch.answers"].kind == erasure.ERASE
    orch = dict(OWED_TABLES)["orch"]
    assert any(t == "answers" and "DELETE FROM answers WHERE pid = ANY" in d for t, _, d in orch)
    assert "`answers`" in (ROOT / "docs/validation/record-inventory.md").read_text(encoding="utf-8")
    assert "orch.answers" in (ROOT / "tools/support_bundle.py").read_text(encoding="utf-8").split('"""')[1]
    assert "orch.answers" in (ROOT / "tools/restore_drill.py").read_text(encoding="utf-8")
    assert "orch.answers" in (ROOT / "docs/runbook/05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")


def test_an_answer_nobody_gave_never_replaces_a_decided_one(db: JobDB) -> None:
    """The review of D-1360 (M2): D-642's rule in the store: the model down, or not evaluated, is stored only where
    no "met" or "not met" is."""
    answer_store.record(_ctx(db), "T", "1.0.0", {A: _pv(A, _v("T-INC-02", "pass", "Gout flare", "pair"))},
                        date(2026, 11, 2), SNAP)  # fmt: skip
    down = _v("T-INC-02", "unknown", reason="model_down")
    answer_store.record(_ctx(db), "T", "1.0.0", {A: _pv(A, down), B: _pv(B, down)}, date(2026, 11, 9), SNAP)
    assert answer_store.last(_ctx(db), A, "T", "1.0.0")["T-INC-02"]["status"] == "pass"
    assert answer_store.last(_ctx(db), B, "T", "1.0.0")["T-INC-02"]["reason"] == "model_down"  # none was stored
    answer_store.record(_ctx(db), "T", "1.0.0", {A: _pv(A, _v("T-INC-02", "unknown", reason="no_evidence"))},
                        date(2026, 11, 9), SNAP)  # fmt: skip
    assert answer_store.last(_ctx(db), A, "T", "1.0.0")["T-INC-02"]["status"] == "unknown"  # an answer given


def test_a_held_back_not_met_is_never_shown_as_not_met(db: JobDB) -> None:
    """The review of D-1360 (H2): ``final`` and the basis are stored; a single model's "not met", or one given while
    notes could not exclude, reads as an open point on CASE and in MICROBATCH's changes (D-478)."""
    single = _v("T-EXC-01", "fail", "No flare", "single")
    unfinal = _v("T-EXC-02", "fail", "No flare", "pair", final=False)
    pair = _v("T-EXC-03", "fail", "No flare", "pair", final=True)
    answer_store.record(_ctx(db), "T", "1.0.0", {A: _pv(A, single, unfinal, pair)}, date(2026, 10, 26), SNAP)
    got = answer_store.last(_ctx(db), A, "T", "1.0.0")
    assert [answer_store.shown(got[k]) for k in ("T-EXC-01", "T-EXC-02", "T-EXC-03")] == [
        ("unknown", "single_model"), ("unknown", "not_final"), ("fail", None)]  # fmt: skip
    assert got["T-EXC-02"]["final"] is False
    rows: list[dict[str, Any]] = [{"id": k, "kind": "exclusion", "text": "x", "verdict": "unknown", "source": "chart"}
                                  for k in ("T-EXC-01", "T-EXC-03")]  # fmt: skip
    rs = SimpleNamespace(id="T", version="1.0.0")
    with_last_screening(_ctx(db), rs, Subject(pid=A, in_lake=True, snapshot=SNAP), rows)  # type: ignore[arg-type]
    assert rows[0]["last_screening"]["shown"] == "unknown" and rows[0]["last_screening"]["status"] == "fail"
    assert "Last screening, 2026-10-26: unknown" in case_html._row(rows[0], "en")
    assert "Last screening, 2026-10-26: not met" in case_html._row(rows[1], "en")
    # MICROBATCH: a stored single-model "not met" and a fresh unknown read alike: no change is told
    now = [_row(A, _v("T-EXC-01", "unknown", reason="no_evidence"), _v("T-EXC-03", "pass"))]
    got_changes = answers_changed(_ctx(db), rs, now, [])  # type: ignore[arg-type]
    assert [(c.criterion_id, c.before, c.after) for c in got_changes] == [("T-EXC-03", "fail", "pass")]


def test_microbatch_reads_the_answers_stored_before_the_job_wrote() -> None:
    """The review of D-1360 (M1): an excluded pool row re-checked and then screened again is told against the
    answers read before this job's re-check wrote, not the re-check's own."""
    rs = SimpleNamespace(id="T", version="1.0.0")
    earlier = {A: {"T-INC-02": {"status": "fail", "reason": "R1", "basis": "pair", "final": True}}}
    rows = [_row(A, _v("T-INC-02", "pass", "Gout flare"))]
    ctx = SimpleNamespace(decision=SimpleNamespace(register_now=frozenset), orch=SimpleNamespace(db=None))
    got = answers_changed(ctx, rs, rows, [], earlier)  # type: ignore[arg-type]
    assert [(c.criterion_id, c.before, c.after) for c in got] == [("T-INC-02", "fail", "pass")]
    # nobody was asked on either side: no change
    rows = [_row(A, _v("T-INC-02", "unknown", reason="model_down"))]
    assert answers_changed(ctx, rs, rows, [], earlier) == []  # type: ignore[arg-type]
    gone = {A: {"T-INC-02": {"status": "unknown", "reason": "model_down", "basis": None, "final": None}}}
    assert answers_changed(ctx, rs, [_row(A, _v("T-INC-02", "pass"))], [], gone) == []  # type: ignore[arg-type]


def test_the_nightly_retention_sweeps_the_store_too(db: JobDB) -> None:
    """The review of D-1360 (L3): a study that stops screening does not keep its rows past D-452."""
    from datetime import UTC, datetime

    from orchestrator.scenarios.retention import answer_rows_swept

    old = "2026-01-05"
    answer_store.record(_ctx(db, today=old), "T", "1.0.0", {A: _pv(A, _v("T-INC-01", "pass"))}, date(2026, 1, 5), old)
    ctx = SimpleNamespace(
        services=SimpleNamespace(lake=SimpleNamespace(snapshot=lambda: SNAP)),
        cfg=SimpleNamespace(settings=SimpleNamespace(retention=None)),
        orch=SimpleNamespace(db=db),
    )
    assert answer_rows_swept(ctx, datetime(2026, 11, 2, 9, tzinfo=UTC)) == 1  # type: ignore[arg-type]
    assert db.answer_store_count() == 0
    ctx.services.lake.snapshot = lambda: None
    assert answer_rows_swept(ctx, datetime(2026, 11, 2, 9, tzinfo=UTC)) == 0  # type: ignore[arg-type]


def test_the_case_sheet_says_it_in_three_languages(db: JobDB) -> None:
    r = {"id": "T-INC-02", "kind": "inclusion", "text": "x", "verdict": "pass", "source": "lake",
         "last_screening": {"shown": "pass", "status": "pass", "index_date": "2026-10-26"}}  # fmt: skip
    assert "Last screening, 2026-10-26" in case_html._row(r, "en")
    assert "前回スクリーニング（2026-10-26）" in case_html._row(r, "ja")
    assert "上次篩選（2026-10-26）" in case_html._row(r, "zh-TW")
