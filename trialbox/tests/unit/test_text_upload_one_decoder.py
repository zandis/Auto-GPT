"""UX-004: a text file a person uploads is read by the one decoder (`tb_common.encoding`, D-215): Shift_JIS and Big5
read as what they say, a file whose character set cannot be told is refused with a reason, and nothing is replaced by
U+FFFD on the way to a model or a form."""

from __future__ import annotations

import json

import pytest
from doc_parser.parser import UnreadableDocument, parse

JA = "選択基準\n1. 同意取得時の年齢が20歳以上の患者\n2. 痛風と診断され、血清尿酸値が7.0 mg/dLを超える患者\n除外基準\n1. 重度の腎機能障害のある患者\n"
ZH = "納入條件\n1. 簽署同意書時年滿20歲之病人\n2. 經診斷為痛風且血清尿酸值高於7.0 mg/dL之病人\n排除條件\n1. 嚴重腎功能不全之病人\n"


def _text(doc: object) -> str:
    return str(doc.model_dump_json())  # type: ignore[attr-defined]  # every text the parsed document carries


@pytest.mark.parametrize(("text", "codec"), [(JA, "cp932"), (JA, "utf-8"), (JA, "utf-8-sig"), (ZH, "big5"),
                                              (ZH, "utf-8")])  # fmt: skip
def test_a_protocol_text_is_read_in_its_own_character_set(text: str, codec: str) -> None:
    got = _text(parse(text.encode(codec), "protocol.txt"))
    assert "�" not in got
    for line in text.splitlines():
        assert line.split(". ", 1)[-1] in got


def test_a_text_whose_character_set_cannot_be_told_is_refused_with_the_reason() -> None:
    mixed = JA.encode("cp932") + ZH.encode("big5")
    with pytest.raises(UnreadableDocument) as e:
        parse(mixed, "protocol.txt")
    assert "character set" in str(e.value) and "protocol.txt" in str(e.value)


# ------------------------------------------------------------------------------------------------ the review
BASE = "Inclusion criteria\n1. Age 20 years or older at consent\n2. Serum urate above 7.0 mg/dL\n"
FEW = ["Body temperature > 38\u00b0C", "Sj\u00f6gren syndrome", "TNF-\u03b1 inhibitor", "\u03b2-blocker",
       "eGFR < 30 mL/min/1.73 m\u00b2", "M\u00e9ni\u00e8re disease", "treatment-na\u00efve", "\u042f",
       "see \u00a7 4.2", "dose in \u00b5g"]  # fmt: skip


@pytest.mark.parametrize("line", FEW)
def test_valid_utf8_is_read_as_utf8_however_few_its_non_ascii_characters(line: str) -> None:
    """The first version asked the sheet detector, which weighs a few non-ASCII bytes against Shift_JIS and Big5:
    such a file was refused, or read as half-width kana. A file that is valid UTF-8 is UTF-8, as it always was."""
    from tb_common.encoding import decode_upload

    data = (BASE + line + "\n").encode("utf-8")
    assert decode_upload(data)[0] == BASE + line + "\n"
    got = json.dumps(json.loads(_text(parse(data, "NCT_eligibility.txt"))), ensure_ascii=False)
    assert line in got


@pytest.mark.parametrize("text", ["Patient\u2019s consent is given\n", "Body temperature > 38\u00b0C\n",
                                  "BMI (kg/m\u00b2)\n"])  # fmt: skip
def test_a_windows_1252_text_is_refused_not_read_as_stray_cjk(text: str) -> None:
    """A western file's one accented byte pairs with the next letter into a kanji or a hanzi: a reading with no run
    of two CJK characters is not CJK text."""
    from tb_common.encoding import EncodingRefused, decode_upload

    with pytest.raises(EncodingRefused):
        decode_upload((BASE + text).encode("cp1252"))
    with pytest.raises(UnreadableDocument) as e:
        parse((BASE + text).encode("cp1252"), "protocol.txt")
    assert "UTF-8" in str(e.value) and "1.00" not in str(e.value)  # the reason, without the detector's scores


def test_a_text_saved_as_unicode_by_notepad_is_read() -> None:
    from tb_common.encoding import decode_upload

    assert decode_upload(JA.encode("utf-16"))[0] == JA  # UTF-16 with its byte order mark


def test_a_valid_utf8_text_that_holds_a_replacement_character_is_read_as_it_always_was() -> None:
    got = json.dumps(json.loads(_text(parse((JA + "x\ufffdy\n").encode("utf-8"), "protocol.txt"))), ensure_ascii=False)
    assert "同意取得時" in got
