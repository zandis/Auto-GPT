"""D-653: whether the values behind a row's coded answers were read is kept per row, by the run that last read it.

D-652 kept it per run, in the screening run's stored list of excluded patients. A weekly or after-ingest run
(MICROBATCH) publishes the candidate list and no such list, and the console's pages read the study's latest run:
the sentence "the values could not be read" went away as soon as a weekly run was the latest, though the rows it
carried from the screening run still had no values; and a weekly run whose own read failed never said so at all.

Now the answer itself carries it (``evidence.coded_read: false``), so it travels with the row through the pool; a
row of the candidate list says ``coded_values: "not read"`` while any of its answers does; a run that reads the row
again writes its answers anew, and the mark goes."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from matching import coded_values
from orchestrator.scenarios import screen
from orchestrator.scenarios.evaluate import PatientVerdicts, row
from orchestrator.scenarios.screen import ScreenRun
from tb_contracts import CriterionVerdict, Evidence, dump

from tests.unit.test_microbatch_cadence import FRI, GZQO, _Box, _new, _pool_row, _verdicts

CODED = next(c for c in GZQO.active() if c.class_ == "structured" and c.kind == "exclusion")
NOTE = next(c for c in GZQO.active() if c.class_ == "note")
RUN = date(2026, 10, 5)


class _Down:
    def query(self, *a: Any, **k: Any) -> Any:
        raise OSError("lake down")


class _Empty:
    """A lake that answers every read with no row."""

    def query(self, *a: Any, **k: Any) -> Any:
        return SimpleNamespace(to_pylist=list)


def _answers() -> list[CriterionVerdict]:
    return [
        CriterionVerdict(
            id=CODED.id, verdict="fail", basis="coded", evidence=Evidence(resource_refs=["Condition/c-1"])
        ),
        CriterionVerdict(
            id=NOTE.id, verdict="pass", evidence=Evidence(quote="q", resource_refs=["DocumentReference/d1"])
        ),
    ]


def _marked(vs: list[CriterionVerdict]) -> list[str]:
    return [v.id for v in vs if v.evidence is not None and v.evidence.coded_read is False]


# ------------------------------------------------------------------------------------------------ the answer
def test_a_failed_read_marks_the_coded_answers_it_would_have_read_and_nothing_else() -> None:
    vs = _answers()
    before = [(v.id, v.verdict) for v in vs]
    assert coded_values.attach(_Down(), GZQO.active(), {"P1": vs}, RUN, None) is None
    assert _marked(vs) == [CODED.id]  # the note's answer has no coded record behind it
    # an age or sex answer reads the patient's row: marked too; a note answer of the same patient is not
    age = next(c for c in GZQO.active() if any(coded_values._demographic(c)))
    person = [CriterionVerdict(id=age.id, verdict="pass", evidence=Evidence(resource_refs=[])), _answers()[1]]
    assert coded_values.attach(_Down(), GZQO.active(), {"P1": person}, RUN, None) is None
    assert _marked(person) == [age.id]
    assert [(v.id, v.verdict) for v in vs] == before and vs[0].evidence is not None and vs[0].evidence.coded is None


def test_a_read_that_is_made_takes_the_mark_away() -> None:
    vs = _answers()
    coded_values.attach(_Down(), GZQO.active(), {"P1": vs}, RUN, None)
    assert _marked(vs) == [CODED.id]
    assert coded_values.attach(_Empty(), GZQO.active(), {"P1": vs}, RUN, None) is not None
    assert _marked(vs) == []  # read again (and no record found): no longer "not read"


def test_a_row_says_not_read_while_one_of_its_answers_does() -> None:
    vs = _answers()
    coded_values.attach(_Down(), GZQO.active(), {"P1": vs}, RUN, None)
    unread = row(PatientVerdicts("P1", vs, "review", [], 0), None, "D1", "RHEU", "2026-10-07T03:00:00+09:00")
    read = row(PatientVerdicts("P2", _answers(), "review", [], 0), None, "D1", "RHEU", "2026-10-07T03:00:00+09:00")
    assert unread.coded_values == "not read" and read.coded_values is None
    dumped = unread.model_dump(mode="json", exclude_none=True)
    assert dumped["coded_values"] == "not read" and "coded_values" not in read.model_dump(
        mode="json", exclude_none=True
    )
    assert [c["id"] for c in dumped["criteria"] if c.get("evidence", {}).get("coded_read") is False] == [CODED.id]


def test_the_screening_runs_list_carries_the_rows_and_the_count() -> None:
    vs = _answers()
    coded_values.attach(_Down(), GZQO.active(), {"P1": vs}, RUN, None)
    rows = [
        row(PatientVerdicts("P1", vs, "review", [], 0), None, "D1", "RHEU", "2026-10-07T03:00:00+09:00"),
        row(PatientVerdicts("P2", _answers(), "high", [], 0), None, "D1", "RHEU", "2026-10-07T03:00:00+09:00"),
    ]
    run = ScreenRun(GZQO, RUN, "2026-10-05", [], {}, rows, [], [], 7, None, coded_values_read=False)
    cl = dump(screen.candidate_list(run))
    assert [r.get("coded_values") for r in cl["rows"]] == ["not read", None]
    assert cl["summary"]["coded_values_not_read"] == 1
    clean = ScreenRun(GZQO, RUN, "2026-10-05", [], {}, rows[1:], [], [], 7, None)
    assert "coded_values_not_read" not in dump(screen.candidate_list(clean))["summary"]  # as before the card


# --------------------------------------------------------------------------------------- the weekly run after it
def _mark(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """As a screening run whose read failed left them in the pool."""
    for v in verdicts:
        if v["id"] == CODED.id:
            v["evidence"]["resource_refs"] = ["Condition/c-1"]
            v["evidence"]["coded_read"] = False
    return verdicts


def _list(box: _Box) -> dict[str, Any]:
    name = next(n for n in box.published if n.startswith("candidate_list_"))
    doc: dict[str, Any] = json.loads(box.published[name])
    return doc


def test_a_weekly_run_keeps_not_read_on_the_rows_it_carries_and_not_on_the_rows_it_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A screening run's read failed; then a weekly run is the study's latest. The rows it carries from the pool
    still have no values and say so; the patients it screens itself were read."""
    box = _Box(pool=["P1", "P2"], booked={"P1": FRI, "P2": FRI}, scope=[_new("N1", FRI)])
    box.pool = [{**_pool_row("P1"), "verdicts": _mark(_pool_row("P1")["verdicts"])}, _pool_row("P2")]
    box.go(monkeypatch)
    by = {r["pid"]: r for r in _list(box)["rows"]}
    assert by["P1"].get("coded_values") == "not read"
    assert "coded_values" not in by["P2"] and "coded_values" not in by["N1"]
    assert _list(box)["summary"]["coded_values_not_read"] == 1


