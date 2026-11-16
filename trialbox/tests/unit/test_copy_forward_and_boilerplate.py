"""Lane G's review (#639, 2026-11-15), card 3: copy-forward notes, boilerplate and long inputs.

* **Copy-forward.** A note whose text is the same as a newer note's in the window (whitespace aside) is shown once,
  as the newest copy. The older copies are neither shown nor counted as left out: the models read every word.
* **Boilerplate.** A sentence that recurs in at least three notes of the window (a template line, a disclaimer) is
  not embedded for S2b: it would rank every note alike. It stays in every text the judge reads.
* **Long inputs.** A sentence longer than the embed window is embedded as overlapping windows, and its score is its
  best window's: the service cuts an input at its cap, which would leave the end of a long report unscored.

Synthetic notes.
"""

from __future__ import annotations

from datetime import date

from matching import excerpts
from matching.cascade.s2b_semantic import PUBLIC_PRIOR_THRESHOLD, Threshold, boilerplate, screen, windows


def _note(did: str, d: date, text: str) -> excerpts.Note:
    return excerpts.Note(did, d, "progress", text, excerpts.sentences(text))


def test_a_copied_forward_note_is_shown_once_and_not_counted_as_left_out() -> None:
    body = "Gout since 2019.\nOn allopurinol 300 mg daily."
    window = [_note("n1", date(2026, 7, 1), body), _note("n2", date(2026, 8, 1), body + "  \n"),
              _note("n3", date(2026, 9, 1), "Knee swollen today.")]  # fmt: skip
    got = excerpts.build(window, {}, 10_000)
    assert [x["did"] for x in got.shown] == ["n3", "n2"] and got.left_out == 0
    assert got.duplicates == ["n1"]


def test_boilerplate_sentences_are_not_embedded_but_stay_in_the_text() -> None:
    line = "This note was dictated and may contain errors."
    texts = [f"{line}\nKnee pain.", f"{line}\nBlood pressure stable.", f"{line}\nNo tuberculosis history."]
    window = [_note(f"n{i}", date(2026, 9, i + 1), t) for i, t in enumerate(texts)]
    sents = [s for n in window for s in (n.sents or [])]
    skip = boilerplate([list(n.sents or []) for n in window])
    assert line in skip and "Knee pain." not in skip
    shown = excerpts.build(window, {}, 10_000).shown
    assert all(line in x["text"] for x in shown)  # the judge reads it
    assert len([s for s in sents if s not in skip]) == 3


class _Recorder:
    model = "rec"

    def __init__(self) -> None:
        self.inputs: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.inputs += texts
        return [[1.0, 0.0] if "tuberculosis" in t else [0.0, 1.0] for t in texts]


def test_a_long_sentence_is_scored_by_its_best_window() -> None:
    long = "Filler words about routine follow-up. " * 60 + "Active tuberculosis on treatment."
    assert len(windows(long)) > 1 and all(len(w) <= 600 for w in windows(long))
    rec = _Recorder()
    thr = Threshold(PUBLIC_PRIOR_THRESHOLD, "public_prior", "x")
    got = screen(rec, "tuberculosis", ["Short line.", long], thr)
    assert got.top[0][0] == 1 and got.best > 0.99  # the decisive end of the long sentence scored
    assert max(len(t) for t in rec.inputs) <= 600 and len(rec.inputs) > 3


def test_a_copy_not_shown_leaves_its_first_date_on_the_note_that_is_and_the_models_read_it() -> None:
    """D-941 (review of D-940): "last dose given today" copied forward from January into June was read only under
    June's date, so a washout criterion would read the dose as June. The note shown says when the same text was first
    written and how many other copies there are, and both judge paths send it (review of D-941: they sent only the
    date, note type and text)."""
    from matching.cascade.judge import GatewayJudge
    from tb_llm import budget

    body = "Last dose of pembrolizumab given today."
    window = [_note("n1", date(2026, 1, 10), body), _note("n2", date(2026, 3, 2), body + "\n"),
              _note("n3", date(2026, 6, 10), body), _note("n4", date(2026, 6, 20), "Seen for follow-up.")]  # fmt: skip
    got = excerpts.build(window, {}, 10_000)
    by = {x["did"]: x for x in got.shown}
    assert sorted(by) == ["n3", "n4"] and got.duplicates == ["n2", "n1"]
    first, many = budget.COPIES
    assert (by["n3"][first], by["n3"][many]) == ("2026-01-10", 2)
    assert first not in by["n4"]  # a note with no copy says nothing of copies
    # what a model is shown, on every path: never the record's id, the copies' two values where there are copies
    sent = [budget.shown(e) for e in got.shown]
    assert sent[0] == {"date": "2026-06-20", "note_type": "progress", "text": "Seen for follow-up."}
    assert sent[1] == {"date": "2026-06-10", "note_type": "progress", "text": body, first: "2026-01-10", many: 2}
    import inspect

    from orchestrator.scenarios import evaluate

    assert "budget.shown(e)" in inspect.getsource(GatewayJudge.judge)  # the cascade's judge and verifier
    assert "shown_excerpt(e)" in inspect.getsource(evaluate.NoteJudge.judge_excerpts)  # v1 evaluate, CASE


def test_the_copies_are_counted_in_the_budget_and_never_grow_with_them() -> None:
    body = "Last dose given today."
    window = [_note(f"n{i}", date(2026, 1, 1 + i), body) for i in range(20)]
    (one,) = excerpts.build(window, {}, 10_000).shown
    from tb_llm import budget

    assert one[budget.COPIES[1]] == 19
    assert budget.excerpt_tokens(one) > budget.excerpt_tokens({k: one[k] for k in budget.SHOWN})
    tight = budget.excerpt_tokens({k: one[k] for k in budget.SHOWN})  # room for the text only, not the copies
    assert excerpts.build(window, {}, tight).shown == []  # it is not squeezed in over the budget


def test_a_copy_of_the_same_day_adds_no_date() -> None:
    body = "Gout since 2019."
    window = [_note("n1", date(2026, 7, 1), body), _note("n2", date(2026, 7, 1), body)]
    (shown,) = excerpts.build(window, {}, 10_000).shown
    from tb_llm import budget

    assert budget.COPIES[0] not in shown
