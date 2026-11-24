"""R22-44: an SS-MIX2 file cut short (half written by the gateway, or truncated for good) is not read as complete.

A message is complete only when its last segment carries its segment end (CR; CRLF and LF are read as before) and,
for an order message (OMP-01 / OMP-02), every ORC has its RXE. A file that is not complete is quarantined (counted
in ``stats`` and listed in ``quarantined`` with the reason "file cut short"), never read tonight. The older version
of the same record stays the version read, as for any newest version that cannot be read (D-1252 P4: its rows go
out with the reason in ``version_note``). Synthetic data only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
P = kit.P1
D1, D2 = "20261110", "20261117"
OLD_DRUG, NEW_DRUG = "999000001", "999000009"
CUT = "file cut short"
FALLBACK = "the newest version could not be read"


def _storage(tmp_path: Path) -> kit.Storage:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True)
    return st


def _rx(st: kit.Storage, stamp: str, drug: str, flag: str = "1") -> Path:
    segs = [
        kit._msh(f"{D1}090000", "RDE^O11^RDE_O11", "RX01"),
        kit._pid(P),
        f"ORC|NW|RX01||1|IP||||{D1}0900",
        "|".join(["RXE", "", f"{drug}^x^HOT9", "2", "", "TAB"] + [""] * 26),
        f"TQ1|1||U03&1日3回&99XYZ||||{D1}|",
    ]
    return kit._write(st, P, D1, "OMP-01", "RX01", stamp, segs, flag=flag)


def _two_orders(st: kit.Storage) -> Path:
    """Night 1's order (flag 2 once replaced) and night 2's newer version with another drug, returned to be cut."""
    _rx(st, f"{D1}090000000", OLD_DRUG, flag="2")
    return _rx(st, f"{D2}100000000", NEW_DRUG)


def _medication(st: kit.Storage) -> tuple[list[dict[str, str]], Ssmix2Source]:
    src = Ssmix2Source(st.root, licensed=EMPTY, today=D2)
    return list(src.rows("medication", "medication", None, None)), src


def _held(src: Ssmix2Source, typ: str) -> None:
    assert [q[0] for q in src.quarantined] == [typ]
    assert src.quarantined[0][2].startswith(f"{CUT}: ")
    assert src.stats[f"{typ}:quarantined ({CUT})"] == 1


def _keeps_the_older_order(rows: list[dict[str, str]]) -> None:
    (row,) = rows
    assert row["rx_no"] == "RX01"
    assert row["source_drug_code"] == OLD_DRUG  # never the cut code, never nothing
    assert row["daily_dose"] == "6"
    assert row["version_note"] == FALLBACK


def _cut_at(path: Path, at: int) -> None:
    path.write_bytes(path.read_bytes()[:at])


def test_an_order_cut_inside_its_drug_code_is_held_and_the_older_order_is_read(tmp_path: Path) -> None:
    st = _storage(tmp_path)
    p = _two_orders(st)
    data = p.read_bytes()
    _cut_at(p, data.index(NEW_DRUG.encode()) + 5)  # RXE-2 reads "99900"
    rows, src = _medication(st)
    _held(src, "OMP-01")
    _keeps_the_older_order(rows)


def test_an_order_cut_before_its_rxe_is_held_and_the_older_order_is_read(tmp_path: Path) -> None:
    st = _storage(tmp_path)
    p = _two_orders(st)
    _cut_at(p, p.read_bytes().index(b"RXE"))  # ends with the ORC's CR: an ORC with no RXE
    rows, src = _medication(st)
    _held(src, "OMP-01")
    _keeps_the_older_order(rows)


def test_an_order_cut_inside_its_usage_is_held_and_the_older_order_is_read(tmp_path: Path) -> None:
    st = _storage(tmp_path)
    p = _two_orders(st)
    _cut_at(p, p.read_bytes().index(b"U03") + 3)  # TQ1-3 reads "U03" with no text: no doses a day
    rows, src = _medication(st)
    _held(src, "OMP-01")
    _keeps_the_older_order(rows)


def test_an_order_without_the_last_segment_end_is_held(tmp_path: Path) -> None:
    st = _storage(tmp_path)
    p = _two_orders(st)
    data = p.read_bytes()
    assert data.endswith(b"\r")
    _cut_at(p, len(data) - 1)  # every segment whole, the last one's CR missing
    rows, src = _medication(st)
    _held(src, "OMP-01")
    _keeps_the_older_order(rows)


def test_a_cut_order_with_no_older_version_gives_no_row(tmp_path: Path) -> None:
    st = _storage(tmp_path)
    p = _rx(st, f"{D2}100000000", NEW_DRUG)
    _cut_at(p, p.read_bytes().index(NEW_DRUG.encode()) + 5)
    rows, src = _medication(st)
    _held(src, "OMP-01")
    assert rows == []


def _ppr(st: kit.Storage, stamp: str, flag: str = "1") -> Path:
    prbs = [
        kit._prb("AD", "99990001", "胃炎", icd10="K297", established="20261101"),
        kit._prb("AD", "99990002", "２型糖尿病", icd10="E119", established="20261101"),
    ]
    segs = [kit._msh(stamp[:14], "PPR^ZD1^PPR_ZD1", "PPR" + stamp[-6:]), kit._pid(P), *prbs]
    return kit._write(st, P, "-", "PPR-01", "ALL9", stamp, segs, flag=flag)


def test_a_diagnosis_snapshot_cut_inside_its_second_prb_is_held_and_the_older_snapshot_is_read(
    tmp_path: Path,
) -> None:
    st = _storage(tmp_path)
    _ppr(st, f"{D1}090000000", flag="2")
    p = _ppr(st, f"{D2}090000000")
    data = p.read_bytes()
    second = data.index(b"PRB|AD|", data.index(b"PRB|AD|") + 3)
    _cut_at(p, second + 12)
    src = Ssmix2Source(st.root, licensed=EMPTY, today=D2)
    rows = list(src.rows("diagnosis", "diagnosis", None, None))
    _held(src, "PPR-01")
    assert sorted(r["icd10"] for r in rows) == ["E11.9", "K29.7"]  # the second diagnosis is not lost
    assert {r["version_note"] for r in rows} == {FALLBACK}


@pytest.mark.parametrize("end", ["\r", "\r\n", "\n"])
def test_a_complete_order_is_read_with_any_segment_end_the_reader_reads(tmp_path: Path, end: str) -> None:
    st = _storage(tmp_path)
    p = _two_orders(st)
    p.write_bytes(p.read_bytes().replace(b"\r", end.encode()))
    rows, src = _medication(st)
    assert src.quarantined == []
    (row,) = rows
    assert (row["source_drug_code"], row["status"], row["daily_dose"]) == (NEW_DRUG, "active", "6")
    assert "version_note" not in row


#: the two lab messages earlier tests wrote with no final CR (``test_lab_units_per_row._oml`` and
#: ``integration/test_ssmix2_path``'s ``put``): (MSH-18, encoding, OBX-14 and what follows it)
OLD_FORMS = {
    "lab-units-oml": ("~ISO IR87", "iso2022_jp", "クレアチニン", "20261001090000"),
    "ssmix2-path-put-utf8": ("UNICODE UTF-8", "utf-8", "尿酸", "20261001090000"),
}


@pytest.mark.parametrize("form", sorted(OLD_FORMS))
def test_a_lab_message_written_without_its_final_cr_is_held(tmp_path: Path, form: str) -> None:
    cs, enc, name, when = OLD_FORMS[form]
    st = _storage(tmp_path)
    d = st.root / P[0:3] / P[3:6] / P / "20261001" / "OML-11"
    d.mkdir(parents=True)
    msg = "\r".join(
        [
            f"MSH|^~\\&|HIS||TB||20261001||OUL^R22|1|P|2.5||||||{cs}",
            f"PID|||{P}^^^^PI",
            "OBR|1|L1",
            f"OBX|1|NM|3C015000002327101^{name}^JC10||0.9|mg/dL||||||||{when}" + "|" * 7 + "L1",
        ]
    )  # the old way: the last segment's CR missing
    (d / f"{P}_20261001_OML-11_L1_20261001000000000_-_1").write_bytes(msg.encode(enc))
    src = Ssmix2Source(st.root, licensed=EMPTY, today=D2)
    assert list(src.rows("lab", "lab", None, None)) == []
    _held(src, "OML-11")
    assert src.quarantined[0][2] == f"{CUT}: the last segment has no segment end (CR)"


def test_a_short_complete_order_with_no_timing_is_read(tmp_path: Path) -> None:
    st = _storage(tmp_path)
    segs = [
        kit._msh(f"{D1}090000", "RDE^O11^RDE_O11", "RX02"),
        kit._pid(P),
        f"ORC|NW|RX02||1|IP||||{D1}0900",
        "|".join(["RXE", "", f"{NEW_DRUG}^x^HOT9", "1", "", "TAB"]),
    ]
    kit._write(st, P, D1, "OMP-01", "RX02", f"{D1}090000000", segs)
    rows, src = _medication(st)
    assert src.quarantined == []
    assert [(r["rx_no"], r["status"]) for r in rows] == [("RX02", "active")]
