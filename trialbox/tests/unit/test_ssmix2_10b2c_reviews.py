"""Card 10B-2c (D-1257): the SS-MIX2 reader answers its independent reviews.

Section "the second tool's review of #1189" (seven findings) and section "the two reviews of #1095" (reviewer A's
seven, reviewer B's ten). Each test is a finding's own input as a storage tree. A test marked ``guard`` passes on
master ``d28f6c03`` already (the finding was fixed by #1189, or does not reproduce); every other test fails there.

Every delta claim is checked with ``tests/ssmix2_nights.py``: the lake after a delta night 2 must equal the lake a
full read of night 2's storage gives an empty lake. All data is synthetic.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2 import source as reader
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_nights as nights
from tests import ssmix2_probes as pb
from tests import ssmix2_spec_kit as kit

P, Q = kit.P1, kit.P2
D1, D2 = nights.D1, nights.D2
DRUG_A, DRUG_B = "999000001", "999000002"


def _storage(tmp_path: Path) -> kit.Storage:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True, exist_ok=True)
    return st


def _read(st: kit.Storage, table: str, **kw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Ssmix2Source]:
    src = Ssmix2Source(st.root, licensed=kw.pop("licensed", nights.EMPTY), today="20261231", **kw)
    live, dead = nights.night(src, table, None)
    return live, dead, src


# ================================================================== the second tool's review of #1189
# ------------------------------------------------------------------ High, source.py:1913
@pytest.mark.parametrize(
    ("zpr", "field"),
    [
        ("ZPR||12345678^糖尿病^MDCDX2|||ZZZZ^糖尿病^MDCDX2", 5),  # the finding: ZPR-2 is PRB-3's code, ZPR-5 another
        ("ZPR||87654321^糖尿病^MDCDX2|||12345678^糖尿病^MDCDX2", 2),  # the same hole from the other side (class F)
        ("ZPR|||||ZZZZ^糖尿病^MDCDX2", 5),  # ZPR-5 alone, not PRB-3's code
    ],
)
def test_without_the_master_a_zpr_disease_code_that_is_not_prb3s_own_is_never_confirmed(
    tmp_path: Path, zpr: str, field: int
) -> None:
    st = _storage(tmp_path)
    nights.snapshot(st, f"{D1}090000000", [nights.prb("DX01", code="12345678", name="糖尿病"), zpr])
    (row,), _dead, src = _read(st, "diagnosis")
    assert row["suspected"] == "U"
    assert field in (2, 5)  # whichever field carries it, the site sees one counted reason
    assert src.stats[f"PPR-01:certainty unknown ({reader.NEEDS_MASTER})"] == 1
    assert reader.NEEDS_MASTER == "a ZPR disease code cannot be verified without the MEDIS master"


@pytest.mark.parametrize(
    "zpr", ["ZPR||12345678^糖尿病^MDCDX2", "ZPR|||||12345678^糖尿病^MDCDX2", "ZPR||12345678^糖尿病^MDCDX2|||12345678"]
)
def test_without_the_master_a_zpr_that_repeats_prb3s_own_code_still_confirms(tmp_path: Path, zpr: str) -> None:
    """Guard: what can be compared without the master (the very code PRB-3 carries) still confirms."""
    st = _storage(tmp_path)
    nights.snapshot(st, f"{D1}090000000", [nights.prb("DX01", code="12345678", name="糖尿病"), zpr])
    (row,), _dead, _src = _read(st, "diagnosis")
    assert (row["status"], row["suspected"]) == ("A", "")


def test_with_the_master_the_specifications_own_zpr_shape_is_confirmed_and_a_wrong_exchange_code_is_not(
    tmp_path: Path,
) -> None:
    """The shape the specification's example writes (ZPR-2 the 病名管理番号, ZPR-5 the 病名交換用コード) is confirmed
    where it can be checked, with the site's master; the finding's conflicting code is unknown there too."""
    for n, (dis_ex, want) in enumerate([("ZA05", ""), ("ZA04", "U")]):
        st = _storage(tmp_path / str(n))
        body = [pb.prb("99990005", "糖尿病", "DX01"), pb.zpr(dis="99990005", dis_ex=dis_ex)]
        kit._write(st, P, "-", "PPR-01", "ALL9", f"{D1}090000000", pb.ppr(P, body))
        (row,), _dead, _src = _read(st, "diagnosis", licensed=pb.licensed_tables("master"))
        assert row["suspected"] == want, dis_ex


# ------------------------------------------------------------------ High, source.py:777
WIDE = "ＲＸ０１"


def test_an_order_id_is_written_as_every_earlier_reader_wrote_it(tmp_path: Path) -> None:
    """The file's オーダNo as written: ``ＲＸ０１`` stays ``ＲＸ０１`` (compared as ``RX01``, D-1252 P8, never rewritten).
    #1189 published ``RX01`` for it, so the id an earlier night stored was never replaced nor tombstoned."""
    st = _storage(tmp_path)
    nights.rx(st, WIDE, D1, f"{D1}090000000", [("NW", "1", DRUG_A)])
    (row,), _dead, _src = _read(st, "medication")
    assert row["rx_no"] == WIDE


def test_a_cancellation_reaches_the_id_an_earlier_reader_published(tmp_path: Path) -> None:
    """The finding: the lake holds the active order under the id the reader before #1189 published; the first delta
    night under the new code brings its cancellation. No active copy of the order may survive."""
    st = _storage(tmp_path)
    nights.rx(st, WIDE, D1, f"{D1}090000000", [("NW", "1", DRUG_A)])
    lake: nights.Lake = {}
    nights.apply(lake, "medication", [{"mrn": P, "rx_no": WIDE, "status": "active"}], [])  # as #1095's head wrote it
    nights.rename_to_past(next(st.root.rglob(f"*_{D1}090000000_*_1")))
    nights.rx(st, WIDE, D1, f"{D2}100000000", [("CA", "1", DRUG_A)], orc5="CA")
    nights.apply(lake, "medication", *nights.night(nights.reader(st.root), "medication", nights.SINCE))
    assert [(rid, r["status"]) for rid, r in nights.shown(lake, "medication").items()] == [(f"{P}/{WIDE}", "cancelled")]


