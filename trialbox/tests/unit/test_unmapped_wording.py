"""NEW-B-8 (D-530): what the night says about values the mapping could not use.

The night's log called every counted value "rows dropped: values have no look-up row with a code". Since D-587,
D-590 and D-593 the counter also holds rows that are KEPT without the value (a unit that was not read, a value
implausible without a unit) and rows whose code the reference data could not be asked for. The line says what is
counted, and an outage of the reference data has a line of its own (the night is not held for it: D-530)."""

from __future__ import annotations

import pytest
from adapter.pipeline import unmapped_lines

pytestmark = pytest.mark.nodb


def test_the_line_does_not_call_a_kept_row_dropped() -> None:
    by = {"lab": {"X1": 3, "X2": 1}, "unit_mismatch": {"2160-0": 2}, "no_unit_implausible": {"718-7": 1}}
    (line,) = unmapped_lines("lab", by, "unmapped_codes.json")
    assert "dropped" not in line
    assert line == (
        "lab: 7 rows hold a value the mapping could not use (4 distinct values): the row is left out or kept "
        "without that value, by the mapping's rule (unmapped_codes.json)"
    )


def test_an_outage_of_the_reference_data_is_said_by_name_and_counted_apart() -> None:
    by = {"map:icd9cm->icd10cm": {"E03.0": 1}, "map:icd9cm->icd10cm:unavailable": {"042": 5, "7140": 2}}
    first, second = unmapped_lines("diagnosis", by, "unmapped_codes.json")
    assert first.startswith("diagnosis: 8 rows hold a value the mapping could not use (3 distinct values)")
    assert second == (
        "diagnosis: the reference data did not answer for 7 rows (map:icd9cm->icd10cm): their codes were not "
        "mapped tonight and stay so until the row is sent again or the next full load. The night is not held "
        "for this (D-530)"
    )
    for line in (first, second):
        assert "042" not in line and "7140" not in line and "E03" not in line  # counts and names, never a code


def test_no_outage_no_second_line() -> None:
    assert len(unmapped_lines("lab", {"lab": {"X1": 1}}, "unmapped_codes.json")) == 1
