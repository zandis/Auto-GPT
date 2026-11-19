"""The second review of PR #1095 (plan 10 cards 10B-2 to 10B-5): one test, or a few, per item. Each failed on the
reader before the fix (head 93506e57), except the item 8 tests, which hold rules that were already in place but that
no test held (the tie rule, the tombstone trimming, symbolic links in the standardised storage). All data is
synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
DAY = "20261001"


def _source(st: kit.Storage) -> Ssmix2Source:
    return Ssmix2Source(st.root, licensed=EMPTY)


def _ss(tmp_path: Path) -> kit.Storage:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True)
    return st


def _msh(charset: str) -> str:
    return f"MSH|^~\\&|HIS||TB||{DAY}0900||ORL^O22^ORL_O22|1|P|2.5||||||{charset}"


# ------------------------------------------------------------------------------------------------ item 1: encodings
@pytest.mark.parametrize("charset", ["", "~ISO IR87", "ISO IR87"])
def test_1_euc_jp_that_msh18_does_not_name_is_set_aside_never_read_as_shift_jis(charset: str) -> None:
    data = f"{_msh(charset)}\rOBX|1|ST|X||肺癌|mg/dL\r".encode("euc_jp")
    with pytest.raises(hl7.Undecodable, match="not named|separator is lost"):
        hl7.decode_bytes(data)
    plain = f"{_msh(charset)}\rOBX|1|ST|X||肺|mg/dL\r".encode("euc_jp")  # no separator after a character
    with pytest.raises(hl7.Undecodable, match="not named"):
        hl7.decode_bytes(plain)


def test_1_a_lead_byte_that_would_swallow_a_separator_sets_the_message_aside() -> None:
    """0xE9 0x7C reads as one Shift_JIS character (and is not EUC-JP): the ``|`` after it would be lost and every
    later field shift (an OBX-5 value read as its unit)."""
    data = _msh("").encode("ascii") + b"\rOBX|1|ST|X||\xe9|mg/dL\r"
    with pytest.raises(hl7.Undecodable, match="separator is lost"):
        hl7.decode_bytes(data)


def test_1_the_sites_declared_encoding_reads_an_undeclared_file(monkeypatch: pytest.MonkeyPatch) -> None:
    data = f"{_msh('')}\rOBX|1|ST|X||肺癌|mg/dL\r".encode("euc_jp")
    monkeypatch.setenv(hl7.ENCODING_ENV, "EUC-JP")
    assert hl7.decode_bytes(data) == (data.decode("euc_jp"), "euc_jp")
    monkeypatch.setenv(hl7.ENCODING_ENV, "SHIFT_JIS")
    sjis = f"{_msh('')}\rOBX|1|ST|X||ポ（−）|mg/dL\r".encode("cp932")
    assert hl7.decode_bytes(sjis)[0].split("\r")[1].split("|")[5] == "ポ（−）"


def test_1_shift_jis_whose_trail_byte_equals_a_separator_still_reads_undeclared() -> None:
    """ポ is 0x83 0x7C: a lead byte EUC-JP never writes, so the reading is not in doubt (T-613b's case)."""
    text, codec = hl7.decode_bytes(f"{_msh('')}\rOBX|1|ST|X||ポ（−）|mg/dL\r".encode("cp932"))
    assert codec == "cp932" and text.split("\r")[1].split("|")[5:7] == ["ポ（−）", "mg/dL"]


def test_1_the_reader_quarantines_an_undeclared_euc_jp_file(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    path = kit._write(st, kit.P1, DAY, "ADT-12", "1", kit._stamp(DAY), ["MSH"])
    msg = ["MSH|^~\\&|HIS||TB||202610010900||ADT^A04^ADT_A01|1|P|2.5", kit._pid(kit.P1), kit._pv1("O", "V1", DAY)]
    path.write_bytes(("\r".join(msg) + "\r").replace("PID|||", "PID|||").encode("ascii").replace(
        b"||\r", "||東京^太郎\r".encode("euc_jp"), 1))  # fmt: skip
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert [q[0] for q in src.quarantined] == ["ADT-12"]


# ------------------------------------------------------------------------------------------------ item 2: suspicion
def _prb(name: str, flag: str = "", written: str = "") -> dict[str, object]:
    prb = ["PRB", "AD", "20261001", f"99990001^{name}^MDCDX2", "DX1"] + [""] * 14
    prb[10], prb[13], prb[17] = "C349^^I10", flag, written
    return {"prb": "|".join(prb)}


@pytest.mark.parametrize(
    ("name", "flag"),
    [("肺癌の疑い", "0^疑いなし^JHSD0005"), ("肺癌疑", "0"), ("肺癌", "1^疑いあり^99JHSD0005"), ("肺癌?", ""),
     ("肺癌？", ""), ("R/O 肺癌", ""), ("s/o 肺癌", ""), ("肺癌（疑診）", "0^なし^JHSD0005")],
)  # fmt: skip
def test_2_a_suspicion_anywhere_makes_the_diagnosis_provisional(tmp_path: Path, name: str, flag: str) -> None:
    st = _ss(tmp_path)
    segs = [kit._msh("20261001090000", "PPR^ZD1^PPR_ZD1", "P1"), kit._pid(kit.P1), str(_prb(name, flag)["prb"])]
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY), segs)
    (row,) = list(_source(st).rows("diagnosis", "diagnosis", None, None))
    assert row["suspected"] == "Y"


