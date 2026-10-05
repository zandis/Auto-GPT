"""Derived observations (SPEC §3.3): one constants file shared by the Python reference, the CQL helper library
``TB_Common`` (rendered from these constants) and the DuckDB SQL templates.

* BMI = weight[kg] / (height[cm] / 100)^2, latest height and weight within the window (default 365 d).
* eGFR = CKD-EPI 2021 (race-free) from latest serum creatinine [mg/dL], age at index, sex (default 365 d).
* DAS28 = DAS28-ESR when an ESR exists in the window, else DAS28-CRP (CRP in mg/L); needs latest TJC28, SJC28 and
  patient global (0-100 mm); null if any component is missing (default 90 d).
* BASDAI = (Q1 + Q2 + Q3 + Q4 + (Q5 + Q6) / 2) / 5 (each 0-10).
* ASDAS-CRP = 0.12 back pain + 0.06 morning-stiffness duration + 0.11 patient global (0-10) + 0.07 peripheral pain
  + 0.58 ln(CRP + 1).

Values are compared unrounded (DECISIONS D-17).
"""

from __future__ import annotations

import math

LOINC = "http://loinc.org"
SCORE = "https://trialbox.local/fhir/CodeSystem/clinical-score"

# component -> (system, code)
CODES: dict[str, tuple[str, str]] = {
    "weight": (LOINC, "29463-7"),
    "height": (LOINC, "8302-2"),
    "creatinine": (LOINC, "2160-0"),
    "tjc28": (SCORE, "TJC28"),
    "sjc28": (SCORE, "SJC28"),
    "ptga": (SCORE, "PTGA"),
    "esr": (LOINC, "4537-7"),
    "crp": (LOINC, "1988-5"),
    "basdai_q1": (SCORE, "BASDAI-Q1"),
    "basdai_q2": (SCORE, "BASDAI-Q2"),
    "basdai_q3": (SCORE, "BASDAI-Q3"),
    "basdai_q4": (SCORE, "BASDAI-Q4"),
    "basdai_q5": (SCORE, "BASDAI-Q5"),
    "basdai_q6": (SCORE, "BASDAI-Q6"),
}

COMPONENTS: dict[str, list[str]] = {
    "bmi": ["weight", "height"],
    "egfr": ["creatinine"],
    "das28": ["tjc28", "sjc28", "ptga", "esr", "crp"],
    "basdai": ["basdai_q1", "basdai_q2", "basdai_q3", "basdai_q4", "basdai_q5", "basdai_q6"],
    "asdas": ["basdai_q2", "basdai_q6", "ptga", "basdai_q3", "crp"],
}

DEFAULT_WINDOW_DAYS: dict[str, int] = {"bmi": 365, "egfr": 365, "das28": 90, "basdai": 90, "asdas": 90}

EGFR = {
    "k": 142.0,
    "kappa_f": 0.7,
    "kappa_m": 0.9,
    "alpha_f": -0.241,
    "alpha_m": -0.302,
    "exp_hi": -1.200,
    "age_base": 0.9938,
    "female": 1.012,
}
DAS28 = {"tjc": 0.56, "sjc": 0.28, "gh": 0.014, "esr_ln": 0.70, "crp_ln": 0.36, "crp_const": 0.96}
ASDAS = {"back": 0.12, "stiff": 0.06, "ptga": 0.11, "periph": 0.07, "crp_ln": 0.58}


def bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100.0) ** 2


def egfr(creatinine_mg_dl: float, age_years: int, female: bool) -> float:
    kappa = EGFR["kappa_f"] if female else EGFR["kappa_m"]
    alpha = EGFR["alpha_f"] if female else EGFR["alpha_m"]
    ratio = creatinine_mg_dl / kappa
    val = EGFR["k"] * min(ratio, 1.0) ** alpha * max(ratio, 1.0) ** EGFR["exp_hi"] * EGFR["age_base"] ** age_years
    return float(val * EGFR["female"] if female else val)


def das28_esr(tjc: float, sjc: float, ptga: float, esr: float) -> float:
    return (
        DAS28["tjc"] * math.sqrt(tjc)
        + DAS28["sjc"] * math.sqrt(sjc)
        + DAS28["esr_ln"] * math.log(esr)
        + DAS28["gh"] * ptga
    )


def das28_crp(tjc: float, sjc: float, ptga: float, crp_mg_l: float) -> float:
    return (
        DAS28["tjc"] * math.sqrt(tjc)
        + DAS28["sjc"] * math.sqrt(sjc)
        + DAS28["crp_ln"] * math.log(crp_mg_l + 1)
        + DAS28["gh"] * ptga
        + DAS28["crp_const"]
    )


def basdai(q1: float, q2: float, q3: float, q4: float, q5: float, q6: float) -> float:
    return (q1 + q2 + q3 + q4 + (q5 + q6) / 2.0) / 5.0


def asdas_crp(back_pain: float, stiffness: float, ptga_mm: float, peripheral: float, crp_mg_l: float) -> float:
    return (
        ASDAS["back"] * back_pain
        + ASDAS["stiff"] * stiffness
        + ASDAS["ptga"] * (ptga_mm / 10.0)
        + ASDAS["periph"] * peripheral
        + ASDAS["crp_ln"] * math.log(crp_mg_l + 1)
    )
