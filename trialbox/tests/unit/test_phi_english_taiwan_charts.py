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
# the adversarial review's leaks (fictional): whole names and addresses each must be masked
# (a name with no label, no comma and no hyphen, Chen Meiling, is a known limit of D-923: see KNOWN_LIMIT)
REVIEW_LEAKS = [
    "Chen Mei'ling", "Chen M.L.", "MEI-LING CHEN", "CHEN, MEI LING",
    "CHEN,MEI-LING", "Chen, Mei-Ling", "Ou Mei-Ling", "Liang Mei-Ling", "LIANG MEI-LING", "Ou-Yang Mei-Ling",
    "Sung Chih-Ming", "Tung Ya-Ting", "Hsia Pei-Shan", "Tien Kuan-Yu", "Kung Hui-Min", "Hsiung Chia-Hao",
    "No. 322, Section 4, Minsheng Road, Da'an District, Taipei City",
    "No 8, Zhongshan Rd., Banqiao Dist., New Taipei City",
    "No. 8, Neighborhood 5, Xinyi Vil., Hualien County",
    "No. 8, Section 2, Zhongshan N. Rd., Taipei",
    "No. 322, Minsheng E. Rd. Sec. 4, Da'an Dist., Taipei City",
    "No. 9, Taiwan Blvd. Sec. 3, Xitun Dist., Taichung City",
    "No. 3, Zhongshan Rd., Xinyi Vil., Banqiao Dist., New Taipei City",
    "No. 3, Zhongshan Rd, Banqiao, New Taipei",
    "No. 3, Zhongshan Rd., Hualien City, Hualien County",
    "No. 3, Zhongshan Rd., Banqiao Dist.\nNew Taipei City",
    "5th Fl., No. 8, Zhongshan Rd., Banqiao Dist.",
    "Rm. 2, 5F., No. 8, Zhongshan Rd., Banqiao Dist.",
]  # fmt: skip
# the review's names after a label or a word, and in a sentence: (text, the names to be masked whole)
REVIEW_IN_TEXT = [
    ("Mr. CHEN was seen", ["CHEN"]),
    ("Name: CHEN Mei-Ling", ["CHEN Mei-Ling"]),
    ("Patient: O'Neil Kuo", ["O'Neil Kuo"]),
    ("Talked to Chen Mei-Ling's son", ["Chen Mei-Ling"]),
    ("Mei-Ling Chen's son called", ["Mei-Ling Chen"]),
    ("Patient: CHEN MEI LING, F/67", ["CHEN MEI LING"]),
    ("Informant: 陳美玲", ["陳美玲"]),
    ("Attending: 陳美玲", ["陳美玲"]),
    ("nurse 陳美玲 gave meds", ["陳美玲"]),
    ("VS 陳美玲", ["陳美玲"]),
    ("Wife (陳美玲) at bedside", ["陳美玲"]),
    ("mother-in-law 陳美玲", ["陳美玲"]),
    ("son 陳 美玲", ["陳 美玲"]),
    ("Name: 陳美玲 林志明", ["陳美玲", "林志明"]),
]
# the second review's leaks (fictional), each masked whole
SECOND_LEAKS = [
    "Chiou Yi-Ting", "Jhang Mei-Ling", "Syu Chia-Hao", "Shieh Pei-Shan", "Tsay Kuan-Yu", "Chen Szu-Yu",
    "Lin Ssu-Yu", "Chen Erh-Kang", "Lin Kwei-Fen", "Chen Lin Mei-Ling", "CHEN LIN MEI-LING", "Chen, Meiling",
    "Taipei City Da'an District Heping E. Rd. Sec. 1 No. 18 5F", "Jianguo Rd. No. 18",
    "No. 18, 5F, Heping E. Rd., Da'an Dist.",
    "No. 18, 12th Neighborhood, Fuxing Village, Dongshan Township, Yilan County",
    "No. 18, Aly. 3, Ln. 2, Sec. 1, Nbhd. 4, Zhongshan Rd.",
    "No. 3, Zhongshan Rd., Da’an Dist., Taipei City",
    "No. 3, Zhongshan Rd., Luodong Town, Yilan County",
    "No. 3, Zhongshan Rd., 4th Fl.",
    "No. 3, Zhongshan Rd., Da'an Dist., Taipei City, Taiwan 106",
]  # fmt: skip
SECOND_IN_TEXT = [
    ("VS: 陳美玲", ["陳美玲"]), ("son: 陳美玲", ["陳美玲"]), ("Nurse: 陳美玲", ["陳美玲"]), ("Pt: 陳美玲", ["陳美玲"]),
    ("Resident: 陳美玲", ["陳美玲"]), ("Physician: 陳美玲", ["陳美玲"]), ("Attending physician: 陳美玲", ["陳美玲"]),
    ("Primary nurse: 陳美玲", ["陳美玲"]), ("R1 陳美玲", ["陳美玲"]), ("NSP 陳美玲", ["陳美玲"]),
    ("daughter 陳 美 玲", ["陳 美 玲"]), ("Name CHEN, MEI-LING", ["CHEN, MEI-LING"]), ("Dr. CHEN", ["CHEN"]),
    ("Dr. J. Smith", ["J. Smith"]), ("Reviewed by J. Smith", ["J. Smith"]), ("Patient: Smith, John", ["Smith, John"]),
    ("Patient: O'NEIL, MARY", ["O'NEIL, MARY"]), ("Dr. McDonald", ["McDonald"]),
]  # fmt: skip
# the second review's over-masking: two capitalised words of a chart are often a finding, a formula or a place
SECOND_LEFT = [
    "Lung Cancer; Dx: Lung Cancer; LUNG CANCER; Lung Lesion; Lung Tumor Board; Lower Lung Field; RIGHT LOWER LUNG",
    "He Tender; Pan Neuro Exam; Sun Mon Tue; Senior Lee; Nurse Lan; Pending Ma",
    "Tang Kuei; Ding Chuan; Lian Qiao; Kao Hsiung; Tao Yuan; Lin Kou; Tan Shui; Hua Lien",
    "Kaohsiung Chang Gung; Chi Mei Medical Center; Yuan Lin Christian; Kuang Tien General",
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
    # the review's over-masking (v5 left them; v6 must too)
    "Patient 高血壓 hx; Patient 白內障; Patient 曾經 fell; Patient 方便",
    "Referred by 林口 CGMH; by 施打 vaccine",
    "PATIENT: NPO AFTER MIDNIGHT",
    "PATIENT: HTN, DM",
    "Brought by Ambulance",
    "He Self-Harmed; He Co-Signed; Fan Co-Morbid",
    "Long-Term Ma Huang-Tea; Tai Chi-Chuan exercise; Qi Gong; Ho Chi-Minh City trip",
    "Item No. 5 of 10 tablets; No. 2, Ward 5; No fever. No 2 episodes",
]