@pytest.mark.parametrize("placer", [WIDE, "RX01"])
def test_a_newer_version_named_in_another_width_is_the_same_record_under_its_first_id(
    tmp_path: Path, placer: str
) -> None:
    """I1: the record's id is built from the オーダNo as its first file wrote it and never changes, whichever width
    a later version writes its file name or its ORC-2 in (deep review of #1238, H2: ORC-2 is compared as the key
    compares it). The delta night leaves what a full night leaves."""
    rid = WIDE

    def night1(st: kit.Storage) -> None:
        nights.rx(st, WIDE, D1, f"{D1}090000000", [("NW", "1", DRUG_A)])

    def night2(st: kit.Storage) -> None:
        nights.rename_to_past(next(st.root.rglob(f"*_{D1}090000000_*_1")))
        nights.rx(st, "RX01", D1, f"{D2}100000000", [("CA", "1", DRUG_A)], orc5="CA", placer=placer)

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert [(r, row["status"]) for r, row in full.items()] == [(f"{P}/{rid}", "cancelled")]
    assert delta == full


def test_the_ids_two_widths_gave_an_earlier_reader_are_tombstoned(tmp_path: Path) -> None:
    """A reader before D-1252 read ``ＲＸ０１`` and ``RX01`` as two orders and published both ids. They are one record
    (P8); the form that is not the record's id is a tombstone on every night, never the id in force."""
    st = _storage(tmp_path)
    nights.rx(st, "RX01", D1, f"{D1}090000000", [("NW", "1", DRUG_A)])
    nights.rx(st, WIDE, D1, f"{D2}100000000", [("NW", "1", DRUG_A)], placer=WIDE)
    rows, dead, _src = _read(st, "medication")
    assert [r["rx_no"] for r in rows] == ["RX01"]
    assert {r["rx_no"] for r in dead} == {WIDE, f"RX01:{WIDE}"}


# ------------------------------------------------------------------ High, source.py:2141 (and reviewer B, :1487)
MON, TUE = "20261109", "20261110"


def test_an_administration_of_a_reused_order_number_never_fills_another_days_prescription(tmp_path: Path) -> None:
    """``RX01`` orders drug A on Monday and drug B on Tuesday; a Tuesday administration for ``RX01`` and drug A is
    not Monday's (which order it belongs to cannot be told): it fills no line and is a row of its own, counted."""
    st = _storage(tmp_path)
    nights.rx(st, "RX01", MON, f"{MON}090000000", [("NW", "1", DRUG_A)], ordered=f"{MON}0900")
    nights.rx(st, "RX01", TUE, f"{TUE}090000000", [("NW", "1", DRUG_B)], ordered=f"{TUE}0900")
    nights.given(st, "RX01", TUE, f"{TUE}100000000", DRUG_A)
    rows, _dead, src = _read(st, "medication")
    by = {r["rx_no"]: r for r in rows}
    assert by[f"RX01@{MON}"]["end_date"] == "" and by[f"RX01@{MON}"]["dose_per_time"] == "1"
    assert by[f"RX01@{TUE}"]["end_date"] == ""
    assert by[f"RX01~{DRUG_A}"]["end_date"] == "2026-11-10 10:00:00"
    assert src.stats["OMP-11:administration not tied to an order line (the order number is filed on several days)"] == 1


def test_an_injection_administration_never_fills_a_prescription_line(tmp_path: Path) -> None:
    """Reviewer B: prescription and injection orders were pooled. An OMP-12 (injection 実施) is of an OMP-02 order."""
    st = _storage(tmp_path)
    nights.rx(st, "RX07", MON, f"{MON}090000000", [("NW", "1", DRUG_A)], ordered=f"{MON}0900")
    nights.given(st, "RX07", MON, f"{MON}100000000", DRUG_A, typ="OMP-12")
    rows, _dead, src = _read(st, "medication")
    by = {r["rx_no"]: r for r in rows}
    assert by["RX07"]["end_date"] == "" and by["RX07"]["rx_kind"] == "prescription"
    assert by[f"RX07~{DRUG_A}"]["rx_kind"] == "injection"  # a row of its own, never under the prescription's id
    assert src.stats["OMP-12:administration not tied to an order line (the number is an order of another kind)"] == 1
    assert src.stats["OMP-12:with its order"] == 0


def test_an_administration_still_fills_the_line_of_its_one_order(tmp_path: Path) -> None:
    """Guard: the order number on one day, the administration of its drug: filled as before."""
    st = _storage(tmp_path)
    nights.rx(st, "RX09", MON, f"{MON}090000000", [("NW", "1", DRUG_A)], ordered=f"{MON}0900")
    nights.given(st, "RX09", TUE, f"{TUE}100000000", DRUG_A)
    (row,), _dead, src = _read(st, "medication")
    assert row["end_date"] == "2026-11-10 10:00:00" and src.stats["OMP-11:with its order"] == 1


# ------------------------------------------------------------------ High, source.py:1348
def test_a_cross_day_rekey_never_deletes_the_id_another_record_still_carries(tmp_path: Path) -> None:
    """An OMP-02 injection of another number's file carries the id ``RX01`` (its ORC-2); two OMP-01 prescriptions
    numbered ``RX01`` arrive on two days. The plain ``RX01`` of the prescriptions is tombstoned; the injection's
    unchanged ``RX01`` must stay."""

    def night1(st: kit.Storage) -> None:
        nights.rx(st, "ALL9", D1, f"{D1}090000000", [("NW", "1", DRUG_B)], typ="OMP-02", placer="RX01")

    def night2(st: kit.Storage) -> None:
        nights.rx(st, "RX01", "20261116", f"{D2}090000000", [("NW", "1", DRUG_A)])
        nights.rx(st, "RX01", D2, f"{D2}100000000", [("NW", "1", DRUG_A)])

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert set(full) == {f"{P}/RX01", f"{P}/RX01@20261116", f"{P}/RX01@{D2}"}
    assert full[f"{P}/RX01"]["rx_kind"] == "injection"
    assert delta == full


