"""Deep review 2026-11-13 (screening, SCR-02): a lab fact read from a chart is stored under the code of the test the
chart names, in the unit it is stored in, whatever LOINC the model guessed.

Lane G's real-model runs of stage 12 (P5) gave the practice chart's urate a LOINC other than 3084-1, so the urate
criterion did not see it and the patient stayed "needs information" after every fact was confirmed. Worse, a
creatinine code on a urate line stored the urate value as a creatinine value: once a coordinator confirms it, a
renal exclusion reads it. Synthetic data only.
"""

from __future__ import annotations

import pytest
from sitesetup import charts


def _obs(term: str, code: str, value: str = "8.1", unit: str = "mg/dL") -> dict[str, str] | None:
    return charts.normalise(
        {"domain": "observation", "term": term, "value": value, "unit": unit, "code": code, "system": "loinc",
         "quote": f"{term} {value} {unit}", "date": ""}  # fmt: skip
    )


@pytest.mark.parametrize("guess", ["14933-6", "2160-0", "9999-9", "3084-1", ""])
@pytest.mark.parametrize("term", ["尿酸", "uric acid", "UA"])
def test_a_urate_line_is_stored_as_serum_urate_whatever_code_the_model_guessed(term: str, guess: str) -> None:
    got = _obs(term, guess)
    assert got is not None and got["code"] == "3084-1" and got["system"] == charts.LOINC
    assert got["value"] == "8.1" and got["unit"] == "mg/dL"


def test_a_urate_value_in_micromoles_is_converted_with_the_urate_factor_not_the_codes() -> None:
    """Before: the creatinine code chose creatinine's factor (88.42) for a urate value in µmol/L."""
    got = _obs("尿酸", "2160-0", "476", "µmol/L")
    assert got is not None and got["code"] == "3084-1" and got["value"] == "8"  # 476 / 59.48 = 8.0


def test_a_term_trialbox_does_not_know_keeps_the_models_code() -> None:
    got = _obs("フェリチン", "2276-4", "120", "ng/mL")
    assert got is not None and got["code"] == "2276-4"


def test_a_code_without_a_known_term_still_names_the_analyte() -> None:
    got = _obs("検査値", "2160-0", "1.1")
    assert got is not None and got["code"] == "2160-0" and got["unit"] == "mg/dL"


@pytest.mark.parametrize("term", ["尿中尿酸", "尿液肌酸酐", "urine creatinine"])
def test_a_urine_test_is_never_turned_into_the_serum_test(term: str) -> None:
    got = _obs(term, "", "40")
    assert got is None or got["code"] not in ("3084-1", "2160-0")