# D-1252: the JHSD0005 code table (表95) holds only "1 疑いあり"; a "0" is not a value of it, so "0^疑いなし" is U
@pytest.mark.parametrize(("name", "flag", "want"), [("肺癌", "0^疑いなし^JHSD0005", "U"), ("Rosacea", "", "")])
def test_2_no_suspicion_written_anywhere_is_confirmed(tmp_path: Path, name: str, flag: str, want: str) -> None:
    st = _ss(tmp_path)
    segs = [kit._msh("20261001090000", "PPR^ZD1^PPR_ZD1", "P1"), kit._pid(kit.P1), str(_prb(name, flag)["prb"])]
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY), segs)
    (row,) = list(_source(st).rows("diagnosis", "diagnosis", None, None))
    assert row["suspected"] == want


# ------------------------------------------------------------------------------------------------ item 3: offsets
def test_3_a_time_with_an_offset_is_the_sites_time_or_no_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    assert hl7.ts("202611012330-0500") == "2026-11-02 13:30:00"
    assert hl7.ts("202611011230+0900") == "2026-11-01 12:30:00"
    monkeypatch.delenv("TB_TZ")
    assert hl7.ts("202611012330-0500") == "2026-11-01"  # no zone to convert to: no time, never a wrong one


# ------------------------------------------------------------------------------------------------ items 4 and 5
_DRUGS = {"A": ("999000001", "3943001F1020"), "B": ("999000003", "3962002F1020"), "C": ("999000005", "1149019F1560")}


def _order(st: kit.Storage, drugs: str, stamp: str) -> None:
    segs = [kit._msh(f"{DAY}0900", "RDE^O11^RDE_O11", stamp), kit._pid(kit.P1)]
    for d in drugs:
        rp = "ABC".index(d) + 1  # the Rp number stays with its drug
        rxe = ["RXE", "", f"{_DRUGS[d][0]}^薬{d}^HOT9", "1", "", "TAB"] + [""] * 26
        rxe[31] = f"{_DRUGS[d][1]}^x^YJ"
        segs += [f"ORC|NW|RX7||{rp}|IP||||{DAY}0900", f"TQ1|1||&1日2回朝夕食後&99XYZ||||{DAY}", "|".join(rxe)]
    kit._write(st, kit.P1, DAY, "OMP-01", "RX7", kit._stamp(DAY, stamp), segs)


