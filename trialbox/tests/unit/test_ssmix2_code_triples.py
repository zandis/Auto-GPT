"""Four findings of the review of #393 (NEW-DIN-5), one card: in the SS-MIX2 reader a code is found in whichever
triple or repetition of its field names its code system, and a system's name is matched whatever its case.
All data is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source, _suspected, drug_codes, storage_dir

MRN, DAY = "P0001", "20261001"


def _store(root: Path, typ: str, order: str, segs: list[str]) -> None:
    d = storage_dir(root, MRN, DAY, typ)
    d.mkdir(parents=True, exist_ok=True)
    pid = (
        [] if any(s.startswith("PID|") for s in segs) else [f"PID|||{MRN}^^^^PI"]
    )  # every SS-MIX2 message carries its patient (PR #1095 fourth review b)
    kind = "PPR^ZD1" if typ == "PPR-01" else "X"  # a PPR-01 file carries PPR^ZD1 (D-1252: another MSH-9 is set aside)
    body = "\r".join([f"MSH|^~\\&|HIS||TB||{DAY}||{kind}|1|P|2.5||||||~ISO IR87", *pid, *segs]) + "\r"
    (d / f"{MRN}_{DAY}_{typ}_{order}_{DAY}000000000_-_1").write_bytes(body.encode("iso2022_jp"))


def _seg(text: str) -> hl7.Segment:
    return hl7.parse("MSH|^~\\&|HIS||TB||20261001||X|1|P|2.5\r" + text + "\r").segments[-1]


# ------------------------------------------------------------------------------------------------ lab OBX-3
def _lab_rows(tmp_path: Path, obx3: str) -> list[dict[str, str]]:
    obx = ["OBX", "1", "NM", obx3, "", "6.0", "%", *[""] * 15]
    obx[11], obx[14], obx[21] = "F", f"{DAY}090000", "U1"
    _store(tmp_path, "OML-11", "O1", ["OBR|1|O1", "|".join(obx)])
    return [dict(r) for r in Ssmix2Source(tmp_path, licensed={}).rows("lab", "OML-11", None, None)]


@pytest.mark.parametrize(("obx3", "local", "jlac"), [
    ("3D046000001906202^HbA1c^JC10", "3D046000001906202", "3D046000001906202"),            # as before
    ("H123^HbA1c^99LAB^3A999000002399901^HbA1c^JC10", "H123", "3A999000002399901"),        # JLAC10 second
    ("H123^HbA1c^99LAB^3A999000002399901^HbA1c^jc10", "H123", "3A999000002399901"),        # ... whatever its case
    ("3D046000001906202^HbA1c^jlac10", "3D046000001906202", "3D046000001906202"),
    ("H123^HbA1c^99LAB", "H123", ""),                                                     # no JLAC10 at all
    ("3D046000001906202^HbA1c", "3D046000001906202", "3D046000001906202"),                # no system, the shape
    ("H123^HbA1c^99LAB^9Z999^x^LN", "H123", ""),                                          # another system second
])  # fmt: skip
def test_the_jlac10_code_of_a_result_is_read_from_the_triple_that_names_it(
    tmp_path: Path, obx3: str, local: str, jlac: str
) -> None:
    (row,) = _lab_rows(tmp_path, obx3)
    assert (row["local_code"], row["jlac10_code"]) == (
        local,
        jlac,
    )  # the key: the first code (a JLAC10 code the table does not know)


# ------------------------------------------------------------------------------------------------ drug codes
@pytest.mark.parametrize(("cwe", "want"), [
    ("620000001^薬^HOT9", {"hot": "620000001", "yj": "", "atc": ""}),
    ("620000001^薬^hot9", {"hot": "620000001", "yj": "", "atc": ""}),             # was taken for the YJ code
    ("3999001F1020^薬^yj^620000001^薬^Hot9", {"yj": "3999001F1020", "hot": "620000001", "atc": ""}),
    ("L01XC02^x^whoatc", {"atc": "L01XC02", "yj": "", "hot": ""}),
    ("X1^薬^99XYZ", {"yj": "X1", "hot": "", "atc": ""}),   # a hospital's own code: still looked up as the local code
    ("3999001F1020^薬", {"yj": "3999001F1020", "hot": "", "atc": ""}),
    ("X1^薬^99XYZ^3999001F1020^薬^YJ", {"yj": "3999001F1020", "hot": "", "atc": ""}),  # a named YJ wins over a local
])  # fmt: skip
def test_a_drug_code_system_is_matched_whatever_its_case(cwe: str, want: dict[str, str]) -> None:
    got = drug_codes(_seg(f"RXE|1|{cwe}"), 2)
    assert {k: got[k] for k in ("yj", "hot", "atc")} == want


# ------------------------------------------------------------------------------------------------ PRB-13
@pytest.mark.parametrize(("prb13", "prb3", "want"), [
    ("1^疑いあり^JHSD0005", "X^病", True), ("0^なし^JHSD0005", "X^病", False), ("", "X^病", False),
    ("S^x^99LOC^1^疑いあり^JHSD0005", "X^病", True),   # the flag in the second triple
    ("S^x^99LOC^1^^jhsd0005", "X^病", True),
    ("S^x^99LOC^0^なし^JHSD0005", "X^病", False),
    ("1^x^99LOC", "X^病", False),                      # a 1 of another table is not the flag
    ("", "X^糖尿病の疑い", True),
])  # fmt: skip
def test_the_suspected_flag_is_read_from_the_triple_that_names_its_table(prb13: str, prb3: str, want: bool) -> None:
    assert _suspected(_seg(f"PRB|AD|20261001|{prb3}|D1|||||||||{prb13}")) is want


# ------------------------------------------------------------------------------------------------ PRB-3 repetitions
def _diag(tmp_path: Path, prb3: str) -> tuple[list[dict[str, str]], Ssmix2Source]:
    segs = ["PID|1||P0001^^^^PI", "PV1|1|O||||||||||||||||E1", f"PRB|AD|20261001|{prb3}|D1||||||||||A||20260930"]
    _store(tmp_path, "PPR-01", "D1", segs)
    src = Ssmix2Source(tmp_path, licensed={})
    return [dict(r) for r in src.rows("diagnosis", "PPR-01", None, None)], src


@pytest.mark.parametrize(("prb3", "icd", "byomei"), [
    ("20054174^2型糖尿病^MDCDX2~E11.9^2型糖尿病^I10", "E11.9", "20054174"),   # ICD-10 in a second repetition
    ("20054174^2型糖尿病^MDCDX2~E11.9^2型糖尿病^i10", "E11.9", "20054174"),
    ("E11.9^x^I10~M06.9^y^I10", "E11.9", ""),                                # two ICD-10: the first, one diagnosis
    ("20054174^x^MDCDX2^E11.9^x^I10~M06.9^y^I10", "E11.9", "20054174"),
    ("20054174^2型糖尿病^MDCDX2^E11.9^2型糖尿病^I10", "E11.9", "20054174"),   # as before
])  # fmt: skip
def test_icd10_in_a_later_repetition_of_prb3_is_read_and_a_repetition_is_counted(
    tmp_path: Path, prb3: str, icd: str, byomei: str
) -> None:
    (row,), src = _diag(tmp_path, prb3)
    assert (row["icd10"], row["byomei_code"]) == (icd, byomei)
    assert src.stats["PPR-01:PRB-3 repeated"] == (1 if "~" in prb3 else 0)
    assert not [k for k in src.missed if k.startswith("diagnosis:")]


# ------------------------------------------------------------------------------------------------ the review of this card
def test_a_later_repetition_never_replaces_what_the_first_one_gives(tmp_path: Path) -> None:
    """A licensed 病名 code of the first repetition is the diagnosis; a later repetition's ICD-10 is read only when
    the first repetition gives none."""
    prb3 = "20054174^2型糖尿病^MDCDX2~8830417^関節リウマチ^MDCDX2^M06.9^関節リウマチ^I10"
    segs = ["PID|1||P0001^^^^PI", "PV1|1|O||||||||||||||||E1", f"PRB|AD|20261001|{prb3}|D1||||||||||A||20260930"]
    _store(tmp_path, "PPR-01", "D1", segs)
    src = Ssmix2Source(tmp_path, licensed={"medis": {"20054174": {"target_code": "E11.9"}}})
    (row,) = [dict(r) for r in src.rows("diagnosis", "PPR-01", None, None)]
    assert (row["icd10"], row["byomei_code"]) == ("E11.9", "20054174")
    assert src.stats["PPR-01:PRB-3 repeated"] == 1


@pytest.mark.parametrize("prb13", [
    "0^なし^JHSD0005^1^確定^", "0^なし^JHSD0005^1", "0^なし^JHSD0005~1", "2^x^99LOC^1",
    "0^なし^JHSD0005^X^疑いあり^99LOC",
])  # fmt: skip
def test_a_named_flag_of_no_suspicion_is_not_overruled_by_another_triple(prb13: str) -> None:
    assert _suspected(_seg(f"PRB|AD|20261001|X^病|D1|||||||||{prb13}")) is False


@pytest.mark.parametrize("cwe", ["^^^X1^薬^99XYZ", "^^^X1^薬", "~X1^薬^99XYZ"])
def test_only_the_very_first_code_of_a_drug_field_is_its_local_code(cwe: str) -> None:
    assert drug_codes(_seg(f"RXE|1|{cwe}"), 2)["yj"] == ""


@pytest.mark.parametrize(("obx3", "local", "jlac", "hosp"), [
    ("H123^x^99LAB^ 3D046000001906202 ^x^JC10", "3D046000001906202", "3D046000001906202", "H123"),  # blanks
    ("H123^x^99LAB^garbage^x^JC10", "H123", "", "H123"),               # not a JLAC10 code, whatever it is called
    ("3D046000001906202^HbA1c^^3A010000002327101^TP^JC10", "3D046000001906202", "3D046000001906202", ""),
    ("H123^HbA1c^99LAB^3D046000001906202^HbA1c^JC10", "3D046000001906202", "3D046000001906202", "H123"),
])  # fmt: skip
def test_a_jlac10_code_of_a_later_triple_has_its_shape_and_is_the_key_when_the_first_code_is_unknown(
    tmp_path: Path, obx3: str, local: str, jlac: str, hosp: str
) -> None:
    """The look-up key is the first code when the table knows it, else the JLAC10 code the table knows: a result
    whose hospital code is unknown and whose JLAC10 code is known gets its LOINC code and is no missed code."""
    obx = ["OBX", "1", "NM", obx3, "", "6.0", "%", *[""] * 15]
    obx[11], obx[14], obx[21] = "F", f"{DAY}090000", "U1"
    _store(tmp_path, "OML-11", "O1", ["OBR|1|O1", "|".join(obx)])
    src = Ssmix2Source(tmp_path, licensed={})
    (row,) = [dict(r) for r in src.rows("lab", "OML-11", None, None)]
    assert (row["local_code"], row["jlac10_code"], row["hosp_lab_code"]) == (local, jlac, hosp)
    assert ("lab:H123" in src.missed) is (jlac == "")
