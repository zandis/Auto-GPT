"""CGRD-A2 (D-813): medication and procedures from one table of order lines; the NHIA list's ATC beside the
hospital's; a class-level ATC written as a class only.

* ``tables.<t>.rows: {column, in | not_in}``: a site whose drug orders and procedure orders are lines of one table
  (told apart by an order kind) maps the same source as two tables, each keeping its own rows. A row of the other
  kind is counted as left to the other table, never as lost.
* ``beside: <hospital ATC column>`` (refines D-689): the mapped ATC is written beside the hospital's own, not only when
  that is empty. Where the two disagree at level 5 (neither code begins the other), the row's ATC is unknown: both
  codings move to ``urn:trialbox:atc-disputed``, which no ATC reader reads, and the row is counted. Never the one that
  happens to match.
* ``class_target: atc4`` (refines D-689): a map answer that is a level-4 class is written under
  ``urn:trialbox:atc-class``, not the ATC system: a level-5 criterion still reads the row as unknown (it has no ATC);
  a level-4 criterion may read the class.

Synthetic NHI-shaped codes; ATC codes are public WHO codes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError

from tests.unit.test_nhi_drug_to_atc_at_night import ATC, BASE, NHI_LIST, _rx

DISPUTED, CLASS = "urn:trialbox:atc-disputed", "urn:trialbox:atc-class"
MAP = {
    "AC00011100": [("C10AA05", "wider")],
    "AC00055500": [("C10AA", "wider")],  # a level-4 class
}


def _ask(system: str, code: str) -> list[dict[str, Any]]:
    if system != NHI_LIST:
        return []
    return [{"source_system": NHI_LIST, "source_code": code, "target_system": ATC, "target_code": t, "relation": rel,
             "extra": {}} for t, rel in MAP.get(code, [])]  # fmt: skip


def _mapping(tmp_path: Path, element: dict[str, Any] | None = None, rows: Any = None) -> Mapping:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    for spec in (doc.get("lookups") or {}).values():
        spec["file"] = str(BASE.parent / spec["file"])
    med = next(r for r in doc["resources"] if r["type"] == "MedicationRequest")
    spec = med["elements"]["medicationCodeableConcept.coding[2]"]
    if element is not None:
        spec.pop("when", None)
        spec.update(element)
    if rows is not None:
        doc["tables"]["medication"]["rows"] = rows
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return Mapping.load(path)


def _codings(m: Mapping, row: dict[str, str]) -> tuple[Mapper, list[tuple[str, str]]]:
    mp = Mapper(m, b"k" * 32, "s", concept_map=_ask)
    (res,) = mp.map_table("medication", iter([m.normalize("medication", row)]))
    return mp, [(c["system"], c["code"]) for c in res["medicationCodeableConcept"]["coding"] if "atc" in c["system"]]


@pytest.mark.parametrize(("hospital", "want"), [
    ("", [(ATC, "C10AA05")]),                          # no hospital ATC: the map's
    ("C10AA05", [(ATC, "C10AA05"), (ATC, "C10AA05")]),  # the same: both, as recorded and as mapped
    ("C10AA", [(ATC, "C10AA"), (ATC, "C10AA05")]),      # the hospital's class, the map's drug in it: agree
    ("L04AX03", [(DISPUTED, "L04AX03"), (DISPUTED, "C10AA05")]),  # disagree: unknown, both moved, counted
])  # fmt: skip
def test_the_mapped_atc_is_written_beside_the_hospitals_and_a_disagreement_is_unknown(
    tmp_path: Path, hospital: str, want: list[tuple[str, str]]
) -> None:
    m = _mapping(tmp_path, {"beside": "atc"})
    mp, got = _codings(m, _rx("AC00011100", hospital))
    assert got == want
    assert mp.atc_disputed() == ({"medication": 1} if want[0][0] == DISPUTED else {})


def test_a_level_4_answer_is_written_as_a_class_only(tmp_path: Path) -> None:
    m = _mapping(tmp_path, {"beside": "atc", "class_target": "atc4"})
    _, got = _codings(m, _rx("AC00055500"))
    assert got == [(CLASS, "C10AA")]


def test_without_class_target_a_level_4_answer_is_still_not_written(tmp_path: Path) -> None:
    m = _mapping(tmp_path, {"beside": "atc"})
    mp, got = _codings(m, _rx("AC00055500"))
    assert got == [] and mp.unmapped


@pytest.mark.parametrize("element", [{"beside": "drug_name"}, {"class_target": "atc3", "beside": "atc"}])
def test_beside_and_class_target_stated_badly_are_refused_at_load(tmp_path: Path, element: dict[str, Any]) -> None:
    with pytest.raises(MappingError):
        _mapping(tmp_path, element)


def test_one_table_of_order_lines_feeds_medication_with_its_own_rows(tmp_path: Path) -> None:
    m = _mapping(tmp_path, rows={"column": "order_kind", "in": ["51"]})
    assert m.keeps("medication", m.normalize("medication", _rx("AC00011100", order_kind="51")))
    assert not m.keeps("medication", m.normalize("medication", _rx("AC00011100", order_kind="7")))
    assert not m.keeps("medication", m.normalize("medication", _rx("AC00011100")))  # no kind: not a drug line
    (tmp_path / "p").mkdir()
    m2 = _mapping(tmp_path / "p", rows={"column": "order_kind", "not_in": ["51"]})
    assert m2.keeps("medication", m2.normalize("medication", _rx("AC00011100", order_kind="7")))


@pytest.mark.parametrize("rows", [{"column": "order_kind"}, {"in": ["51"]}, {"column": "k", "in": "51"}])
def test_a_row_filter_stated_badly_is_refused_at_load(tmp_path: Path, rows: Any) -> None:
    with pytest.raises(MappingError):
        _mapping(tmp_path, rows=rows)


def test_the_night_maps_each_table_from_its_own_lines_and_reports_the_counts(tmp_path: Path) -> None:
    import csv
    import json

    from adapter.ndjson import read_type, snapshot_dir
    from adapter.pipeline import run_ingest

    from tests.unit.test_dataflow_lake_p0 import _cfg

    site = {"version": 1, "name": "lines", "extends": str(BASE), "tz": "Asia/Taipei",
            "tables": {"medication": {"source": "order_lines", "key": "rx_no",
                                      "rows": {"column": "order_kind", "in": ["51"]}}}}  # fmt: skip
    (tmp_path / "site.yaml").write_text(yaml.safe_dump(site, sort_keys=False), encoding="utf-8")
    cfg = _cfg(tmp_path)
    cfg.mapping_path = tmp_path / "site.yaml"
    feed = tmp_path / "feed"
    feed.mkdir()
    rows = [{**_rx("AC00011100", rx_no=f"M{n}"), "order_kind": "51" if n < 3 else "7"} for n in range(5)]
    with (feed / "order_lines.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    run_ingest(cfg, "csv", str(feed), snapshot="2026-08-02", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-08-02")
    assert len(list(read_type(folder, "MedicationRequest"))) == 3
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["medication"]["rows_of_other_tables"] == 2
