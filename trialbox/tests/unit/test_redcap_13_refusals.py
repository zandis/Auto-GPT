"""RC13-A (D-847): REDCap 13.7's English refusals read as their kinds.

The private REDCap 13.7 instance (D-1021; synthetic projects only) refused imports with English sentences the bridge
did not know: a date it cannot read, a value that is not one of the field's choices, a missing record-id field,
an import that is not well-formed JSON, and a write to a record of another data access group. A bad repeat instance
was read as an event problem, because REDCap's sentence names the event before the instance. The texts below are
written for the test around the words REDCap's sentences hold; no record's value is in them."""

from __future__ import annotations

import pytest
from rc_bridge.client import error_kind

VALIDATION = "a value does not fit its field's validation"


@pytest.mark.parametrize(("text", "kind"), [
    ('"1","visit_date","x","Invalid date format. (dates are Y-M-D)"', VALIDATION),
    ('"1","sex","9","The value is not a valid category for sex"', VALIDATION),
    ("The record id field (record_id) is missing.", "the record identifier field is missing"),
    ("The data being imported is not formatted correctly: the JSON must be an array", "the import is not in a valid "
     "format"),
    ("These records cannot be modified because they do not belong to your Data Access Group: 2",
     "a record belongs to another data access group"),
    ('"5","redcap_repeat_instance","x","(redcap_event_name=""week1_arm_1"") redcap_repeat_instance must be a number"',
     "a repeating instrument or its instance number is not valid"),
])  # fmt: skip
def test_a_redcap_13_refusal_reads_as_its_kind(text: str, kind: str) -> None:
    assert error_kind(text) == kind


@pytest.mark.parametrize(("text", "kind"), [
    ("The redcap_event_name nope_arm_1 is not a valid event name", "the event is missing or is not an event of the "
     "project"),
    ("The data access group nope is not valid", "the data access group is not valid"),
])  # fmt: skip
def test_the_kinds_read_before_stay(text: str, kind: str) -> None:
    assert error_kind(text) == kind
