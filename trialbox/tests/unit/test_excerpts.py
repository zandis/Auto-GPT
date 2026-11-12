"""One excerpt builder (T-710, D-479): ``matching.excerpts.build`` and the three paths that call it.

The paths against each other and the oracle that reads what it is shown are ``tests/property/`` (T-705, T-706).
Here: the builder's rules as cases, the budget from the models' context, and the row's acceptance case (a patient
with five long notes on a 32k build).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from matching import excerpts
from matching.cascade import engine as cascade_engine
from matching.excerpts import DEFAULT_TOKENS, Note, build, clip, note_tokens, sentences
from orchestrator.scenarios import evaluate
from orchestrator.scenarios.case import ChartJudge
from orchestrator.scenarios.evaluate import NoteJudge, evaluate_patients

from tests.judge_kit import ScriptedModel, ruleset, says
from tests.unit.test_context_budgets import GOOD, INDEX, LINE, PROFILES, _box, _client, _Lake
from tests.unit.test_screen_exclusion_pair import FLARE, IDX, INC, _chunk, _Chunks, _NoStructured

FILLER = "Routine follow-up, vitals stable, no change in plan.\n"  # a note's sentences are its lines


def _n(did: str, day: str, text: str) -> Note:
    return Note(did, date.fromisoformat(day), "progress", text)


# ------------------------------------------------------------------------------------------------ the builder
def test_every_window_note_is_shown_while_it_fits_and_nothing_is_left_out() -> None:
    window = [_n("b", "2026-09-01", "Uric acid 9.1."), _n("a", "2026-10-01", "Gout flare."), _n("c", "2026-08-01", "x")]
    got = build(window, {"a": ["Gout flare."]}, 1000)
    assert [e["did"] for e in got.shown] == ["a", "b", "c"]  # newest first, whatever the ranking
    assert got.left_out == 0 and got.cut == []
    assert got.shown[0] == {"date": "2026-10-01", "note_type": "progress", "text": "Gout flare.", "did": "a"}


def test_the_evidence_notes_are_read_first_and_the_rest_counts_as_left_out() -> None:
    """The ranking decides what is read first, never what counts as read (review H4)."""
    long = FILLER * 40
    window = [_n("new", "2026-10-01", long), _n("mid", "2026-09-01", long), _n("old", "2026-08-01", "Gout flare.")]
    one = note_tokens(long)
    got = build(window, {"old": ["Gout flare."]}, one + note_tokens("Gout flare.") + 5)
    assert [e["did"] for e in got.shown] == ["new", "old"]  # the evidence note, then the newest that fits
    assert got.left_out == 1 and got.cut == ["mid"]
    none = build(window, {}, one + 5)  # no ranking: newest first, and the decisive old note is left out
    assert [e["did"] for e in none.shown] == ["new"] and none.left_out == 2


def test_a_note_that_does_not_fit_is_cut_around_its_evidence_and_counts_as_left_out() -> None:
    key = "右第一MTP関節の急性痛風発作。"
    long = FILLER * 400 + key + "\n" + FILLER * 400
    got = build([_n("n", "2026-10-01", long), _n("o", "2026-09-01", "Colchicine given.")], {"n": [key]}, 600)
    by = {e["did"]: e["text"] for e in got.shown}
    assert key in by["n"] and len(by["n"]) < len(long) and note_tokens(by["n"]) <= 300  # half the budget
    assert by["o"] == "Colchicine given."  # one long note never hides the others (D-142, review A-06)
    assert got.left_out == 1 and got.cut == ["n"]  # cut: not read in full, whatever is shown of it
    assert all(s in long for s in by["n"].split("\n"))  # whole sentences of the note: a quote is found in it


def test_a_ranking_orders_the_reading_of_its_notes_best_first() -> None:
    """``ranked``: the note the ranking puts first is read first, even when it is the older one."""
    long = FILLER * 40
    window = [_n("new", "2026-10-01", long), _n("old", "2026-08-01", long)]
    budget = note_tokens(long) + 5  # room for one
    by_rank = build(window, {"old": ["x"], "new": ["y"]}, budget, ranked=True)
    assert [e["did"] for e in by_rank.shown] == ["old"] and by_rank.cut == ["new"]
    by_date = build(window, {"old": ["x"], "new": ["y"]}, budget)
    assert [e["did"] for e in by_date.shown] == ["new"] and by_date.cut == ["old"]


def test_a_short_note_that_no_longer_fits_is_skipped_never_shredded() -> None:
    """Only an evidence note longer than half the budget is cut, to that half; the others are whole or absent."""
    note = FILLER * 20
    one = note_tokens(note)
    window = [_n(f"n{i}", f"2026-09-{i:02d}", note) for i in range(1, 7)]
    got = build(window, {n.did: [FILLER.strip()] for n in window}, 2 * one + one // 2)
    assert [e["text"] == note for e in got.shown] == [True, True] and got.left_out == 4


def test_an_empty_note_is_neither_shown_nor_left_out() -> None:
    got = build([_n("e", "2026-10-01", "  \n"), _n("a", "2026-09-01", "Gout flare.")], {}, 1000)
    assert [e["did"] for e in got.shown] == ["a"] and got.left_out == 0


def test_a_note_without_evidence_that_does_not_fit_is_skipped_not_cut() -> None:
    got = build([_n("n", "2026-10-01", FILLER * 400)], {}, 300)
    assert got.shown == [] and got.left_out == 1


def test_a_retrieved_chunk_is_evidence_for_the_sentences_it_holds() -> None:
    """The v1 ranking gives chunks, not sentences: the note is cut around the chunk's sentences."""
    key = "Tophus on the left ear."
    long = FILLER * 300 + key + "\n" + FILLER * 300
    chunk = FILLER + key + "\n" + FILLER
    got = build([_n("n", "2026-10-01", long)], {"n": [chunk]}, 400)
    assert key in got.shown[0]["text"] and got.left_out == 1


