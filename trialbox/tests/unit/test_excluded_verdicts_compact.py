"""prof16 (CODED-PROFILE §4, ruling of 2026-11-27): verdict assembly kept one CriterionVerdict and one Evidence per patient
and criterion, 22.7 M objects and 4.4 GB at 100,000 patients, 98 % of them excluded (GZQO on the 100k twin). An answer
with no record, quote, opinion or call is now one object shared by every patient who has it; each verdict reads and
writes the same bytes as before. Synthetic pseudonyms only."""

from __future__ import annotations

import tracemalloc
from datetime import date
from typing import Any

import pytest
from matching.cascade.model import Outcome, PatientTrace
from matching.decision import Policy
from orchestrator.scenarios.screen_cascade import _final, _Shared, basis_of, verdict_of, verdicts_of
from pydantic import BaseModel
from tb_common.reasons import code_of
from tb_contracts import CriterionVerdict, Evidence

from tests.judge_kit import AGE, note_criterion, ruleset

pytestmark = pytest.mark.nodb

IDX = date(2026, 10, 5)
CRITS = [AGE] + [note_criterion(f"T-EXC-{i:02d}", "exclusion", f"condition {i}", f"Condition {i}?") for i in range(20)]
RS = ruleset(CRITS)
POLICY = Policy(threshold=0.75, note_block=False)


def _as_before(o: Outcome, pair: bool = False) -> CriterionVerdict:
    """The verdict as verdict_of built it for an answer with no record, quote, opinion or call."""
    status = "unknown" if o.status == "pass" and o.unknown_kind == "data_gap" else o.status
    return CriterionVerdict(
        id=o.criterion_id,
        verdict=status,
        evidence=Evidence(
            resource_refs=[],
            quote=None,
            quote_date=None,
            confidence=None,
            reason=code_of(o.reason, status, False),
            opinions=None,
        ),
        final=_final(o, status),
        basis=basis_of(o, status, pair),
        affirmed=o.affirmed if status == "fail" else None,
        prov=[],
    )


@pytest.mark.parametrize(
    "o",
    [
        Outcome("T-INC-01", "fail", "S1", hard=True, reason="age below the minimum"),
        Outcome("T-EXC-01", "pass", "S1", reason="no record"),
        Outcome("T-EXC-02", "pass", "S1", unknown_kind="data_gap", reason="value missing"),
        Outcome("T-EXC-03", "unknown", "S2", reason="no notes"),
        Outcome("T-EXC-04", "fail", "S3", hard=True, affirmed=True, reason="judge"),
    ],
)
def test_a_shared_verdict_writes_the_same_bytes_as_before(o: Outcome) -> None:
    got, want = verdict_of(o), _as_before(o)
    assert got.model_dump_json() == want.model_dump_json()
    assert got.model_fields_set == want.model_fields_set
    assert got.evidence is not None and want.evidence is not None
    assert got.evidence.model_fields_set == want.evidence.model_fields_set


def test_an_answer_with_records_is_its_patients_own() -> None:
    ev: list[dict[str, Any]] = [{"source": "lake", "record": "Condition/c1"}]
    a = verdict_of(Outcome("T-EXC-05", "fail", "S1", hard=True, evidence=ev, reason="coded"))
    b = verdict_of(Outcome("T-EXC-05", "fail", "S1", hard=True, evidence=ev, reason="coded"))
    assert a is not b and a.evidence is not None and a.evidence.resource_refs == ["Condition/c1"]


def _excluded(i: int) -> PatientTrace:
    """A patient the records exclude at S1 (under the minimum age); the cascade stopped before the notes."""
    t = PatientTrace(f"pseudo{i:06d}", IDX, tier="excluded")
    t.outcomes["T-INC-01"] = Outcome("T-INC-01", "fail", "S1", hard=True, reason="age below the minimum")
    for c in CRITS[1:11]:
        t.outcomes[c.id] = Outcome(c.id, "pass", "S1", reason="no record")
    return t