def test_a_prescription_and_an_injection_with_one_number_are_two_records_with_two_ids(tmp_path: Path) -> None:
    """The record is patient, day, データ種別 and オーダNo (D-1252 R1): an OMP-01 and an OMP-02 of one number are two
    records. With one id the lake kept whichever was written last, and a delta night and a full night disagreed."""

    def night1(st: kit.Storage) -> None:
        nights.rx(st, "RX01", D1, f"{D1}090000000", [("NW", "1", DRUG_B)], typ="OMP-02")

    def night2(st: kit.Storage) -> None:
        nights.rx(st, "RX01", D2, f"{D2}100000000", [("NW", "1", DRUG_A)])

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert sorted((rid, r["rx_kind"]) for rid, r in full.items()) == [
        (f"{P}/RX01@OMP-01", "prescription"),
        (f"{P}/RX01@OMP-02", "injection"),
    ]
    assert delta == full


# ------------------------------------------------------------------ Medium, source.py:1016
def test_a_lab_tie_resolved_by_a_newer_file_tombstones_the_ids_only_the_tie_published(tmp_path: Path) -> None:
    def night1(st: kit.Storage) -> None:
        nights.lab(st, "L02", D1, f"{D1}090000000", [("LAB-A", "5.1", "F")])
        nights.lab(st, "L02", D1, f"{D1}090000000", [("LAB-B", "9.9", "F")], dept="02")

    def night2(st: kit.Storage) -> None:
        nights.lab(st, "L02", D1, f"{D2}100000000", [("LAB-A", "5.1", "F")])

    full, delta = nights.two_nights(tmp_path, "lab", night1, night2)
    assert [(rid, r["result_status"]) for rid, r in full.items()] == [(f"{P}/LAB-A", "final")]
    assert delta == full


def test_a_result_a_newer_version_of_its_file_no_longer_holds_is_tombstoned(tmp_path: Path) -> None:
    """The same rule without a tie: one file is one order's results (D-1252 R7), a newer version replaces them all."""

    def night1(st: kit.Storage) -> None:
        nights.lab(st, "L03", D1, f"{D1}090000000", [("LAB-A", "5.1", "F"), ("LAB-B", "9.9", "F")])

    def night2(st: kit.Storage) -> None:
        nights.rename_to_past(next(st.root.rglob(f"*_L03_{D1}090000000_*_1")))
        nights.lab(st, "L03", D1, f"{D2}100000000", [("LAB-A", "5.1", "F")])

    full, delta = nights.two_nights(tmp_path, "lab", night1, night2)
    assert set(full) == {f"{P}/LAB-A"}
    assert delta == full


def test_a_deleted_lab_file_tombstones_what_its_older_versions_named(tmp_path: Path) -> None:
    def night1(st: kit.Storage) -> None:
        nights.lab(st, "L04", D1, f"{D1}090000000", [("LAB-A", "5.1", "F"), ("LAB-B", "9.9", "F")])

    def night2(st: kit.Storage) -> None:
        nights.lab(st, "L04", D1, f"{D2}100000000", [("LAB-A", "5.1", "F")], flag="0")

    full, delta = nights.two_nights(tmp_path, "lab", night1, night2)
    assert full == {} and delta == full


# ------------------------------------------------------------------ Medium, source.py:1524
def _master(retired: str = "") -> dict[str, dict[str, dict[str, str]]]:
    tables = copy.deepcopy(pb.licensed_tables("master"))
    if retired:
        extra = json.loads(tables["medis_modifier"][retired]["extra"])
        tables["medis_modifier"][retired]["extra"] = json.dumps({**extra, "change": "1"}, ensure_ascii=False)
    return tables


def test_a_master_change_reaches_a_diagnosis_whose_file_did_not_change_on_a_delta_night(tmp_path: Path) -> None:
    """A modifier used by a confirmed diagnosis of D1 is retired in the master the site loads before night 2. No
    hospital file changes; the delta night must still send the diagnosis, now unconfirmed."""

    def night1(st: kit.Storage) -> None:
        body = [pb.prb("99990001", "左肺炎", "DX01"), pb.zpr(pre=["99980002"], dis="99990001", pre_ex=["ZM02"])]
        kit._write(st, P, "-", "PPR-01", "ALL9", f"{D1}090000000", pb.ppr(P, body))

    def with_master(retired: str = "") -> nights.Reader:
        return lambda root: Ssmix2Source(root, licensed=_master(retired), today="20261231")

    full, delta = nights.two_nights(
        tmp_path, "diagnosis", night1, lambda st: None, read1=with_master(), read2=with_master("99980002")
    )
    assert [r["suspected"] for r in full.values()] == ["U"]
    assert delta == full


def test_with_the_master_loaded_before_the_window_an_unchanged_diagnosis_is_not_sent_again(tmp_path: Path) -> None:
    """When the pipeline says when the master was loaded (``licensed_loaded_at``) and that is before the window, a
    diagnosis whose files did not change stays out of the delta; loaded inside the window, it is sent."""
    st = _storage(tmp_path)
    body = [pb.prb("99990001", "左肺炎", "DX01"), pb.zpr(pre=["99980002"], dis="99990001", pre_ex=["ZM02"])]
    kit._write(st, P, "-", "PPR-01", "ALL9", f"{D1}090000000", pb.ppr(P, body))
    for loaded, sent in (("2026-11-12T00:00:00+00:00", 0), ("2026-11-17T03:00:00+00:00", 1), (None, 1)):
        src = Ssmix2Source(st.root, licensed=_master(), today="20261231", licensed_loaded_at=loaded)
        assert len(list(src.rows("diagnosis", "diagnosis", "recorded_date", nights.SINCE))) == sent, loaded


def test_a_diagnosis_read_without_the_master_is_not_sent_on_every_night(tmp_path: Path) -> None:
    """Guard: only a row read by the master rule depends on the master."""
    st = _storage(tmp_path)
    nights.snapshot(st, f"{D1}090000000", [nights.prb("DX01")])
    src = nights.reader(st.root)
    assert list(src.rows("diagnosis", "diagnosis", "recorded_date", nights.SINCE)) == []