def test_clip_and_sentences_are_the_cascades_own() -> None:
    assert sentences("痛風発作。再診予定！\nUric acid 9.1? ok") == ["痛風発作。", "再診予定！", "Uric acid 9.1?", "ok"]
    assert cascade_engine.sentences is sentences  # type: ignore[attr-defined]  # one splitter
    note = _n("n", "2026-10-01", "First.\nSecond.\nThird.")
    assert clip(note, ["Third."], 10_000) == "First.\nSecond.\nThird."
    assert clip(note, ["Third."], note_tokens("Third.") + 2) == "Third."  # the evidence sentence first
    start = clip(_n("n", "2026-10-01", "x" * 4000), [], note_tokens("") + 10)
    assert start == "x" * 40  # one sentence over the cap: the note's start


def test_the_cascade_counts_a_window_note_without_a_hit_as_left_out() -> None:
    """Review H4, the S2 half: a window note with no lexicon hit was neither shown nor counted."""
    hit = cascade_engine._Note("h", date(2026, 10, 1), "progress", "Gout clinic follow-up booked.",
                               ["Gout clinic follow-up booked."])  # fmt: skip
    text = (FILLER * 60) + "Painful swollen red first toe since Monday."
    other = cascade_engine._Note("o", date(2026, 9, 1), "progress", text, sentences(text))
    keep = {"h": {"Gout clinic follow-up booked."}}
    shown, left = cascade_engine._Run.excerpt_set([hit, other], keep, budget=200)
    assert [e["did"] for e in shown] == ["h"] and left == 1  # the other note did not fit: a "not met" is not final
    shown, left = cascade_engine._Run.excerpt_set([hit, other], keep, budget=20_000)
    assert [e["did"] for e in shown] == ["h", "o"] and left == 0  # room for the window: both are read


# ------------------------------------------------------------------------------------------------ the budget
class _Tells(ScriptedModel):
    """A scripted model that tells its context: ``room`` tokens for notes."""

    def __init__(self, model: str, answer: Any, room: int) -> None:
        super().__init__(model, answer)
        self.room = room

    def text_budget(self, prompt: str, fixed: dict[str, Any]) -> int:
        return self.room


def _judge(lake: Any, answer: str, judge_room: int | None, verifier_room: int | None,
           quote: str = FLARE) -> NoteJudge:  # fmt: skip
    def model(name: str, room: int | None) -> Any:
        return _Tells(name, says(answer, quote), room) if room is not None else ScriptedModel(name, says(answer, quote))

    return NoteJudge(lake=lake, llm=model("judge-a", judge_room), verifier=model("verifier-b", verifier_room))


def test_the_budget_is_the_smaller_context_of_the_pair_and_the_default_when_neither_tells() -> None:
    lake = _Chunks([_chunk(1, FLARE)])
    assert _judge(lake, "pass", 20_000, 9_000).excerpt_budget(INC, IDX) == 9_000
    assert _judge(lake, "pass", 20_000, None).excerpt_budget(INC, IDX) == 20_000
    assert _judge(lake, "pass", None, None).excerpt_budget(INC, IDX) is None
    assert DEFAULT_TOKENS == 2500 == cascade_engine.EXCERPT_TOKENS  # the one declared default of both pipelines
    assert not hasattr(evaluate, "CHUNK_TOKENS") and not hasattr(evaluate, "FULL_RECORD_MAX_CANDIDATES")


