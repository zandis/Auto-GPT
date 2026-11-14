"""A-SENT-EN (found by the NEW-LLM-6 review, 2026-11-14): the excerpt builder splits English text into sentences.

``matching.excerpts.sentences`` split only at 。！？!? and line ends, so an English note written as a paragraph was
one "sentence". The cascade reads its lexicon hits, its S2b ranking and the cut of a long note (``clip``) in those
units: the evidence of an English paragraph note was the whole paragraph, and a paragraph longer than half the
budget was cut to nothing (the models read nothing; the answer was unknown, "notes over budget"). English is now
also split after ". " before a capital letter, a digit or an opening bracket, never after a title or a short form
that does not end a sentence (Dr., e.g., vs., No.), an initial, or inside a number. Japanese and Chinese text is
split as before. Synthetic text, no model.
"""

from __future__ import annotations

import pytest
from matching.excerpts import DEFAULT_TOKENS, Note, build, note_tokens, sentences

PARA = "Seen in clinic. Known interstitial lung disease, on pirfenidone. Follow-up in three months."


def test_an_english_paragraph_is_split_into_its_sentences() -> None:
    assert sentences(PARA) == [
        "Seen in clinic.",
        "Known interstitial lung disease, on pirfenidone.",
        "Follow-up in three months.",
    ]


@pytest.mark.parametrize(
    "text,want",
    [
        ("Seen by Dr. Smith today. Stable.", ["Seen by Dr. Smith today.", "Stable."]),
        ("Plan e.g. MTX. Review i.e. in May.", ["Plan e.g. MTX.", "Review i.e. in May."]),
        ("Drug A vs. B was discussed. Chose A.", ["Drug A vs. B was discussed.", "Chose A."]),
        ("Ref No. 12 noted. Done.", ["Ref No. 12 noted.", "Done."]),
        ("Letter from J. Smith received. Filed.", ["Letter from J. Smith received.", "Filed."]),
        ("HbA1c 7.4% today. eGFR 52.", ["HbA1c 7.4% today. eGFR 52."]),  # lower case after the stop: not split
        ("Methotrexate 7.5 mg weekly. 2 flares this year.", ["Methotrexate 7.5 mg weekly.", "2 flares this year."]),
        ("Seen. (Daughter present.) Plan agreed.", ["Seen.", "(Daughter present.)", "Plan agreed."]),
        ("Is she pregnant? No. Test negative!", ["Is she pregnant?", "No.", "Test negative!"]),
    ],
)
def test_short_forms_initials_and_numbers_are_kept_whole(text: str, want: list[str]) -> None:
    assert sentences(text) == want


@pytest.mark.parametrize(
    "text",
    [
        "評価：2型糖尿病。メトホルミン500mg 1日2回内服中。HbA1c 7.4%。",
        "第二型糖尿病，服用metformin。空腹血糖正常。",
        "血圧128/76mmHg。Dr. 山田より紹介。",
        "line one\nline two\n",
    ],
)
def test_japanese_chinese_and_lines_split_as_before(text: str) -> None:
    import re

    old = [s.strip() for s in re.findall(r"[^。！？!?\n]+[。！？!?]?", text) if s.strip()]
    assert sentences(text) == old


def test_a_long_english_paragraph_note_is_cut_around_its_evidence() -> None:
    """The review's case: before, the cut of a long paragraph note showed nothing."""
    filler = " ".join(["Walked to the shops without difficulty."] * 200)
    target = "Known interstitial lung disease, on pirfenidone."
    text = f"{filler} {target} {filler}"
    assert note_tokens(text) > DEFAULT_TOKENS
    got = build([Note("d1", "2026-10-01", "progress", text)], {"d1": [target]}, DEFAULT_TOKENS)
    assert got.left_out == 1 and any(target in e["text"] for e in got.shown)
