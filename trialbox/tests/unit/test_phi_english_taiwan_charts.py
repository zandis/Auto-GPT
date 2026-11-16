"""NEW-B-55 (D-923): an English chart from a Taiwan hospital (D-1037's independent check; synthetic strings only).

The owner: charts are mainly English in Taiwan, with Chinese headings, names, addresses and drug names mixed in.
Presidio beside the masker (``tools/phi_second_opinion.py``, ``eval/phi_second_opinion``) found three shapes the
note masker (version 5) missed or cut short: a name in Latin letters (a hyphenated given name, capitals, no label),
a Han name after an English label or a word for a relative, and a Taiwan address in its English form."""

from __future__ import annotations

import random
import time

import pytest
from tb_common import phi_guard as pg

# (text, the identifiers in it that must be masked whole); every person and place is fictional
SHAPES = [
    ("Patient: CHEN, MEI-LING  F/67", ["CHEN, MEI-LING"]),
    ("PATIENT: LIN CHIH-MING", ["LIN CHIH-MING"]),
    ("Patient: Margaret Ellen Whitcombe, 92-year-old", ["Margaret Ellen Whitcombe"]),
    ("Name: 黃家豪 (Huang Chia-Hao)", ["黃家豪", "Huang Chia-Hao"]),
    ("姓名: 劉冠宇", ["劉冠宇"]),
    ("brought by son 曾冠宇 (Tseng Kuan-Yu).", ["曾冠宇", "Tseng Kuan-Yu"]),
    ("Seen at CV OPD by Dr. Chang Mei-Ling; consulted 張美玲 醫師.", ["Chang Mei-Ling", "張美玲"]),
    ("contact Tseng Kuan-Yu at the ward", ["Tseng Kuan-Yu"]),
    ("Seen with Mei-Ling Chen this morning", ["Mei-Ling Chen"]),
    ("Home with daughter, Linda Ellison-Ward, who will help", ["Linda Ellison-Ward"]),
    ("accompanied by Priya Whitcombe-Shah", ["Priya Whitcombe-Shah"]),
    ("Caregiver: 陳雅婷", ["陳雅婷"]),
    (
        "Address: 13F., No. 322, Sec. 4, Minsheng Rd., Da'an Dist., Taipei City   Tel",
        ["13F., No. 322, Sec. 4, Minsheng Rd., Da'an Dist., Taipei City"],
    ),
    (
        "lives at No. 12, Wenhua 1st Rd., Guishan Dist., Taoyuan City 333 with",
        ["No. 12, Wenhua 1st Rd., Guishan Dist., Taoyuan City 333"],
    ),
    (
        "addr No. 5-1, Ln. 20, Aly. 3, Zhongshan Rd., Banqiao Dist., New Taipei City",
        ["No. 5-1, Ln. 20, Aly. 3, Zhongshan Rd., Banqiao Dist., New Taipei City"],
    ),
]
# what an English Taiwan chart holds that is no one's identifier: eponyms and hyphenated terms, drugs, departments,
# a list number, a word after a label, a surname alone in a citation
LEFT_ALONE = [
    "Guillain-Barre syndrome; Non-Hodgkin lymphoma; Creutzfeldt-Jakob disease; Wolff-Parkinson-White",
    "CXR: no infiltrate. Follow-Up in Cardiology OPD; X-ray and Lee-Enfield are not names here",
    "Patient: alert and oriented, afebrile",
    "Name of drug: Norvasc 脈優 5 mg qd; 心臟內科 follow-up",
    "Item No. 5 of 10 tablets; No. 2, Ward 5",
    "as reported by Chen et al. (2019); the Lin-Benson criteria",
    "by 2 weeks, son was told; daughter agreed",
    "s/p CABG, PMH: HTN, DM; Hb 12.3; BP 130/80",
]


def _masked(text: str, value: str) -> bool:
    i = text.index(value)
    out = pg.mask_note(text)
    return all(out[j] == pg.MASK_CHAR for j in range(i, i + len(value)) if not text[j].isspace())


@pytest.mark.parametrize(("text", "values"), SHAPES)
def test_each_shape_of_an_english_taiwan_chart_is_masked_whole(text: str, values: list[str]) -> None:
    for v in values:
        assert _masked(text, v), (v, pg.mask_note(text))


@pytest.mark.parametrize("text", LEFT_ALONE)
def test_what_is_no_ones_identifier_is_left(text: str) -> None:
    assert pg.note_spans(text) == [], [(k, text[a:b]) for k, a, b in pg.note_spans(text)]


def test_the_version_says_the_masking_changed() -> None:
    assert pg.NOTE_MASK_VERSION == "6"


def _corpus() -> list[str]:
    rnd = random.Random(23)
    words = ["Patient:", "Name:", "son", "daughter,", "Dr.", "CHEN,", "MEI-LING", "Chen", "Mei-Ling", "Ellison-Ward",
             "黃家豪", "曾", "冠宇", "No.", "12,", "Sec. 4,", "Minsheng Rd.,", "Da'an Dist.,", "Taipei City", "13F.,",
             "Ln. 20,", " ", "\n", "(", ")", "醫師", "3", "-", "Guillain-Barre", "by", "Tel"]  # fmt: skip
    gen = ["".join(rnd.choice(words) + rnd.choice(["", " "]) for _ in range(rnd.randint(5, 120))) for _ in range(400)]
    return [t for t, _ in SHAPES] + LEFT_ALONE + gen


def test_the_gates_and_window_find_what_the_whole_note_gives(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-756: the new patterns' gates are necessary conditions and the address's window holds every match."""
    corpus = _corpus()
    fast = [pg.note_spans(t) for t in corpus]
    monkeypatch.setattr(pg, "_NOTE_GATES", tuple(lambda f: True for _ in pg._NOTE_GATES))
    monkeypatch.setattr(pg, "_NOTE_WINDOWS", {})
    whole = [pg.note_spans(t) for t in corpus]
    assert [(t, a) for t, a, b in zip(corpus, fast, whole, strict=True) if a != b] == []


@pytest.mark.parametrize(
    "text",
    [
        "No. 1, " * 8000,
        "No. 1, Sec. 2, " + "Aa " * 20000,
        "Chen " + "Mei-" * 15000,
        "CHEN, " + "AB-" * 15000,
        "Patient: " + "Abc-" * 15000,
        "Name: " + "Ab Cd " * 10000,
        "son " + "陳" * 30000,
        ("daughter, " + "Ab-Cd " * 3) * 4000,
    ],
)
def test_a_long_run_is_read_in_one_pass(text: str) -> None:
    """The masking review's rule: no shape may take time that grows faster than the note."""
    start = time.monotonic()
    pg.mask_note(text)
    assert time.monotonic() - start < 1.0, text[:12]


def test_the_guard_masks_the_same_shapes() -> None:
    """The guard reads the masker's spans: what the note masker masks, the guard does not let pass."""
    from guard.guard import Guard

    for text, values in SHAPES:
        out = Guard("^\\d{8}$").redact(text)
        for v in values:
            assert v not in out, (v, out)
