"""T-105b (STD-030, STD-034): an Athena bundle in the vocabulary, and the standard concepts it gives.

The bundle is ``tests/fixtures/vocab/athena-test``: synthetic, shaped like an Athena download (tab-separated,
``YYYYMMDD`` dates), no licensed content. Its ATC concept ids (1,900,000,001 and up) are made up; the RxNorm, LOINC,
UCUM, gender, visit and type ids are the public OHDSI ids of those concepts. Cases: a ``Maps to`` row (atorvastatin
C10AA05), the primary lateral ATC link (metformin A10BA02), the plain ATC link (methotrexate L04AX03), a deprecated
``Maps to`` that is ignored (amlodipine C08CA01), a combination with two ingredients that stays 0 (C10BX03) and an
ATC class with no link (allopurinol M04AA01).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_omop_core import _feed, _load, db, feed_dir  # noqa: F401 - fixtures used by name

ATHENA = Path(__file__).resolve().parents[1] / "fixtures" / "vocab" / "athena-test"
ATC = "http://www.whocc.no/atc"
INGREDIENT = {"C10AA05": 1545958, "A10BA02": 1503297, "L04AX03": 1305058, "C08CA01": 1332418}


def test_atc_drug_rows_get_rxnorm_ingredient_ids(feed_dir: Path, db: Any) -> None:  # noqa: F811
    from omop import dqd, vocab_load

    res = vocab_load.load_athena(db, ATHENA, by="test")
    assert res.new and res.concepts == 19
    _load(db, _feed(feed_dir))
    got = dict(db.fetchall(
        "SELECT drug_source_value, min(drug_concept_id) FROM drug_exposure WHERE drug_source_value = ANY(?) "
        "GROUP BY 1 HAVING min(drug_concept_id) = max(drug_concept_id)", ([*INGREDIENT, "M04AA01"],)))  # fmt: skip
    assert got == {**INGREDIENT, "M04AA01": 0}  # every row of each code; allopurinol has no link in the bundle
    assert db.fetchval("SELECT count(*) FROM drug_exposure WHERE drug_source_value = ANY(?) "
                       "AND drug_source_concept_id < 2000000000", (list(INGREDIENT),)) == 0  # fmt: skip
    assert db.fetchval("SELECT count(*) FROM condition_occurrence WHERE condition_concept_id <> 0") == 0
    assert db.fetchval("SELECT count(*) FROM condition_occurrence") > 0
    assert db.fetchall("SELECT DISTINCT measurement_concept_id FROM measurement "
                       "WHERE measurement_source_value = '2160-0'") == [(3016723,)]  # fmt: skip
    res_dqd = dqd.run(db)
    assert [r for r in res_dqd if r["status"] == "fail"] == []
    notes = {r["cdmTableName"]: r["notes"] for r in res_dqd if r["checkName"] == "standardConceptRecordCompleteness"}
    assert "SNOMED" in notes["condition_occurrence"] and "until" not in notes["condition_occurrence"]
    assert "single RxNorm ingredient" in notes["drug_exposure"] and "TEST-SYNTHETIC" in notes["drug_exposure"]


def test_maps_to_takes_one_valid_standard_concept_or_none(db: Any) -> None:  # noqa: F811
    from omop import vocab_load
    from omop.vocab import Code, Concepts

    vocab_load.load_athena(db, ATHENA)
    with db.transaction() as tx:
        c = Concepts(tx)
        codes = ["C10AA05", "A10BA02", "L04AX03", "C08CA01", "C10BX03", "M04AA01", "Z99ZZ99"]
        c.prepare([*(Code(ATC, k, None, "Drug") for k in codes),
                   Code("http://hl7.org/fhir/sid/icd-10-cm", "E11.9", None, "Condition"),
                   Code("http://loinc.org", "2160-0", None, "Measurement")])  # fmt: skip
        assert {k: c.standard_id(ATC, k) for k in codes} == {**INGREDIENT, "C10BX03": 0, "M04AA01": 0, "Z99ZZ99": 0}
        assert c.standard_id("http://hl7.org/fhir/sid/icd-10-cm", "E11.9") == 0  # SNOMED is not on the box
        assert c.standard_id("http://loinc.org", "2160-0") == 3016723  # a standard code is its own concept
        assert c.source_id(ATC, "A10BA02") >= 2_000_000_000  # the source concept stays the site's own


def test_bundle_version_is_recorded_and_a_second_load_changes_nothing(db: Any) -> None:  # noqa: F811
    from omop import vocab_load

    first = vocab_load.load_athena(db, ATHENA)
    rel = [r for r in vocab_load.releases(db) if r["release_name"] == "ATHENA"]
    assert len(rel) == 1 and rel[0]["version"] == "v5.0 TEST-SYNTHETIC 10-NOV-26" and not rel[0]["compile"]
    assert db.fetchval("SELECT vocabulary_version FROM vocabulary WHERE vocabulary_id = 'RxNorm'").startswith(
        "TEST-SYNTHETIC"
    )
    loaded = vocab_load.athena_loaded(db)
    assert {"ATC", "RxNorm", "LOINC", "None"} <= set(loaded)
    count = db.fetchval("SELECT count(*) FROM concept_relationship")
    again = vocab_load.load_athena(db, ATHENA)
    assert first.new and not again.new and db.fetchval("SELECT count(*) FROM concept_relationship") == count


def test_a_bundle_with_a_vocabulary_off_the_allow_list_is_refused(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load
    from omop.schema import OmopError

    bad = tmp_path / "bundle"
    shutil.copytree(ATHENA, bad)
    with (bad / "CONCEPT.csv").open("a", encoding="utf-8") as f:
        f.write("4000001\tSynthetic disorder\tCondition\tSNOMED\tClinical Finding\tS\t1000001\t19700101\t20991231\t\n")
    with pytest.raises(OmopError, match="not on the allow-list: SNOMED"):
        vocab_load.load_athena(db, bad, strict=True)  # a release build (card 22-2): refused whole
    assert vocab_load.athena_loaded(db) == {}
    high = tmp_path / "high"
    shutil.copytree(ATHENA, high)
    with (high / "CONCEPT.csv").open("a", encoding="utf-8") as f:
        f.write("2000000500\tA local\tDrug\tATC\tATC 5th\tC\tX01XX01\t19700101\t20991231\t\n")
    with pytest.raises(OmopError, match="outside the OHDSI range"):
        vocab_load.load_athena(db, high)


def test_dqd_says_why_without_a_bundle() -> None:
    from omop.dqd import vocab_gap

    assert "no RxNorm on the box" in vocab_gap("drug_exposure", {})
    assert "SNOMED" in vocab_gap("condition_occurrence", {"RxNorm": "x", "ATC": "y"})
    assert vocab_gap("visit_occurrence", {}) == ""