def _masked(text: str, value: str) -> bool:
    i = text.index(value)
    out = pg.mask_note(text)
    return all(out[j] == pg.MASK_CHAR for j in range(i, i + len(value)) if not text[j].isspace())


@pytest.mark.parametrize(("text", "values"), SHAPES)
def test_each_shape_of_an_english_taiwan_chart_is_masked_whole(text: str, values: list[str]) -> None:
    for v in values:
        assert _masked(text, v), (v, pg.mask_note(text))


@pytest.mark.parametrize("text", REVIEW_LEAKS)
def test_the_reviews_leaks_are_masked_whole(text: str) -> None:
    out = pg.mask_note(text)
    assert all(c == pg.MASK_CHAR or c.isspace() for c in out), out


@pytest.mark.parametrize(("text", "values"), REVIEW_IN_TEXT)
def test_the_reviews_names_after_a_word_are_masked_whole(text: str, values: list[str]) -> None:
    for v in values:
        assert _masked(text, v), (v, pg.mask_note(text))
    assert pg.mask_note("Mr. CHEN was seen").startswith("Mr. ")  # the title is kept


#: D-923's known limit: a romanised name with no label, no comma and no hyphen is not read (two capitalised words
#: of a chart are too often a finding); after a label, a title or a relative's word it is
KNOWN_LIMIT = ["Chen Meiling", "Chen Mei Ling", "CHEN MEILING"]


@pytest.mark.parametrize("name", KNOWN_LIMIT)
def test_the_known_limit_holds_and_a_label_closes_it(name: str) -> None:
    assert pg.note_spans(f"seen {name} today") == []  # the limit, stated: it fails when the rule changes
    for text in (f"Patient: {name}", f"Name: {name}", f"Dr. {name}", f"daughter {name}"):
        assert _masked(text, name), (text, pg.mask_note(text))


@pytest.mark.parametrize("text", SECOND_LEAKS)
def test_the_second_reviews_leaks_are_masked_whole(text: str) -> None:
    out = pg.mask_note(text)
    assert all(c == pg.MASK_CHAR or c.isspace() for c in out), out


