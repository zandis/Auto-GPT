"""D-215's one rule is "the right text or a refusal, never wrong text". The detector read some valid UTF-8 (no mark,
a few non-ASCII characters) as Shift_JIS or Big5: a line holding one Cyrillic letter came back as half-width kana,
with no refusal. Found by the review of #452. Bytes that are valid UTF-8 are read as UTF-8 or refused; a legacy
reading wins over them only on clear CJK text."""

from __future__ import annotations

import unicodedata

import pytest
from tb_common import encoding

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

BASE = "id,note\n1,Age 20 years or older at consent\n2,Serum urate above 7.0 mg/dL\n"


def _answer(data: bytes) -> str:
    try:
        return encoding.detect(data)[0]
    except encoding.EncodingRefused:
        return "refused"


def _typed(lo: int, hi: int) -> list[str]:
    return [chr(o) for o in range(lo, hi) if unicodedata.category(chr(o))[0] in "LNPS"]


def test_no_single_character_makes_a_utf8_file_read_as_shift_jis_or_big5() -> None:
    """The reviewer's sweep: every letter, digit, mark of punctuation and symbol from U+0080 to U+2FFF, once, in an
    English sheet: alone in a cell, inside a word, and after a number."""
    wrong: list[str] = []
    for ch in _typed(0x80, 0x3000):
        for cell in (ch, f"ab{ch}cd", f"38{ch}C"):
            got = _answer((BASE + f"3,{cell}\n").encode("utf-8"))
            if got not in ("utf-8", "refused"):
                wrong.append(f"U+{ord(ch):04X} in {cell!r}: {got}")
    assert wrong == [], f"{len(wrong)} read as a legacy character set, e.g. {wrong[:5]}"


@pytest.mark.parametrize("cell", [
    "Body temperature > 38\u00b0C", "Sj\u00f6gren syndrome", "TNF-\u03b1 inhibitor", "\u03b2-blocker",
    "eGFR < 30 mL/min/1.73 m\u00b2", "M\u00e9ni\u00e8re disease", "treatment-na\u00efve", "dose 5 \u00b5g",
    "5 \u00b1 2", "37.5 \u00b0C", "480 \u00b5mol/L",
])  # fmt: skip
def test_an_unmistakably_western_word_or_unit_in_a_utf8_sheet_is_utf8(cell: str) -> None:
    """An accented letter inside a word, a degree before C, a micro before a unit, a square after m, a plus-minus
    between numbers, a Greek letter hyphened to a word: no Japanese or Chinese text looks like these. Read."""
    assert _answer((BASE + f"3,{cell}\n").encode("utf-8")) == "utf-8"


HEAD = "ID,item,value\n1,WBC,5.1\n"


@pytest.mark.parametrize(("cell", "codec"), [
    ("\uff90\uff77", "cp932"), ("\uff8f\uff77", "cp932"), ("\uff95\uff77", "cp932"),   # two half-width kana: D0 B7 ...
    ("\u8077", "big5"), ("\u7c3d", "big5"), ("\u7c21", "big5"),                        # one hanzi that is also ¾ ñ ²
    # the review of the first version: the same cells beside a letter or a digit, as names and codes stand
    ("\uff90\uff771", "cp932"), ("\uff95\uff77A", "cp932"), ("A-\uff90\uff77", "cp932"), ("\uff90\uff77(1)", "cp932"),
    ("\uff8f\uff7b\uff95\uff771", "cp932"), ("\uff83\uff7d\uff84\u524d", "cp932"), ("\uff82\uff77 1", "cp932"),
    ("\uff85\uff7c1", "cp932"),
    ("\u80771", "big5"), ("No.\u8077", "big5"), ("\u7c3d1", "big5"), ("\u7f85A", "big5"), ("A\u7c21", "big5"),
    ("\u79ae3", "big5"), ("\u7ffb\u8b6f1", "big5"),
])  # fmt: skip
def test_a_legacy_cell_whose_bytes_are_also_utf8_is_never_read_as_utf8(cell: str, codec: str) -> None:
    """The other side: kana or a hanzi, alone or beside a letter or a digit, can be valid UTF-8 by chance (a
    Cyrillic letter, ``¾``). Too little to tell: the legacy reading or a refusal, never the UTF-8 one."""
    data = (HEAD + "2," + cell + ",x\n").encode(codec)
    data.decode("utf-8")  # the premise: these bytes are valid UTF-8 too
    assert _answer(data) in (codec, "cp950", "refused")
    many = (HEAD + "".join(f"{n},{cell},x\n" for n in range(2, 62))).encode(codec)
    assert _answer(many) in (codec, "cp950", "refused")


@pytest.mark.parametrize("word", [
    "\u0636\u062f", "\u062d\u0627\u062f", "\u0635\u062f\u0627\u0639", "\u05e8\u05e2", "\u05e7\u05e9\u05e8",
    "\u0161\u017e", "\u0414\u0430", "\u041d\u0435\u0442", "\u03b1\u03b2",
])  # fmt: skip
@pytest.mark.parametrize("candidates", [("cp932", "big5"), ("cp932",), ("cp932", "euc_jp")])
def test_a_word_of_another_script_in_utf8_is_never_read_as_a_legacy_character_set(
    word: str, candidates: tuple[str, ...]
) -> None:
    """The review: two or three Arabic, Hebrew or Latin Extended letters read as a run of half-width kana."""
    for cell in (word, f"ab{word}cd", f"{word} 1"):
        try:
            got = encoding.detect((HEAD + f"2,{cell},x\n").encode("utf-8"), candidates)[0]
        except encoding.EncodingRefused:
            got = "refused"
        assert got in ("utf-8", "refused"), (cell, got)


@pytest.mark.parametrize("cell", ["\u00bd", "\u00be", "\u00b2", "\u00a7"])
def test_a_column_of_a_symbol_that_is_also_a_frequent_hanzi_is_not_certain_either_way(cell: str) -> None:
    """``½`` is 翻, ``¾`` is 職, ``²`` is 簡, ``§`` is 禮 in Big5: a column of one of them, in UTF-8 or in Big5, was
    read as UTF-8. Now refused: the same bytes, nothing else to tell by."""
    data = ("ID,x\n" + "".join(f"{n},{cell}\n" for n in range(1, 6))).encode("utf-8")
    assert _answer(data) == "refused"
    assert encoding.file_codec.__name__ and data.decode("big5")  # the premise: Big5 reads these bytes too


@pytest.mark.parametrize("cell", ["\u00b1", "(\u00b1)", "\u00b0", "\u00b5", "\u00d7"])
def test_a_column_of_a_symbol_alone_is_read_as_it_was(cell: str) -> None:
    """A urine protein column of ``±``: three or more usual symbols make a UTF-8 file certain, as before."""
    data = ("ID,protein\n" + "".join(f"{n},{cell}\n" for n in range(1, 6))).encode("utf-8")
    assert _answer(data) == "utf-8"
