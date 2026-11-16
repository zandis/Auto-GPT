"""TERM-1 (D-858): a condition named in a protocol resolves to ICD-10-CM codes through the full code list, its block
hierarchy and its Alphabetic Index, not only through the 79 curated rows.

Launch P1b's review (public ClinicalTrials.gov protocols): of 588 condition concepts the compiler drafted, 47 resolved
to a code; no coded value-set criterion decided anything. ICD-10-CM's full list was shipped (D-122) but used for code
lookups only. The names below are concept names as the compiler drafted them from those public protocols."""

from __future__ import annotations

import pytest
from criteria_compiler.terminology.mapper import SYSTEMS, Terminology

ICD = SYSTEMS["icd10cm"]


@pytest.fixture(scope="module")
def term() -> Terminology:
    return Terminology()


def _families(r: object) -> set[str]:
    return {p for s, p in getattr(r, "families", []) if s == ICD}


@pytest.mark.parametrize(("name", "family"), [
    ("ischemic heart disease", {"I20", "I21", "I22", "I23", "I24", "I25"}),  # a block: every category in it
    ("cerebrovascular disease", {"I60", "I61", "I62", "I63", "I65", "I66", "I67", "I68", "I69"}),  # no I64 in -CM
    ("congestive heart failure", {"I50"}),  # an abbreviation or trial word, then the category
    ("COPD", {"J44"}),
    ("epilepsy", {"G40"}),  # the Alphabetic Index leads to a code; the concept is its category
    ("systemic lupus erythematosus", {"M32"}),
    ("bipolar disorder", {"F31"}),
])  # fmt: skip
def test_a_named_condition_resolves_to_its_icd10cm_family(term: Terminology, name: str, family: set[str]) -> None:
    r = term.map("condition", name)
    assert r.concepts and r.method == "icd10cm"
    assert family <= _families(r), (name, sorted(_families(r))[:12])
    assert all(c.system == ICD for c in r.concepts)


@pytest.mark.parametrize(("name", "family"), [("gout", {"M10", "M1A"}), ("malignancy", {"C0", "C9"})])
def test_a_curated_grouper_still_wins(term: Terminology, name: str, family: set[str]) -> None:
    r = term.map("condition", name)
    assert r.method == "synonym" and family <= _families(r)


def test_a_name_no_table_knows_stays_unmapped(term: Terminology) -> None:
    assert term.map("condition", "qwerty zxcv syndrome").method == "none"


def test_icd10cm_names_answer_conditions_only(term: Terminology) -> None:
    assert term.map("medication", "epilepsy").method != "icd10cm"


# concept names the compiler drafted (condition domain) from P1b's public protocols, as written
P1B = ["esophageal squamous cell carcinoma", "basal cell skin carcinoma", "carcinoma in situ of the cervix",
       "epilepsy", "cerebrovascular disease", "migraine", "alcohol abuse", "hypertension", "ischemic heart disease",
       "chronic heart failure", "unstable angina", "bronchiectasis", "cystic fibrosis", "bipolar disorder",
       "neutropenia", "endometriosis", "ectopic pregnancy", "systemic lupus erythematosus", "dyslipidemia",
       "claudication", "seizure disorder", "cerebrovascular accident", "tuberculosis", "malignancy", "liver disease",
       "asthma", "major depressive disorder", "chronic subdural hematoma", "uterine fibroids", "copd"]  # fmt: skip


def test_most_p1b_condition_names_resolve(term: Terminology) -> None:
    hits = [n for n in P1B if term.map("condition", n).concepts]
    assert len(hits) >= 25, sorted(set(P1B) - set(hits))
