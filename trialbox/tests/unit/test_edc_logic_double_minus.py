"""CGRD-B4 (D-819): two minus signs in a row make a calculation blank, as REDCap stores it.

On a real REDCap, ``2*2*2*2*2*2*2*2*2*2 - -1`` is stored blank (its calculation reads the two signs as one operator
it cannot apply); TrialBox's evaluator gave 1025. The send compares REDCap's calculated values with TrialBox's
(R6), and a value REDCap leaves blank must never be filled by TrialBox. A calculation with two minus signs in a row
(spaces between them or not) is blank now; branching logic with them is refused as unreadable (TrialBox does not
guess what REDCap would show). One minus before a bracket is still a negation."""

from __future__ import annotations

from datetime import date

import pytest
from edc import logic

TODAY = date(2026, 11, 15)


def _none(event: str | None, name: str, code: str | None, instance: int | None) -> str:
    return {"x": "3"}.get(name, "")


@pytest.mark.parametrize(("text", "want"), [
    ("2*2*2*2*2*2*2*2*2*2 - -1", ""), ("2*2 --1", ""), ("[x] - - 1", ""), ("1 + - -1", ""),
    ("2*2*2*2*2*2*2*2*2*2 - 1", "1023"), ("2 - (-1)", "3"), ("-1 + 2", "1"), ("[x] - 1", "2"), ("-(-1)", "1"),
])  # fmt: skip
def test_two_minus_signs_in_a_row_make_a_calculation_blank(text: str, want: str) -> None:
    assert logic.calculate(text, _none, TODAY) == want


def test_branching_logic_with_two_minus_signs_is_refused_as_unreadable() -> None:
    with pytest.raises(logic.LogicError):
        logic.shown("[x] - -1 > 0", _none, TODAY)
