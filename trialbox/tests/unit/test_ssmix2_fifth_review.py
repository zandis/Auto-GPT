"""The fifth review of PR #1095 (lane J's probe at 0cbe4aab): points 1 to 7, the same allow-list principle. Each
test failed on the reader at 0cbe4aab, except the guards named in their docstrings. All data is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source, outcome_table

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
DAY = "20261001"


def _prb(**at: str) -> str:
    prb = ["PRB", "AD", DAY, "99990001^肺炎^MDCDX2", "DX1"] + [""] * 14
    prb[10] = "J189^^I10"
    for n, v in at.items():
        prb[int(n[1:])] = v
    return "|".join(prb)


def _rows(tmp_path: Path, *prbs: str) -> tuple[list[dict[str, object]], Ssmix2Source]:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True)
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp(DAY),
               [kit._msh(f"{DAY}0900", "PPR^ZD1^PPR_ZD1", "P"), kit._pid(kit.P1), *prbs])  # fmt: skip
    src = Ssmix2Source(st.root, licensed=EMPTY)
    return list(src.rows("diagnosis", "diagnosis", None, None)), src


def _one(tmp_path: Path, **at: str) -> dict[str, object]:
    (row,), _ = _rows(tmp_path, _prb(**at))
    return row


# ------------------------------------------------------------------------------------------------ 1: PRB-14
@pytest.mark.parametrize(
    "outcome", ["A^^99LOCAL", "A^^ZZZ", "X^継続^99LOCAL", "^継続中", "^ 継続 ", "a", "A~F", "A^継続"]
)
def test_1_an_outcome_that_is_not_exactly_a_recognised_pair_is_never_active(tmp_path: Path, outcome: str) -> None:
    assert _one(tmp_path, f14=outcome)["status"] == "U"


@pytest.mark.parametrize(("outcome", "status"), [("", "A"), ("A", "A"), ("R", "R")])
def test_1_guard_an_empty_outcome_and_the_readers_legacy_words_keep_their_meaning(
    tmp_path: Path, outcome: str, status: str
) -> None:
    """Guard (passes before and after)."""
    assert _one(tmp_path, f14=outcome)["status"] == status


# ------------------------------------------------------------------------------------------------ 2: repetitions
@pytest.mark.parametrize(
    ("field", "value", "column", "want"),
    [("f3", "99990001^肺炎^MDCDX2~99990002^胃炎^MDCDX2", "status", "U"),
     ("f13", "0^^JHSD0005~1^^JHSD0005", "suspected", "U"),
     ("f17", "肺炎~胃炎", "suspected", "U"),
     ("f16", "20260101~20260201", "status", "U"),
     ("f2", "20260101~20260201", "status", "U")],
)  # fmt: skip
def test_2_a_second_repetition_is_never_dropped(tmp_path: Path, field: str, value: str, column: str, want: str) -> None:
    row = _one(tmp_path, **{field: value})
    assert row[column] == want
    if field in ("f16", "f2"):
        assert value in str(row["date_text"])  # the raw text kept


# ------------------------------------------------------------------------------------------------ 3: JHSD0005
def test_3_a_table_name_that_only_ends_in_jhsd0005_is_not_it(tmp_path: Path) -> None:
    assert _one(tmp_path, f13="1^疑いあり^XYZJHSD0005")["suspected"] in ("U", "Y")
    assert _one(tmp_path / "b", f13="0^^XYZJHSD0005")["suspected"] == "U"


# ------------------------------------------------------------------------------------------------ 4: dates
def test_4_a_full_width_date_is_read_as_a_date() -> None:
    assert hl7.ts("２０２６０３０１") == "2026-03-01"


@pytest.mark.parametrize("field", ["f16", "f2", "f7"])
def test_4_an_onset_diagnosis_or_record_after_its_file_was_written_is_unknown(tmp_path: Path, field: str) -> None:
    assert _one(tmp_path, **{field: "20301231"})["status"] == "U"


# ------------------------------------------------------------------------------------------------ 5: one number
@pytest.mark.parametrize("other", ["ＤＸ１", "DX1 ", "dx1"])
def test_5_one_number_written_two_ways_is_a_duplicate(tmp_path: Path, other: str) -> None:
    rows, src = _rows(tmp_path, _prb(), _prb(f3="99990002^胃炎^MDCDX2", f4=other))
    assert rows == [] and [q[2].split(":")[0] for q in src.quarantined] == ["duplicate key"]


# ------------------------------------------------------------------------------------------------ 6: no code
def test_6_a_name_with_no_code_at_all_is_never_confirmed(tmp_path: Path) -> None:
    assert _one(tmp_path, f3="^肺炎", f10="")["suspected"] == "U"


def test_6_guard_a_local_code_is_still_a_code(tmp_path: Path) -> None:
    """Guard: TrialBox's exporter writes a local 99XYZ 病名 code with no ICD-10 for some rows."""
    assert _one(tmp_path, f3="ZB30^骨粗鬆症^99XYZ", f10="")["suspected"] == ""


# ------------------------------------------------------------------------------------------------ 7: the source
GOOD = {"system": "HL70241", "code": "F", "status": "R", "meaning": "治癒", "verified": "yes", "title": "A table",
        "publisher": "A standards body", "version": "1.2", "section": "3.4", "document": "https://example.org/a"}  # fmt: skip


@pytest.mark.parametrize(
    ("field", "value"),
    [("document", "—"), ("document", "－"), ("document", "未定"), ("document", "なし"), ("document", "TODO"),
     ("document", "http://example.org/a"), ("document", "example.org"), ("version", "draft"), ("version", "..."),
     ("version", "x"), ("version", "0"), ("version", "未定"), ("publisher", "Trial Box"), ("publisher", "trial-box"),
     ("publisher", "ＴｒｉａｌＢｏｘ"), ("title", ""), ("section", "")],
)  # fmt: skip
def test_7_a_verified_row_needs_an_https_url_or_doi_and_a_real_version(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="cites no public source"):
        outcome_table([{**GOOD, field: value}])


@pytest.mark.parametrize(
    ("field", "value"), [("document", "10.1000/xyz123"), ("version", "2016-03-01"), ("version", "v1.2h")]
)
def test_7_guard_a_doi_a_dated_or_lettered_version_is_accepted(field: str, value: str) -> None:
    """Guard: the forms a real source takes."""
    assert outcome_table([{**GOOD, field: value}])[0] == {"HL70241": {"F": "R"}}