def test_4_a_drug_removed_in_a_newer_version_is_a_tombstone_and_no_line_takes_its_key(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    _order(st, "ABC", "090000")
    _order(st, "AC", "100000")  # B taken out of the order
    src = _source(st)
    rows = {r["rx_no"]: r["drug_name"] for r in src.rows("medication", "medication", None, None)}
    assert rows == {"RX7#1:999000001": "薬A", "RX7#3:999000005": "薬C"}
    assert [r["rx_no"] for r in src.deleted_rows("medication", "medication", None, None)] == ["RX7#2:999000003"]
    assert src.stats["OMP-01:drug line gone from a newer version"] == 1


def test_5_timing_that_the_structure_does_not_tie_to_one_drug_gives_no_daily_dose(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    rxe = ["RXE", "", "999000001^薬A^HOT9", "1", "", "TAB"] + [""] * 26
    other = ["RXE", "", "999000003^薬B^HOT9", "1", "", "TAB"] + [""] * 26
    segs = [kit._msh(f"{DAY}0900", "RDE^O11^RDE_O11", "x"), kit._pid(kit.P1), f"ORC|NW|RX8||1|IP||||{DAY}0900",
            "|".join(rxe), f"TQ1|1||&1日3回毎食後&99XYZ||||{DAY}", "|".join(other)]  # fmt: skip
    kit._write(st, kit.P1, DAY, "OMP-01", "RX8", kit._stamp(DAY), segs)
    src = _source(st)
    rows = list(src.rows("medication", "medication", None, None))
    assert [(r["drug_name"], r["daily_dose"], r["usage_text"]) for r in rows] == [("薬A", "", ""), ("薬B", "", "")]
    assert src.stats["OMP-01:timing not tied to one drug (no daily dose)"] == 2


# ------------------------------------------------------------------------------------------------ item 6: documents
def _doc(st: kit.Storage, name: str, text: str = "退院時サマリ", patient: str = kit.P1) -> Path:
    d = st.extended / patient[0:3] / patient[3:6] / patient / DAY / "DSC-01"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d / name


def _std(stamp: str, dept: str, flag: str) -> str:
    return f"{kit.P1}_{DAY}_DSC-01_D1_{stamp}_{dept}_{flag}.txt"


def test_6_the_extended_storage_follows_no_link_reads_no_backup_and_a_deletion_wins_a_tie(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    stamp = kit._stamp(DAY)
    _doc(st, _std(stamp, "01", "1"))  # listed first by name ...
    _doc(st, _std(stamp, "02", "0"))  # ... the deletion at the same time wins all the same
    _doc(st, "b.txt.bak")
    outside = tmp_path / "elsewhere" / "DSC-01"
    outside.mkdir(parents=True)
    (outside / "x.txt").write_text("外の文書", encoding="utf-8")
    (st.extended / kit.P1[0:3] / kit.P1[3:6] / kit.P1 / "20261002").mkdir(parents=True)
    (st.extended / kit.P1[0:3] / kit.P1[3:6] / kit.P1 / "20261002" / "DSC-01").symlink_to(outside)
    src = _source(st)
    assert list(src.rows("note", "note", None, None)) == []
    assert len(list(src.deleted_rows("note", "note", None, None))) == 1
    assert src.stats["document:not read (a backup or temporary copy)"] == 1
    assert src.stats["document:not read (a symbolic link, not followed)"] == 1


# ------------------------------------------------------------------------------------------------ item 7: the delta
def test_7_a_diagnosis_ended_after_the_last_run_is_read_on_a_delta_by_its_end_date(tmp_path: Path) -> None:
    """Recorded in 2020, its snapshot file written in 2020: only PRB-9 (the end day, 2026-11-02) is new."""
    st = _ss(tmp_path)
    prb = ["PRB", "UP", "20200101090000", "99990003^急性上気道炎^MDCDX2", "DX0003"] + [""] * 14
    prb[9], prb[10] = "20261102", "J069^^I10"
    segs = [kit._msh("20200101090000", "PPR^ZD1^PPR_ZD1", "P1"), kit._pid(kit.P1), "|".join(prb)]
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp("20200101"), segs)
    rows = list(_source(st).rows("diagnosis", "diagnosis", "recorded_date", "2026-11-01 00:00:00"))
    assert [(r["diag_no"], r["end_date"]) for r in rows] == [("DX0003", "2026-11-02")]


# ------------------------------------------------------------------------------------------------ item 8: the rules
def test_8_a_deletion_wins_a_tie_even_when_the_live_file_is_listed_first(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    segs = [kit._msh("20261001093000", "ADT^A04^ADT_A01", "x"), kit._pid(kit.P1), kit._pv1("O", "V1", "202610010930")]
    kit._write(st, kit.P1, DAY, "ADT-12", "1", kit._stamp(DAY), segs, flag="1", dept="01")  # sorts first
    kit._write(st, kit.P1, DAY, "ADT-12", "1", kit._stamp(DAY), segs, flag="0", dept="02")
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert [r["enc_no"] for r in src.deleted_rows("encounter", "encounter", None, None)] == ["V1"]


def test_8_tombstones_read_from_a_deleted_snapshot_never_repeat_on_another_call(tmp_path: Path) -> None:
    """A deleted (flag 0) snapshot whose message holds a ``DE`` diagnosis: reading it appends to the tombstone list,
    which must be trimmed back, or the second call names that diagnosis twice."""
    st = _ss(tmp_path)
    dead = ["PRB", "DE", "20261001", "99990001^胃炎^MDCDX2", "DX1"] + [""] * 14
    live = ["PRB", "AD", "20261001", "99990002^肺炎^MDCDX2", "DX2"] + [""] * 14
    segs = [kit._msh("20261001090000", "PPR^ZD1^PPR_ZD1", "P1"), kit._pid(kit.P1), "|".join(dead), "|".join(live)]
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY), segs, flag="0")
    src = _source(st)
    list(src.rows("diagnosis", "diagnosis", None, None))
    first = sorted(str(r["diag_no"]) for r in src.deleted_rows("diagnosis", "diagnosis", None, None))
    second = sorted(str(r["diag_no"]) for r in src.deleted_rows("diagnosis", "diagnosis", None, None))
    assert first == second == ["DX1", "DX2"]


def test_8_a_linked_file_in_the_standardised_storage_is_not_followed(tmp_path: Path) -> None:
    outside = kit.build(tmp_path / "elsewhere")
    st = _ss(tmp_path)
    target = next(f for f in outside.files if "_ADT-12_" in f.name)
    d = st.root / kit.P1[0:3] / kit.P1[3:6] / kit.P1 / target.parent.parent.name / "ADT-12"
    d.mkdir(parents=True)
    (d / target.name).symlink_to(target)
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert src.stats["storage:symbolic link not followed"] == 1


# ------------------------------------------------------------------------------------------------ item 9: flag 2
def test_9_a_record_whose_newest_version_carries_flag_2_is_set_aside(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    segs = [kit._msh("20261001093000", "ADT^A04^ADT_A01", "x"), kit._pid(kit.P1), kit._pv1("O", "V1", "202610010930")]
    kit._write(st, kit.P1, DAY, "ADT-12", "1", kit._stamp(DAY), segs, flag="2")
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert list(src.deleted_rows("encounter", "encounter", None, None)) == []
    # D-1252: flag 2 is cited now (過去履歴, 構築ガイドライン Ver.1.2j 表3.1-3 No.7): a newest version of flag 2 means
    # no version is in force; for the types D-1252 does not read as unknown the record is still set aside
    assert src.stats["ADT-12:set aside (no version in force: the newest carries flag 2)"] == 1
