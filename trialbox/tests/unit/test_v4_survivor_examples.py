"""Evidence for card V-4's findings V4-06 and V4-05 (docs/plan/measurements/test-trust-2026-11-17.md).

Each test passes on the product code and fails under one mutant that the mutation targets' own tests let live. It is
shown at the level of ``refs()``: an empty list there leaves the coded FALSE in place in
``orchestrator.scenarios.evaluate`` (lines 157-170) and in the cascade engine (lines 632 and 682), so the patient
fails an inclusion instead of being unknown. Lane A2 may move these tests beside its own.
"""

from __future__ import annotations

from datetime import date

from matching.coverage import Coverage, GapRow
from matching.proposed import FactRow

from tests.unit.test_code_coverage import _inclusion
from tests.unit.test_one_rule import INDEX, _crit, _facts

FEMALE = _crit("RULE-INC-09", "inclusion", "Female", {"domain": "demographic", "valueset": "NONE", "sex": "female"})
GOUT_AND_FEMALE = _crit(
    "RULE-INC-10",
    "inclusion",
    "Gout, in a woman",
    {"op": "and", "args": [
        {"domain": "condition", "quantifier": "any", "valueset": "VS_GOUT"},
        {"domain": "demographic", "valueset": "NONE", "sex": "female"},
    ]},
)  # fmt: skip


def test_v4_06_a_proposed_sex_makes_a_decided_sex_answer_unknown() -> None:
    """V4-06, proposed.py:159 (``f.code == "sex"`` to ``!=``): coded male fails "Female"; a proposed sex could change
    that, so refs() names it and the answer becomes unknown."""
    p = _facts(FactRow("f-sex", "demographic", "sex", "", None))
    assert p.refs(FEMALE, "P", INDEX, False) == ["f-sex"]
    assert p.refs(FEMALE, "P", INDEX, True) == ["f-sex"]


def test_v4_06_an_atom_of_the_wrong_sign_does_not_stop_the_scan() -> None:
    """V4-06, proposed.py:187 (``continue`` to ``break``): on a TRUE answer the gout atom (+) is skipped; the sex atom
    after it must still be read."""
    p = _facts(FactRow("f-sex", "demographic", "sex", "", None))
    assert p.refs(GOUT_AND_FEMALE, "P", INDEX, True) == ["f-sex"]


def test_v4_05_a_row_of_another_domain_does_not_stop_the_gap_scan() -> None:
    """V4-05, coverage.py:146 (``continue`` to ``break``): an unreadable condition after a medication row still makes
    the inclusion's FALSE unknown."""
    cov = Coverage(
        {"P": [GapRow("medication", "m-1", None, "urn:x"), GapRow("condition", "c-1", None, "urn:who-icd10")]}
    )
    assert cov.refs(_inclusion(None), "P", date(2026, 10, 5)) == ["c-1"]


def test_v4_05_a_row_outside_the_window_does_not_stop_the_gap_scan() -> None:
    """V4-05, coverage.py:148 (``continue`` to ``break``): an old row before an undated one."""
    window = {"anchor": "index", "from_days": -365, "to_days": 0}
    rows = [GapRow("condition", "c-old", date(2020, 1, 1), "urn:who-icd10"),
            GapRow("condition", "c-1", None, "urn:who-icd10")]  # fmt: skip
    assert Coverage({"P": rows}).refs(_inclusion(window), "P", date(2026, 10, 5)) == ["c-1"]
