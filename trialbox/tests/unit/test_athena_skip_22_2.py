"""Card 22-2 (root review 22, T6-5): the Athena loader loads the vocabularies the licence register allows and skips
the rest, reporting which loaded, which were skipped and why; ``strict`` keeps the old whole-bundle refusal.

The downloads are ``tests/fixtures/vocab/athena-test`` (synthetic) with a few invented rows appended per test:
a SNOMED concept (class c, row ``snomed-ct``: must not ship), a KCD7 concept (class c, row ``athena-licensed``: the
site loads it under its own licence), a HemOnc one, and a vocabulary no row names. No real vocabulary content.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_omop_core import db  # noqa: F401 - fixture used by name
from tools import licence_register as lr

ATHENA = Path(__file__).resolve().parents[1] / "fixtures" / "vocab" / "athena-test"
# the hard-coded list the loader had before card 22-2 (PR #145, T-105b): the register must give exactly it
BEFORE_22_2 = frozenset({
    "LOINC", "UCUM", "RxNorm", "RxNorm Extension", "ATC", "Gender", "Race", "Ethnicity", "Visit", "Type Concept",
    "None", "Domain", "Vocabulary", "Concept Class", "Relationship", "Metadata", "Note Encoding", "Language",
    "Condition Status", "Meas Type", "Cost", "Cost Type", "Episode", "Episode Type", "OMOP Extension",
})  # fmt: skip
# invented concepts: ids in the OHDSI range, made-up names and codes
EXTRA = {
    "SNOMED": ("4000001", "Synthetic disorder alpha", "Condition", "Clinical Finding", "S", "1000001"),
    "KCD7": ("4000002", "Synthetic Korean code beta", "Condition", "KCD7 code", "", "Z00.0"),
    "HemOnc": ("4000003", "Synthetic regimen gamma", "Regimen", "Regimen", "S", "999001"),
    "Made Up": ("4000004", "Synthetic thing delta", "Observation", "Thing", "", "MU-1"),
}
ATORVASTATIN = "1545958"  # an RxNorm ingredient of the fixture


def _download(tmp_path: Path, *vocabs: str) -> Path:
    out = tmp_path / "download"
    shutil.copytree(ATHENA, out)
    with (out / "VOCABULARY.csv").open("a", encoding="utf-8") as f:
        for v in vocabs:
            f.write(f"{v}\t{v} (synthetic)\tinvented\tTEST-SYNTHETIC {v}\t0\n")
    with (out / "CONCEPT.csv").open("a", encoding="utf-8") as f:
        for v in vocabs:
            cid, name, domain, klass, std, code = EXTRA[v]
            f.write(f"{cid}\t{name}\t{domain}\t{v}\t{klass}\t{std}\t{code}\t19700101\t20991231\t\n")
    with (out / "CONCEPT_RELATIONSHIP.csv").open("a", encoding="utf-8") as f:
        for v in vocabs:  # a map from the skipped concept to a loaded one, and back: both must be left out
            cid = EXTRA[v][0]
            f.write(f"{cid}\t{ATORVASTATIN}\tMaps to\t19700101\t20991231\t\n")
            f.write(f"{ATORVASTATIN}\t{cid}\tMapped from\t19700101\t20991231\t\n")
    return out


# ------------------------------------------------------------------------------------------------ the list
def test_the_loadable_list_comes_from_the_register_and_is_the_list_of_before() -> None:
    from omop import vocab_load

    assert vocab_load.ATHENA_ALLOW == BEFORE_22_2
    reg = vocab_load.athena_register()
    assert {v for v, c in reg.items() if c.loadable} == BEFORE_22_2
    assert reg["SNOMED"].loadable is False and reg["SNOMED"].klass == "c" and reg["SNOMED"].status == "removed"
    assert reg["CPT4"].loadable is False and reg["HemOnc"].row == "athena-licensed"
    assert not any(c.klass == "c" for c in reg.values() if c.loadable)  # class c never loads


def test_the_register_refuses_a_class_c_vocabulary_on_the_loadable_column() -> None:
    rows = lr.load()
    snomed = next(r for r in rows if r.id == "snomed-ct")
    bad = lr.Row(snomed.id, snomed.kind, "site-loaded", snomed.source, snomed.spdx, ("SNOMED",), (), snomed.raw, "c",
                 ())  # fmt: skip
    assert "register row snomed-ct: class c, status site-loaded: its vocabularies go in athena_never, not athena" in (
        lr.row_problems([bad])
    )
    loinc = next(r for r in rows if r.id == "loinc")
    odd = lr.Row(loinc.id, loinc.kind, loinc.status, loinc.source, loinc.spdx, loinc.athena, (), loinc.raw, "",
                 ("KCD7",))  # fmt: skip
    problems = lr.row_problems([odd, snomed])
    assert "register row loinc: names Athena vocabularies but has no class" in problems
    assert "register row loinc: athena_never on a row of class (none) (only class c never loads)" in problems
    twice = lr.Row("x-row", "code-system", "removed", "s", "x", (), (), loinc.raw, "c", ("SNOMED",))
    assert "Athena vocabulary 'SNOMED' named by rows snomed-ct and x-row" in lr.row_problems([snomed, twice])


def test_selection_leaves_out_the_rows_of_skipped_vocabularies(tmp_path: Path) -> None:
    from omop import vocab_load

    tables = vocab_load.read_athena(_download(tmp_path, "SNOMED", "KCD7", "Made Up"))
    n_rel = len(tables["CONCEPT_RELATIONSHIP"])
    sel = vocab_load.select_athena(tables, vocab_load.ATHENA_ALLOW, vocab_load.athena_register())
    assert set(sel.skipped) == {"SNOMED", "KCD7", "Made Up"}
    assert sel.skipped["SNOMED"].startswith("licence class must not ship (register row snomed-ct")
    assert sel.skipped["KCD7"].startswith("licence class must not ship: the site loads it under its own licence")
    assert sel.skipped["Made Up"] == vocab_load.NOT_LISTED
    assert {r["vocabulary_id"] for r in tables["CONCEPT"]} == set(sel.loaded)
    assert {r["vocabulary_id"] for r in tables["VOCABULARY"]} <= set(sel.loaded)
    assert len(tables["CONCEPT_RELATIONSHIP"]) == n_rel - 6
    assert sel.rows_skipped == {"VOCABULARY": 3, "CONCEPT": 3, "CONCEPT_RELATIONSHIP": 6}
    d = sel.as_dict()
    assert d["counts"] == {"loaded": 8, "skipped": 3, "skipped_not_on_the_list": 1, "skipped_must_not_ship": 2}
    assert d["release"] == "v5.0 TEST-SYNTHETIC 10-NOV-26"
    assert {x["vocabulary"]: x["version"] for x in d["loaded"]}["RxNorm"] == "TEST-SYNTHETIC RxNorm 2026-11-03"


# ------------------------------------------------------------------------------------------------ the load
def test_a_download_with_other_vocabularies_loads_the_rest_and_reports_the_skipped(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load

    res = vocab_load.load_athena(db, _download(tmp_path, "SNOMED", "KCD7"), by="test")
    assert res.new and res.concepts == 19  # the fixture's own 19; the two invented ones left out
    report = res.as_dict()["athena"]
    assert [s["vocabulary"] for s in report["skipped"]] == ["KCD7", "SNOMED"]
    assert report["counts"]["skipped"] == 2 and report["counts"]["loaded"] == 8
    assert db.fetchval("SELECT count(*) FROM concept WHERE vocabulary_id IN ('SNOMED', 'KCD7')") == 0
    assert db.fetchval("SELECT count(*) FROM vocabulary WHERE vocabulary_id IN ('SNOMED', 'KCD7')") == 0
    assert db.fetchval("SELECT count(*) FROM concept_relationship WHERE concept_id_1 IN (4000001, 4000002) "
                       "OR concept_id_2 IN (4000001, 4000002)") == 0  # fmt: skip
    # the build record: the release, and each loaded vocabulary with its version
    rel = {r["release_name"]: r for r in vocab_load.releases(db) if r["release_name"].startswith("ATHENA")}
    assert rel["ATHENA"]["version"] == "v5.0 TEST-SYNTHETIC 10-NOV-26"
    assert rel["ATHENA:RxNorm"]["version"] == "TEST-SYNTHETIC RxNorm 2026-11-03"
    assert "ATHENA:SNOMED" not in rel and "ATHENA:KCD7" not in rel
    loaded = vocab_load.athena_loaded(db)  # with the box's seeded OMOP rows
    assert {"None", "ATC", "RxNorm", "LOINC", "UCUM"} <= set(loaded) and not {"SNOMED", "KCD7"} & set(loaded)
    assert not vocab_load.load_athena(db, _download(tmp_path / "again", "SNOMED", "KCD7")).new


def test_strict_refuses_the_whole_download(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load
    from omop.schema import OmopError

    with pytest.raises(OmopError, match="not on the allow-list: HemOnc, SNOMED"):
        vocab_load.load_athena(db, _download(tmp_path, "SNOMED", "HemOnc"), strict=True)
    assert vocab_load.athena_loaded(db) == {}


def test_an_allowed_only_download_loads_as_before(db: Any) -> None:  # noqa: F811
    from omop import vocab_load

    res = vocab_load.load_athena(db, ATHENA, by="test")
    assert res.sha256 == vocab_load.athena_sha(ATHENA)  # the same release identity as before card 22-2
    assert res.as_dict()["athena"]["skipped"] == [] and res.as_dict()["athena"]["counts"]["loaded"] == 8
    strict = vocab_load.load_athena(db, ATHENA, strict=True)  # nothing off the list: strict changes nothing
    assert not strict.new


def test_a_download_with_nothing_on_the_list_is_refused(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load
    from omop.schema import OmopError

    only = tmp_path / "only"
    only.mkdir()
    (only / "VOCABULARY.csv").write_text("vocabulary_id\tvocabulary_name\tvocabulary_reference\tvocabulary_version\t"
                                         "vocabulary_concept_id\nKCD7\tinvented\tinvented\tv1\t0\n",
                                         encoding="utf-8")  # fmt: skip
    cid, name, domain, klass, std, code = EXTRA["KCD7"]
    (only / "CONCEPT.csv").write_text(
        "concept_id\tconcept_name\tdomain_id\tvocabulary_id\tconcept_class_id\tstandard_concept\tconcept_code\t"
        f"valid_start_date\tvalid_end_date\tinvalid_reason\n{cid}\t{name}\t{domain}\tKCD7\t{klass}\t{std}\t{code}\t"
        "19700101\t20991231\t\n",
        encoding="utf-8",
    )
    with pytest.raises(OmopError, match="none of its vocabularies is on the list"):
        vocab_load.load_athena(db, only)
