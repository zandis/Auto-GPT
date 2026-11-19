"""The fourth review of PR #1095 (lane J's re-probe at 91601b6f), group 1, points a to f: a value is confirmed,
active or this patient's only when everything about it is positively recognised. Each test failed on the reader at
91601b6f, except the guards named in their docstrings. All data is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source, outcome_table

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
DAY = "20261001"


def _source(st: kit.Storage) -> Ssmix2Source:
    return Ssmix2Source(st.root, licensed=EMPTY)


def _ss(tmp_path: Path) -> kit.Storage:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True)
    return st


def _prb(**at: str) -> str:
    prb = ["PRB", "AD", DAY, "99990001^肺癌^MDCDX2", "DX1"] + [""] * 14
    prb[10] = "C349^^I10"
    for n, v in at.items():
        prb[int(n[1:])] = v
    return "|".join(prb)


def _dx(tmp_path: Path, *segs: str, pid: str | None = None) -> tuple[list[dict[str, object]], Ssmix2Source]:
    st = _ss(tmp_path)
    head = [kit._msh(f"{DAY}0900", "PPR^ZD1^PPR_ZD1", "P")] + (
        [kit._pid(kit.P1)] if pid is None else [pid] if pid else []
    )
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY), [*head, *segs])
    src = _source(st)
    return list(src.rows("diagnosis", "diagnosis", None, None)), src


# ------------------------------------------------------------------------------------------------ a: allow-list
def test_a_a_plain_recognised_diagnosis_is_still_confirmed_and_active(tmp_path: Path) -> None:
    """Guard (passes before and after): PRB-1 AD, no flag, no modifier, no outcome, no end."""
    (row,), _ = _dx(tmp_path, _prb())
    assert (row["status"], row["suspected"]) == ("A", "")


@pytest.mark.parametrize("flag", ["0^否定できない^JHSD0005", "^可能性^99XYZ", "2^x^JHSD0005", "0^仮診断^JHSD0005"])
def test_a_a_certainty_field_the_reader_does_not_recognise_is_unknown(tmp_path: Path, flag: str) -> None:
    (row,), _ = _dx(tmp_path, _prb(f13=flag))
    assert row["suspected"] == "U"


@pytest.mark.parametrize(("written", "zpr"), [("肺癌の可能性", ()), ("肺癌", ("ZPR|1|9001^除外^99XYZ",)),
                                              ("possible lung cancer", ()), ("肺癌の恐れ", ())])  # fmt: skip
def test_a_a_written_name_or_modifier_the_reader_does_not_recognise_is_unknown(
    tmp_path: Path, written: str, zpr: tuple[str, ...]
) -> None:
    (row,), _ = _dx(tmp_path, _prb(f17=written), *zpr)
    assert row["suspected"] == "U"


@pytest.mark.parametrize("action", ["D", "XX", "UN", ""])
def test_a_an_action_code_the_reader_does_not_recognise_is_unknown(tmp_path: Path, action: str) -> None:
    (row,), _ = _dx(tmp_path, _prb(f1=action))
    assert row["status"] == "U"


def test_a_an_outcome_date_with_no_outcome_code_is_ended(tmp_path: Path) -> None:
    (row,), _ = _dx(tmp_path, _prb(f15="20261020"))
    assert (row["status"], row["outcome_date"]) == ("E", "2026-10-20")


@pytest.mark.parametrize(("field", "column"), [("f9", "end_date"), ("f15", "outcome_date"), ("f16", "")])
def test_a_a_date_that_cannot_be_read_is_unknown_and_its_text_kept(tmp_path: Path, field: str, column: str) -> None:
    (row,), _ = _dx(tmp_path, _prb(**{field: "2026"}))
    assert row["status"] == "U"
    if column:
        assert (row[column], row[f"{column}_text"]) == ("", "2026")


# ------------------------------------------------------------------------------------------------ b: identity
@pytest.mark.parametrize("pid", ["", 'PID|||""', "PID|||^^^^PI"])
def test_b_a_diagnosis_message_with_no_patient_is_quarantined(tmp_path: Path, pid: str) -> None:
    rows, src = _dx(tmp_path, _prb(), pid=pid)
    assert rows == [] and [q[2].split(":")[0] for q in src.quarantined] == ["patient"]


@pytest.mark.parametrize("typ", ["OMP-01", "OML-11"])
def test_b_an_order_or_result_with_no_pid_is_quarantined(tmp_path: Path, typ: str) -> None:
    st = _ss(tmp_path)
    if typ == "OMP-01":
        body = ["ORC|NW|RX1||1|IP||||202610010900", "|".join(["RXE", "", "999000001^薬^HOT9", "1", "", "TAB"])]
        table = "medication"
    else:
        body = ["OBR|1|L1", "OBX|1|NM|3D046000001906202^HbA1c^JC10||6.0|%|||||F|||20261001090000"]
        table = "lab"
    kit._write(st, kit.P1, DAY, typ, "X1", kit._stamp(DAY), [kit._msh(f"{DAY}0900", "X", "1"), *body])
    src = _source(st)
    assert list(src.rows(table, table, None, None)) == []
    assert [q[2] for q in src.quarantined] == ["patient: no PID segment"]


@pytest.mark.parametrize(
    ("segs", "why"),
    [
        ([kit._pid(kit.P1), kit._pid(kit.P2)], "more than one PID segment"),
        ([f"PID|||{kit.P1}^^^^PI~{kit.P2}^^^^PI"], "PID-3 names two patients"),
        ([kit._pid(kit.P1), f"MRG|{kit.P2}^^^^PI"], "an MRG segment outside an ADT message"),
        ([f"PID||{kit.P2}^^^^PI|{kit.P1}^^^^PI"], "PID-2 names another patient than the file name"),
        ([f"PID|||{kit.P1}^^^^PI|{kit.P2}"], "PID-4 names another patient than the file name"),
    ],
)
def test_b_another_patients_id_anywhere_in_the_message_quarantines_it(
    tmp_path: Path, segs: list[str], why: str
) -> None:
    st = _ss(tmp_path)
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY),
               [kit._msh(f"{DAY}0900", "PPR^ZD1^PPR_ZD1", "P"), *segs, _prb()])  # fmt: skip
    src = _source(st)
    assert list(src.rows("diagnosis", "diagnosis", None, None)) == []
    assert [q[2] for q in src.quarantined] == [f"patient: {why}"]


def test_b_another_id_type_in_pid3_is_not_another_patient(tmp_path: Path) -> None:
    """Guard: a medical-record number (``MR``) next to the patient id is no second patient."""
    rows, _ = _dx(tmp_path, _prb(), pid=f"PID|||K-1^^^^MR~{kit.P1}^^^^PI")
    assert len(rows) == 1


# ------------------------------------------------------------------------------------------------ c: one id form
@pytest.mark.parametrize(
    "written", [f" {kit.P1} ", kit.P1.translate(str.maketrans("0123456789", "０１２３４５６７８９"))]
)
def test_c_the_patient_row_carries_the_same_id_as_every_other_table(tmp_path: Path, written: str) -> None:
    st = _ss(tmp_path)
    kit._write(st, kit.P1, "-", "ADT-00", "-", kit._stamp(DAY),
               [kit._msh(f"{DAY}0900", "ADT^A08^ADT_A01", "P"), "EVN||", f"PID|||{written}^^^^PI||山田^花子"])  # fmt: skip
    (row,) = list(_source(st).rows("patient", "patient", None, None))
    assert row["mrn"] == kit.P1


# ------------------------------------------------------------------------------------------------ d: C1 controls
@pytest.mark.parametrize("msh18", ["", "UNICODE UTF-8"])
def test_d_a_c1_control_is_refused_as_a_c0_one_is(msh18: str) -> None:
    data = f"MSH|^~\\&|HIS||TB||{DAY}||ADT^A08|1|P|2.5||||||{msh18}\rPID|||1^^^^PI||東京\u0085太郎\r".encode()
    with pytest.raises(hl7.Undecodable, match="control character"):
        hl7.decode_bytes(data)


# ------------------------------------------------------------------------------------------------ e: the source
GOOD = {"system": "HL70241", "code": "F", "status": "R", "meaning": "治癒", "verified": "yes", "title": "A table",
        "publisher": "A standards body", "version": "1.2", "section": "3.4", "document": "https://example.org/a"}  # fmt: skip


@pytest.mark.parametrize(
    ("field", "value"),
    [("document", "review 12 §4.10 F2"), ("document", "TBD"), ("version", "-"), ("version", "n/a"),
     ("document", "Internal Review 12"), ("document", ""), ("publisher", "TrialBox")],
)  # fmt: skip
def test_e_a_verified_row_without_a_named_public_source_stops_the_reader(field: str, value: str) -> None:
    """The bad value also in the old free-text ``source`` column, which the guard at 91601b6f accepted."""
    with pytest.raises(ValueError, match="cites no public source"):
        outcome_table([{**GOOD, field: value, "source": value}])


def test_e_a_verified_row_with_its_source_named_in_every_field_is_applied() -> None:
    assert outcome_table([GOOD])[0] == {"HL70241": {"F": "R"}}


# ------------------------------------------------------------------------------------------------ f: one key
def test_f_two_diagnoses_with_one_number_in_a_snapshot_quarantine_it(tmp_path: Path) -> None:
    rows, src = _dx(tmp_path, _prb(), _prb(f3="99990002^胃炎^MDCDX2"))
    assert rows == [] and [q[2].split(":")[0] for q in src.quarantined] == ["duplicate key"]
