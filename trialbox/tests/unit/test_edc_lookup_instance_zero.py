"""An EDC lookup asked for instance 0 reads instance 0, not the current slot's instance (0 is a value, not "unset")."""

import datetime
from typing import Any, cast

from edc.rows import Rows


class _Slot:
    def __init__(self, event: str, instrument: str = "", instance: int = 0, repeat: bool = False) -> None:
        self.event = event
        self.instrument = instrument
        self.instance = instance
        self.repeat = repeat


class _Layout:
    def __init__(self) -> None:
        self.longitudinal = True
        self.events = {"EV": 1}

    def key(self, record: str, slot: Any) -> tuple[str, str, str, int]:
        return (record, slot.event, slot.instrument, slot.instance)

    def repeating_instrument(self, ev: str, form: str) -> bool:
        return True

    def repeating_event(self, ev: str) -> bool:
        return False


def test_lookup_of_instance_zero_reads_instance_zero() -> None:
    rows = Rows(
        cast(Any, _Layout()),
        {"f1": {"field_type": "text", "form_name": "myform"}},
        "record_id",
        rows=[],
        today=datetime.date(2026, 1, 1),
    )
    rows.rows = {("R1", "EV", "myform", 0): {"f1": "zero"}, ("R1", "EV", "myform", 5): {"f1": "five"}}
    lookup = rows._lookup("R1", cast(Any, _Slot("EV", "myform", 5)))
    assert lookup(None, "f1", None, 0) == "zero"
