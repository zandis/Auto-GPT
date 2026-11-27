"""``note_prep``: what each part does on a small input: offsets, headers, sentences, cues, dates, numbers, the cache.

The metrics on generated notes are in ``test_note_prep_metrics.py``; the rules that decide a case are here, with the
near misses beside them.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

import pytest
from adapter import note_cues, note_prep
from adapter.note_dates import dates_in
from adapter.note_prep import prepare

pytestmark = pytest.mark.nodb


def spans(text: str, note_date: object = None) -> list[tuple[str, str]]:
    return [(s.section, s.raw) for s in prepare("d", text, note_date)]


# ------------------------------------------------------------------------------------------ offsets and text
@pytest.mark.parametrize("nl", ["\n", "\r\n"])
def test_offsets_are_exact_in_the_raw_note_and_text_is_nfkc(nl: str) -> None:
    note = nl.join(["Chief complaint: ＡＬＴ １２０ Ｕ/Ｌ。", "- 令和６年１月１０日 受診", "・ 咳なし。 熱なし。"])
    segs = prepare("d", note)
    assert [s.raw for s in segs] == ["ＡＬＴ １２０ Ｕ/Ｌ。", "令和６年１月１０日 受診", "咳なし。", "熱なし。"]
    for s in segs:
        assert note[s.start : s.end] == s.raw
        assert s.text == unicodedata.normalize("NFKC", s.raw)
        assert "\r" not in s.raw
    assert [q.ucum for q in segs[0].numbers] == ["U/L"] and segs[0].numbers[0].value == 120.0
    assert [(d.lo, d.hi) for d in segs[1].dates] == [("2024-01-10", "2024-01-10")]


def test_empty_and_blank_notes_give_no_segments() -> None:
    assert prepare("d", "") == [] and prepare("d", " \n\t\n") == [] and prepare("d", "Allergies:\n\n") == []


def test_every_sentence_is_kept_whatever_it_says() -> None:
    note = "No fever. Denies cough. No chest pain. Never smoked."
    assert [s.raw for s in prepare("d", note)] == ["No fever.", "Denies cough.", "No chest pain.", "Never smoked."]


# ------------------------------------------------------------------------------------------ sections
def test_headers_in_three_languages_and_forms() -> None:
    note = "\n".join(
        [
            "Visit note",
            "CC: chest pain",
            "【既往歴】",
            "高血圧あり。",
            "家族歴：母が糖尿病。",
            "用藥：",
            "aspirin 100 mg",
            "A / P:",
            "Start statin.",
            "Physical exam:",
            "Clear.",
            "Allergies: NKDA",
            "Time: 10:30 seen",
        ]
    )
    assert spans(note) == [
        ("unlabelled", "Visit note"),
        ("chief_complaint", "chest pain"),
        ("history", "高血圧あり。"),
        ("family_history", "母が糖尿病。"),
        ("medication", "aspirin 100 mg"),
        ("assessment_plan", "Start statin."),
        ("other", "Clear."),
        ("allergy", "NKDA"),
        ("allergy", "Time: 10:30 seen"),  # "Time" is no header: the line is text of the section it is in
    ]


def test_a_line_that_only_starts_like_a_header_is_text() -> None:
    assert spans("Plan to start metformin: 500 mg") == [("unlabelled", "Plan to start metformin: 500 mg")]
    assert spans("History of MI: 2019") == [("unlabelled", "History of MI: 2019")]


# ------------------------------------------------------------------------------------------ sentences
def test_sentence_marks_and_the_dots_that_are_not_marks() -> None:
    note = "Seen by Dr. Lee. J. Smith agrees. Dose 2.5 mg. ALT 40 U/L. Next. Go on. approx. 5 mg qd.　次へ。終わり！"
    assert [s.raw for s in prepare("d", note)] == [
        "Seen by Dr. Lee.",
        "J. Smith agrees.",
        "Dose 2.5 mg.",
        "ALT 40 U/L.",
        "Next.",
        "Go on. approx. 5 mg qd.",  # a lower-case word after a full stop continues the sentence
        "次へ。",
        "終わり！",
    ]


def test_a_full_width_point_between_digits_is_a_decimal_point_not_a_sentence_mark() -> None:
    segs = prepare("d", "Dose ２．５ mg daily．Next．")
    assert [s.raw for s in segs] == ["Dose ２．５ mg daily．", "Next．"]
    assert [(q.value, q.ucum) for q in segs[0].numbers] == [(2.5, "mg")]


def test_a_standalone_nkda_line_is_a_segment_with_its_cue() -> None:
    (seg,) = prepare("d", "NKDA")
    assert (seg.raw, seg.section) == ("NKDA", "unlabelled")
    assert [(c.kind, c.value) for c in seg.cues] == [("negation", "absent")]


def test_bullets_and_numbering_leave_the_sentence() -> None:
    note = "1. aspirin\n2) metformin\n(3) statin\n・ x\n- ***\n* 12 mg"
    assert [s.raw for s in prepare("d", note)] == ["aspirin", "metformin", "statin", "x", "12 mg"]


# ------------------------------------------------------------------------------------------ cues
def kinds(text: str) -> list[tuple[str, str, str]]:
    return [(c.kind, c.value, c.text) for c in note_cues.tag(unicodedata.normalize("NFKC", text))]


@pytest.mark.parametrize(
    "text",
    [
        "No longer taking aspirin",
        "Non-small cell lung cancer",
        "Not to exceed 10 mg",
        "No. 5 tablet",
        "May 2026 visit",
        "Known asthma, Parkinson disease, nocturia, nonsteroidal drug",
        "体重55kg未満",
        "母集団解析",
        "非常に良好",
        "無理なく歩行可能",
        "麻酔科ないし外科",
        "無法行走",
        "未滿18歲",
        "排除標準請參閱",
        "若干變化",
        "歩行可能",
    ],
)
def test_pseudo_cues_and_neutral_words_carry_no_cue(text: str) -> None:
    assert kinds(text) == []


def test_cues_of_every_kind_and_language() -> None:
    assert kinds("Patient denies cough") == [("negation", "absent", "denies")]
    assert kinds("HIV was negative") == [("negation", "absent", "was negative")]
    assert kinds("Allergies: NKDA") == [("negation", "absent", "NKDA")]
    assert kinds("doesn't smoke") == [("negation", "absent", "doesn't")]
    assert kinds("咳なし") == [("negation", "absent", "なし")]
    assert kinds("結核を認めず") == [("negation", "absent", "認めず")]
    assert kinds("未治療") == [("negation", "absent", "未")]
    assert kinds("否認糖尿病") == [("negation", "absent", "否認")]
    assert kinds("Mother had MI") == [("experiencer", "family", "Mother")]
    assert kinds("母が糖尿病") == [("experiencer", "family", "母")]
    assert kinds("母親有高血壓") == [("experiencer", "family", "母親")]
    assert kinds("wife reports pain") == [("experiencer", "other", "wife")]
    assert kinds("s/p appendectomy") == [("temporality", "historical", "s/p")]
    assert kinds("既往に喘息") == [("temporality", "historical", "既往")]
    assert kinds("預計下週入院") == [("temporality", "planned", "預計")]
    assert kinds("Return if fever") == [("temporality", "hypothetical", "if")]
    assert kinds("r/o pneumonia") == [("uncertainty", "uncertain", "r/o")]
    assert kinds("it may recur") == [("uncertainty", "uncertain", "may")]
    assert kinds("肺炎の疑い") == [("uncertainty", "uncertain", "疑い")]
    assert kinds("可能是肺炎") == [("uncertainty", "uncertain", "可能")]


def test_the_longer_cue_wins_an_overlap_and_directions_are_tagged() -> None:
    assert kinds("Family history of MI") == [("experiencer", "family", "Family history")]
    assert [(c.kind, c.value) for c in note_cues.tag("cannot be excluded")] == [("uncertainty", "uncertain")]
    assert [(c.kind, c.value) for c in note_cues.tag("否定できない")] == [("uncertainty", "uncertain")]
    assert [(c.kind, c.value) for c in note_cues.tag("無法排除肺炎")] == [("uncertainty", "uncertain")]
    assert [c.direction for c in note_cues.tag("Denies cough, HIV negative")] == ["forward", "backward"]


# ------------------------------------------------------------------------------------------ dates
def day(text: str, nd: object = None) -> list[tuple[str, str, str]]:
    return [(d.lo, d.hi, d.kind) for d in dates_in(unicodedata.normalize("NFKC", text), nd)]


def test_gregorian_forms_and_partial_dates_are_intervals() -> None:
    assert day("seen 2026-07-24") == [("2026-07-24", "2026-07-24", "day")]
    assert day("seen 2026/7/4") == [("2026-07-04", "2026-07-04", "day")]
    assert day("2026.07.24") == [("2026-07-24", "2026-07-24", "day")]
    assert day("2026-02") == [("2026-02-01", "2026-02-28", "month")]
    assert day("2026年2月") == [("2026-02-01", "2026-02-28", "month")]
    assert day("2024年2月") == [("2024-02-01", "2024-02-29", "month")]
    assert day("Jul 24, 2026") == [("2026-07-24", "2026-07-24", "day")]
    assert day("24th July 2026") == [("2026-07-24", "2026-07-24", "day")]
    assert day("March 2019") == [("2019-03-01", "2019-03-31", "month")]
    assert day("since 2019") == [("2019-01-01", "2019-12-31", "year")]
    assert day("in 2019.") == [("2019-01-01", "2019-12-31", "year")]


@pytest.mark.parametrize(
    "text", ["2026.07", "2026-02-30", "20260724", "Order 2019", "July 24", "12/31", "2020-20", "5 mg in 2 days"]
)
def test_a_date_that_is_not_one_gives_nothing(text: str) -> None:
    assert day(text, "2026-08-01") == []


def test_roc_forms() -> None:
    assert day("民國113年3月5日") == [("2024-03-05", "2024-03-05", "day")]
    assert day("民国113年") == [("2024-01-01", "2024-12-31", "year")]
    assert day("113/03/05") == [("2024-03-05", "2024-03-05", "day")]
    assert day("113年3月") == [("2024-03-01", "2024-03-31", "month")]
    assert day("98年3月5日") == [("2009-03-05", "2009-03-05", "day")]
    assert day("98年3月") == []  # two digits, no day, no 民國: a duration as often as a date
    assert day("113年") == []


def test_relative_dates_resolve_only_with_a_note_date() -> None:
    for phrase in ("3 days ago", "yesterday", "last month", "3か月前", "先月", "3個月前", "昨天"):
        assert day(phrase) == [], phrase
    nd = "2026-08-15"
    assert day("3 days ago", nd) == [("2026-08-12", "2026-08-12", "relative")]
    assert day("yesterday", nd) == [("2026-08-14", "2026-08-14", "relative")]
    assert day("today", nd) == [("2026-08-15", "2026-08-15", "relative")]
    assert day("2 weeks ago", nd) == [("2026-07-28", "2026-08-05", "relative")]
    assert day("3 months ago", nd) == [("2026-04-28", "2026-06-01", "relative")]
    assert day("a year ago", nd) == [("2025-02-12", "2026-02-15", "relative")]
    assert day("last month", nd) == [("2026-07-01", "2026-07-31", "relative")]
    assert day("last year", nd) == [("2025-01-01", "2025-12-31", "relative")]
    assert day("last week", nd) == [("2026-08-03", "2026-08-09", "relative")]
    assert day("三ヶ月前", nd) == day("3か月前", nd) == day("3 months ago", nd)
    assert day("先月", nd) == day("last month", nd) and day("昨日", nd) == day("yesterday", nd)
    assert day("上個月", nd) == day("last month", nd) and day("昨天", nd) == day("yesterday", nd)
    assert day("3天前", nd) == day("3 days ago", nd) and day("2週間前", nd) == day("2 weeks ago", nd)
    assert day("0 days ago", nd) == []


def test_a_note_date_that_cannot_be_read_resolves_nothing() -> None:
    assert day("3 days ago", "yesterday") == [] and day("3 days ago", "2026-13-40") == [] and day("3 days ago", 5) == []


def test_a_date_inside_a_wareki_phrase_is_read_once_or_not_at_all() -> None:
    assert day("令和6年1月10日") == [("2024-01-10", "2024-01-10", "day")]
    assert day("令和7年2月30日") == []  # not also read as 7年2月30日 of another calendar
    assert day("令和0年") == [] and day("平成31年5月") == []
    assert day("平成31年") == [("2019-01-01", "2019-04-30", "year")]
    assert day("令和元年") == [("2019-05-01", "2019-12-31", "year")]


def test_an_impossible_full_english_date_is_not_read_as_the_month_inside_it() -> None:
    assert day("30 February 2026", "2026-08-01") == [] and day("February 30, 2026", "2026-08-01") == []
    assert day("30 April 2026") == [("2026-04-30", "2026-04-30", "day")]
    assert day("February 2026") == [("2026-02-01", "2026-02-28", "month")]


# ------------------------------------------------------------------------------------------ numbers
def nums(text: str) -> list[tuple[float, str | None, str]]:
    seg = prepare("d", text)[0]
    return [(q.value, q.comparator, q.ucum) for q in seg.numbers]


def test_numbers_with_units_comparators_and_width() -> None:
    assert nums("ALT ５０ Ｕ/Ｌ") == [(50.0, None, "U/L")]
    assert nums("Cr <0.3 mg/dL, K ≧5.5 mmol/L") == [(0.3, "<", "mg/dL"), (5.5, ">=", "mmol/L")]
    assert nums("WBC 1,200 /uL") == [(1200.0, None, "/uL")]
    assert nums("BP 120/80 mmHg") == []
    assert nums("Takes 100 mg/day, 5 mg qd, 10mg/日") == [
        (100.0, None, "mg/d"),
        (5.0, None, "mg"),
        (10.0, None, "mg/d"),
    ]
    assert nums("HbA1c 6.9 %") == [(6.9, None, "%")]


def test_a_minus_sign_is_part_of_the_number_and_its_quote() -> None:
    seg = prepare("d", "Base excess -5 mmol/L, K −2.5 mmol/L")[0]
    assert [(q.value, q.text) for q in seg.numbers] == [(-5.0, "-5 mmol/L"), (-2.5, "−2.5 mmol/L")]
    assert nums("Take 10-20 mg, T-5 mg") == [(20.0, None, "mg"), (5.0, None, "mg")]


def test_an_unknown_unit_or_a_date_digit_is_no_number() -> None:
    assert nums("3 days later, 5 cups, 2 foo/bar, 10 mg/kg") == []
    assert nums("Seen 2026-07-24 and 令和6年1月10日") == []
    assert nums("room 12b, A1c") == []


# ------------------------------------------------------------------------------------------ cache and determinism
def test_the_cache_returns_what_was_prepared_and_prepares_nothing_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    note = "Chief complaint: cough 3 days ago. ALT 45 U/L, mother had MI。令和6年1月10日。"
    cache: dict[str, list[dict[str, Any]]] = {}
    first = prepare("a", note, "2026-08-15", cache=cache)
    assert list(cache) == [note_prep.cache_key(note, "2026-08-15")]
    monkeypatch.setattr(note_prep, "_prepare", lambda *a: pytest.fail("prepared a cached note again"))
    again = prepare("b", note, "2026-08-15", cache=cache)
    assert [s.row() | {"did": ""} for s in first] == [s.row() | {"did": ""} for s in again]
    assert {s.did for s in again} == {"b"}
    assert first[0].cues == again[0].cues


def test_the_key_changes_with_text_note_date_and_table_version(monkeypatch: pytest.MonkeyPatch) -> None:
    base = note_prep.cache_key("x 3 days ago", "2026-08-15")
    assert base == note_prep.cache_key("x 3 days ago", "2026-08-15")
    assert base != note_prep.cache_key("x 3 days ago", "2026-08-16")
    assert base != note_prep.cache_key("x 3 days ago")
    assert base != note_prep.cache_key("x 4 days ago", "2026-08-15")
    monkeypatch.setattr(note_prep, "PREP_VERSION", "note-prep-next")
    assert base != note_prep.cache_key("x 3 days ago", "2026-08-15")


def test_the_same_note_gives_the_same_bytes_and_the_row_is_json() -> None:
    note = "【主訴】咳なし。\n家族史：母親有高血壓。民國113年3月5日。\nPlan: r/o TB? 3 months ago, 40 mg/day."
    a = json.dumps([s.row() for s in prepare("d", note, "2026-08-15")], sort_keys=True, ensure_ascii=False)
    b = json.dumps([s.row() for s in prepare("d", note, "2026-08-15")], sort_keys=True, ensure_ascii=False)
    assert a == b
    row = json.loads(a)[0]
    assert set(row) == {
        "did",
        "seg_id",
        "section",
        "start",
        "end",
        "raw",
        "text",
        "cues",
        "dates",
        "numbers",
        "prep_version",
    }
    assert row["prep_version"] == note_prep.PREP_VERSION
