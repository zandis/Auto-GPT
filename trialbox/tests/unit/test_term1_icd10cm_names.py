"""TERM-1 (D-858): a condition named in a protocol resolves to ICD-10-CM families through code systems loaded on the
box at install (D-528: never committed): ICD-10-CM's blocks and its Alphabetic Index, beside the full code list.

Launch P1b's review (public ClinicalTrials.gov protocols): 47 of 588 drafted condition concepts resolved. The tables
here are loaded from a stand-in of CMS's code-tables zip written by the test (a few blocks and index terms, worded
as the release words them); the real release is loaded on the box by ``tools.terminology_install``."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from criteria_compiler.terminology import installed
from criteria_compiler.terminology.mapper import SYSTEMS, Terminology

ICD = SYSTEMS["icd10cm"]
TABULAR = """<?xml version="1.0"?><ICD10CM.tabular><chapter><name>9</name>
<desc>Diseases of the circulatory system (I00-I99)</desc>
<section id="I10-I1A"><desc>Hypertensive diseases (I10-I1A)</desc></section>
<section id="I20-I25"><desc>Ischemic heart diseases (I20-I25)</desc></section>
<section id="I60-I69"><desc>Cerebrovascular diseases (I60-I69)</desc></section></chapter>
<chapter><name>6</name><desc>Diseases of the nervous system (G00-G99)</desc>
<section id="G40-G47"><desc>Episodic and paroxysmal disorders (G40-G47)</desc></section></chapter></ICD10CM.tabular>"""
INDEX = """<?xml version="1.0"?><ICD10CM.index><letter><title>A</title>
<mainTerm><title>Accident</title><term level="1"><title>cerebrovascular</title><code>I63.9</code></term></mainTerm>
</letter><letter><title>B</title>
<mainTerm><title>Bipolar disorder</title><code>F31.9</code></mainTerm></letter>
<letter><title>D</title><mainTerm><title>Dyslipidemia</title><code>E78.5</code></mainTerm></letter>
<letter><title>S</title><mainTerm><title>Seizure disorder</title><see>Epilepsy</see></mainTerm>
<mainTerm><title>Epilepsy</title><code>G40.909</code></mainTerm></letter></ICD10CM.index>"""


def _zip(tmp: Path) -> Path:
    z = tmp / "2026-code-tables-tabular-and-index.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Table and Index/icd10cm_tabular_2026.xml", TABULAR)
        f.writestr("Table and Index/icd10cm_index_2026.xml", INDEX)
    return z


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("term1")
    where = tmp / "terminology"
    got = installed.install_icd10cm(_zip(tmp), where, "2026")
    assert got == {"icd10cm_blocks": 6, "icd10cm_index": 5}
    return where


@pytest.fixture(scope="module")
def term(loaded: Path) -> Terminology:
    return Terminology(installed=loaded)


def _families(r: object) -> set[str]:
    return {p for s, p in getattr(r, "families", []) if s == ICD}


@pytest.mark.parametrize(("name", "family"), [
    ("ischemic heart disease", {"I20", "I21", "I22", "I23", "I24", "I25"}),  # a block: every category in it
    ("cerebrovascular disease", {"I60", "I61", "I62", "I63", "I65", "I66", "I67", "I68", "I69"}),  # no I64 in -CM
    ("hypertension", {"I10", "I11", "I12", "I13", "I15", "I16", "I1A"}),  # a trial word, then its block
    ("congestive heart failure", {"I50"}),  # a trial word, then a category's own description (the shipped list)
    ("COPD", {"J44"}),  # an abbreviation to its category
    ("bipolar disorder", {"F31"}),  # the Alphabetic Index leads to a code; the concept is its category
    ("cerebrovascular accident", {"I63"}),  # read turned, as the index writes it: "Accident, cerebrovascular"
    ("seizure disorder", {"G40"}),
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


def test_a_name_no_table_knows_stays_unmapped_and_conditions_only(term: Terminology) -> None:
    assert term.map("condition", "qwerty zxcv syndrome").method == "none"
    assert term.map("medication", "epilepsy").method != "icd10cm"


def test_without_the_loaded_tables_blocks_and_index_do_not_answer(tmp_path: Path) -> None:
    t = Terminology(installed=tmp_path / "nothing")
    assert t.map("condition", "ischemic heart disease").method == "none"  # the block is loaded at install only
    assert t.map("condition", "bipolar disorder").method != "icd10cm" or "F31" in _families(
        t.map("condition", "bipolar disorder"))  # the shipped list's own description may still answer  # fmt: skip


def test_a_table_without_its_manifest_line_or_with_other_bytes_is_refused(loaded: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "icd10cm_blocks.parquet").write_bytes((loaded / "icd10cm_blocks.parquet").read_bytes())
    t = Terminology(installed=copy)  # copied by hand: no manifest
    assert t.icd_blocks == {} and any("no line in manifest.json" in p for p in t.installed_problems)
    data = json.loads((loaded / "manifest.json").read_text(encoding="utf-8"))
    data["tables"]["icd10cm_blocks"]["sha256"] = "0" * 64
    (copy / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    assert any("sha256 differs" in p for p in Terminology(installed=copy).installed_problems)
    assert all(t.problem for t in installed.status(copy))  # the changed table, and the index line with no file


def test_the_manifest_says_source_version_licence_and_sha(loaded: Path) -> None:
    line = installed.manifest(loaded)["tables"]["icd10cm_index"]
    assert line["version"] == "ICD-10-CM 2026" and "public domain" in line["licence"]
    assert len(line["sha256"]) == 64 and line["rows"] == 5 and line["source"].startswith("CMS ICD-10-CM 2026")


def test_doctor_says_what_is_loaded(loaded: Path, tmp_path: Path) -> None:
    from tools.trialbox import doctor

    ok = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(loaded)}))
    assert ok.status == "PASS" and "icd10cm_blocks 6 rows (ICD-10-CM 2026)" in ok.detail
    none = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(tmp_path / "empty")}))
    assert none.status == "WARN" and "terminology_install" in none.detail
