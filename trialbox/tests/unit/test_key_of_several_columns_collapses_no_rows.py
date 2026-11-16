"""CGRD-A1 (D-812): a table whose key column repeats keys its rows by several columns, and a row with no key is
refused, never merged into another.

Some exports give a diagnosis or a procedure row the visit's number as its own: every diagnosis of one visit then
had the same key, the same record id, and one survived. A site keys such a table by the columns that are unique
together, with the table's ``join`` (D-809) written over the key column the base mapping's id reads
(``join: {diag_no: [enc_no, diag_seq]}``). A row that lacks a part has an empty key; an empty key gave every such row
one id, so they collapsed too. A record id from an empty key is now refused: the row is rejected and counted, as the
night counts a row it cannot read. Synthetic rows only."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"


def _site(tmp_path: Path) -> Path:
    doc: dict[str, Any] = {
        "version": 1, "name": "keyed_site", "extends": str(BASE), "tz": "Asia/Taipei",
        "tables": {"patient": {"source": "patient", "key": "mrn"},
                   "diagnosis": {"source": "diagnosis", "key": "diag_no",
                                 "join": {"diag_no": ["enc_no", "diag_seq"]}}},
    }  # fmt: skip
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _diag(visit: str, seq: str, code: str) -> dict[str, str]:
    # the source's own diagnosis number is the visit's: it repeats within a visit
    return {"diag_no": visit, "enc_no": visit, "diag_seq": seq, "mrn": "10000001", "icd10": code,
            "diag_date": "2026-01-13", "recorded_date": "2026-01-13", "status": "A"}  # fmt: skip


def _ids(m: Mapping, rows: list[dict[str, str]]) -> list[str]:
    mp = Mapper(m, b"k" * 32, "s")
    return [str(r["id"]) for row in rows for r in mp.map_table("diagnosis", iter([m.normalize("diagnosis", row)]))
            if r["resourceType"] == "Condition"]  # fmt: skip


def test_each_diagnosis_of_one_visit_is_its_own_record(tmp_path: Path) -> None:
    m = Mapping.load(_site(tmp_path))
    ids = _ids(m, [_diag("V1", "1", "M10.9"), _diag("V1", "2", "E11.9"), _diag("V2", "1", "M10.9")])
    assert len(set(ids)) == 3


@pytest.mark.parametrize("seq", ["", "  "])
def test_a_row_without_a_part_of_its_key_is_refused_not_merged(tmp_path: Path, seq: str) -> None:
    m = Mapping.load(_site(tmp_path))
    mp = Mapper(m, b"k" * 32, "s")
    with pytest.raises(MappingError, match="no key"):
        list(mp.map_table("diagnosis", iter([m.normalize("diagnosis", _diag("V1", seq, "M10.9"))])))


def test_a_base_mapping_row_with_an_empty_key_is_refused_too(tmp_path: Path) -> None:
    """Before: two diagnosis rows with an empty number were one record."""
    m = Mapping.load(BASE)
    mp = Mapper(m, b"k" * 32, "s")
    row = {**_diag("", "1", "M10.9"), "diag_no": ""}
    with pytest.raises(MappingError, match="no key"):
        list(mp.map_table("diagnosis", iter([row])))


def test_the_night_keeps_every_diagnosis_and_counts_the_row_without_a_key(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.mapping_path = _site(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    rows = [_diag("V1", str(n), "M10.9") for n in range(1, 200)] + [_diag("V1", "", "E11.9")]
    with (feed / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (feed / "patient.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mrn", "name", "id_no", "birth_date", "sex", "death_date"])
        w.writeheader()
        w.writerow({"mrn": "10000001", "name": "a", "id_no": "b", "birth_date": "1960-01-01", "sex": "F",
                    "death_date": ""})  # fmt: skip
    run_ingest(cfg, "csv", str(feed), snapshot="2026-01-14", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-01-14")
    assert len(list(read_type(folder, "Condition"))) == 199
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert sum(comp["tables"]["diagnosis"]["rejected"].values()) == 1
