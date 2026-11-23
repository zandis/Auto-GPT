"""V-18 with DB-C1 (D-1182): one install step loads the code systems of one manifest into the vocabulary and the FHIR
store, from the same rows; the doctor's check says when they differ from the terminology as it is now.

Synthetic data only: the ATC index here is three invented rows in the shape of the site's own export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_fhir_codesystems import MemoryStore
from tools import fhir_codesystems as fc
from tools import terminology_load as tl

SYN_ATC = "ATC code,ATC level name\nV99SY01,synthetic drug one\nV99SY02,synthetic drug two\nV99SY,synthetic group\n"
PERSON = "Synthetic Person"


@pytest.fixture
def term_dir(tmp_path: Path) -> Path:
    from criteria_compiler.terminology import installed as inst

    src = tmp_path / "atc_index.csv"
    src.write_text(SYN_ATC, encoding="utf-8")
    where = tmp_path / "terminology"
    inst.install_atc(src, where, accepted_by=PERSON, accepted_on="2026-11-23", version="2099")
    return where


@pytest.fixture
def omop(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    from omop import schema

    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    monkeypatch.delenv("TB_OMOP_DB_URL", raising=False)
    db = schema.connect(db_url)
    yield db
    db.close()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    mem = MemoryStore()
    monkeypatch.setattr(fc, "Store", lambda base: mem)
    keep = ("atc", "department", "icd10pcs")  # a site's licensed copy, a shipped table, a system nobody loaded
    monkeypatch.setattr(fc, "SOURCES", tuple(s for s in fc.SOURCES if s.key in keep))
    return mem


def test_the_release_is_one_digest_of_what_ships_and_what_was_loaded(term_dir: Path, tmp_path: Path) -> None:
    man = tl.manifest(term_dir)
    assert man["release"].startswith("TL-") and len(man["release"]) == 15
    assert set(man["loaded"]) == {"atc_index"} and len(man["loaded"]["atc_index"]["sha256"]) == 64
    assert tl.manifest(term_dir)["release"] == man["release"]
    assert tl.manifest(tmp_path / "empty")["release"] != man["release"]  # nothing loaded: another release


def test_one_run_feeds_the_vocabulary_and_the_fhir_store_from_the_same_rows(
    term_dir: Path, omop: Any, store: MemoryStore
) -> None:
    report = tl.run(term_dir, "http://fhir.invalid/fhir", omop, wait=0)
    assert report["problems"] == []
    tables = {r["table"]: r for r in report["omop"]}
    assert tables["atc_index"]["system"] == fc.ATC and tables["atc_index"]["concepts"] == 3
    assert tables["shipped"]["concepts"] > 0
    states = {r["key"]: r["state"] for r in report["fhir"]}
    assert states == {"atc": "loaded", "department": "loaded", "icd10pcs": "skipped"}
    cs = store.get("CodeSystem", "tb-atc")
    assert cs is not None and "atc_index, loaded at install" in cs["description"]
    in_store = {c["code"] for c in cs["concept"]}
    in_vocab = {r[0] for r in omop.fetchall("SELECT concept_code FROM concept WHERE vocabulary_id = 'ATC'")}
    assert in_store == {"V99SY01", "V99SY02", "V99SY"} and in_store <= in_vocab


def test_the_check_says_when_the_readers_hold_another_release(term_dir: Path, omop: Any, store: MemoryStore) -> None:
    report = tl.run(term_dir, "http://fhir.invalid/fhir", omop, wait=0)
    assert tl.check(report, term_dir) == []
    assert tl.check(None, term_dir) == [
        "the code systems were never loaded into the vocabulary and the FHIR store: run the load step"
    ]
    stale = {**report, "release": "TL-000000000000"}
    (problem,) = tl.check(stale, term_dir)
    assert "TL-000000000000" in problem and "run the load step again" in problem
    broken = {**report, "problems": ["omop: the vocabulary database could not be opened"]}
    assert tl.check(broken, term_dir) == ["omop: omop: the vocabulary database could not be opened"]


def test_the_command_reports_and_lists_each_system_not_loaded(
    term_dir: Path, store: MemoryStore, db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    monkeypatch.delenv("TB_OMOP_DB_URL", raising=False)
    out = tmp_path / "report.json"
    rc = tl.main(["load", "--terminology", str(term_dir), "--fhir", "http://fhir.invalid/fhir", "--deploy",
                  str(tmp_path), "--report", str(out), "--wait", "0"])  # fmt: skip
    report = json.loads(out.read_text("utf-8"))
    stops = [json.loads(x) for x in (tmp_path / "site/poc-stops.jsonl").read_text("utf-8").splitlines()]
    assert rc == 0 and report["release"] == tl.manifest(term_dir)["release"]
    assert [s["key"] for s in stops] == ["terminology_load/fhir/icd10pcs"]
    assert tl.main(["check", "--report", str(out), "--terminology", str(term_dir)]) == 0
    assert tl.main(["check", "--report", str(tmp_path / "missing.json"), "--terminology", str(term_dir)]) == 1


def test_the_doctor_fails_when_the_terminology_changed_after_the_load(
    term_dir: Path, omop: Any, store: MemoryStore, tmp_path: Path
) -> None:
    from criteria_compiler.terminology import installed as inst

    from tools.trialbox import doctor

    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    report = tl.run(term_dir, "http://fhir.invalid/fhir", omop, wait=0)
    (deploy / "site" / tl.REPORT).write_text(json.dumps(report), encoding="utf-8")
    inp = doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(term_dir)}, deploy=deploy)
    ok = doctor.check_terminology(inp)
    assert ok.status == "PASS" and f"vocabulary and FHIR store: release {report['release']}" in ok.detail
    assert "atc 2099+" in ok.detail and "not loaded: icd10pcs" in ok.detail
    newer = tmp_path / "atc_2100.csv"
    newer.write_text(SYN_ATC + "V99SY03,synthetic drug three\n", encoding="utf-8")
    inst.install_atc(newer, term_dir, accepted_by=PERSON, accepted_on="2026-11-23", version="2100")
    stale = doctor.check_terminology(inp)
    assert stale.status == "FAIL" and "run the load step again" in stale.detail
    gone = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(tmp_path / "nowhere")},
                                                        deploy=deploy))  # fmt: skip
    assert gone.status == "WARN" and "cannot be read here" in gone.detail


def test_the_mapping_check_reports_a_code_missing_from_a_loaded_system(term_dir: Path, tmp_path: Path) -> None:
    from tools import mapping_coverage as mc

    rows = [{"system": "atc", "local_code": code, "local_name": name} for code, name in
            (("V99SY01", "in the loaded index"), ("M04AA01", "the right shape, not in the loaded index"))]  # fmt: skip
    loaded = mc.Reference.load(terminology=term_dir)
    assert loaded.loaded["atc"] == {"V99SY01", "V99SY02", "V99SY"}
    got = {r.local_code: r.reason for r in (mc.check_code(x, loaded) for x in rows)}
    assert got == {"V99SY01": "", "M04AA01": "not in the loaded atc table (atc_index)"}
    none = mc.Reference.load(terminology=tmp_path / "nothing-loaded")  # nothing loaded: the shape decides, as before
    assert none.loaded == {} and all(mc.check_code(x, none).mapped for x in rows)
