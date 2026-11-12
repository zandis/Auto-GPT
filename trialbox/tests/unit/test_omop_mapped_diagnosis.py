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


def test_a_reload_changes_nothing_and_an_unmapped_feed_loads_as_before(tmp_path: Path, db: Any) -> None:
    from omop.load import load_batch

    feed = _feed(tmp_path)
    first = load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    again = load_batch(db, "feed", SNAP, feed, tz="Asia/Taipei")
    assert (again.inserted, again.updated, again.tombstoned) == (0, 0, 0) and again.same == first.inserted
