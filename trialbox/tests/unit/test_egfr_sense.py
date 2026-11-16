"""D-986 (the integrator's side finding on D-983, #639): ``terms.py`` mapped every "egfr" to the epidermal growth
factor receptor, so a kidney line ("eGFR < 30 mL/min") retrieved notes for 表皮生長因子受體. The spelling decides
(capitals: the receptor; "eGFR": the kidney) unless the line says otherwise: a kidney word or a comparison with a
number makes it the kidney's, an oncology word the receptor's. Public protocol wording; no patient data."""

from __future__ import annotations

import pytest
from orchestrator.scenarios.terms import egfr_sense, keywords, source_words

KIDNEY = [
    ("eGFR", "eGFR < 30 mL/min/1.73m2"),
    ("eGFR", "eGFR ≥ 45"),
    ("EGFR", "EGFR < 30"),
    ("EGFR", "EGFR 30 mL/min or on dialysis"),
    ("eGFR", "eGFR < 30 on an ACE inhibitor or angiotensin receptor blocker"),
    ("eGFR", "腎功能不全 eGFR<30"),
    ("egfr", "egfr below 30"),
    ("eGFR", "eGFR"),
]
RECEPTOR = [
    ("EGFR", "EGFR mutation-positive lung adenocarcinoma"),
    ("EGFR", "Prior EGFR-TKI within 4 weeks"),
    ("EGFR", "EGFR exon 19 deletion or L858R"),
    ("eGFR", "eGFR mutation (exon 19)"),
    ("EGFR", "EGFR amplification"),
    ("EGFR", "EGFR 突變陽性之肺腺癌"),
    ("EGFR", "EGFR"),
]


@pytest.mark.parametrize(("word", "text"), KIDNEY)
def test_the_kidneys_egfr(word: str, text: str) -> None:
    assert egfr_sense(word, text) == "kidney"


@pytest.mark.parametrize(("word", "text"), RECEPTOR)
def test_the_receptor(word: str, text: str) -> None:
    assert egfr_sense(word, text) == "receptor"


def test_a_kidney_line_retrieves_the_kidneys_words_never_the_receptors() -> None:
    kw = keywords("eGFR < 30 mL/min/1.73m2")
    assert "腎絲球過濾率" in kw and "表皮生長因子受體" not in kw
    assert source_words("eGFR < 30 mL/min/1.73m2") == ["egfr"]


def test_a_receptor_line_keeps_the_receptors_words() -> None:
    kw = keywords("EGFR mutation positive")
    assert "表皮生長因子受體" in kw and "腎絲球過濾率" not in kw
