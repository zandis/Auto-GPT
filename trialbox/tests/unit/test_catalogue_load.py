"""T-107 (WS-04.1, D-353): the catalogue loaded as data.

The LOINC concepts are seeded here as a stand-in for the Athena bundle: the public LOINC codes of the catalogue with
made-up concept ids (1,800,000,001 and up) and a placeholder name; no licensed text.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any

import pytest
from tb_common import catalogue

from tests.unit.test_omop_core import db  # noqa: F401 - fixture used by name

SHIPPED = catalogue.CATALOGUE_DIR


def _seed_loinc(db: Any, skip: frozenset[str] = frozenset()) -> dict[str, int]:  # noqa: F811
    codes = sorted({it.loinc for it in catalogue.read() if it.loinc} - skip)
    ids = {c: 1_800_000_001 + n for n, c in enumerate(codes)}
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, "
            "vocabulary_concept_id) SELECT 'LOINC', 'LOINC', NULL, 'TEST', 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM vocabulary WHERE vocabulary_id = 'LOINC')"
        )
        tx.execute(
            "INSERT INTO concept_class (concept_class_id, concept_class_name, concept_class_concept_id) "
            "SELECT 'Lab Test', 'Lab Test', 0 WHERE NOT EXISTS (SELECT 1 FROM concept_class "
            "WHERE concept_class_id = 'Lab Test')"
        )
        for code, cid in ids.items():
            tx.execute(
                "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
                "standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason) "
                "VALUES (?, ?, 'Measurement', 'LOINC', 'Lab Test', 'S', ?, '1970-01-01', '2099-12-31', NULL)",
                (cid, f"test concept {code}", code),
            )
    return ids


def _copy(tmp_path: Path) -> Path:
    out = tmp_path / "catalogue"
    shutil.copytree(SHIPPED, out, ignore=shutil.ignore_patterns("evidence.json", "scores"))
    return out


def _edit(folder: Path, fn: Any) -> None:
    path = folder / "items.csv"
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols, rows = list(reader.fieldnames or []), list(reader)
    rows = fn(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------------------------------------ acceptance (1)
def test_every_item_resolves_to_a_concept_and_a_domain(db: Any) -> None:  # noqa: F811
    from omop import catalogue_load

    loinc = _seed_loinc(db)
    rep = catalogue_load.load(db)
    n = len(catalogue.read())
    assert n == 469
    assert rep.items == n and len(rep.resolved) == n and rep.unresolved == 0, rep.unmapped
    assert set(rep.domains) == set(rep.resolved)
    assert rep.local == 235 and rep.loinc == 234 and rep.added == 235
    it = {i.id: i for i in catalogue.read()}
    assert rep.resolved["vital.sbp"] == loinc["8480-6"]
    assert rep.resolved["lab.afb_smear"] == it["lab.afb_smear"].local_id == 2_000_001_004
    row = db.fetchone(
        "SELECT vocabulary_id, concept_class_id, standard_concept, concept_code, domain_id FROM concept "
        "WHERE concept_id = 2000001004"
    )
    assert tuple(row) == ("TB-SHARED", "TB Catalogue Item", None, "lab.afb_smear", it["lab.afb_smear"].domain)
    syn = {r[0] for r in db.fetchall("SELECT concept_synonym_name FROM concept_synonym WHERE concept_id = 2000001004")}
    assert {it["lab.afb_smear"].names["ja"], it["lab.afb_smear"].names["zh-TW"]} <= syn
    assert rep.as_dict()["concepts"] == n


def test_a_second_load_changes_nothing_and_ids_are_stable(db: Any) -> None:  # noqa: F811
    from omop import catalogue_load

    _seed_loinc(db)
    first = catalogue_load.load(db)
    count = db.fetchval("SELECT count(*) FROM concept")
    syn = db.fetchval("SELECT count(*) FROM concept_synonym")
    again = catalogue_load.load(db)
    assert first.new_release and not again.new_release and again.added == 0
    assert again.resolved == first.resolved
    assert db.fetchval("SELECT count(*) FROM concept") == count
    assert db.fetchval("SELECT count(*) FROM concept_synonym") == syn
    rel = db.fetchall("SELECT release_name, rows FROM tb_vocab_release WHERE release_name = 'CATALOGUE'")
    assert [tuple(r) for r in rel] == [("CATALOGUE", 469)]


def test_a_loinc_code_the_vocabulary_lacks_is_unmapped_not_invented(db: Any) -> None:  # noqa: F811
    from omop import catalogue_load

    _seed_loinc(db, skip=frozenset({"8480-6"}))
    rep = catalogue_load.load(db)
    assert rep.unresolved == 1 and rep.unmapped[0]["item"] == "vital.sbp" and rep.unmapped[0]["loinc"] == "8480-6"
    assert "vital.sbp" not in rep.resolved
    assert "vital.sbp" in rep.unmapped_by_specialty()["CARD"]
    assert db.fetchval("SELECT count(*) FROM concept WHERE concept_code = '8480-6'") == 0  # nothing minted for it


def test_without_the_vocabulary_every_loinc_item_is_listed_per_specialty(db: Any) -> None:  # noqa: F811
    from omop import catalogue_load

    rep = catalogue_load.load(db)
    assert rep.local == 235 and rep.unresolved == 234
    by = rep.unmapped_by_specialty()
    assert "RHEU" in by and all(by.values())


# ------------------------------------------------------------------------------------------------ id rules
def test_a_renumbering_attempt_is_refused_and_writes_nothing(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import catalogue_load

    catalogue_load.load(db)
    folder = _copy(tmp_path)

    def renumber(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        for r in rows:
            if r["id"] == "func.contrast_allergy":
                r["omop_concept_id"] = "2000001300"  # the last row: the file's own rules still hold
        return rows

    _edit(folder, renumber)
    count = db.fetchval("SELECT count(*) FROM concept")
    with pytest.raises(catalogue_load.CatalogueRefused) as exc:
        catalogue_load.load(db, folder)
    assert exc.value.code == "CAT-RENUMBER" and "func.contrast_allergy" in exc.value.problems[0]
    assert db.fetchval("SELECT count(*) FROM concept") == count


def test_an_id_that_holds_another_code_is_refused(db: Any, tmp_path: Path) -> None:  # noqa: F811
    from omop import catalogue_load

    catalogue_load.load(db)
    folder = _copy(tmp_path)

    def swap_code(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        for r in rows:
            if r["id"] == "lab.afb_smear":
                r["id"] = "lab.afb_smear_grade"
        return rows

    _edit(folder, swap_code)
    with pytest.raises(catalogue_load.CatalogueRefused) as exc:
        catalogue_load.load(db, folder)
    assert exc.value.code == "CAT-RENUMBER"


@pytest.mark.parametrize(
    ("item", "value", "words"),
    [
        ("lab.afb_smear", "2000001001", "retired"),  # anti-MDA5's retired id
        ("lab.afb_smear", "2000001256", "two items"),
        ("rheum.tjc68", "2000001003", "file order"),
        ("lab.afb_smear", "1999999999", "outside the catalogue band"),
        ("lab.afb_smear", "", "needs its concept id"),
    ],
)
def test_a_file_that_breaks_an_id_rule_is_refused_whole(tmp_path: Path, item: str, value: str, words: str) -> None:
    folder = _copy(tmp_path)

    def change(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        for r in rows:
            if r["id"] == item:
                r["omop_concept_id"] = value
        return rows

    _edit(folder, change)
    with pytest.raises(catalogue.CatalogueError) as exc:
        catalogue.read(folder)
    assert any(words in p for p in exc.value.problems), exc.value.problems


def test_the_shipped_catalogue_keeps_the_id_rules() -> None:
    assert catalogue.check(catalogue.read(), catalogue.retired_ids()) == []
    assert all(i.storable in catalogue.STORABLE for i in catalogue.read())


# ------------------------------------------------------------------------------------------------ acceptance (2)
class _Stub:
    def __init__(self, facts: list[dict[str, str]]) -> None:
        self.facts = facts
        self.variables: dict[str, Any] = {}

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        self.variables = variables
        return {"facts": self.facts}


CHART = "2026-10-01 外来\n認知機能検査: MMSE 24/30（見当識 3/5、遅延再生 1/3）。\nMMSE orientation 3/5. HbA1c 7.2 %.\n"


def test_an_item_answer_of_a_score_only_instrument_is_never_extracted() -> None:
    from sitesetup import charts

    planted = [
        {"domain": "observation", "term": "MMSE 見当識", "value": "3", "unit": "", "date": "2026-10-01",
         "quote": "見当識 3/5", "code": "", "system": ""},
        {"domain": "observation", "term": "MMSE orientation", "value": "3", "unit": "", "date": "2026-10-01",
         "quote": "MMSE orientation 3/5", "code": "", "system": ""},
        {"domain": "observation", "term": "HbA1c", "value": "7.2", "unit": "%", "date": "2026-10-01",
         "quote": "HbA1c 7.2 %", "code": "", "system": ""},
    ]  # fmt: skip
    kept, dropped = charts.extract(_Stub(planted), CHART, "ja")
    assert dropped == 2
    assert [f["term"] for f in kept] == ["HbA1c"]
    assert not any("MMSE" in f["term"] or "見当識" in f["quote"] for f in kept)


@pytest.mark.parametrize(
    ("term", "owner"),
    [
        ("MMSE orientation", "neuro.mmse_total"),
        ("MoCA visuospatial", "neuro.moca_total"),
        ("PANSS positive", "psy.panss"),
        ("ADAS-Cog word recall", "neuro.adas_cog"),
        ("MMSE", None),
        ("MMSE total", None),
        ("MMSE 24/30", None),
        ("MDS-UPDRS Part III", None),  # a stored score of its own
        ("CDR global", None),
        ("DAS28-ESR", None),
        ("HbA1c", None),
        ("", None),
    ],
)
def test_the_storable_gate(term: str, owner: str | None) -> None:
    got = catalogue.refused_fact(term)
    assert (got.id if got else None) == owner


def test_hints_block_is_generated_and_optional() -> None:
    block = catalogue.hints_block(["neuro.mmse_total", "vital.sbp"])
    lines = block.splitlines()
    assert len(lines) == 2 and lines[0].startswith("- vital.sbp: Systolic blood pressure.")
    assert "never list its item answers" in lines[1]
    assert catalogue.hints_block([]) == ""  # no hints: the prompt runs without the block
    assert len(catalogue.hints_block().splitlines()) == sum(1 for i in catalogue.read() if i.extraction_hint)


def test_the_command_line_reports_and_refuses(db_url: str, tmp_path: Path, capsys: Any) -> None:
    import json

    from omop import catalogue_load

    assert catalogue_load.main(["--db", db_url]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["items"] == 469 and out["local"] == 235
    folder = _copy(tmp_path)
    _edit(folder, lambda rows: [*rows, dict(rows[-1])])  # the last row twice
    assert catalogue_load.main(["--db", db_url, "--catalogue", str(folder)]) == 1
    assert json.loads(capsys.readouterr().out)["refused"] == "CAT-FILE"
