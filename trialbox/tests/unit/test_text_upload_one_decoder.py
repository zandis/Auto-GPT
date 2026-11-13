"""UX-004: a text file a person uploads is read by the one decoder (`tb_common.encoding`, D-215): Shift_JIS and Big5
read as what they say, a file whose character set cannot be told is refused with a reason, and nothing is replaced by
U+FFFD on the way to a model or a form."""

from __future__ import annotations

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


def test_a_text_already_damaged_is_refused_not_passed_on() -> None:
    with pytest.raises(UnreadableDocument):
        parse((JA + "�\n").encode("utf-8"), "protocol.txt")
