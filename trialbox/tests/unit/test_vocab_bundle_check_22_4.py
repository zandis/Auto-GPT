"""Card 22-4 (root review 22): the build-time check that fails when a row of a must-not-ship vocabulary (licence
class c in ``docs/licences/register.csv``) reaches a terminology artefact going into a bundle.

The artefacts are tiny synthetic files written here: a clean table, a table carrying a row of a forbidden vocabulary,
a derived mapping whose source is forbidden, a FHIR value set naming a forbidden system and a Parquet table. Concept
names and codes are invented.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tools import vocab_bundle_check as vbc

pytestmark = pytest.mark.nodb

CONCEPT_HEADER = "concept_id,concept_name,domain_id,vocabulary_id,concept_class_id,standard_concept,concept_code\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_forbidden_list_is_the_registers_class_c() -> None:
    bad = vbc.forbidden()
    assert bad.ids["SNOMED"] == "snomed-ct" and bad.ids["CPT4"] == "athena-licensed" and bad.ids["ICD10"] == "icd10-who"
    assert bad.uris["http://snomed.info/sct"] == "snomed-ct"
    assert not {"RxNorm", "RxNorm Extension", "LOINC", "UCUM", "ATC", "None", "Gender"} & set(bad.ids)
    assert "http://www.whocc.no/atc" not in bad.uris and "http://loinc.org" not in bad.uris


def test_a_clean_table_passes(tmp_path: Path) -> None:
    clean = _write(tmp_path / "bundle/rxnorm_candidates.csv", CONCEPT_HEADER +
                   "1545958,Invented ingredient one,Drug,RxNorm,Ingredient,S,83367\n"
                   "8507,Invented gender,Gender,Gender,Gender,S,M\n")  # fmt: skip
    assert vbc.check([clean]) == []


def test_a_row_of_a_forbidden_vocabulary_fails_naming_file_and_vocabulary(tmp_path: Path) -> None:
    dirty = _write(tmp_path / "bundle/open_subset.csv", CONCEPT_HEADER +
                   "1545958,Invented ingredient one,Drug,RxNorm,Ingredient,S,83367\n"
                   "4000001,Invented disorder alpha,Condition,SNOMED,Clinical Finding,S,1000001\n")  # fmt: skip
    assert vbc.check([tmp_path / "bundle"]) == [
        f"{dirty}: 1 row(s) of vocabulary 'SNOMED', licence class c, must not ship (register row snomed-ct)"
    ]


def test_a_derived_mapping_whose_source_is_forbidden_fails(tmp_path: Path) -> None:
    m = _write(tmp_path / "maps/regimen_to_rxnorm.tsv.gz", "")
    with gzip.open(m, "wt", encoding="utf-8") as fh:  # the source_to_concept_map shape, tab-separated
        fh.write("source_code\tsource_vocabulary_id\ttarget_concept_id\ttarget_vocabulary_id\n"
                 "R-1\tHemOnc\t1545958\tRxNorm\nR-2\tHemOnc\t1503297\tRxNorm\nX-1\tRxNorm\t1545958\tRxNorm\n")  # fmt: skip
    assert vbc.check([m]) == [
        f"{m}: 2 row(s) of vocabulary 'HemOnc', licence class c, must not ship (register row athena-licensed)"
    ]


def test_a_value_set_and_a_concept_map_naming_a_forbidden_system_fail(tmp_path: Path) -> None:
    vs = _write(tmp_path / "rulesets/X/valuesets/VS_INVENTED.json", json.dumps({
        "resourceType": "ValueSet", "compose": {"include": [
            {"system": "http://www.whocc.no/atc", "concept": [{"code": "Z99ZZ99"}]},
            {"system": "http://snomed.info/sct", "concept": [{"code": "1000001"}]}]}}))  # fmt: skip
    cm = _write(tmp_path / "rulesets/X/maps/CM_INVENTED.json", json.dumps({
        "resourceType": "ConceptMap", "group": [{"source": "http://hl7.org/fhir/sid/icd-10",
                                                 "target": "http://hl7.org/fhir/sid/icd-10-cm"}]}))  # fmt: skip
    assert vbc.check([tmp_path / "rulesets"]) == [
        f"{cm}: 1 row(s) of vocabulary 'http://hl7.org/fhir/sid/icd-10', licence class c, must not ship "
        "(register row icd10-who)",
        f"{vs}: 1 row(s) of vocabulary 'http://snomed.info/sct', licence class c, must not ship "
        "(register row snomed-ct)",
    ]


def test_a_parquet_table_is_read_by_its_vocabulary_and_system_columns(tmp_path: Path) -> None:
    f = tmp_path / "terminology/candidates.parquet"
    f.parent.mkdir(parents=True)
    pq.write_table(pa.table({"code": ["A", "B", "C"], "vocabulary_id": ["RxNorm", "CPT4", "RxNorm"],
                             "name": ["Invented a", "Invented b", "Invented c"]}), f)  # fmt: skip
    assert vbc.check([f]) == [
        f"{f}: 1 row(s) of vocabulary 'CPT4', licence class c, must not ship (register row athena-licensed)"
    ]
    clean = tmp_path / "terminology/clean.parquet"
    pq.write_table(pa.table({"system": ["http://loinc.org"], "code": ["2160-0"]}), clean)
    assert vbc.check([clean]) == []


def test_the_command_fails_and_names_the_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = _write(tmp_path / "ok/a.csv", CONCEPT_HEADER + "8507,Invented gender,Gender,Gender,Gender,S,M\n")
    assert vbc.main([str(clean)]) == 0
    bad = _write(tmp_path / "bad/b.csv", CONCEPT_HEADER + "4000003,Invented regimen,Regimen,HemOnc,Regimen,S,9\n")
    assert vbc.main([str(clean), str(bad)]) == 1
    err = capsys.readouterr().err
    assert str(bad) in err and "'HemOnc'" in err and str(clean) not in err
