"""Card 10B-2b (D-1252), lane J's ruling P10: PRB-13 confirms a diagnosis only when it is empty.

The code table of JHSD0005 (SS-MIX2 標準化ストレージ仕様書 Ver.1.2j 別紙：コード表, 表95 疑い病名フラグ, JAMI
2026-08-14) lists one value, ``1`` 疑いあり. A ``0`` is not a value of the table, whatever its text, so the reader does
not recognise it as "not suspected": the certainty is unknown (U). TrialBox's own writers never write PRB-13.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}


def _read(tmp_path: Path, flag: str) -> dict[str, str]:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    prb = ["PRB", "AD", "20260901090000", "99990001^肺炎^MDCDX2", "DX001"] + [""] * 14
    prb[10], prb[13] = "J189^^I10", flag
    segs = [kit._msh("20261001090000", "PPR^ZD1^PPR_ZD1", "P1"), kit._pid(kit.P1), "|".join(prb)]
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp("20261001"), segs)
    (row,) = list(Ssmix2Source(st.root, licensed=EMPTY).rows("diagnosis", "diagnosis", None, None))
    return row


@pytest.mark.parametrize(
    "flag",
    ["0^^JHSD0005", "0^疑いなし^JHSD0005", "0^なし^JHSD0005", "0^^99JHSD0005", "0", "０^^JHSD0005", "^^JHSD0005"],
)
def test_a_zero_flag_is_not_a_value_of_the_table_so_the_certainty_is_unknown(tmp_path: Path, flag: str) -> None:
    row = _read(tmp_path, flag)
    assert row["suspected"] == "U"
    assert row["status"] == "A"  # the certainty is unknown; the status is read as before


def test_an_empty_flag_still_confirms(tmp_path: Path) -> None:
    assert _read(tmp_path, "")["suspected"] == ""


def test_the_one_value_of_the_table_is_still_suspected(tmp_path: Path) -> None:
    assert _read(tmp_path, "1^疑いあり^JHSD0005")["suspected"] == "Y"
