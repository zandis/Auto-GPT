"""CGRD-B5b (D-844): the simulator refuses a data dictionary a real REDCap refuses.

A real REDCap refused the conformance kit's dictionary for ``^`` in a calculation, and for ``number_1dp``, which that
instance does not offer (an instance's administrator chooses the validations it offers). The simulator took both:
a dictionary loadable here was not loadable there. It now refuses ``^`` in a calculation always, and a validation the
instance does not offer (``create_app(not_offered=...)``; the default offers every one, as REDCap's own list does).
Synthetic dictionaries only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from rc_sim.app import create_app

BASE = [{"field_name": "record_id", "form_name": "f", "field_type": "text"},
        {"field_name": "h", "form_name": "f", "field_type": "text"}]  # fmt: skip


def _load(meta: list[dict[str, str]], not_offered: set[str] | None = None) -> int:
    app = create_app(not_offered=not_offered or ())
    return int(TestClient(app).post("/sim/projects", json={"metadata": BASE + meta}).status_code)


@pytest.mark.parametrize("calc", ["[h]^2", "round([h]^2, 1)", "2 ^ 10"])
def test_a_power_in_a_calculation_is_refused(calc: str) -> None:
    assert (
        _load([{"field_name": "c", "form_name": "f", "field_type": "calc", "select_choices_or_calculations": calc}])
        == 400
    )


def test_a_product_in_a_calculation_is_taken() -> None:
    assert _load([{"field_name": "c", "form_name": "f", "field_type": "calc",
                   "select_choices_or_calculations": "round([h]*[h], 1)"}]) == 200  # fmt: skip


def test_a_validation_the_instance_does_not_offer_is_refused() -> None:
    temp = [{"field_name": "t", "form_name": "f", "field_type": "text",
             "text_validation_type_or_show_slider_number": "number_1dp"}]  # fmt: skip
    assert _load(temp, not_offered={"number_1dp"}) == 400
    assert _load(temp) == 200  # offered by default, as REDCap's own list offers it