def test_the_v1_read_counts_a_window_note_the_retrieval_did_not_return() -> None:
    """Review H4, the v1 half: the retrieval returns two notes that say nothing; the third note of the window does
    not fit. Before, nothing was "left out" and both models' "not met" excluded the patient."""

    class Lake(_Chunks):
        def chunks_search(self, pid: str, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
            return [c for c in self.chunks if c["did"] != "D3"]

    lake = Lake([_chunk(1, "Seen in clinic."), _chunk(2, "Seen in clinic."), _chunk(3, f"{FLARE}.\n" + FILLER * 300)])
    nj = _judge(lake, "fail", 1500, 1500, quote="Seen in clinic")
    got = nj.window("P", INC, IDX)
    assert {e["did"] for e in got.shown} == {"D1", "D2"} and got.cut == ["D3"]
    out = evaluate_patients(ruleset([INC]), ["P"], IDX, _NoStructured(), nj, 0.75, only={INC.id}, all_candidates=True)
    v = out["P"].verdicts[0]
    assert out["P"].tier == "review" and v.verdict == "unknown"
    assert v.evidence is not None and v.evidence.reason == "notes_over_budget"
    roomy = _judge(
        lake, "fail", 20_000, 20_000, quote="Seen in clinic"
    )  # control: with room for the window the pair's answer is final
    assert roomy.window("P", INC, IDX).left_out == 0
    out = evaluate_patients(ruleset([INC]), ["P"], IDX, _NoStructured(), roomy, 0.75, only={INC.id},
                            all_candidates=True)  # fmt: skip
    assert out["P"].tier == "excluded"


def test_a_window_with_notes_none_of_which_fits_is_unknown_not_no_notes() -> None:
    class Unranked(_Chunks):  # the retrieval returns nothing: the note is not evidence, so it is skipped, not cut
        def chunks_search(self, pid: str, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
            return []

    nj = _judge(Unranked([_chunk(1, FILLER * 400)]), "fail", 100, 100)
    r = nj.judge_patient("P", INC, IDX)
    assert (r.predicate, r.reason, r.left_out) == ("unknown", "notes_over_budget", 1)
    empty = _judge(_Chunks([]), "fail", 100, 100).judge_patient("P", INC, IDX)
    assert (empty.predicate, empty.reason) == ("unknown", "no_notes")


def test_case_reads_the_chart_through_the_builder_and_the_judges_budget() -> None:
    """CASE showed the whole upload with no budget, and a "not met" on it was final whatever was read."""
    chart = [{"did": f"C{i}", "date": f"2026-09-{i:02d}", "note_type": "progress",
              "text": f"{FLARE}.\nVisit {i}.\n" + FILLER * 60} for i in range(1, 6)]  # fmt: skip
    small = ChartJudge(_judge(None, "fail", 1500, 1500), chart).decide(INC, IDX)
    assert (small.predicate, small.reason) == ("unknown", "notes_over_budget") and small.left_out > 0
    whole = ChartJudge(_judge(None, "fail", 20_000, 20_000), chart).decide(INC, IDX)
    assert whole.predicate == "fail" and whole.left_out == 0


# ------------------------------------------------------------------------------------------------ the acceptance case
@pytest.mark.parametrize(("gpu", "decided"), [("rtxpro6000", True), ("rtx5090", False)])
def test_five_long_notes_get_a_decided_verdict_on_a_32k_build(
    tmp_path: Path, gpu: str, decided: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's acceptance: a patient with five long notes. On the 32k build the pair reads all five (through the
    real gateway and its context) and the answer is decided: ``high``. On the 8k build the same five do not fit:
    the answer is flagged and the patient goes to review, never out."""
    _, rec, app = _box(tmp_path, gpu, monkeypatch)
    lake = _Lake(n=5, lines=100)
    assert all(note_tokens(r["text"]) > 2000 for r in lake.rows)  # long: over 2,000 tokens each
    nj = NoteJudge(
        lake=lake,  # type: ignore[arg-type]
        llm=_client(app, "orchestrator", "j-workhorse"),
        verifier=_client(app, "orchestrator", "v-verifier"),
        job_id="STUDY-1",
    )
    room = nj.excerpt_budget(GOOD, INDEX)
    assert room is not None and 0 < room < PROFILES[gpu]  # from the context, not a fixed number
    got = nj.window("P", GOOD, INDEX)
    assert sum(note_tokens(e["text"]) for e in got.shown) <= room
    assert (got.left_out == 0) == decided and (len(got.shown) == 5) == decided
    out = evaluate_patients(ruleset([GOOD]), ["P"], INDEX, _NoStructured(), nj, 0.0, only={GOOD.id},
                            all_candidates=True)  # fmt: skip
    v = out["P"].verdicts[0]
    assert v.verdict == "pass" and nj.failures == 0, (v, nj.failures, rec.log)
    assert all(status == 200 for _, status in rec.log), rec.log
    assert out["P"].tier == ("high" if decided else "review")
    assert (v.evidence is not None and v.evidence.reason == "notes_over_budget") == (not decided)
    assert LINE in lake.rows[0]["text"] and room > excerpts.DEFAULT_TOKENS
