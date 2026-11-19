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


# ------------------------------------------------------------------------------------------------ 7: suspicion
def _dx(tmp_path: Path, name: str, flag: str = "", written: str = "", outcome: str = "") -> dict[str, object]:
    st = _ss(tmp_path)
    prb = ["PRB", "AD", DAY, f"99990001^{name}^MDCDX2", "DX1"] + [""] * 14
    prb[10], prb[13], prb[14], prb[17] = "C349^^I10", flag, outcome, written
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY),
               [kit._msh(f"{DAY}0900", "PPR^ZD1^PPR_ZD1", "P"), kit._pid(kit.P1), "|".join(prb)])  # fmt: skip
    (row,) = list(_source(st).rows("diagnosis", "diagnosis", None, None))
    return row


@pytest.mark.parametrize(("name", "flag", "written", "want"), [
    ("肺癌の疑いなし", "", "", "X"),                 # ruled out: refuted, never confirmed
    ("Pneumonia, ruled out", "", "", "X"),
    ("肺癌", "１^疑いあり^JHSD0005", "", "Y"),        # a full-width flag
    ("肺癌", "1^x^99LOC", "", "U"),                  # a flag of a table the reader does not know: unknown
    ("rule out pneumonia", "", "", "Y"),
    ("Suspected pneumonia", "", "", "Y"),
    ("肺癌", "", "肺癌の疑い", "Y"),                  # the suspicion only in PRB-17
    ("肺癌の疑い", "", "肺癌の疑いなし", "U"),         # suspected and ruled out at once: unknown
])  # fmt: skip
def test_7_every_way_of_writing_certainty_is_read(
    tmp_path: Path, name: str, flag: str, written: str, want: str
) -> None:
    assert _dx(tmp_path, name, flag, written)["suspected"] == want


def test_7_an_outcome_code_whose_own_text_disagrees_is_unknown(tmp_path: Path) -> None:
    assert _dx(tmp_path, "胃炎", outcome="A^治癒")["status"] == "U"


def test_7_the_mapping_gives_ruled_out_refuted_and_unknown_unconfirmed(tmp_path: Path) -> None:
    from adapter.mapping.engine import Mapper, Mapping

    m = Mapping.load(Path(__file__).resolve().parents[2] / "services/adapter/mapping/jp_core/ssmix2_site.yaml")
    spec = next(r for r in m.resources if r.type == "Condition")
    for want, code in (("X", "refuted"), ("U", "unconfirmed")):
        row = {**_dx(tmp_path / want, "胃炎"), "suspected": want}
        res = Mapper(m, b"k" * 32, "S").map_row(spec, row)
        assert res is not None and res["verificationStatus"]["coding"][0]["code"] == code


# ------------------------------------------------------------------------------------------------ 8: snapshots
def _snapshot(st: kit.Storage, day: str, stamp: str, prbs: list[list[str]], flag: str = "1") -> None:
    segs = [kit._msh(f"{day}0900", "PPR^ZD1^PPR_ZD1", day), kit._pid(kit.P1), *("|".join(p) for p in prbs)]
    kit._write(st, kit.P1, day, "PPR-01", "ALL9", kit._stamp(day, stamp), segs, flag=flag)


def _prb(no: str, name: str) -> list[str]:
    prb = ["PRB", "AD", DAY, f"99990001^{name}^MDCDX2", no] + [""] * 14
    prb[10] = "K297^^I10"
    return prb