@pytest.mark.parametrize(("text", "values"), SECOND_IN_TEXT)
def test_the_second_reviews_names_after_a_word_are_masked_whole(text: str, values: list[str]) -> None:
    for v in values:
        assert _masked(text, v), (v, pg.mask_note(text))


@pytest.mark.parametrize("text", SECOND_LEFT)
def test_the_second_reviews_findings_are_left(text: str) -> None:
    assert pg.note_spans(text) == [], [(k, text[a:b]) for k, a, b in pg.note_spans(text)]


@pytest.mark.parametrize("text", LEFT_ALONE)
def test_what_is_no_ones_identifier_is_left(text: str) -> None:
    assert pg.note_spans(text) == [], [(k, text[a:b]) for k, a, b in pg.note_spans(text)]


def test_the_version_says_the_masking_changed() -> None:
    assert pg.NOTE_MASK_VERSION == "8"  # 6: these charts (D-923); 7: Japanese rules (10C-1); 8: analyser (10C-1b)


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
        # the review's HIGH-1: a run of white space after a label, Han text further on
        "Dr." + "\t" * 40000 + "x 陳",
        "son" + " " * 40000 + "x 陳",
        "Patient" + " " * 40000 + ",x 陳",
        "Name:" + " " * 40000 + "陳",
        "No. 1," + " " * 40000 + "Zhongshan Rd.",
        "Chen" + " " * 40000 + "Mei-Ling",
        "No. 1, " + "Ab " * 20000 + "Rd.",
        "No. 1, Ln. 2, " * 5000,
        # the second review's: the Chinese order runs back from each "No" over the window's whole reach
        "Taipei City " * 8000 + "No. 1",
        ("Abc Rd. Sec. 1 " * 3 + "No. 1 ") * 3000,
        "Chen Lin " * 10000 + "Mei-Ling",
        "Szu-" * 20000,
    ],
)
def test_a_long_run_is_read_in_one_pass(text: str) -> None:
    """The masking review's rule: no shape may take time that grows faster than the note."""
    start = time.monotonic()
    pg.mask_note(text)
    assert time.monotonic() - start < 1.0, text[:12]


def test_the_address_window_reaches_past_the_longest_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """The review's MEDIUM-5: every part of the address is bounded, so the window (the anchor and
    ADDRESS_TW_EN_MAX after it, on to the line's end) holds the longest match; the windowed scan and the whole note
    give the same spans, also for an address longer than the old window."""
    word = "Abcdefghijklmnopqrstuvwxy"  # 25 characters, the longest word a part takes
    part_road = " ".join([word] * 4) + " Boulevard Section 12"
    part_area = " ".join([word] * 4) + " Township"
    longest = (
        "Rm. 1234A, 123rd Floor-12, No. 12345-1234, Neighborhood 1234, Neighborhood 1234, Neighborhood 1234, "
        + ", ".join([part_road] + [part_road] * 3 + [part_area] * 3)
    )
    texts = [
        longest,
        "Taipei City Da'an District " + " ".join([word] * 4) + " Rd. Sec. 1, Ln. 12, Aly. 3, No. 18, 5F",
        "No. 12345-1234, Ln. 1234, Aly. 1234, Sec. 12, Kaohsiungxiaogangriverside Northeastern Riverside Boulevard, "
        "Xiaogangqianzhenlinhai Industrial Park Dist., Greater New Kaohsiung City 81245",
        "No. 8, B" + "a" * 150 + " Roadside clinic",
        "see No. 3, Zhongshan Rd., Banqiao Dist.\nNew Taipei City 220\nnext line",
    ]
    fast = [pg.note_spans(t) for t in texts]
    m = pg.ADDRESS_TW_EN.search(longest)
    assert m and len(longest) - longest.index("No.") < pg.ADDRESS_TW_EN_MAX
    monkeypatch.setattr(pg, "_NOTE_WINDOWS", {})
    assert fast == [pg.note_spans(t) for t in texts]


def test_the_guard_masks_the_same_shapes() -> None:
    """The guard reads the masker's spans: what the note masker masks, the guard does not let pass."""
    from guard.guard import Guard

    for text, values in SHAPES + REVIEW_IN_TEXT + SECOND_IN_TEXT:
        out = Guard("^\\d{8}$").redact(text)
        for v in values:
            assert v not in out, (v, out)
