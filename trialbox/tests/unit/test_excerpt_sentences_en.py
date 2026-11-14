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


# ------------------------------------------------------------------------------------------------- review fixes
@pytest.mark.parametrize(
    "text,want",
    [
        (
            "Family history: breast cancer. Ovarian cancer. Colon cancer.",
            ["Family history: breast cancer. Ovarian cancer. Colon cancer."],
        ),
        ("Denies: chest pain. Shortness of breath.", ["Denies: chest pain. Shortness of breath."]),
        (
            "Seen today. Family history: breast cancer. Ovarian cancer.",
            ["Seen today.", "Family history: breast cancer. Ovarian cancer."],
        ),
        ("Seen at 10:00. Stable.", ["Seen at 10:00.", "Stable."]),  # a time is no label
    ],
)
def test_a_label_keeps_the_rest_of_its_line_together(text: str, want: list[str]) -> None:
    """Review: split into sentences, "Ovarian cancer." was shown without "Family history:" and "Shortness of
    breath." without "Denies:" (the judge reads them as the patient's own). From a sentence that carries a label to
    the end of its line is one unit, as the whole line was before."""
    assert sentences(text) == want


def test_a_cut_long_note_never_shows_a_relatives_item_without_its_label() -> None:
    lines = [f"Routine line {i} without findings." for i in range(400)]
    lines.insert(200, "Family history: breast cancer. Ovarian cancer. Colon cancer.")
    text = "\n".join(lines)
    target = "Family history: breast cancer. Ovarian cancer. Colon cancer."
    for budget in (60, 90, 140, DEFAULT_TOKENS):
        got = build([Note("d1", "2026-10-01", "progress", text)], {"d1": [target]}, budget)
        for e in got.shown:
            for line in e["text"].splitlines():
                assert "Ovarian" not in line or line.startswith("Family history:"), (budget, line)


def test_a_huge_paragraph_is_split_in_linear_time() -> None:
    """Review: the word before each stop was found by scanning the whole text before it (116 KB: 18 s)."""
    import time

    text = "Walked to the shops without difficulty. " * 3000 + "x" * 5000 + ". A" * 200
    t0 = time.perf_counter()
    sentences(text)
    assert time.perf_counter() - t0 < 1.0


@pytest.mark.parametrize(
    "text,want",
    [
        ("Pt. seen today. Stable.", ["Pt. seen today.", "Stable."]),
        ("Hx. of gout. Dx. confirmed.", ["Hx. of gout.", "Dx. confirmed."]),
        ("Started Jan. 2021 on MTX. Stable.", ["Started Jan. 2021 on MTX.", "Stable."]),
        ("Started Sept. 12 on MTX. Stable.", ["Started Sept. 12 on MTX.", "Stable."]),
        ("Problems 1. Hypertension 2. Diabetes", ["Problems 1. Hypertension 2. Diabetes"]),
        ("As shown by Smith et al. In 2020 it was confirmed.", ["As shown by Smith et al. In 2020 it was confirmed."]),
    ],
)
def test_clinical_short_forms_months_and_list_numbers_end_no_sentence(text: str, want: list[str]) -> None:
    assert sentences(text) == want


@pytest.mark.parametrize(
    "text",
    [
        "HbA1c 7.4. Dr. 山田より紹介。",
        "胸部CT施行 2024/1/5. MRIでは異常なし。",
        "vit. D 低値。",
        "HbA1c 7.4. LDL 120。",
    ],
)
def test_a_line_with_japanese_or_chinese_splits_exactly_as_before(text: str) -> None:
    import re

    old = [s.strip() for s in re.findall(r"[^。！？!?\n]+[。！？!?]?", text) if s.strip()]
    assert sentences(text) == old
