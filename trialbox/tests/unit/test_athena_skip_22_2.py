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
# invented concepts: ids in the OHDSI range, made-up names and codes no vocabulary could hold
EXTRA = {
    "SNOMED": ("4000001", "Synthetic disorder alpha", "Condition", "Clinical Finding", "S", "NOT-A-CODE-1"),
    "KCD7": ("4000002", "Synthetic Korean code beta", "Condition", "KCD7 code", "", "NOT-A-CODE-2"),
    "HemOnc": ("4000003", "Synthetic regimen gamma", "Regimen", "Regimen", "S", "NOT-A-CODE-3"),
    "Made Up": ("4000004", "Synthetic thing delta", "Observation", "Thing", "", "NOT-A-CODE-4"),
    "CPT4": ("4000005", "Synthetic procedure epsilon", "Procedure", "CPT4", "S", "NOT-A-CODE-5"),
}
# what review 22 classes c and the register must keep in athena_never: dropping one fails here
NEVER_22 = frozenset({"SNOMED", "CPT4", "HemOnc", "ICDO3", "ICD10", "SMQ", "EORTC QLQ", "GCN_SEQNO", "Multum", "SUS",
                      "MMI", "JMDC"})  # fmt: skip
ATORVASTATIN = "1545958"  # an RxNorm ingredient of the fixture


def _download(tmp_path: Path, *vocabs: str, label: dict[str, str] | None = None) -> Path:
    """The fixture plus one invented concept per vocabulary; ``label`` writes a vocabulary under another spelling."""
    out = tmp_path / "download"
    shutil.copytree(ATHENA, out)
    names = {v: (label or {}).get(v, v) for v in vocabs}
    with (out / "VOCABULARY.csv").open("a", encoding="utf-8") as f:
        for v in vocabs:
            f.write(f"{names[v]}\t{v} (synthetic)\tinvented\tTEST-SYNTHETIC {v}\t0\n")
    with (out / "CONCEPT.csv").open("a", encoding="utf-8") as f:
        for v in vocabs:
            cid, name, domain, klass, std, code = EXTRA[v]
            f.write(f"{cid}\t{name}\t{domain}\t{names[v]}\t{klass}\t{std}\t{code}\t19700101\t20991231\t\n")
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


