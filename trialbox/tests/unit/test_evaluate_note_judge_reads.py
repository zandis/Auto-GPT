"""What the note judge reads and how it answers a cut record (``orchestrator.scenarios.evaluate``, safety core).

The nightly mutation run left the window, the token budgets, the cut-record rule and the failure paths of
``NoteJudge`` without a test that fails when they change (rc1 line 1, mutation floor 60 %). Each test here says what
the code must do, with synthetic notes only:

* the window of a note criterion: a year back unless the criterion names a shorter one, never longer;
* the token room of a prompt: the smaller of the judge's and the verifier's, at most the default, None when neither
  client can tell;
* the window read: its dates, its ranking query and its budget reach the lake and the builder;
* a patient with no notes, or whose notes all over the budget, is unknown with the reason that says which;
* a record the budget cut: an answer that would exclude is unknown, an answer that keeps the patient stands flagged;
* a model that fails, a prompt too long and a hold on note reading each become unknown with their own reason, and
  the failures stop a job past their share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any

import orchestrator.scenarios.evaluate as ev
import pytest
from orchestrator.clients import StepFailed
from orchestrator.scenarios.evaluate import NoteJudge, NoteResult, note_window
from tb_common.llm import LlmError, LlmPromptTooLong
from tb_common.reasons import Reason

DAY = date(2026, 11, 1)


def _c(kind: str = "inclusion", from_days: int | None = None, question: str = "") -> Any:
    window = None if from_days is None else SimpleNamespace(from_days=from_days)
    return SimpleNamespace(
        id="X-1", kind=kind, text="the criterion text", note_question=question, logic=SimpleNamespace(window=window)
    )


# ------------------------------------------------------------------------------------------------ the window
def test_a_note_window_is_a_year_unless_the_criterion_names_a_shorter_one() -> None:
    assert note_window(_c(), DAY) == (date(2025, 11, 1), DAY)  # none named: 365 days back
    assert note_window(_c(from_days=-30), DAY) == (date(2026, 10, 2), DAY)  # shorter: honoured
    assert note_window(_c(from_days=-365), DAY) == (date(2025, 11, 1), DAY)  # as long as the year: the year
    assert note_window(_c(from_days=-400), DAY) == (date(2025, 11, 1), DAY)  # longer: never more than the year
    assert note_window(_c(from_days=0), DAY) == (DAY, DAY)  # today only
    no_window = SimpleNamespace(logic=SimpleNamespace(window=SimpleNamespace(from_days=None)))
    assert note_window(no_window, DAY) == (date(2025, 11, 1), DAY)  # a window with no start


# ------------------------------------------------------------------------------------------------ token room
@dataclass
class Client:
    room: Any = None  # what text_budget answers
    asked: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def text_budget(self, prompt: str, fixed: dict[str, Any]) -> Any:
        self.asked.append((prompt, fixed))
        return self.room


def _judge(llm: Any = None, verifier: Any = None, lake: Any = None, **kw: Any) -> NoteJudge:
    return NoteJudge(lake, llm if llm is not None else Client(), verifier=verifier, **kw)


def test_the_room_of_a_prompt_is_the_smaller_of_the_two_models_and_at_most_the_default() -> None:
    j = _judge(Client(9000), Client(7000))
    assert j.excerpt_budget(_c(), DAY) == 7000 and j.budget(_c(), DAY, 20000) == 7000
    assert j.budget(_c(), DAY, 5000) == 5000  # the default caps it
    assert _judge(Client(3000), Client(8000)).excerpt_budget(_c(), DAY) == 3000
    assert _judge(Client(4000)).excerpt_budget(_c(), DAY) == 4000  # no verifier: the judge's alone


def test_a_model_that_cannot_tell_its_context_leaves_the_default() -> None:
    j = _judge(Client(None), Client(None))
    assert j.excerpt_budget(_c(), DAY) is None and j.budget(_c(), DAY, 12345) == 12345
    assert _judge(Client("many"), None).budget(_c(), DAY, 800) == 800  # an answer that is not a number is none
    assert _judge(SimpleNamespace(), None).excerpt_budget(_c(), DAY) is None  # a client with no text_budget at all
    assert _judge(Client(None), Client(6000)).excerpt_budget(_c(), DAY) == 6000  # one of two can tell


def test_the_room_is_asked_with_the_criterion_its_question_and_no_excerpts() -> None:
    llm = Client(1000)
    j = _judge(llm)
    j.excerpt_budget(_c(question="Is it?"), DAY)
    j.excerpt_budget(_c(), DAY)
    (prompt, fixed), (_, plain) = llm.asked
    assert prompt == "judge"
    assert fixed == {
        "criterion_text": "the criterion text",
        "note_question": "Is it?",
        "index_date": "2026-11-01",
        "excerpts": [],
    }
    assert plain["note_question"] == "the criterion text"  # no question of its own: the text
    llm.asked.clear()
    j.budget(_c(question="Is it?"), DAY, 99)
    assert llm.asked[0][1] == fixed  # budget() asks the same


# ------------------------------------------------------------------------------------------------ the read
class Lake:
    def __init__(self, rows: list[dict[str, Any]], hits: list[dict[str, Any]]) -> None:
        self.rows, self.hits = rows, hits
        self.queries: list[tuple[str, list[Any]]] = []
        self.searches: list[tuple[Any, ...]] = []

    def query(self, sql: str, params: list[Any]) -> Any:
        self.queries.append((sql, params))
        return SimpleNamespace(to_pylist=lambda: self.rows)

    def chunks_search(self, pid: str, query: str, k: int, date_from: date, date_to: date) -> list[dict[str, Any]]:
        self.searches.append((pid, query, k, date_from, date_to))
        return self.hits


ROWS = [
    {"did": "D2", "d": date(2026, 10, 20), "type": "progress", "text": "newer note about gout"},
    {"did": "D1", "d": date(2026, 10, 1), "type": None, "text": "older note, no type, on the knee"},
]


def test_the_window_read_asks_the_lake_for_the_criterions_dates_and_ranks_by_the_question() -> None:
    lake = Lake(ROWS, [{"did": "D2", "text": "gout"}, {"did": None, "text": "x"}, {"did": "D2"}])
    got = _judge(Client(None), lake=lake).window("P1", _c(from_days=-30, question="Gout?"), DAY)
    sql, params = lake.queries[0]
    assert sql == ev.DOCUMENT_SQL and params == ["P1", "2026-10-02", "2026-11-01"]
    ((pid, query, k, lo, hi),) = lake.searches
    assert (pid, k, lo, hi) == ("P1", ev.RANKING_CHUNKS, date(2026, 10, 2), DAY) and ev.RANKING_CHUNKS == 5
    assert query.startswith("Gout?")  # the note question, then the criterion's keywords
    assert [e["did"] for e in got.shown] == ["D2", "D1"]  # both notes, the newer one first
    assert got.left_out == 0


def test_a_window_with_no_notes_does_not_search() -> None:
    lake = Lake([], [{"did": "D1", "text": "x"}])
    got = _judge(lake=lake).window("P1", _c(), DAY)
    assert lake.searches == [] and got.shown == [] and got.left_out == 0


def test_a_window_too_small_for_its_notes_counts_what_it_leaves_out() -> None:
    rows = [
        {"did": f"D{i}", "d": date(2026, 10, i + 1), "type": "progress", "text": f"visit {i} " + "word " * 400}
        for i in range(6)
    ]
    got = _judge(Client(900), lake=Lake(rows, [])).window("P1", _c(), DAY)  # room for about one note
    assert 0 < len(got.shown) < 6 and got.left_out > 0
    assert len(got.shown) + got.left_out == 6  # nothing is lost silently: shown or counted


def test_a_judge_with_no_lake_cannot_read_a_window() -> None:
    with pytest.raises(RuntimeError, match="no lake"):
        _judge(lake=None).window("P1", _c(), DAY)


def test_full_record_and_excerpts_are_the_windows_shown_notes() -> None:
    j = _judge(Client(None), lake=Lake(ROWS, []))
    assert [e["did"] for e in j.full_record("P1", _c(), DAY)] == ["D2", "D1"]
    assert [e["did"] for e in j.excerpts("P1", _c(), DAY)] == ["D2", "D1"]


# ------------------------------------------------------------------------------------------------ judge_patient
def _window(shown: list[dict[str, Any]], left_out: int) -> Any:
    return SimpleNamespace(shown=shown, left_out=left_out)


class Seen(NoteJudge):
    """A judge whose window and answer are given, to see what judge_patient hands on."""

    given: Any = None
    handed: tuple[Any, ...] = ()

    def window(self, pid: str, c: Any, index_date: date) -> Any:  # type: ignore[override]
        return self.given

    def judge_window(self, c: Any, index_date: date, excerpts: Any, left_out: int, source: str) -> NoteResult:
        self.handed = (excerpts, left_out, source)
        return NoteResult("pass", 0.9)


def _seen(window: Any) -> Seen:
    j = Seen(None, Client())
    j.given = window
    return j


def test_a_patient_with_no_notes_is_unknown_with_the_reason_no_notes() -> None:
    r = _seen(_window([], 0)).judge_patient("P1", _c(), DAY)
    assert (r.predicate, r.confidence, r.reason, r.source, r.left_out) == (
        "unknown",
        0.0,
        Reason.NO_NOTES.value,
        "full_record",
        0,
    )


def test_a_patient_whose_notes_all_left_the_budget_is_unknown_over_budget() -> None:
    r = _seen(_window([], 3)).judge_patient("P1", _c(), DAY)
    assert (r.predicate, r.reason, r.source, r.left_out) == ("unknown", Reason.NOTES_OVER_BUDGET.value, "chunks", 3)


def test_shown_notes_go_to_the_models_with_what_was_left_out_and_where_they_came_from() -> None:
    shown = [{"did": "D1"}]
    j = _seen(_window(shown, 0))
    assert j.judge_patient("P1", _c(), DAY).predicate == "pass"
    assert j.handed == (shown, 0, "full_record")  # the whole window was read
    j2 = _seen(_window(shown, 2))
    j2.judge_patient("P1", _c(), DAY, full=True)  # full changes nothing
    assert j2.handed == (shown, 2, "chunks")


# ------------------------------------------------------------------------------------------------ judge_window
class Answer(NoteJudge):
    answer: NoteResult = NoteResult("pass", 0.8, quote="q", quote_date="2026-10-01", dids=["D1"])

    def judge_excerpts(self, text: str, question: str, index_date: date, excerpts: Any, source: str) -> NoteResult:  # type: ignore[override]
        self.asked = (text, question, index_date, excerpts, source)
        return self.answer


def _answering(predicate: str) -> Answer:
    j = Answer(None, Client())
    j.answer = NoteResult(predicate, 0.8, quote="q", quote_date="2026-10-01", dids=["D1"], source="chunks")
    return j


def test_the_models_are_asked_the_note_question_or_else_the_criterion_text() -> None:
    j = _answering("pass")
    j.judge_window(_c(question="Q?"), DAY, [{"did": "D1"}], 0, "chunks")
    assert j.asked == ("the criterion text", "Q?", DAY, [{"did": "D1"}], "chunks")
    j.judge_window(_c(), DAY, [], 0, "full_record")
    assert j.asked[:2] == ("the criterion text", "the criterion text")


def test_a_whole_record_answers_as_the_models_said() -> None:
    r = _answering("fail").judge_window(_c(), DAY, [{"did": "D1"}], 0, "chunks")
    assert r.predicate == "fail" and r.reason is None and r.left_out == 0


def test_a_cut_record_never_excludes() -> None:
    # an exclusion criterion the models found (pass) would exclude the patient: with notes left out it is unknown
    r = _answering("pass").judge_window(_c("exclusion"), DAY, [{"did": "D1"}], 2, "chunks")
    assert (r.predicate, r.confidence, r.quote, r.quote_date, r.dids) == ("unknown", 0.0, None, None, [])
    assert (r.reason, r.left_out) == (Reason.NOTES_OVER_BUDGET.value, 2)
    # an inclusion the models did not find (fail) would exclude too
    r = _answering("fail").judge_window(_c("inclusion"), DAY, [{"did": "D1"}], 1, "chunks")
    assert (r.predicate, r.reason, r.left_out) == ("unknown", Reason.NOTES_OVER_BUDGET.value, 1)


def test_a_cut_record_that_keeps_the_patient_stands_flagged() -> None:
    r = _answering("pass").judge_window(_c("inclusion"), DAY, [{"did": "D1"}], 2, "chunks")
    assert (r.predicate, r.quote, r.dids) == ("pass", "q", ["D1"])  # the answer is kept
    assert (r.reason, r.left_out) == (Reason.NOTES_OVER_BUDGET.value, 2)  # and flagged for review
    r = _answering("fail").judge_window(_c("exclusion"), DAY, [{"did": "D1"}], 1, "chunks")
    assert (r.predicate, r.reason, r.left_out) == ("fail", Reason.NOTES_OVER_BUDGET.value, 1)


def test_a_cut_record_with_no_answer_stays_unknown_and_says_what_was_left_out() -> None:
    r = _answering("unknown").judge_window(_c("exclusion"), DAY, [{"did": "D1"}], 4, "chunks")
    assert (r.predicate, r.left_out, r.reason) == ("unknown", 4, None)


# ------------------------------------------------------------------------------------------------ _ask
class Raises:
    gateway = None

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def chat_json(self, prompt: str, variables: dict[str, Any], job_id: str | None = None) -> Any:
        raise self.exc


def _ask(j: NoteJudge, client: Any) -> NoteResult:
    return j._ask(client, {}, [], "chunks")


def test_a_prompt_too_long_is_unknown_over_budget_and_counts_as_a_failure() -> None:
    j = _judge()
    r = _ask(j, Raises(LlmPromptTooLong("long")))
    assert (r.predicate, r.confidence, r.reason, r.source) == ("unknown", 0.0, Reason.NOTES_OVER_BUDGET.value, "chunks")
    assert (j.failures, j.calls) == (1, 0)


def test_a_model_that_does_not_answer_is_unknown_model_down_and_counts_as_a_failure() -> None:
    j = _judge()
    r = _ask(j, Raises(LlmError("down")))
    assert (r.predicate, r.reason, r.source) == ("unknown", Reason.MODEL_DOWN.value, "chunks")
    assert (j.failures, j.calls) == (1, 0)


def test_while_note_reading_is_held_no_model_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "notes_held", lambda: True)
    j = _judge()
    r = _ask(j, Raises(AssertionError("a model was asked during a hold")))
    assert (r.predicate, r.reason) == ("unknown", Reason.NOT_EVALUATED.value)
    assert (j.held, j.failures, j.calls) == (1, 0, 0)


def test_a_gateway_answer_with_no_build_is_no_answer() -> None:
    class NoBuild:
        gateway = object()

        def chat_json(self, prompt: str, variables: dict[str, Any], job_id: str | None = None) -> Any:
            return SimpleNamespace(build_sha="", tokens_in=5, tokens_out=3)

    j = _judge()
    r = _ask(j, NoBuild())
    assert (r.predicate, r.reason) == ("unknown", Reason.MODEL_DOWN.value) and (j.failures, j.calls) == (1, 0)


# ------------------------------------------------------------------------------------------------ the share
def test_failures_stop_a_running_job_past_their_share_and_not_before() -> None:
    j = _judge(in_flight=1)
    need = ev.running_share_min(1)
    assert need == 20  # two full rounds of the one call in flight are exactly the share
    j._count(calls=need - 3)
    j._count(failures=1)  # 1 of need - 2: under the minimum, never stops
    j._count(failures=1)  # 2 of need - 1: still under the minimum
    with pytest.raises(StepFailed, match="did not answer 3 of 20 note checks so far"):
        j._count(failures=1)  # 3 of 20 at the minimum: 15 %, past 10 %


def test_a_job_with_no_calls_in_flight_is_judged_only_at_its_end() -> None:
    j = _judge(in_flight=0)
    j._count(calls=1)
    j._count(failures=5)  # 5 of 6, but nothing is in flight: no stop while it runs
    assert (j.calls, j.failures) == (1, 5)


def test_the_share_that_is_exactly_the_limit_does_not_stop_a_job() -> None:
    j = _judge(in_flight=1)
    j._count(calls=18)
    j._count(failures=1)
    j._count(failures=1)  # 2 of 20: 10 %, not past it
    assert j.failures == 2


def test_the_minimum_checks_grow_with_the_calls_in_flight() -> None:
    assert [ev.running_share_min(n) for n in (0, 1, 4, 16)] == [20, 20, 80, 320]
    assert ev.MAX_JUDGE_FAILURE_SHARE == 0.1


def test_a_failure_share_over_a_tenth_stops_a_finished_job() -> None:
    j = _judge()
    j.calls, j.failures = 18, 2
    ev.check_judge(j)  # 2 of 20: exactly a tenth passes
    j.failures = 3
    with pytest.raises(StepFailed, match="3 of 21 note checks"):
        ev.check_judge(j)