def test_8_the_newest_snapshot_supersedes_older_ones_in_other_day_folders(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _snapshot(st, "20261001", "090000", [_prb("DX1", "胃炎"), _prb("DX2", "肺炎")])
    _snapshot(st, "20261005", "090000", [_prb("DX1", "胃炎の疑い")])  # DX1 now suspected, DX2 dropped
    src = _source(st)
    rows = list(src.rows("diagnosis", "diagnosis", None, None))
    assert [(r["diag_no"], r["suspected"]) for r in rows] == [("DX1", "Y")]
    assert [r["diag_no"] for r in src.deleted_rows("diagnosis", "diagnosis", None, None)] == ["DX2"]


def test_8_a_deleted_newest_snapshot_takes_the_older_ones_with_it(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _snapshot(st, "20261001", "090000", [_prb("DX1", "胃炎"), _prb("DX2", "肺炎")])
    _snapshot(st, "20261005", "090000", [_prb("DX1", "胃炎")], flag="0")
    src = _source(st)
    assert list(src.rows("diagnosis", "diagnosis", None, None)) == []
    assert sorted(str(r["diag_no"]) for r in src.deleted_rows("diagnosis", "diagnosis", None, None)) == ["DX1", "DX2"]


# ------------------------------------------------------------------------------------------------ 9: administrations
def _rx(st: kit.Storage, typ: str, order: str, drugs: list[tuple[str, str]], orc1: str = "NW") -> None:
    segs = [kit._msh(f"{DAY}0900", "RDE^O11^RDE_O11", typ), kit._pid(kit.P1)]
    for rp, (code, system) in enumerate(drugs, start=1):
        segs.append(f"ORC|{orc1}|{order}||{rp}|IP||||{DAY}0900")
        if typ == "OMP-01":
            segs.append("|".join(["RXE", "", f"{code}^薬^{system}", "1", "", "TAB"] + [""] * 26))
        else:
            segs.append(f"RXA|0|1|{DAY}0900|{DAY}0900|{code}^薬^{system}|1|TAB")
    kit._write(st, kit.P1, DAY, typ, order, kit._stamp(DAY, "100000" if typ != "OMP-01" else "090000"), segs)


def test_9_an_administration_of_another_drug_never_fills_its_order(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _rx(st, "OMP-01", "RX1", [("3943001F1020", "YJ")])
    _rx(st, "OMP-11", "RX1", [("999000003", "HOT9")], orc1="RE")
    src = _source(st)
    rows = {r["rx_no"]: r for r in src.rows("medication", "medication", None, None)}
    assert rows["RX1"]["hot_code"] == ""
    assert rows["RX1~999000003"]["hot_code"] == "999000003"
    assert src.stats["OMP-11:administration not tied to an order line (another drug)"] == 1


def test_9_an_administration_of_one_line_of_a_multi_line_order_fills_that_line_only(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _rx(st, "OMP-01", "RX7", [("999000001", "HOT9"), ("999000003", "HOT9")])
    _rx(st, "OMP-11", "RX7", [("999000003", "HOT9")], orc1="RE")
    rows = {r["rx_no"]: r for r in _source(st).rows("medication", "medication", None, None)}
    assert sorted(rows) == ["RX7#1:999000001", "RX7#2:999000003"]  # no duplicate row
    assert (rows["RX7#2:999000003"]["start_date"], rows["RX7#1:999000001"]["start_date"]) == ("2026-10-01 09:00:00", "")


# ------------------------------------------------------------------------------------------------ 10: offsets, stamps
def test_10_an_offset_out_of_range_quarantines_its_message_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    st = _ss(tmp_path)
    for order, when in (("1", "202610010930+2400"), ("2", "202610011030+0900")):
        segs = [kit._msh(f"{DAY}0930", "ADT^A04^ADT_A01", order), kit._pid(kit.P1), kit._pv1("O", f"V{order}", when)]
        kit._write(st, kit.P1, DAY, "ADT-12", order, kit._stamp(DAY, f"0{order}0000"), segs)
    src = _source(st)
    assert [r["enc_no"] for r in src.rows("encounter", "encounter", None, None)] == ["V2"]
    assert [q[2].split(":")[0] for q in src.quarantined] == ["time"]
    assert hl7.ts("202610010930+9900") == "2026-10-01"  # never an uncaught error


def test_10_a_file_stamp_that_is_not_a_real_time_is_quarantined_and_never_wins(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    good = _visit(st, kit.P1)
    bad = good.parent / good.name.replace(kit._stamp(DAY), "9")
    bad.write_bytes(good.read_bytes().replace(b"V1", b"V9"))
    src = _source(st)
    assert [r["enc_no"] for r in src.rows("encounter", "encounter", None, None)] == ["V1"]
    assert [q[2] for q in src.quarantined] == ["a 発生日時 that is not 17 digits of a real time"]


# ------------------------------------------------------------------------------------------------ 11: outcome sources
def test_11_an_outcome_row_is_applied_only_with_a_named_public_source() -> None:
    from adapter.sources.ssmix2.source import outcome_table

    row = {"system": "HL70241", "code": "F", "status": "R", "meaning": "治癒", "verified": "yes", "title": "T",
           "publisher": "P", "version": "1.0", "section": "3.1", "document": "https://example.org/t"}  # fmt: skip
    with pytest.raises(ValueError, match="no public source"):
        outcome_table([{**row, "document": "proposal from review 12 (an internal review)"}])
    with pytest.raises(ValueError):
        outcome_table([{**row, "section": ""}])
    applied, _ = outcome_table([row])
    assert applied == {"HL70241": {"F": "R"}}
    shipped, tables = outcome_table(
        [dict(r) for r in __import__("csv").DictReader(
            (Path(__file__).resolve().parents[2] / "services/adapter/mapping/jp_core/prb14_outcome.csv").open())]
    )  # fmt: skip
    assert shipped == {} and tables == {"HL70241", "JHSD0006"}


# ------------------------------------------------------------------------------------------------ minor
def test_minor_a_full_width_de_deletes(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    prb = _prb("DX1", "胃炎")
    prb[1] = "ＤＥ"
    _snapshot(st, "20261001", "090000", [prb])
    src = _source(st)
    assert list(src.rows("diagnosis", "diagnosis", None, None)) == []
    assert [r["diag_no"] for r in src.deleted_rows("diagnosis", "diagnosis", None, None)] == ["DX1"]


def test_minor_a_time_part_is_never_half_read_and_a_leap_second_is_not_a_time() -> None:
    before = hl7.REFUSED.copy()
    assert hl7.ts("20261001093") == "2026-10-01"
    assert hl7.ts("20261001 0930") == "2026-10-01"
    assert hl7.ts("20261231235960") == "2026-12-31 23:59:60"  # passed on, for the mapping to reject (STD-025)
    got = hl7.REFUSED - before
    assert got["a time part that is not read: the day kept"] == 2
    assert got["not a time of day (the row is rejected by the mapping)"] == 1


def _snapshot_of(st: kit.Storage, patient: str, day: str, prbs: list[list[str]], flag: str = "1") -> None:
    segs = [kit._msh(f"{day}0900", "PPR^ZD1^PPR_ZD1", day), kit._pid(patient), *("|".join(p) for p in prbs)]
    kit._write(st, patient, day, "PPR-01", "ALL9", kit._stamp(day, "090000"), segs, flag=flag)


def _de(no: str, name: str) -> list[str]:
    prb = _prb(no, name)
    prb[1] = "DE"  # PRB-1 DE: this diagnosis is deleted (a tombstone, 10B-3)
    return prb


@pytest.mark.parametrize("deleting", [kit.P1, kit.P2])
def test_8_one_patients_tombstones_never_hide_anothers_diagnosis_gone_from_a_newer_snapshot(
    tmp_path: Path, deleting: str
) -> None:
    """D-1253 (review E): a diagnosis number already tombstoned may be another patient's. One patient's newer
    snapshot deletes DX2 (PRB-1 DE); another patient's newer snapshot drops its own DX2: that one is a tombstone of
    its own too, whichever patient is read first."""
    st = _ss(tmp_path)
    dropping = kit.P2 if deleting == kit.P1 else kit.P1
    for p in (kit.P1, kit.P2):
        _snapshot_of(st, p, "20261001", [_prb("DX1", "胃炎"), _prb("DX2", "肺炎")])
    _snapshot_of(st, deleting, "20261005", [_prb("DX1", "胃炎"), _de("DX2", "肺炎")])
    _snapshot_of(st, dropping, "20261005", [_prb("DX1", "胃炎")])
    src = _source(st)
    rows = list(src.rows("diagnosis", "diagnosis", None, None))
    assert sorted((r["mrn"], r["diag_no"]) for r in rows) == sorted([(kit.P1, "DX1"), (kit.P2, "DX1")])
    dead = sorted((str(r["mrn"]), str(r["diag_no"])) for r in src.deleted_rows("diagnosis", "diagnosis", None, None))
    assert dead == sorted([(deleting, "DX2"), (dropping, "DX2")])
