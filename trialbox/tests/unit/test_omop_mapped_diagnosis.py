"""D-597: in OMOP a mapped ICD-9-CM diagnosis (D-593) keeps the hospital's code as its source value; the standard
concept is found through the mapped code; the lake reads the mapped code from both sources. Synthetic rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
I9, I10 = "http://hl7.org/fhir/sid/icd-9-cm", "http://hl7.org/fhir/sid/icd-10-cm"
SNAP = "2026-10-04"


def _ask(system: str, code: str) -> list[dict[str, Any]]:
    exact = {"585.3": "N18.3", "042": "B20"}
    return [{"target_system": I10, "target_code": exact[code], "relation": "equivalent"}] if code in exact else []


def _feed(tmp_path: Path) -> dict[str, list[dict[str, Any]]]:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    doc["params"] = {"icd9cm_before": "2016-01-01"}
    for name, spec in (doc.get("lookups") or {}).items():
        spec["file"] = str(BASE.parent / spec["file"])
        doc["lookups"][name] = spec
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    m = Mapping.load(path)
    mapper = Mapper(m, b"k" * 32, "s", concept_map=_ask)
    patient = {"mrn": "10000001", "name": "x", "id_no": "y", "birth_date": "1960-03-02", "sex": "M"}

    def diag(no: str, code: str, day: str) -> dict[str, str]:
        return {"diag_no": no, "enc_no": "", "mrn": "10000001", "icd10": code, "diag_date": day,
                "recorded_date": day, "status": "A"}  # fmt: skip

    rows = [diag("D1", "585.3", "2014-03-02"), diag("D2", "714.0", "2014-03-02"), diag("D3", "M05.79", "2019-03-02")]
    out: dict[str, list[dict[str, Any]]] = {}
    for table, feed in (("patient", [patient]), ("diagnosis", rows)):
        for res in mapper.map_table(table, iter(feed)):
            out.setdefault(str(res["resourceType"]), []).append(dict(res))
    return out


@pytest.fixture
def db(db_url: str) -> Any:
    from omop import schema

    d = schema.connect(db_url)
    yield d
    d.close()


def _conditions(db: Any) -> dict[str, dict[str, Any]]:
    rows = db.fetchdicts(
        "SELECT c.condition_source_value AS value, c.condition_source_concept_id AS source, "
        "c.condition_concept_id AS concept FROM condition_occurrence c"
    )
    return {str(r["value"]): r for r in rows}


def test_the_source_value_is_the_hospitals_code_and_the_lake_reads_the_mapped_one(tmp_path: Path, db: Any) -> None:
    from lake.source import lake_rows
    from omop.export import export_rows
    from omop.load import load_batch

    feed = _feed(tmp_path)
    codings = [[(c["system"], c["code"]) for c in r["code"]["coding"]] for r in feed["Condition"]]
    assert [(I10, "N18.3"), (I9, "585.3")] in codings and [(I9, "714.0")] in codings  # the premise: D-593
    load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    got = _conditions(db)
    assert set(got) == {"585.3", "714.0", "M05.79"}  # what the hospital recorded, never the mapped code
    assert got["585.3"]["source"] and got["585.3"]["source"] != got["714.0"]["source"]
    lake = {r["code"]: r["system"] for r in export_rows(db)["condition"]}
    assert lake == {"N18.3": I10, "714.0": I9, "M05.79": I10}  # a criterion over the lake sees what D-593 decided
    legacy = lake_rows(feed, {}, tz="Asia/Taipei", snapshot=SNAP, source="legacy")
    assert export_rows(db)["condition"] == legacy["condition"]  # the two lake sources, row for row


def test_the_standard_concept_is_the_one_the_mapped_code_has(tmp_path: Path, db: Any) -> None:
    """A diagnosis recorded as N18.3 and one mapped to N18.3 stand for one concept (whatever the vocabulary loaded
    here gives it, 0 included)."""
    from omop.load import load_batch

    feed = _feed(tmp_path)
    direct = dict(next(r for r in feed["Condition"] if r["code"]["coding"][0]["code"] == "M05.79"))
    direct = {**direct, "id": "direct-n183", "code": {"coding": [{"system": I10, "code": "N18.3"}]}}
    feed["Condition"].append(direct)
    load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    got = _conditions(db)
    assert got["585.3"]["concept"] == got["N18.3"]["concept"]
    assert got["585.3"]["source"] != got["N18.3"]["source"]  # two source codes


def test_a_reload_changes_nothing(tmp_path: Path, db: Any) -> None:
    from omop.load import load_batch

    feed = _feed(tmp_path)
    first = load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    again = load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    assert (again.inserted, again.updated, again.tombstoned) == (0, 0, 0) and again.same == first.inserted


def _cond(feed: dict[str, list[dict[str, Any]]], rid: str, codings: list[dict[str, Any]]) -> dict[str, Any]:
    base = next(r for r in feed["Condition"] if r["code"]["coding"][0]["code"] == "M05.79")
    return {**base, "id": rid, "code": {"coding": codings}}


def test_a_mapped_code_of_the_observation_domain_is_routed_as_a_recorded_one_is(tmp_path: Path, db: Any) -> None:
    """The review's finding: the domain was looked up by the ICD-9-CM source code, which the vocabulary does not
    know, so a V code mapped to a Z code stayed in CONDITION_OCCURRENCE while a recorded Z code moved."""
    from omop.load import load_batch

    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
            "concept_code, valid_start_date, valid_end_date) VALUES (45500001, 'history of smoking', 'Observation', "
            "'ICD10CM', '4-char billing code', 'Z87.891', '1970-01-01', '2099-12-31')"
        )
    feed = _feed(tmp_path)
    feed["Condition"] = [
        _cond(feed, "direct", [{"system": I10, "code": "Z87.891"}]),
        _cond(feed, "mapped", [{"system": I10, "code": "Z87.891", "userSelected": False},
                               {"system": I9, "code": "V15.82"}]),
    ]  # fmt: skip
    rep = load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    assert rep.skipped.get("routed:condition_occurrence:observation") == 2
    values = sorted(str(r[0]) for r in db.fetchall("SELECT observation_source_value FROM observation"))
    assert "V15.82" in values and "Z87.891" in values  # each keeps what its hospital recorded


@pytest.mark.parametrize(("codings", "value"), [
    # a first coding flagged for the source's own reasons, not a D-593 pair: exactly as before
    ([{"system": "http://snomed.info/sct", "code": "44054006", "userSelected": False}, {"system": I10, "code": "E11.9"}],
     "44054006"),
    ([{"system": I10, "code": "N18.3", "userSelected": False}], "N18.3"),                      # nothing else there
    ([{"system": I9, "code": "585.3"}, {"system": I10, "code": "N18.3", "userSelected": False}], "585.3"),
    ([{"system": I10, "code": "N18.3", "userSelected": "false"}, {"system": I9, "code": "585.3"}], "N18.3"),
    ([{"system": I10, "code": "N18.3", "userSelected": False}, {"system": I9, "code": "5" * 60}], "N18.3"),  # too long
    ([{"system": I10, "code": "N18.3", "userSelected": False}, {"system": I9, "code": "585.3"}], "585.3"),   # the pair
])  # fmt: skip
def test_only_the_pair_the_map_makes_changes_the_source_value(
    tmp_path: Path, db: Any, codings: list[dict[str, Any]], value: str
) -> None:
    from omop.load import load_batch

    feed = _feed(tmp_path)
    feed["Condition"] = [_cond(feed, "one", codings)]
    load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    assert set(_conditions(db)) == {value}
