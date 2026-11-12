"""Review A-06 (R-37, D-142): one long note never hides the rest of a patient's evidence.

The excerpt budget (``EXCERPT_TOKENS``) used to ``break`` at the first note that did not fit: when the newest note
holding an evidence sentence was longer than the budget, the model got no excerpt at all and older notes with the
evidence were never shown. Now a note over half the budget is cut to that half (its evidence sentences first, whole
sentences of the note), and a note that does not fit is skipped while the search goes on.
"""

from __future__ import annotations

from datetime import date

from matching.cascade.engine import EXCERPT_TOKENS, _Note, _Run, sentences
from matching.cascade.judge import expected_tokens


def _note(did: str, d: date, text: str) -> _Note:
    return _Note(did, d, "progress", text, sentences(text))


def test_a_long_newest_note_is_cut_and_older_evidence_still_shown() -> None:
    filler = "Routine follow-up, vitals stable, no change in plan.\n" * 400  # far over the whole budget
    key = "右第一MTP関節の急性痛風発作。"
    long_new = _note("n-new", date(2026, 10, 1), filler + key + "\n" + filler)
    old = _note("n-old", date(2026, 9, 1), "Gout flare treated with colchicine.")
    assert expected_tokens([{"text": long_new.text}]) - 300 > EXCERPT_TOKENS
    out = _Run.excerpts([long_new, old], {"n-new": {key}, "n-old": {"Gout flare treated with colchicine."}})
    assert [x["did"] for x in out] == ["n-new", "n-old"]
    cut = out[0]["text"]
    assert key in cut and len(cut) < len(long_new.text)
    assert expected_tokens([{"text": cut}]) - 300 <= EXCERPT_TOKENS // 2
    assert sum(expected_tokens([{"text": x["text"]}]) - 300 for x in out) <= EXCERPT_TOKENS


def test_short_notes_are_kept_whole_and_newest_first() -> None:
    a = _note("a", date(2026, 10, 2), "Gout flare.")
    b = _note("b", date(2026, 10, 1), "Uric acid 9.1.")
    c = _note("c", date(2026, 9, 1), "No mention.")
    out, left = _Run.excerpt_set([b, a, c], {"a": {"Gout flare."}, "b": {"Uric acid 9.1."}})
    # T-710 (D-479): the window's other note is shown too while it fits (before, only the evidence notes were),
    # so nothing is left out and an answer on this set is an answer on the whole window
    assert [(x["did"], x["text"]) for x in out] == [("a", "Gout flare."), ("b", "Uric acid 9.1."), ("c", "No mention.")]
    assert left == 0