# ------------------------------------------------------------------ Medium, source.py:2048
def test_a_newer_order_message_with_no_drug_line_carries_the_older_version_forward_as_unknown(tmp_path: Path) -> None:
    def night1(st: kit.Storage) -> None:
        nights.rx(st, "RX05", D1, f"{D1}090000000", [("NW", "1", DRUG_A), ("NW", "2", DRUG_B)])

    def night2(st: kit.Storage) -> None:
        nights.rename_to_past(next(st.root.rglob(f"*_RX05_{D1}090000000_*_1")))
        nights.rx(st, "RX05", D1, f"{D2}100000000", [])  # MSH and PID only ...
        path = next(st.root.rglob(f"*_RX05_{D2}100000000_*_1"))
        path.write_bytes(path.read_bytes() + f"ORC|NW|RX05||1|IP||||{D1}0900\r".encode())  # ... and an ORC, no RXE

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert {(rid, r["status"], r["version_note"]) for rid, r in full.items()} == {
        (f"{P}/RX05#1:{DRUG_A}", "unknown", "the newest version could not be read"),
        (f"{P}/RX05#2:{DRUG_B}", "unknown", "the newest version could not be read"),
    }
    assert delta == full


def test_a_delete_file_with_no_drug_line_still_deletes_the_order(tmp_path: Path) -> None:
    """Guard: flag 0 is the deletion; its message need not repeat the lines."""

    def night1(st: kit.Storage) -> None:
        nights.rx(st, "RX06", D1, f"{D1}090000000", [("NW", "1", DRUG_A)])

    def night2(st: kit.Storage) -> None:
        nights.rx(st, "RX06", D1, f"{D2}100000000", [], flag="0")

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert full == {} and delta == full


# ================================================================== the two reviews of #1095
# ------------------------------------------------------------------ A :1674 and B :1665 (named by both)
@pytest.mark.parametrize(
    ("folder", "name"),
    [
        (P, f"{Q}_20261001_DSC-01_D1_20261001090000000_01_1.txt"),  # reviewer A's input
        (Q, f"{P}_20261001_NOTE_ALL9_20261001090000000_-_1"),  # reviewer B's input
        (P, f"{Q}_20261001_DSC-01_D1_2026100109_01_1.txt"),  # a standardised name that is not valid, another patient
    ],
)
def test_a_document_named_for_another_patient_is_never_stored_under_the_folders_patient(
    tmp_path: Path, folder: str, name: str
) -> None:
    st = _storage(tmp_path)
    d = st.extended / folder[0:3] / folder[3:6] / folder / "20261001" / "DSC-01"
    d.mkdir(parents=True)
    (d / name).write_bytes("患者2の退院サマリ".encode())
    rows, dead, src = _read(st, "note")
    # no note; the id a reader before this card stored it under (the folder's patient) is tombstoned
    assert rows == [] and dead == [{"note_no": f"ext/{folder}/20261001/DSC-01/{name}", "mrn": folder}]
    assert src.stats["document:quarantined (named for another patient than its folder)"] == 1
    assert [(q[0], q[2]) for q in src.quarantined] == [
        ("document", "patient: the folders name another patient than the file name")
    ]


def test_a_content_folder_named_for_another_patient_is_not_read(tmp_path: Path) -> None:
    st = _storage(tmp_path)
    d = st.extended / P[0:3] / P[3:6] / P / "20261001" / "^^^18842-5^退院時サマリー^LN"
    (d / f"{Q}_20261001_18842-5_S1_20261001090000000_01_1").mkdir(parents=True)
    (d / f"{Q}_20261001_18842-5_S1_20261001090000000_01_1" / "summary.txt").write_bytes("患者2".encode())
    rows, _dead, src = _read(st, "note")
    assert rows == [] and src.stats["document:quarantined (named for another patient than its folder)"] == 1


# ------------------------------------------------------------------ A :1208 and B :1208 (named by both)
def test_one_diagnosis_number_of_two_patients_is_two_diagnoses_in_supersession(tmp_path: Path) -> None:
    """Guard (fixed on master by #1189). Reviewer A's input: patient 1's snapshot still has DX0001, patient 2's
    newer snapshot drops it: only patient 2's DX0001 is tombstoned."""

    def night1(st: kit.Storage) -> None:
        nights.snapshot(st, "20261001090000000", [nights.prb("DX0001")], patient=P)
        nights.snapshot(st, "20261001090000000", [nights.prb("DX0001"), nights.prb("DX0002")], patient=Q)

    def night2(st: kit.Storage) -> None:
        nights.snapshot(st, "20261002090000000", [nights.prb("DX0002")], patient=Q)

    full, delta = nights.two_nights(tmp_path, "diagnosis", night1, night2, since="2026-10-02")
    assert set(full) == {f"{P}/DX0001", f"{Q}/DX0002"}
    assert delta == full


def test_another_patients_deleted_number_never_hides_a_patients_own_removal(tmp_path: Path) -> None:
    """Guard (fixed on master by #1189). Reviewer B's input: patient A drops DX42 while an earlier-read patient B
    deletes its own DX42 with ``DE``: both tombstones are sent."""
    st = _storage(tmp_path)
    nights.snapshot(st, "20261001090000000", [nights.prb("DX42", action="DE"), nights.prb("DX01")], patient=P)
    nights.snapshot(st, "20261001090000000", [nights.prb("DX42"), nights.prb("DX01")], patient=Q)
    nights.snapshot(st, "20261002090000000", [nights.prb("DX01")], patient=Q)
    _rows, dead, _src = _read(st, "diagnosis")
    assert sorted((r["mrn"], r["diag_no"]) for r in dead) == [(P, "DX42"), (Q, "DX42")]


# ------------------------------------------------------------------ A :843
@pytest.mark.parametrize("middle", ["dropped", "DE"])
def test_a_diagnosis_removed_before_the_newest_predecessor_is_still_tombstoned_on_a_delta_night(
    tmp_path: Path, middle: str
) -> None:
    """Guard (fixed on master by #1189). Reviewer A's input: three ALL9 files on one day; the middle one drops
    DX0001 (or deletes it with ``DE``); a read since 10:30 must tombstone it."""

    def night1(st: kit.Storage) -> None:
        nights.snapshot(st, "20261001090000000", [nights.prb("DX0001"), nights.prb("DX0002")])

    def night2(st: kit.Storage) -> None:
        gone = [nights.prb("DX0001", action="DE")] if middle == "DE" else []
        nights.snapshot(st, "20261001100000000", [*gone, nights.prb("DX0002")])
        nights.snapshot(st, "20261001110000000", [nights.prb("DX0002"), nights.prb("DX0003")])

    full, delta = nights.two_nights(tmp_path, "diagnosis", night1, night2, since="2026-10-01 10:30:00")
    assert set(full) == {f"{P}/DX0002", f"{P}/DX0003"}
    assert delta == full