def test_a_weekly_run_whose_own_read_failed_says_so_on_the_rows_it_read(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing(_Box):
        def run_screen(
            self, ctx: Any, rs: Any, run_date: date, snapshot: str, select: Any = None, scope: Any = None
        ) -> Any:
            out = super().run_screen(ctx, rs, run_date, snapshot, select, scope)
            marked = []
            for r in out.rows:  # as the real run leaves them when its read of the values fails
                vs = [
                    CriterionVerdict.model_validate(v) for v in _mark([c.model_dump(mode="json") for c in r.criteria])
                ]
                marked.append(row(PatientVerdicts(r.pid, vs, r.tier, [], 0), r.next_appointment, "D1", "RHEU", FRI))
            out.rows = marked
            return out

    box = Failing(pool=["P1"], booked={"P1": FRI}, scope=[_new("N1", FRI)])
    box.go(monkeypatch)
    by = {r["pid"]: r for r in _list(box)["rows"]}
    assert by["N1"].get("coded_values") == "not read" and "coded_values" not in by["P1"]
    assert _list(box)["summary"]["coded_values_not_read"] == 1


def test_a_weekly_run_with_nothing_unread_writes_the_list_as_before_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _Box(pool=["P1"], booked={"P1": FRI}, scope=[_new("N1", FRI)])
    box.go(monkeypatch)
    doc = _list(box)
    assert all("coded_values" not in r for r in doc["rows"]) and "coded_values_not_read" not in doc["summary"]
    assert "coded_read" not in json.dumps(doc) and _verdicts()
