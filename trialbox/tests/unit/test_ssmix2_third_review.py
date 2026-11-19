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


# ------------------------------------------------------------------------------------------------ 3: the patient
def _visit(st: kit.Storage, patient_in_pid: str, typ: str = "ADT-12") -> Path:
    segs = [kit._msh(f"{DAY}0930", "ADT^A04^ADT_A01", "x"), kit._pid(patient_in_pid), kit._pv1("O", "V1", DAY)]
    return kit._write(st, kit.P1, DAY, typ, "1", kit._stamp(DAY), segs)


def test_3_a_file_holding_another_patients_pid_is_quarantined(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _visit(st, kit.P2)
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert [q[2].split(":")[0] for q in src.quarantined] == ["patient"]


def test_3_full_width_digits_in_pid3_are_the_same_patient(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _visit(st, kit.P1.translate(str.maketrans("0123456789", "０１２３４５６７８９")))
    assert len(list(_source(st).rows("encounter", "encounter", None, None))) == 1


def test_3_a_file_filed_in_another_patients_folder_is_quarantined(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    path = _visit(st, kit.P2)
    other = st.root / kit.P2[0:3] / kit.P2[3:6] / kit.P2 / DAY / "ADT-12"
    other.mkdir(parents=True)
    path.rename(other / path.name)  # the file name says P1, the folders P2
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert "the folders name another patient" in src.quarantined[0][2]


def test_3_a_message_filed_under_another_data_type_folder_is_quarantined(tmp_path: Path) -> None:
    """The minor case: a PPR-01 file inside an ADT-00 folder."""
    st = _ss(tmp_path)
    prb = ["PRB", "AD", DAY, "99990001^胃炎^MDCDX2", "DX1"] + [""] * 14
    path = kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY),
                      [kit._msh(f"{DAY}0900", "PPR^ZD1^PPR_ZD1", "P"), kit._pid(kit.P1), "|".join(prb)])  # fmt: skip
    wrong = path.parent.parent / "ADT-00"
    wrong.mkdir()
    path.rename(wrong / path.name)
    src = _source(st)
    assert list(src.rows("diagnosis", "diagnosis", None, None)) == []
    assert "another day or data type" in src.quarantined[0][2]


# ------------------------------------------------------------------------------------------------ 4: an end date
def test_4_a_diagnosis_with_an_end_date_and_no_outcome_is_ended_never_active(tmp_path: Path) -> None:
    from adapter.mapping.engine import Mapper, Mapping

    st = _ss(tmp_path)
    prb = ["PRB", "AD", DAY, "99990001^胃炎^MDCDX2", "DX1"] + [""] * 14
    prb[9], prb[10] = "20261020", "K297^^I10"
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY),
               [kit._msh(f"{DAY}0900", "PPR^ZD1^PPR_ZD1", "P"), kit._pid(kit.P1), "|".join(prb)])  # fmt: skip
    (row,) = list(_source(st).rows("diagnosis", "diagnosis", None, None))
    assert (row["status"], row["end_date"]) == ("E", "2026-10-20")
    m = Mapping.load(Path(__file__).resolve().parents[2] / "services/adapter/mapping/jp_core/ssmix2_site.yaml")
    spec = next(r for r in m.resources if r.type == "Condition")
    res = Mapper(m, b"k" * 32, "S").map_row(spec, row)
    assert res is not None
    assert [c["code"] for c in res["clinicalStatus"]["coding"]] == ["inactive"]
    assert res["abatementDateTime"].startswith("2026-10-20")


# ------------------------------------------------------------------------------------------------ 5: ORC-1
def _order(st: kit.Storage, order: str, orc1: str, orc2: str, stamp: str = "090000", day: str = DAY) -> None:
    rxe = ["RXE", "", "999000001^薬A^HOT9", "1", "", "TAB"] + [""] * 26
    segs = [kit._msh(f"{day}0900", "RDE^O11^RDE_O11", order), kit._pid(kit.P1),
            f"ORC|{orc1}|{orc2}||1|IP||||{day}0900", "|".join(rxe)]  # fmt: skip
    kit._write(st, kit.P1, day, "OMP-01", order, kit._stamp(day, stamp), segs)


@pytest.mark.parametrize(("orc1", "status"), [("CA", "cancelled"), ("DC", "stopped"), ("OC", "cancelled"),
                                              ("ZZ", "unknown"), ("", "unknown"), ("NW", "active")])  # fmt: skip
def test_5_order_control_is_read_and_an_unknown_one_is_never_active(tmp_path: Path, orc1: str, status: str) -> None:
    st = _ss(tmp_path)
    _order(st, "RX1", orc1, "RX1")
    (row,) = list(_source(st).rows("medication", "medication", None, None))
    assert row["status"] == status


# ------------------------------------------------------------------------------------------------ 6: order keys
def test_6_two_orders_with_an_empty_or_equal_orc2_keep_two_keys(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _order(st, "RX1", "NW", "")
    _order(st, "RX2", "NW", "")
    _order(st, "RX3", "NW", "SAME")
    _order(st, "RX4", "NW", "SAME")
    keys = sorted(r["rx_no"] for r in _source(st).rows("medication", "medication", None, None))
    assert keys == ["RX1", "RX2", "RX3:SAME", "RX4:SAME"]


def test_6_an_order_with_no_key_at_all_is_quarantined(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _order(st, "ALL9", "NW", "")
    src = _source(st)
    assert list(src.rows("medication", "medication", None, None)) == []
    assert [q[2].split(":")[0] for q in src.quarantined] == ["no order key"]