def test_excluded_patients_are_held_compactly() -> None:
    n = 3000
    traces = [_excluded(i) for i in range(n)]
    verdicts_of(RS, traces[0], policy=POLICY)  # the shared answers exist before the count
    owned = not tracemalloc.is_tracing()  # a session run with -X tracemalloc keeps its own traces (review R2)
    if owned:
        tracemalloc.start()
    try:
        before = tracemalloc.take_snapshot()
        results = {t.pid: verdicts_of(RS, t, policy=POLICY) for t in traces}
        grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(before, "filename"))
    finally:
        if owned:
            tracemalloc.stop()
    assert all(r.tier == "excluded" for r in results.values())
    per = grown / n
    # 21 criteria a patient: one CriterionVerdict and one Evidence each was about 21 x 1.5 KB; now the row's own list
    assert per < 2048, f"{per:.0f} bytes held per excluded patient"


def test_a_shared_answer_is_never_another_patients() -> None:
    """Review of #1594, R1: two patients with the same shared answers (a coded "no record" and a "not evaluated"
    row); a caller that changes one patient's lists changes nothing for the other, nor for a later patient."""
    a, b = (verdicts_of(RS, _excluded(i), policy=POLICY) for i in (1, 2))
    coded, skipped = 1, 15  # T-EXC-00 (no record at S1) and T-EXC-14 (the cascade stopped before it)
    assert a.verdicts[coded].evidence is not None and a.verdicts[skipped].evidence is not None
    for i in (coded, skipped):
        v = a.verdicts[i]
        assert v.evidence is not None and v.prov is not None
        v.evidence.resource_refs.append("Condition/pseudo-a")  # type: ignore[union-attr]
        v.prov.append("call-a")
    c = verdicts_of(RS, _excluded(3), policy=POLICY)  # a later lookup of the same answers
    one = verdict_of(Outcome(CRITS[1].id, "pass", "S1", reason="no record"))
    for pv in (a, b, c):
        for v in (pv.verdicts[coded], pv.verdicts[skipped]):
            assert v.evidence is not None and v.evidence.resource_refs == [] and v.prov == []
    assert one.evidence is not None and one.evidence.resource_refs == [] and one.prov == []
    assert a.verdicts[coded] is not a.verdicts[coded]  # each read is the reader's own


def _containers(x: Any) -> list[Any]:
    """Every list and dict reachable from a verdict row (its models' fields, recursively)."""
    if isinstance(x, BaseModel):
        return [c for f in type(x).model_fields for c in _containers(getattr(x, f))]
    if isinstance(x, list):
        return [x] + [c for y in x for c in _containers(y)]
    if isinstance(x, dict):
        return [x] + [c for y in x.values() for c in _containers(y)]
    return []


def test_every_container_of_a_read_row_is_the_readers_own() -> None:
    """Review of #1610, R1: every nested list and dict of every row one patient reads (by index and by slice) is
    changed in place; no other patient's row, no stored shared row and no later read of the same answers changes."""
    a, b = (verdicts_of(RS, _excluded(i), policy=POLICY) for i in (1, 2))
    shared = [r.proto for r in a.verdicts._rows if isinstance(r, _Shared)]  # type: ignore[attr-defined]
    assert len(shared) == len(a.verdicts) == len(CRITS)  # every row of an excluded patient is a shared answer
    before = [v.model_dump() for v in b.verdicts]
    assert [v.model_dump() for v in shared] == before  # the stored rows, as a patient reads them
    n = 0
    for v in [*a.verdicts, *a.verdicts[:]]:  # every row by index (iteration) and by slice
        for c in _containers(v):
            if isinstance(c, list):
                c.append("pseudo-a")
            else:
                c["pseudo-a"] = 1
            n += 1
    assert n >= 2 * 2 * len(shared)  # each row's refs and calls at least, read twice
    c = verdicts_of(RS, _excluded(3), policy=POLICY)  # a later lookup of the same cached answers
    for rows in (b.verdicts, shared, c.verdicts, a.verdicts):  # a's stored rows read again are the shared ones
        assert [v.model_dump() for v in rows] == before