# ------------------------------------------------------------------ A :1373 and B :1373 (named by both)
def test_a_prescription_number_filed_on_a_second_day_leaves_no_first_id_in_the_lake(tmp_path: Path) -> None:
    """Guard (fixed on master by #1189). Reviewer A's input: RX1 on 20261001 alone, then filed on 20261002."""

    def night1(st: kit.Storage) -> None:
        nights.rx(st, "RX1", "20261001", "20261001090000000", [("NW", "1", DRUG_A)], ordered="202610010900")

    def night2(st: kit.Storage) -> None:
        nights.rx(st, "RX1", "20261002", "20261002090000000", [("NW", "1", DRUG_A)], ordered="202610020900")

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2, since="2026-10-02")
    assert set(full) == {f"{P}/RX1@20261001", f"{P}/RX1@20261002"}
    assert delta == full


# ------------------------------------------------------------------ B :1430
def test_an_amendment_that_removes_one_of_two_drugs_keeps_the_other_on_a_delta_night(tmp_path: Path) -> None:
    """Guard (fixed on master by #1189). Reviewer B's input: a two-drug order of 1 October amended after the
    window opened; the surviving line's new id is sent on the night its two old ids are tombstoned."""

    def night1(st: kit.Storage) -> None:
        nights.rx(st, "RX3", "20261001", "20261001090000000", [("NW", "1", DRUG_A), ("NW", "2", DRUG_B)],
                  ordered="202610010900")  # fmt: skip

    def night2(st: kit.Storage) -> None:
        nights.rename_to_past(next(st.root.rglob("*_RX3_20261001090000000_*_1")))
        nights.rx(st, "RX3", "20261001", f"{D2}100000000", [("NW", "1", DRUG_A)], ordered="202610010900")

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert set(full) == {f"{P}/RX3"}
    assert delta == full


# ------------------------------------------------------------------ A :1286
@pytest.mark.parametrize("field", [9, 15])
def test_an_end_or_outcome_day_after_the_file_was_written_is_unknown_never_ended(tmp_path: Path, field: int) -> None:
    """Reviewer A's input: file stamp 20261001090000000, PRB-9 20301231, PRB-14 empty. A day that had not come when
    the file was written says nothing has ended: unknown (as PRB-2, 7 and 16 after the file already are), never E."""
    st = _storage(tmp_path)
    nights.snapshot(st, "20261001090000000", [nights.prb("DX01", when="20261001090000", **{f"f{field}": "20301231"})])
    (row,), _dead, src = _read(st, "diagnosis")
    assert row["status"] == "U"
    assert src.stats["PPR-01:a date after its file was written (unknown)"] == 1


def test_an_end_day_on_or_before_the_files_day_still_reads_as_ended(tmp_path: Path) -> None:
    """Guard."""
    st = _storage(tmp_path)
    nights.snapshot(st, "20261001090000000", [nights.prb("DX01", when="20261001090000", f9="20261001")])
    (row,), _dead, _src = _read(st, "diagnosis")
    assert row["status"] == "E"


# ------------------------------------------------------------------ A :551
def test_a_repeated_usage_gives_no_daily_dose_and_keeps_every_text(tmp_path: Path) -> None:
    """Reviewer A's input: TQ1-3 ``&1日1回&99XYZ~&1日3回&99XYZ`` with RXE-3 1 gave "1日1回" and a daily dose of 1."""
    st = _storage(tmp_path)
    segs = [kit._msh(f"{D1}090000", "RDE^O11^RDE_O11", "RX"), kit._pid(P), f"ORC|NW|RX08||1|IP||||{D1}0900",
            "|".join(["RXE", "", f"{DRUG_A}^x^HOT9", "1", "", "TAB"] + [""] * 26),
            f"TQ1|1||&1日1回&99XYZ~&1日3回&99XYZ||||{D1}|"]  # fmt: skip
    kit._write(st, P, D1, "OMP-01", "RX08", f"{D1}090000000", segs)
    (row,), _dead, src = _read(st, "medication")
    assert (row["daily_dose"], row["doses_per_day"], row["usage_text"]) == ("", "", "1日1回; 1日3回")
    assert src.stats["OMP-01:usage repeated in TQ1-3 (no daily dose)"] == 1


# ------------------------------------------------------------------ A hl7.py:407
@pytest.mark.parametrize("when", ["２０２６１００１０９３０＋２４００", "202610010930＋2400", "202610010930+2400"])
def test_an_out_of_range_offset_in_full_width_quarantines_the_message(tmp_path: Path, when: str) -> None:
    st = _storage(tmp_path)
    segs = [kit._msh(f"{D1}090000", "ADT^A04^ADT_A01", "A"), f"EVN||{D1}093000", kit._pid(P),
            kit._pv1("O", "V1", when)]  # fmt: skip
    path = kit._write(st, P, "20261001", "ADT-12", "ALL9", "20261001093000000", segs)
    path.write_bytes(("\r".join(segs) + "\r").encode("utf-8"))
    rows, _dead, src = _read(st, "encounter")
    assert rows == [] and src.stats["ADT-12:quarantined (time)"] == 1


# ------------------------------------------------------------------ B hl7.py:413
def test_an_identifier_shaped_like_a_time_with_an_offset_never_quarantines_its_message(tmp_path: Path) -> None:
    """Reviewer B's input: a lab message with OBR-2 ``20261001-9900`` and valid clinical times."""
    st = _storage(tmp_path)
    nights.lab(st, "L09", "20261001", "20261001090000000", [("LAB-A", "5.1", "F")], placer="20261001-9900")
    rows, _dead, src = _read(st, "lab")
    assert [r["lab_no"] for r in rows] == ["LAB-A"] and src.quarantined == []


