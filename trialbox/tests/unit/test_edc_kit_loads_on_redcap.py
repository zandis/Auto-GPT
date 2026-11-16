"""CGRD-B1 (D-840): the conformance project loads on a real REDCap; TrialBox keeps a field's decimal places itself.

A real REDCap refused the kit's dictionary: ``^`` in a calculation (the BMI and two R6 cases), and ``number_1dp``,
which that instance does not offer. Powers are written as products now, no expression has two minus signs in a row,
and the temperature is ``number`` with its range. The one decimal place is said in the field's annotation as
``@TB-DECIMALS=1``: REDCap ignores an action tag it does not know, and TrialBox reads it as the field's places:
a value with more is refused (never rounded) and ``37`` is sent as ``37.0``. The original forms stay as evaluator
tests (``test_edc_t302b.py``, ``test_edc_logic_double_minus.py``). Synthetic data only."""

from __future__ import annotations

import re

from datacore import forms

from tests import edc_kit as k


def test_no_calculation_of_the_kit_uses_a_power_or_two_minus_signs() -> None:
    calcs = [str(f.get("select_choices_or_calculations") or "") for f in k.CONF_CRF if f.get("field_type") == "calc"]
    calcs += [text for text, _row in k.CONF_CALC] + [text for text, _row in k.CONF_BRANCH]
    assert calcs and not [c for c in calcs if "^" in c or re.search(r"-\s*-", c)]


def test_no_field_uses_a_validation_the_instance_does_not_offer() -> None:
    assert not [f for f in k.CONF_CRF if "1dp" in str(f.get("text_validation_type_or_show_slider_number") or "")]


def test_the_temperature_keeps_one_decimal_place_in_trialbox() -> None:
    temp = forms.field_of(next(f for f in k.CONF_CRF if f["field_name"] == "temp"))
    assert temp.kind == "decimal" and temp.places == "1"
    assert forms.problem(temp, "37.55") == {"field": "temp", "code": "decimals", "places": "1"}
    assert forms.problem(temp, "37.5") is None and forms.redcap_value(temp, "37") == "37.0"
    assert forms.problem(temp, "29.9") == {"field": "temp", "code": "min", "min": "30.0"}


def test_without_the_tag_a_number_field_is_as_before() -> None:
    f = forms.field_of({"field_name": "w", "form_name": "f", "field_type": "text",
                        "text_validation_type_or_show_slider_number": "number"})  # fmt: skip
    assert f.places == "" and forms.problem(f, "72.555") is None and forms.redcap_value(f, "72") == "72"
