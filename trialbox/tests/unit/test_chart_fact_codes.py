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
        {
            "domain": "observation",
            "term": term,
            "value": value,
            "unit": unit,
            "code": code,
            "system": "loinc",
            "quote": f"{term} {value} {unit}",
            "date": "",
        }
    )


@pytest.mark.parametrize("guess", ["14933-6", "2160-0", "2345-7", "3084-1", ""])
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


@pytest.mark.parametrize("term", ["BUN", "検査値", "尿素窒素"])
def test_a_serum_code_on_a_line_that_does_not_name_that_test_is_dropped(term: str) -> None:
    """Review of this fix: "BUN 18 mg/dL" with the creatinine code was stored as creatinine 18 mg/dL."""
    got = _obs(term, "2160-0", "18")
    assert got is not None and got["code"] == "" and got["system"] == "" and got["value"] == "18"


@pytest.mark.parametrize("guess", ["", "3084-1", "2160-0"])
@pytest.mark.parametrize("term", ["尿中尿酸", "尿液肌酸酐", "urine creatinine", "尿中クレアチニン"])
def test_a_urine_test_is_never_turned_into_the_serum_test(term: str, guess: str) -> None:
    got = _obs(term, guess, "40")
    assert got is None or got["code"] not in ("3084-1", "2160-0")
    got = _obs(term, guess, "8840", "µmol/L")
    assert got is None or (got["code"] == "" and got["value"] == "8840")  # never converted as the serum test


def test_a_code_of_another_system_is_not_kept_on_a_lab_fact() -> None:
    got = charts.normalise(
        {
            "domain": "observation",
            "term": "フェリチン",
            "value": "120",
            "unit": "ng/mL",
            "code": "E11.9",
            "system": "icd10cm",
            "quote": "フェリチン 120",
            "date": "",
        }
    )
    assert got is not None and got["code"] == "" and got["system"] == ""


# the adversarial review of this fix: a model's specific LOINC was overwritten by the generic serum code
@pytest.mark.parametrize(
    ("term", "code", "unit"),
    [
        ("尿クレアチニン", "2161-8", "mg/dL"),
        ("尿肌酸酐", "2161-8", "mg/dL"),
        ("UA-PRO", "2888-6", "mg/dL"),
        ("UA 蛋白", "2888-6", "mg/dL"),
        ("UA glucose", "25428-4", "mg/dL"),
        ("胸水 glucose", "2342-4", "mg/dL"),
        ("空腹時血糖", "1558-6", "mg/dL"),
        ("75gOGTT 2時間値 血糖", "20438-8", "mg/dL"),
    ],
)
def test_a_specific_loinc_the_model_gave_is_kept(term: str, code: str, unit: str) -> None:
    got = _obs(term, code, "80", unit)
    assert got is not None and got["code"] == code


@pytest.mark.parametrize(
    "term", ["尿クレアチニン", "UA-PRO", "胸水 glucose", "尿酸クレアチニン比", "体重変化", "出生体重"]
)
def test_a_line_that_is_not_the_serum_result_is_never_given_the_serum_code(term: str) -> None:
    got = _obs(term, "", "3", "mg/dL" if "体重" not in term else "kg")
    assert got is None or got["code"] not in ("3084-1", "2160-0", "2345-7", "29463-7")


def test_the_same_test_in_another_unit_is_stored_under_the_analytes_own_code() -> None:
    got = _obs("HbA1c", "59261-8", "48", "mmol/mol")
    assert got is not None and got["code"] == "4548-4" and got["value"] == "6.54" and got["unit"] == "%"
    got = _obs("Uric acid", "14933-6", "500", "µmol/L")
    assert got is not None and got["code"] == "3084-1" and got["value"] == "8.41"


def test_a_loinc_trialbox_does_not_know_is_kept_as_given_and_decides_nothing_it_should_not() -> None:
    """A code TrialBox has no table for may be right (a specific method) or made up: it is kept, so the fact matches
    only a criterion that lists that code; on a serum urate criterion the patient stays "needs information"."""
    got = _obs("尿酸", "9999-9")
    assert got is not None and got["code"] == "9999-9"