def test_an_out_of_range_offset_in_a_time_the_reader_reads_still_quarantines(tmp_path: Path) -> None:
    """Guard: third review of PR #1095 item 10 stands for the fields that are times."""
    st = _storage(tmp_path)
    path = nights.lab(st, "L10", "20261001", "20261001090000000", [("LAB-A", "5.1", "F")])
    path.write_bytes(path.read_bytes().replace(b"|202610010800\r", b"|202610010800+9900\r"))
    rows, _dead, src = _read(st, "lab")
    assert rows == [] and src.stats["OML-11:quarantined (time)"] == 1
    assert hl7.time_problem(hl7.parse("MSH|^~\\&|a|b|c|d|20261001093000-1500\r")) != ""


# ------------------------------------------------------------------ B :1565
def test_a_lab_result_with_no_id_of_its_own_is_one_record_per_patient(tmp_path: Path) -> None:
    """Reviewer B's input: two patients, each an "ALL9" lab file on 20261001 with OBX-1 1 and no OBX-21. Both rows
    carry ``ALL9@20261001-1``: the record is the patient and that number, which is what the lake's id must be made
    of (the lake-id card, D-1253; not this reader's). Here: each patient's row is read, under its own patient."""
    st = _storage(tmp_path)
    for patient in (P, Q):
        nights.lab(st, "ALL9", "20261001", "20261001090000000", [("", "5.1", "F")], patient=patient)
    rows, _dead, _src = _read(st, "lab")
    assert sorted((r["mrn"], r["lab_no"]) for r in rows) == [(P, "ALL9@20261001-1"), (Q, "ALL9@20261001-1")]


# ------------------------------------------------------------------ B :900
def test_a_misfiled_older_snapshot_never_names_a_tombstone(tmp_path: Path) -> None:
    """Guard (fixed on master by #1189). Reviewer B's input: an older snapshot filed for one patient whose PID-3
    names another; a newer valid snapshot omits its DX42: no tombstone comes from the misfiled message."""
    st = _storage(tmp_path)
    nights.snapshot(st, "20261001090000000", [nights.prb("DX42")], patient=P, pid=Q)
    nights.snapshot(st, "20261002090000000", [nights.prb("DX01")], patient=P)
    rows, dead, _src = _read(st, "diagnosis")
    assert [r["diag_no"] for r in rows] == ["DX01"] and dead == []


# ------------------------------------------------------------------ B :1579
def test_a_correction_on_another_day_never_replaces_that_days_own_result(tmp_path: Path) -> None:
    """Reviewer B's input: one order number, a final result on 1 October and a corrected one on 2 October with the
    same OBR-2, OBX-3 and OBX-4. Under the specification's key each day is its own record: both stay."""
    st = _storage(tmp_path)
    for day, rid, status in (("20261001", "LAB-1", "F"), ("20261002", "LAB-2", "C")):
        nights.lab(st, "L20", day, f"{day}090000000", [(rid, "5.1", status)])
    rows, dead, _src = _read(st, "lab")
    assert sorted(r["lab_no"] for r in rows) == ["LAB-1", "LAB-2"] and dead == []


def test_a_correction_still_replaces_the_result_of_its_own_day(tmp_path: Path) -> None:
    """Guard: STD-021 within one day (two files, the correction under another order number of the same OBR)."""
    st = _storage(tmp_path)
    nights.lab(st, "L21", "20261001", "20261001090000000", [("LAB-1", "5.1", "F")], placer="ORD1")
    nights.lab(st, "L22", "20261001", "20261001100000000", [("LAB-2", "5.3", "C")], placer="ORD1")
    rows, dead, _src = _read(st, "lab")
    assert [r["lab_no"] for r in rows] == ["LAB-2"] and [r["lab_no"] for r in dead] == ["LAB-1"]


def test_under_unique_a_correction_reaches_the_other_day_as_before(tmp_path: Path) -> None:
    """Guard: a site that declares its order numbers unique has one record across the days (D-594)."""
    st = _storage(tmp_path)
    nights.lab(st, "L21", "20261001", "20261001090000000", [("LAB-1", "5.1", "F")], placer="ORD1")
    nights.lab(st, "L22", "20261002", "20261002100000000", [("LAB-2", "5.3", "C")], placer="ORD1")
    rows, _dead, _src = _read(st, "lab", order_key="unique")
    assert [r["lab_no"] for r in rows] == ["LAB-2"]


# ------------------------------------------------------------------ B :413
@pytest.mark.parametrize("value", ["202610010", "2026100109300", "20261001093"])
def test_a_date_with_a_time_part_that_is_not_read_makes_the_diagnosis_unknown(tmp_path: Path, value: str) -> None:
    """Reviewer B's input: PRB-7 ``202610010`` was accepted as 2026-10-01. A date half read is not a real date."""
    assert not reader.real_date(value)
    st = _storage(tmp_path)
    nights.snapshot(st, "20261101090000000", [nights.prb("DX01", when="20261001090000", f7=value)])
    (row,), _dead, src = _read(st, "diagnosis")
    assert row["status"] == "U" and row["date_text"] == f"PRB-7 {value}"
    assert src.stats["PPR-01:a date not read (unknown)"] == 1


@pytest.mark.parametrize("value", ["", "20261001", "2026100109", "202610010930", "20261001093000", "２０２６１００１"])
def test_the_dates_the_specification_writes_are_still_real_dates(value: str) -> None:
    """Guard."""
    assert reader.real_date(value)


# ------------------------------------------------------------------ the invariant behind the tombstone findings
@pytest.mark.parametrize("table", ["diagnosis", "medication", "lab"])
def test_no_tombstone_ever_names_an_id_a_record_in_force_carries(tmp_path: Path, table: str) -> None:
    """Whatever the storage, on any night: an id the full read gives a row is never among the tombstones. Read on
    the kit's whole storage and on one that mixes the cases above."""
    st = kit.build(tmp_path)
    nights.rx(st, "ALL9", D1, f"{D1}090000000", [("NW", "1", DRUG_B)], typ="OMP-02", placer="RX01")
    nights.rx(st, "RX01", "20261116", f"{D2}090000000", [("NW", "1", DRUG_A)])
    nights.rx(st, "RX01", D2, f"{D2}100000000", [("NW", "1", DRUG_A)])
    nights.lab(st, "L02", D1, f"{D1}090000000", [("LAB-A", "5.1", "F"), ("LAB-B", "1", "F")])
    nights.lab(st, "L02", D1, f"{D2}090000000", [("LAB-A", "5.1", "F")])
    nights.lab(st, "L77", D1, f"{D1}090000000", [("LAB-B", "2", "F")])  # another record carries the dropped id
    src = nights.reader(st.root)
    key = nights.KEY[table]
    live = {(r["mrn"], r[key]) for r in src.rows(table, table, None, None)}
    dead = {(r["mrn"], r[key]) for r in src.deleted_rows(table, table, None, None)}
    assert live and not (live & dead)


