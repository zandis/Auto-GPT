"""Red of lane G's accuracy run (#639, 2026-11-15), item 4: generic "diabetes mellitus" mapped to no code, because the
terminology held only type 1 (E10) and type 2 (E11). jmed's "history of diabetes" therefore had an empty list.

"Diabetes mellitus", "diabetes", 糖尿病 (ja and zh-TW) now map to the ICD-10-CM diabetes categories as a grouper:
E08 (due to an underlying condition), E09 (drug or chemical induced), E10, E11 and E13 (other specified). Gestational
diabetes (O24) is not in it: a pregnancy condition a protocol names on its own. Type 1 and type 2 are unchanged.
"""

from __future__ import annotations

import pytest
from criteria_compiler.terminology.mapper import Terminology

DM = {"E08", "E09", "E10", "E11", "E13"}


@pytest.mark.parametrize("name", ["diabetes mellitus", "diabetes", "糖尿病"])
def test_generic_diabetes_maps_to_every_diabetes_category(name: str) -> None:
    r = Terminology().map("condition", name)
    assert r.concepts and not r.needs_review, name
    fams = {pre for sy, pre in (r.families or []) if sy.endswith("icd-10-cm")}
    assert fams == DM, (name, fams)  # plus WHO's E14 under the WHO system (D-314), which ICD-10-CM has not
    assert not any(c.code.startswith("O24") for c in r.concepts)


def test_type_1_and_type_2_are_unchanged() -> None:
    t = Terminology()

    def cm(name: str) -> set[str]:
        return {p for s, p in t.map("condition", name).families or [] if s.endswith("icd-10-cm")}

    assert cm("type 2 diabetes mellitus") == {"E11"} and cm("type 1 diabetes mellitus") == {"E10"}