# ------------------------------------------------------------------------------------------------ review of PR #1093
def test_a_label_with_spaces_or_another_case_is_never_inserted(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load

    labels = {"SNOMED": "SNOMED ", "CPT4": " CPT4", "HemOnc": "hemonc"}
    res = vocab_load.load_athena(db, _download(tmp_path, "SNOMED", "CPT4", "HemOnc", label=labels), by="test")
    assert res.concepts == 19
    assert db.fetchval("SELECT count(*) FROM concept WHERE concept_id BETWEEN 4000001 AND 4000005") == 0
    reasons = {s["vocabulary"]: s["reason"] for s in res.as_dict()["athena"]["skipped"]}
    assert set(reasons) == {"SNOMED ", " CPT4", "hemonc"}
    assert all(r.startswith("licence class must not ship") for r in reasons.values()), reasons


def test_never_wins_and_the_rows_class_and_status_govern(tmp_path: Path) -> None:
    from omop import vocab_load

    reg = tmp_path / "register.csv"
    head = ",".join(lr.COLUMNS)
    row = {c: "x" for c in lr.COLUMNS}

    def line(**kw: str) -> str:
        return ",".join({**row, "athena": "", "athena_never": "", "class": "", **kw}[c] for c in lr.COLUMNS)

    reg.write_text("\n".join([
        head,
        line(id="r1", status="site-loaded", athena="RxNorm", **{"class": "a"}),
        line(id="r2", status="removed", athena_never="RxNorm", **{"class": "c"}),  # never wins over r1
        line(id="r3", status="cleared", athena="LOINC", **{"class": "c"}),  # class c in the wrong column
        line(id="r4", status="removed", athena="UCUM", **{"class": "b"}),  # removed
        line(id="r5", status="cleared", athena="Gender", **{"class": "d"}),
    ]) + "\n", encoding="utf-8")  # fmt: skip
    got = vocab_load.athena_register(reg)
    assert {v for v, c in got.items() if c.loadable} == {"Gender"}
    assert got["RxNorm"].row == "r2" and not got["RxNorm"].loadable


def test_side_rows_are_kept_only_inside_the_kept_concepts(tmp_path: Path) -> None:
    from omop import vocab_load

    d = _download(tmp_path, "SNOMED")
    (d / "CONCEPT_SYNONYM.csv").write_text(
        "concept_id\tconcept_synonym_name\tlanguage_concept_id\n"
        f"04000001\tInvented synonym of a skipped concept\t4180186\n{ATORVASTATIN}\tInvented synonym kept\t4180186\n"
        "4999999\tInvented synonym of a concept not in the download\t4180186\n",
        encoding="utf-8",
    )
    (d / "CONCEPT_ANCESTOR.csv").write_text(
        "ancestor_concept_id\tdescendant_concept_id\tmin_levels_of_separation\tmax_levels_of_separation\n"
        f"{ATORVASTATIN}\t{ATORVASTATIN}\t0\t0\n4000001\t{ATORVASTATIN}\t1\t1\n{ATORVASTATIN}\t004000001\t1\t1\n",
        encoding="utf-8",
    )
    tables = vocab_load.read_athena(d)
    sel = vocab_load.select_athena(tables, vocab_load.ATHENA_ALLOW, vocab_load.athena_register())
    assert [r["concept_synonym_name"] for r in tables["CONCEPT_SYNONYM"]] == ["Invented synonym kept"]
    assert len(tables["CONCEPT_ANCESTOR"]) == 1
    assert sel.rows_skipped["CONCEPT_SYNONYM"] == 2 and sel.rows_skipped["CONCEPT_ANCESTOR"] == 2


def test_rows_left_by_an_earlier_load_of_a_now_skipped_vocabulary_are_removed(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load

    vocab_load.load_athena(db, ATHENA, by="test")
    with db.transaction() as tx:  # as if an earlier load (a wider list) had brought KCD7
        tx.execute("INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, "
                   "vocabulary_concept_id) VALUES ('KCD7', 'invented', 'invented', 'v0', 0)")  # fmt: skip
        tx.execute("INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
                   "standard_concept, concept_code, valid_start_date, valid_end_date) VALUES (4000002, 'Invented', "
                   "'Condition', 'KCD7', 'KCD7 code', NULL, 'NOT-A-CODE-2', '1970-01-01', '2099-12-31')")  # fmt: skip
    res = vocab_load.load_athena(db, _download(tmp_path, "KCD7"), by="test")
    assert db.fetchval("SELECT count(*) FROM concept WHERE vocabulary_id = 'KCD7'") == 0
    assert db.fetchval("SELECT count(*) FROM vocabulary WHERE vocabulary_id = 'KCD7'") == 0
    assert res.as_dict()["athena"]["removed_from_the_box"] == {"KCD7": 1}


def test_a_malformed_download_is_refused_with_a_message(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load
    from omop.schema import OmopError

    d = _download(tmp_path, "SNOMED")
    with (d / "CONCEPT.csv").open("a", encoding="utf-8") as f:
        f.write("not-a-number\tInvented\tDrug\tRxNorm\tIngredient\tS\tNOT-A-CODE-9\t19700101\t20991231\t\n")
    with pytest.raises(OmopError, match="CONCEPT.*concept_id"):
        vocab_load.load_athena(db, d)
    bad = tmp_path / "nocol"
    bad.mkdir()
    (bad / "VOCABULARY.csv").write_text("vocabulary_id\tvocabulary_name\nRxNorm\tx\n", encoding="utf-8")
    (bad / "CONCEPT.csv").write_text("concept_id\tconcept_name\n1\tx\n", encoding="utf-8")
    with pytest.raises(OmopError, match="CONCEPT.*vocabulary_id"):
        vocab_load.load_athena(db, bad)


def test_a_missing_or_empty_register_refuses(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load
    from omop.schema import OmopError

    with pytest.raises(OmopError, match="no licence register"):
        vocab_load.load_athena(db, ATHENA, register=tmp_path / "absent.csv")
    empty = tmp_path / "empty.csv"
    empty.write_text(",".join(lr.COLUMNS) + "\n", encoding="utf-8")
    with pytest.raises(OmopError, match="names a loadable vocabulary"):
        vocab_load.load_athena(db, ATHENA, register=empty)
    assert vocab_load.athena_loaded(db) == {}


def test_the_never_column_keeps_what_review_22_classes_c() -> None:
    from omop import vocab_load

    reg = vocab_load.athena_register()
    assert {v for v, c in reg.items() if not c.loadable} >= NEVER_22
    assert reg["SNOMED"].aliases and "http://snomed.info/sct" in reg["SNOMED"].aliases


# ------------------------------------------------------------------------------------------------ second review
def _register(tmp_path: Path, *rows: dict[str, str]) -> Path:
    reg = tmp_path / "register.csv"
    base = {c: "x" for c in lr.COLUMNS}
    lines = [",".join(lr.COLUMNS)]
    for r in rows:
        full = {**base, "athena": "", "athena_never": "", "class": "", "paths": "", "text_sha256": "", **r}
        lines.append(",".join(full[c] for c in lr.COLUMNS))
    reg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return reg


def test_never_wins_over_case_spaces_aliases_and_look_alike_letters(tmp_path: Path) -> None:
    from omop import vocab_load

    reg = _register(
        tmp_path,
        {"id": "r1", "status": "cleared", "athena": "SNOMED;SNOMED CT;ＣＰＴ４;Gender", "class": "a"},
        {"id": "r2", "status": "removed", "athena_never": "snomed|SNOMED CT;CPT4", "class": "c"},
    )
    got = vocab_load.athena_register(reg)
    assert {v for v, c in got.items() if c.loadable} == {"Gender"}
    for name in ("SNOMED", "SNOMED CT", "ＣＰＴ４"):
        assert not got[name].loadable, name
    reasons = {}
    tables = {"VOCABULARY": [], "CONCEPT": [
        {"concept_id": "4000001", "vocabulary_id": "SNОMED"},  # a Cyrillic O
        {"concept_id": "4000002", "vocabulary_id": "Ｓｎｏｍｅｄ"},  # full-width
    ]}  # fmt: skip
    sel = vocab_load.select_athena(tables, frozenset({"Gender"}), got)
    reasons = sel.skipped
    assert all(r.startswith("licence class must not ship") for r in reasons.values()), reasons


def test_the_register_check_sees_folded_names_twice() -> None:
    raw = {c: "x" for c in lr.COLUMNS}
    a = lr.Row("ra", "code-system", "cleared", "s", "x", ("SNOMED CT",), (), raw, "a", ())
    b = lr.Row("rb", "code-system", "removed", "s", "x", (), (), {**raw, "athena_never": "SNOMED|SNOMED CT"}, "c",
               ("SNOMED",))  # fmt: skip
    c = lr.Row("rc", "code-system", "cleared", "s", "x", ("snomed",), (), raw, "a", ())
    got = lr.row_problems([a, b, c])
    assert any("'SNOMED CT'" in p and "ra" in p and "rb" in p for p in got), got
    assert any("'snomed'" in p and "rb" in p and "rc" in p for p in got), got


def test_a_clean_load_removes_what_an_earlier_load_left_of_a_never_vocabulary(db: Any) -> None:  # noqa: F811
    from omop import vocab_load

    with db.transaction() as tx:  # as if an older loader had let CPT4 in; the new download has none
        tx.execute("INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, "
                   "vocabulary_concept_id) VALUES ('CPT4', 'invented', 'invented', 'v0', 0)")  # fmt: skip
        tx.execute("INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
                   "standard_concept, concept_code, valid_start_date, valid_end_date) VALUES (4000005, 'Invented', "
                   "'Procedure', 'CPT4', 'CPT4', NULL, 'NOT-A-CODE-5', '1970-01-01', '2099-12-31')")  # fmt: skip
    res = vocab_load.load_athena(db, ATHENA, by="test")
    assert db.fetchval("SELECT count(*) FROM concept WHERE vocabulary_id = 'CPT4'") == 0
    assert res.as_dict()["athena"]["removed_from_the_box"] == {"CPT4": 1}
    assert res.as_dict()["athena"]["skipped"] == []


def test_an_explicit_allow_never_lets_a_never_vocabulary_in(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load

    allow = vocab_load.ATHENA_ALLOW | {"CPT4", "snomed"}
    res = vocab_load.load_athena(db, _download(tmp_path, "CPT4", "SNOMED"), allow=allow, by="test")
    assert db.fetchval("SELECT count(*) FROM concept WHERE concept_id IN (4000001, 4000005)") == 0
    reasons = {s["vocabulary"]: s["reason"] for s in res.as_dict()["athena"]["skipped"]}
    assert set(reasons) == {"CPT4", "SNOMED"} and all(
        r.startswith("licence class must not ship") for r in reasons.values()
    )


def test_a_concept_file_that_is_not_utf8_is_refused_with_its_name(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import vocab_load
    from omop.schema import OmopError

    d = _download(tmp_path)
    with (d / "CONCEPT.csv").open("ab") as f:
        f.write(b"4000009\t\xff\xfe invented\tDrug\tRxNorm\tIngredient\tS\tNOT-A-CODE-9\t19700101\t20991231\t\n")
    with pytest.raises(OmopError, match=r"CONCEPT\.csv.*not UTF-8"):
        vocab_load.load_athena(db, d)


# every athena_never id of the register: taking ANY one out, or adding one, fails here (a licence matter)
NEVER_ALL = frozenset({
    "SNOMED", "SNOMED Veterinary", "Nebraska Lexicon", "ICD10", "CPT4", "HemOnc", "ICDO3", "SMQ", "EORTC QLQ",
    "GCN_SEQNO", "Multum", "SUS", "MMI", "JMDC", "Read", "OXMIS", "NUCC", "OncoKB", "JAX", "EphMRA ATC", "NFC",
    "CIM10", "ICD10GM", "ICD10CN", "KCD7", "ICD9ProcCN", "CMS Place of Service", "UB04 Typ bill",
    "UB04 Point of Origin", "UB04 Pt dis status", "UB04 Pri Typ of Adm", "Revenue Code",
})  # fmt: skip


def test_every_never_entry_of_the_register_is_pinned() -> None:
    from omop import vocab_load

    assert {v for v, c in vocab_load.athena_register().items() if not c.loadable} == NEVER_ALL
    assert {v for r in lr.load() for v in r.never} == NEVER_ALL