def test_the_licensed_store_says_when_the_tables_it_gave_were_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """``adapter.licensed.tables()`` is how the pipeline gives the reader its tables: the reader learns from it when
    the newest active release was loaded, with no word from the pipeline. Another dictionary's time is not known."""
    from adapter import licensed as lic

    class Store:
        def __init__(self, url: str | None = None) -> None:
            pass

        def concepts(self, kind: str) -> dict[str, dict[str, str]]:
            return {}

        def status(self) -> list[dict[str, Any]]:
            return [
                {"kind": "medis", "state": "loaded", "loaded_at": "2026-11-12T01:00:00+00:00"},
                {"kind": "medis_modifier", "state": "loaded", "loaded_at": "2026-11-17T03:00:00+00:00"},
                {"kind": "yj", "state": "not_loaded", "loaded_at": ""},
            ]

        def close(self) -> None:
            pass

    monkeypatch.setattr(lic, "TermStore", Store)
    given = lic.tables("memory://d-1257")
    assert lic.loaded_at_of(given) == "2026-11-17T03:00:00+00:00"
    assert lic.loaded_at_of(dict(given)) is None and lic.loaded_at_of(nights.EMPTY) is None
    assert reader._latest_local(lic.loaded_at_of(given)) == "2026-11-17 17:00:00"  # the latest local time anywhere


# ------------------------------------------------------------------ no id the reader ever published is left behind
def _order(number: str, day: str, stamp: str, drugs: list[str], typ: str = "OMP-01", placer: str | None = None) -> Any:
    def write(st: kit.Storage) -> None:
        nights.rx(st, number, day, stamp, [("NW", str(n), d) for n, d in enumerate(drugs, 1)], typ=typ, placer=placer)

    return write


def _past(stamp: str) -> Any:
    return lambda st: nights.rename_to_past(next(st.root.rglob(f"*_{stamp}_*_1")))


S1, S2, S3 = f"{D1}090000000", f"{D2}090000000", f"{D2}100000000"
E16 = "20261116"
#: every form an order id has had (plain, by its lines, by its day, by its type, by both, full-width), as night one
#: leaves it, and the change night two brings: ``(name, night one, night two, the ids a full night two holds)``
KEY_CHANGES: list[tuple[str, list[Any], list[Any], set[str]]] = [
    ("plain to its day", [_order("RX1", D1, S1, [DRUG_A])], [_order("RX1", D2, S2, [DRUG_A])],
     {f"RX1@{D1}", f"RX1@{D2}"}),
    ("plain to its lines", [_order("RX1", D1, S1, [DRUG_A])], [_past(S1), _order("RX1", D1, S2, [DRUG_A, DRUG_B])],
     {f"RX1#1:{DRUG_A}", f"RX1#2:{DRUG_B}"}),
    ("its lines to plain", [_order("RX1", D1, S1, [DRUG_A, DRUG_B])], [_past(S1), _order("RX1", D1, S2, [DRUG_B])],
     {"RX1"}),
    ("plain to its type", [_order("RX1", D1, S1, [DRUG_A])], [_order("RX1", D1, S2, [DRUG_B], "OMP-02")],
     {"RX1@OMP-01", "RX1@OMP-02"}),
    ("its day to its type and day",
     [_order("RX1", D1, S1, [DRUG_A]), _order("RX1", E16, f"{D1}100000000", [DRUG_A])],
     [_order("RX1", D2, S2, [DRUG_B], "OMP-02")],
     {f"RX1@OMP-01@{D1}", f"RX1@OMP-01@{E16}", "RX1@OMP-02"}),
    ("its type to its type and day",
     [_order("RX1", D1, S1, [DRUG_A]), _order("RX1", D1, f"{D1}100000000", [DRUG_B], "OMP-02")],
     [_order("RX1", D2, S2, [DRUG_A])],
     {f"RX1@OMP-01@{D1}", f"RX1@OMP-01@{D2}", "RX1@OMP-02"}),
    ("its lines to its lines and day", [_order("RX1", D1, S1, [DRUG_A, DRUG_B])], [_order("RX1", D2, S2, [DRUG_A])],
     {f"RX1@{D1}#1:{DRUG_A}", f"RX1@{D1}#2:{DRUG_B}", f"RX1@{D2}"}),
    ("full-width, a version in the other width", [_order("ＲＸ１", D1, S1, [DRUG_A])],
     [_past(S1), _order("RX1", D1, S2, [DRUG_B])], {"ＲＸ１"}),
    ("full-width, a version in the other width that writes ORC-2 as before", [_order("ＲＸ１", D1, S1, [DRUG_A])],
     [_past(S1), _order("RX1", D1, S2, [DRUG_B], placer="ＲＸ１")], {"ＲＸ１"}),
    ("half-width, a version in full width", [_order("RX1", D1, S1, [DRUG_A])],
     [_past(S1), _order("ＲＸ１", D1, S2, [DRUG_B])], {"RX1"}),
    ("full-width to its day", [_order("ＲＸ１", D1, S1, [DRUG_A])], [_order("ＲＸ１", D2, S2, [DRUG_A])],
     {f"ＲＸ１@{D1}", f"ＲＸ１@{D2}"}),
    ("full-width on one day, half-width on another", [_order("ＲＸ１", D1, S1, [DRUG_A])],
     [_order("RX1", D2, S2, [DRUG_A])], {f"ＲＸ１@{D1}", f"RX1@{D2}"}),
    ("an administration with no order, then its order", [lambda st: nights.given(st, "RX1", D1, S1, DRUG_A)],
     [_order("RX1", D1, S2, [DRUG_A])], {"RX1"}),
    # deep review of #1238, H1: an administration that filled a line becomes a row of its own when its order's
    # number is filed on a second day; its file is old, and the night must still send it
    ("an administration that filled a line, then its number on a second day",
     [_order("RX1", D1, S1, [DRUG_A]), lambda st: nights.given(st, "RX1", D1, f"{D1}100000000", DRUG_A)],
     [_order("RX1", D2, S2, [DRUG_A])], {f"RX1@{D1}", f"RX1@{D2}", f"RX1~{DRUG_A}"}),
    ("an administration that filled a line, then a version of the order without its drug",
     [_order("RX1", D1, S1, [DRUG_A]), lambda st: nights.given(st, "RX1", D1, f"{D1}100000000", DRUG_A)],
     [_past(S1), _order("RX1", D1, S2, [DRUG_B])], {"RX1", f"RX1~{DRUG_A}"}),
    # L1: the id it had as a row of its own goes when it is tied
    ("an administration of another drug, then a version of the order with its drug",
     [_order("RX1", D1, S1, [DRUG_B]), lambda st: nights.given(st, "RX1", D1, f"{D1}100000000", DRUG_A)],
     [_past(S1), _order("RX1", D1, S2, [DRUG_A])], {"RX1"}),
    ("an administration with no order, then its order of two lines",
     [lambda st: nights.given(st, "RX1", D1, S1, DRUG_A)],
     [_order("RX1", D1, S2, [DRUG_B, "999000003"])],
     {f"RX1#1:{DRUG_B}", "RX1#2:999000003", f"RX1~{DRUG_A}"}),
    # H2 (b), L1: the plain id two days' prescriptions leave is taken by an injection's administration whose file
    # is old: its tombstone is not sent, so the row itself is
    ("an injection's administration takes the plain id two days' prescriptions leave",
     [_order("RX1", D1, S1, [DRUG_A]), lambda st: nights.given(st, "RX1", D1, f"{D1}100000000", DRUG_B, typ="OMP-12")],
     [_order("RX1", D2, S2, [DRUG_A])], {f"RX1@{D1}", f"RX1@{D2}", "RX1"}),
    ("a deleted order of a number another type holds",
     [_order("RX1", D1, S1, [DRUG_A]), _order("RX1", D1, f"{D1}100000000", [DRUG_B], "OMP-02")],
     [lambda st: nights.rx(st, "RX1", D1, S3, [("CA", "1", DRUG_B)], typ="OMP-02", flag="0")],
     {"RX1@OMP-01"}),
]  # fmt: skip


