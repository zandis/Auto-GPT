"""Card 10B-2b (D-1252), the second tester's class A: on a delta night the SS-MIX2 reader sends what a full night
sends, so the lake after a delta night 2 equals the lake after a full night 2.

The window is decided by the newest 発生日時 of the files that decide each record (its versions, flag 2 and deleted
ones included; for an order number filed on several days, all of them), never by a clinical date alone
(ORC-9, the sample time, the visit time). ``pipeline.check_delta`` exempts SS-MIX2 ("it versions its files itself");
these tests are the proof. Each storage is synthetic; each case failed on #1095's head (master 8bfebd70).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import ssmix2_nights as nights
from tests import ssmix2_spec_kit as kit

EMPTY = nights.EMPTY
DELTA, KEY = nights.DELTA, nights.KEY
D1, D2 = nights.D1, nights.D2  # night 1 writes on D1, night 2 on D2
SINCE = nights.SINCE
P = kit.P1
#: review of #1189 (D-1257): "full" is night 2's storage read whole into an empty lake, never seeded with night 1's
#: rows; "delta" is night 1's lake with night 2's window merged over it (``tests/ssmix2_nights.py``)
_two_nights = nights.two_nights
_rename_to_past = nights.rename_to_past


def _rx(st: kit.Storage, number: str, day: str, stamp: str, lines: list[tuple[str, str, str]], orc5: str = "IP",
        flag: str = "1") -> Path:  # fmt: skip
    segs = [kit._msh(f"{day}090000", "RDE^O11^RDE_O11", number), kit._pid(P)]
    for orc1, rp, drug in lines:
        segs += [f"ORC|{orc1}|{number}||{rp}|{orc5}||||{D1}0900",
                 "|".join(["RXE", "", f"{drug}^x^HOT9", "1", "", "TAB"] + [""] * 26),
                 f"TQ1|1||U01&1日1回&99XYZ||||{D1}|"]  # fmt: skip
    return kit._write(st, P, day, "OMP-01", number, stamp, segs, flag=flag)


# ------------------------------------------------------------------------------------------------ orders
@pytest.mark.parametrize(("orc1", "orc5", "status"), [("CA", "CA", "cancelled"), ("DC", "DC", "stopped")])
def test_a_newer_order_version_with_old_clinical_dates_reaches_the_lake_on_a_delta_night(
    tmp_path: Path, orc1: str, orc5: str, status: str
) -> None:
    def night1(st: kit.Storage) -> None:
        _rx(st, "RX01", D1, f"{D1}090000000", [("NW", "1", "999000001")])

    def night2(st: kit.Storage) -> None:
        old = next(st.root.rglob(f"*_RX01_{D1}090000000_*_1"))
        _rename_to_past(old)
        _rx(st, "RX01", D1, f"{D2}100000000", [(orc1, "1", "999000001")], orc5=orc5)

    full, delta = _two_nights(tmp_path, "medication", night1, night2)
    assert full[f"{P}/RX01"]["status"] == status
    assert delta == full


def test_an_order_going_from_two_lines_to_one_is_rekeyed_on_the_same_night(tmp_path: Path) -> None:
    def night1(st: kit.Storage) -> None:
        _rx(st, "RX03", D1, f"{D1}090000000", [("NW", "1", "999000001"), ("NW", "2", "999000002")])

    def night2(st: kit.Storage) -> None:
        _rx(st, "RX03", D1, f"{D2}100000000", [("NW", "1", "999000001")])

    full, delta = _two_nights(tmp_path, "medication", night1, night2)
    assert set(full) == {f"{P}/RX03"}
    assert delta == full


def test_an_order_number_appearing_on_a_second_older_day_is_rekeyed_on_the_same_night(tmp_path: Path) -> None:
    def night1(st: kit.Storage) -> None:
        _rx(st, "RX07", D2, f"{D2}090000000", [("NW", "1", "999000001")])

    def night2(st: kit.Storage) -> None:
        _rx(st, "RX07", D1, f"{D2}100000000", [("NW", "1", "999000001")])

    full, delta = _two_nights(tmp_path, "medication", night1, night2)
    assert set(full) == {f"{P}/RX07@{D1}", f"{P}/RX07@{D2}"}
    assert delta == full


def test_an_administration_written_tonight_reaches_its_order_on_a_delta_night(tmp_path: Path) -> None:
    def night1(st: kit.Storage) -> None:
        _rx(st, "RX09", D1, f"{D1}090000000", [("NW", "1", "999000001")])

    def night2(st: kit.Storage) -> None:
        segs = [kit._msh(f"{D1}100000", "RAS^O17^RAS_O17", "A9"), kit._pid(P), f"ORC|RE|RX09||1|CM||||{D1}0900",
                "RXA|0|1|202611101000|202611101000|999000001^x^HOT9|2|TAB"]  # fmt: skip
        kit._write(st, P, D1, "OMP-11", "RX09", f"{D2}100000000", segs)

    full, delta = _two_nights(tmp_path, "medication", night1, night2)
    assert full[f"{P}/RX09"]["dose_per_time"] == "1"  # the order's own dose, the administration filled the rest
    assert delta == full


# ------------------------------------------------------------------------------------------------ labs
def test_a_corrected_lab_result_with_the_same_sample_time_reaches_the_lake_on_a_delta_night(tmp_path: Path) -> None:
    def lab(value: str, status: str) -> list[str]:
        return [kit._msh(f"{D1}090000", "OUL^R22^OUL_R22", "L"), kit._pid(P), f"SPM|1|||||||||||||||||{D1}0800",
                f"OBR|1|L01|L01||||{D1}0800",
                f"OBX|1|NM|3D010000001927201^HbA1c^JC10||{value}|%|||||{status}|||{D1}0800"]  # fmt: skip

    def night1(st: kit.Storage) -> None:
        kit._write(st, P, D1, "OML-11", "L01", f"{D1}090000000", lab("0.9", "F"))

    def night2(st: kit.Storage) -> None:
        _rename_to_past(next(st.root.rglob(f"*_L01_{D1}090000000_*_1")))
        kit._write(st, P, D1, "OML-11", "L01", f"{D2}100000000", lab("2.9", "C"))

    full, delta = _two_nights(tmp_path, "lab", night1, night2)
    assert [r["result_value"] for r in full.values()] == ["2.9"]
    assert delta == full


# ------------------------------------------------------------------------------------------------ diagnoses, admissions
def test_a_newer_snapshot_with_an_old_record_date_reaches_the_lake_on_a_delta_night(tmp_path: Path) -> None:
    def prb(no: str, outcome: str = "") -> str:
        f = ["PRB", "AD", f"{D1}090000", f"9999000{no[-1]}^肺炎^MDCDX2", no] + [""] * 14
        f[10], f[14] = "J189^^I10", outcome
        return "|".join(f)

    def night1(st: kit.Storage) -> None:
        kit._write(st, P, "-", "PPR-01", "ALL9", f"{D1}090000000",
                   [kit._msh(f"{D1}090000", "PPR^ZD1^PPR_ZD1", "P"), kit._pid(P), prb("DX01"), prb("DX02")])  # fmt: skip

    def night2(st: kit.Storage) -> None:
        _rename_to_past(next(st.root.rglob(f"*_ALL9_{D1}090000000_*_1")))
        kit._write(st, P, "-", "PPR-01", "ALL9", f"{D2}100000000",
                   [kit._msh(f"{D1}090000", "PPR^ZD1^PPR_ZD1", "P"), kit._pid(P), prb("DX01", "Z^x^99XYZ")])  # fmt: skip

    full, delta = _two_nights(tmp_path, "diagnosis", night1, night2)
    assert set(full) == {f"{P}/DX01"} and full[f"{P}/DX01"]["status"] == "U"
    assert delta == full


def test_a_discharge_written_tonight_reaches_its_admission_on_a_delta_night(tmp_path: Path) -> None:
    def night1(st: kit.Storage) -> None:
        segs = [kit._msh(f"{D1}100000", "ADT^A01^ADT_A01", "A"), f"EVN||{D1}100000", kit._pid(P),
                kit._pv1("I", "V1", f"{D1}1000")]  # fmt: skip
        kit._write(st, P, D1, "ADT-22", "1", f"{D1}100000000", segs)

    def night2(st: kit.Storage) -> None:
        segs = [kit._msh(f"{D1}110000", "ADT^A03^ADT_A03", "D"), f"EVN||{D1}110000", kit._pid(P),
                kit._pv1("I", "V1", f"{D1}1000", f"{D1}1100")]  # fmt: skip
        kit._write(st, P, D1, "ADT-52", "1", f"{D2}100000000", segs)

    full, delta = _two_nights(tmp_path, "encounter", night1, night2)
    assert [r["enc_status"] for r in full.values()] == ["finished"]
    assert delta == full


def test_a_late_older_day_file_with_an_old_stamp_never_drops_the_newer_days_order(tmp_path: Path) -> None:
    """Lane J at 9253347e: an older day's file arrives late with an old 発生日時. The plain key is tombstoned that night,
    so every day-keyed row replacing it is sent that night, the newer day's too."""

    def night1(st: kit.Storage) -> None:
        _rx(st, "RX07", D1, f"{D1}090000000", [("NW", "1", "999000001")])

    def night2(st: kit.Storage) -> None:
        _rx(st, "RX07", "20261105", "20261105090000000", [("NW", "1", "999000001")])

    full, delta = _two_nights(tmp_path, "medication", night1, night2)
    assert set(full) == {f"{P}/RX07@20261105", f"{P}/RX07@{D1}"}
    assert delta == full


def test_two_live_lab_versions_with_one_stamp_are_unknown_on_every_night(tmp_path: Path) -> None:
    """P5 applied to OML-11 (lane J at 9253347e): which of two live versions with one 発生日時 is in force cannot be
    told; the result is read with status unknown, never one value chosen by file name."""

    def lab(value: str) -> list[str]:
        return [kit._msh(f"{D1}090000", "OUL^R22^OUL_R22", "L"), kit._pid(P), f"SPM|1|||||||||||||||||{D1}0800",
                f"OBR|1|L02|L02||||{D1}0800",
                f"OBX|1|NM|3D010000001927201^HbA1c^JC10||{value}|%|||||F|||{D1}0800"]  # fmt: skip

    def night1(st: kit.Storage) -> None:
        kit._write(st, P, D1, "OML-11", "L02", f"{D1}090000000", lab("5.1"))

    def night2(st: kit.Storage) -> None:
        kit._write(st, P, D1, "OML-11", "L02", f"{D1}090000000", lab("9.9"), dept="02")

    full, delta = _two_nights(tmp_path, "lab", night1, night2)
    assert [(r["result_status"], r["version_note"]) for r in full.values()] == [
        ("unknown", "two versions with one 発生日時")
    ]
    assert delta == full
