"""9k-6b (D-1389): the reading of a refusal as a field error (``console.form_errors.from_refusal``) and the tables
of the forms that use it (``console.team``): only a 400 refusal on a form's table is shown at a field; a table keeps
to sentences the routes still raise."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from console import form_errors, team

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

SERVICES = Path(team.__file__).parent


class _Refusal(Exception):
    def __init__(self, status: int, key: str, reason: object) -> None:
        super().__init__(key)
        self.status, self.key, self.values = status, key, {"reason": reason}


TABLE: dict[str, form_errors.Rule] = {
    "give the name": ("name", "fe.staff.name"),
    "dates": lambda form: [("day", "fe.x")] if form.get("day") else [],
}


def test_only_a_400_refusal_on_the_table_is_shown_at_a_field() -> None:
    ok = _Refusal(400, "request.refused", "give the name")
    assert form_errors.from_refusal(ok, TABLE, {}) == [("name", "fe.staff.name")]
    # a refusal of a valid request (409), another kind of problem, a sentence not on the table, a missing study
    assert form_errors.from_refusal(_Refusal(409, "request.refused", "give the name"), TABLE, {}) is None
    assert form_errors.from_refusal(_Refusal(400, "forbidden", "give the name"), TABLE, {}) is None
    assert form_errors.from_refusal(_Refusal(400, "request.refused", "another sentence"), TABLE, {}) is None
    assert form_errors.from_refusal(_Refusal(400, "request.refused", None), TABLE, {}) is None
    assert form_errors.from_refusal(ValueError("give the name"), TABLE, {}) is None


def test_a_rule_that_finds_no_field_leaves_the_refusal_as_it_was() -> None:
    exc = _Refusal(400, "request.refused", "dates")
    assert form_errors.from_refusal(exc, TABLE, {"day": "x"}) == [("day", "fe.x")]
    assert form_errors.from_refusal(exc, TABLE, {}) is None


def test_bad_dates_reads_a_day_as_the_stores_do() -> None:
    keys = {"a": "fe.a", "b": "fe.b", "c": "fe.c"}
    form: dict[str, Any] = {"a": " 2026-10-01 ", "b": "2026-02-30", "c": ""}
    assert form_errors.bad_dates(form, keys, keys) == [("b", "fe.b")]
    assert form_errors.bad_dates({"a": "2026-10-01xx"}, keys, keys, cut=10) == []  # cut as the route cuts it


TABLES = {
    "IRB_REFUSALS": team.IRB_REFUSALS,
    "ICF_REFUSALS": team.ICF_REFUSALS,
    "OPTOUT_REFUSALS": team.OPTOUT_REFUSALS,
    "LIFT_REFUSALS": team.LIFT_REFUSALS,
    "STAFF_REFUSALS": team.STAFF_REFUSALS,
    "CONTACT_REFUSALS": team.CONTACT_REFUSALS,
}


@pytest.mark.parametrize("table", sorted(TABLES))
def test_a_table_keeps_to_sentences_the_routes_still_raise(table: str) -> None:
    """A reworded raise would send its form back to the problem page without a word; this fails first."""
    source = (SERVICES / "teamstore.py").read_text() + (SERVICES / "team.py").read_text()
    constants = {v: k for k, v in vars(team).items() if k.isupper() and isinstance(v, str)}
    for sentence in TABLES[table]:
        if sentence in source:  # written where it is raised
            continue
        name = constants.get(sentence)  # or a constant the raise names
        assert name and re.search(rf"raise refused\([^\n]*\b{name}\b", source), sentence


def test_every_message_key_of_a_table_is_in_the_three_catalogues() -> None:
    from console.i18n import CATALOGUES

    for rules in TABLES.values():
        for rule in rules.values():
            if isinstance(rule, tuple):
                for lang in ("en", "ja", "zh-TW"):
                    assert rule[1] in CATALOGUES[lang], (lang, rule)