@pytest.mark.parametrize(("name", "first", "second", "ids"), KEY_CHANGES, ids=[c[0] for c in KEY_CHANGES])
def test_no_id_the_reader_ever_published_is_left_behind_by_a_key_change(
    tmp_path: Path, name: str, first: list[Any], second: list[Any], ids: set[str]
) -> None:
    """The lesson of :777, as one rule over every key form: night one under the old form, night two under the new.
    The delta night leaves exactly what a full night leaves: the new ids, and none of the old."""

    def night1(st: kit.Storage) -> None:
        for write in first:
            write(st)

    def night2(st: kit.Storage) -> None:
        for write in second:
            write(st)

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert set(full) == {f"{P}/{rid}" for rid in ids}, name
    assert delta == full, name


# ================================================================== the deep review of #1238
def test_one_patients_nightly_tombstone_never_removes_another_patients_order_of_the_same_number(tmp_path: Path) -> None:
    """H3: the adapter's id is made of the key column alone, so patient P's tombstone of the plain ``RX01`` (two
    days' prescriptions, tombstoned on every night) is the id of patient Q's unchanged order ``RX01``. The harness
    builds its ids with ``Mapper.row_id``; Q's order is in the lake after a delta night as after a full one."""

    def night1(st: kit.Storage) -> None:
        nights.rx(st, "RX01", D1, f"{D1}090000000", [("NW", "1", DRUG_A)])
        nights.rx(st, "RX01", "20261111", f"{D1}100000000", [("NW", "1", DRUG_A)])
        nights.rx(st, "RX01", D1, f"{D1}090000000", [("NW", "1", DRUG_B)], patient=Q)

    def night2(st: kit.Storage) -> None:
        nights.rx(st, "RX55", D2, f"{D2}090000000", [("NW", "1", DRUG_A)])

    full, delta = nights.two_nights(tmp_path, "medication", night1, night2)
    assert f"{Q}/RX01" in full and full[f"{Q}/RX01"]["source_drug_code"] == DRUG_B
    assert delta == full


def test_a_lab_result_two_orders_name_keeps_the_value_of_the_order_that_still_holds_it(tmp_path: Path) -> None:
    """L3: two lab orders share one result id. The order read last drops it in a newer version; its tombstone is not
    sent (the other order's result carries the id), so that result is sent and the dropped value does not stay."""

    def night1(st: kit.Storage) -> None:
        nights.lab(st, "L10", D1, f"{D1}090000000", [("LAB-B", "2", "F")])
        nights.lab(st, "L90", D1, f"{D1}090000000", [("LAB-A", "5.1", "F"), ("LAB-B", "1", "F")])

    def night2(st: kit.Storage) -> None:
        nights.rename_to_past(next(st.root.rglob(f"*_L90_{D1}090000000_*_1")))
        nights.lab(st, "L90", D1, f"{D2}090000000", [("LAB-A", "5.1", "F")])

    full, delta = nights.two_nights(tmp_path, "lab", night1, night2)
    assert full[f"{P}/LAB-B"]["result_value"] == "2"
    assert delta == full


def test_a_document_whose_name_merely_has_seven_parts_is_the_folders_own_document(tmp_path: Path) -> None:
    """M1: seven parts between underscores are not the standardised form. ``discharge_summary_2026_11_10_final_v2``
    names no patient: it is read as the folder's document, and the id it is stored under is never tombstoned."""
    st = _storage(tmp_path)
    d = st.extended / P[0:3] / P[3:6] / P / "20261001" / "DSC-01"
    d.mkdir(parents=True)
    (d / "discharge_summary_2026_11_10_final_v2.txt").write_bytes("退院サマリ".encode())
    rows, dead, src = _read(st, "note")
    assert [r["note_no"] for r in rows] == [f"ext/{P}/20261001/DSC-01/discharge_summary_2026_11_10_final_v2.txt"]
    assert dead == [] and src.quarantined == []
