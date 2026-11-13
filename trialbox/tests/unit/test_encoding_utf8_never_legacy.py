"""D-215's one rule is "the right text or a refusal, never wrong text". The detector read some valid UTF-8 (no mark,
a few non-ASCII characters) as Shift_JIS or Big5: a line holding one Cyrillic letter came back as half-width kana,
with no refusal. Found by the review of #452. Bytes that are valid UTF-8 are read as UTF-8 or refused; a legacy
reading wins over them only on clear CJK text."""

from __future__ import annotations

import unicodedata

import pytest
from tb_common import encoding

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
    "Body temperature > 38°C", "Sjögren syndrome", "TNF-α inhibitor", "β-blocker",
    "eGFR < 30 mL/min/1.73 m²", "Ménière disease", "treatment-naïve", "see § 4.2",
    "dose 5 µg", "5 ± 2", "José", "37.5 °C",
])  # fmt: skip
def test_a_western_word_or_unit_in_a_utf8_sheet_is_utf8(cell: str) -> None:
    """A non-ASCII character that stands in a western word or beside a number is not a stray kanji: read, not refused."""
    assert _answer((BASE + f"3,{cell}\n").encode("utf-8")) == "utf-8"


@pytest.mark.parametrize(("cell", "codec"), [
    ("ﾐｷ", "cp932"), ("ﾏｷ", "cp932"), ("ﾕｷ", "cp932"),   # two half-width kana: D0 B7 ...
    ("職", "big5"), ("簽", "big5"), ("簡", "big5"),                        # one hanzi that is also ¾ ñ ²
])  # fmt: skip
def test_a_legacy_cell_whose_bytes_are_also_utf8_is_never_read_as_utf8(cell: str, codec: str) -> None:
    """The other side, as before: two kana or one hanzi alone in a cell can be valid UTF-8 by chance (a Cyrillic
    letter, ``¾``). Too little to tell: the legacy reading or a refusal, never the UTF-8 one."""
    data = ("ID,x\n1," + cell + "\n").encode(codec)
    data.decode("utf-8")  # the premise: these bytes are valid UTF-8 too
    assert _answer(data) in (codec, "cp950", "refused")


def test_clear_cjk_text_that_is_valid_utf8_by_chance_is_still_read() -> None:
    """A legacy reading wins over valid UTF-8 only when UTF-8 reads it as text nobody writes and the legacy reading
    is CJK text (a run of characters), as the weighing always meant."""
    data = "ID,職簽簡翻\n".encode("big5")  # four hanzi: C2BE C3B1 C2B2 C2BD = "¾ñ²½" as UTF-8
    assert data.decode("utf-8") == "ID,¾ñ²½\n"
    assert _answer(data) in ("big5", "cp950", "refused")
