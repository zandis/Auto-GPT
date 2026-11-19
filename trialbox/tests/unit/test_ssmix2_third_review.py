"""The third review of PR #1095 (an independent tester's probes of the SS-MIX2 reader at head 81b16bb8): one test, or
a few, per numbered point. Each failed on the reader at 81b16bb8. All data is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
DAY = "20261001"
MSH = "MSH|^~\\&|HIS||TB||20261001||ADT^A08^ADT_A01|1|P|2.5||||||"


def _source(st: kit.Storage) -> Ssmix2Source:
    return Ssmix2Source(st.root, licensed=EMPTY)


def _ss(tmp_path: Path) -> kit.Storage:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True)
    return st


def _name(data: bytes) -> str:
    return hl7.decode_bytes(data)[0].split("\r")[1].split("|")[5]


# ------------------------------------------------------------------------------------------------ 1: the order
def test_1_a_declared_euc_jp_is_read_as_euc_jp_even_when_its_bytes_are_valid_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多村 in EUC-JP is C2 BF C2 BC: also valid UTF-8 ("¿¼"). The declaration is read first."""
    data = f"{MSH}EUC-JP\rPID|||1^^^^PI||多村^速\r".encode("euc_jp")
    assert _name(data) == "多村^速"
    monkeypatch.setenv(hl7.ENCODING_ENV, "EUC-JP")
    assert _name(f"{MSH}\rPID|||1^^^^PI||多村^速\r".encode("euc_jp")) == "多村^速"


def test_1_declared_shift_jis_half_width_katakana_is_read_as_katakana_not_utf8() -> None:
    """ﾂｧﾂｩ in Shift_JIS is C2 A7 C2 A9: also valid UTF-8 ("§©")."""
    assert _name(f"{MSH}SHIFT_JIS\rPID|||1^^^^PI||ﾂｧﾂｩ\r".encode("cp932")) == "ﾂｧﾂｩ"


# ------------------------------------------------------------------------------------------------ 2: strict always
def test_2_a_truncated_character_under_declared_utf8_is_refused() -> None:
    data = MSH.encode() + b"UNICODE UTF-8\rPID|||1^^^^PI||" + "東".encode()[:2] + b"|x\r"
    with pytest.raises(hl7.Undecodable, match="although"):
        hl7.decode_bytes(data)


def test_2_a_separator_swallowed_under_declared_shift_jis_is_refused() -> None:
    data = MSH.encode() + b"SHIFT_JIS\rPID|||1^^^^PI||\xe9|x\r"
    with pytest.raises(hl7.Undecodable, match="separator is lost"):
        hl7.decode_bytes(data)


def test_2_euc_jp_under_a_shift_jis_declaration_is_refused() -> None:
    """燹燿 in EUC-JP is also valid Shift_JIS ("爍爐"): no byte in 0x80-0x9F, a lead byte from 0xE0."""
    data = f"{MSH}SHIFT_JIS\rPID|||1^^^^PI||燹燿^爍爐\r".encode("euc_jp")
    with pytest.raises(hl7.Undecodable, match="EUC-JP"):
        hl7.decode_bytes(data)


def test_2_iso2022_jp_with_a_stray_8_bit_byte_keeps_no_escape_in_a_name() -> None:
    data = f"{MSH}~ISO IR87\rPID|||1^^^^PI||".encode() + b"\x1b$B\xb0\x1b(B\r"
    with pytest.raises(hl7.Undecodable, match="control character"):
        hl7.decode_bytes(data)


def test_2_a_control_character_in_any_reading_is_refused() -> None:
    with pytest.raises(hl7.Undecodable, match="control character"):
        hl7.decode_bytes(f"{MSH}\rPID|||1^^^^PI||A\x07B\r".encode())


def test_2_an_unknown_site_encoding_stops_the_reader_at_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(hl7.ENCODING_ENV, "LATIN-9")
    with pytest.raises(ValueError, match="TB_SSMIX2_ENCODING"):
        _source(_ss(tmp_path))


def test_2_declared_shift_jis_and_plain_kana_still_read() -> None:
    """What must not be refused: declared Shift_JIS with kanji, hiragana and the separator-valued trail bytes."""
    assert _name(f"{MSH}SHIFT_JIS\rPID|||1^^^^PI||山田^ポ（−）\r".encode("cp932")) == "山田^ポ（−）"
    assert _name(f"{MSH}SHIFT_JIS\rPID|||1^^^^PI||ﾔﾏﾀﾞ^ﾀﾛｳ\r".encode("cp932")) == "ﾔﾏﾀﾞ^ﾀﾛｳ"
