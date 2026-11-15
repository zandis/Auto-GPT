"""CGRD-A8 (D-846): a table of vitals written one item per row is turned into one row per patient and time.

An inpatient vitals table may hold one row per measurement (an item code and a value) rather than one row per visit
with a column for each. ``tables.<t>.pivot: {keys, item, value, columns}`` turns the rows of one patient at one exact
time into one wide row, with each known item code in its canonical column (``height_cm``, ``weight_kg``, ``sbp``,
``dbp``): the base mapping's vital observations read it as they read a wide table. Pairing never crosses times. Two
different values of one item at one time leave that item empty and are counted; an item code the site did not list
is counted; neither is guessed. A systolic or diastolic pressure with no partner at that time is an observation of
its own, never a panel with one half. The table is read whole on a delta night (a pair split across nights would
otherwise be read as two halves). Synthetic rows only."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError, pivot_rows
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
PIVOT = {"keys": ["mrn", "measure_datetime"], "item": "item_code", "value": "item_value",
         "columns": {"BH": "height_cm", "BW": "weight_kg", "SBP": "sbp", "DBP": "dbp"}}  # fmt: skip


def _site(tmp_path: Path, pivot: Any = None) -> Path:
    doc = {"version": 1, "name": "long_vitals", "extends": str(BASE), "tz": "Asia/Taipei",
           "tables": {"patient": {"source": "patient", "key": "mrn"},
                      "vital": {"source": "vital_items", "key": "vital_no", "pivot": pivot or PIVOT}}}  # fmt: skip
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _item(mrn: str, when: str, code: str, value: str) -> dict[str, str]:
    return {"mrn": mrn, "measure_datetime": when, "item_code": code, "item_value": value}


def _pivot(rows: list[dict[str, str]], tmp_path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    got = list(pivot_rows(iter(rows), PIVOT, "vital_no", tmp_path / "work", counts))
    return got, counts


def test_the_rows_of_one_patient_at_one_time_become_one_wide_row(tmp_path: Path) -> None:
    rows = [_item("P1", "2026-01-13 08:00", "SBP", "128"), _item("P1", "2026-01-13 08:00", "DBP", "82"),
            _item("P1", "2026-01-13 08:00", "BW", "70.5"), _item("P1", "2026-01-13 20:00", "SBP", "135")]  # fmt: skip
    got, counts = _pivot(rows, tmp_path)
    by_time = {r["measure_datetime"]: r for r in got}
    assert (by_time["2026-01-13 08:00"]["sbp"], by_time["2026-01-13 08:00"]["dbp"]) == ("128", "82")
    assert by_time["2026-01-13 08:00"]["weight_kg"] == "70.5"
    assert by_time["2026-01-13 20:00"]["sbp"] == "135" and by_time["2026-01-13 20:00"]["dbp"] == ""  # never crossed
    assert len({r["vital_no"] for r in got}) == 2 and counts == {}


def test_two_values_of_one_item_at_one_time_are_left_empty_and_counted(tmp_path: Path) -> None:
    rows = [_item("P1", "T1", "SBP", "128"), _item("P1", "T1", "SBP", "140"), _item("P1", "T1", "DBP", "82"),
            _item("P1", "T1", "DBP", "82"), _item("P1", "T1", "XYZ", "1")]  # fmt: skip
    (row,), counts = _pivot(rows, tmp_path)
    assert row["sbp"] == "" and row["dbp"] == "82"  # the same value twice is one value
    assert counts == {"values_that_disagree": 1, "items_not_listed": 1}


def test_an_unpaired_pressure_is_an_observation_of_its_own(tmp_path: Path) -> None:
    m = Mapping.load(_site(tmp_path))
    mp = Mapper(m, b"k" * 32, "s")
    wide = {"vital_no": "P1|T1", "mrn": "P1", "measure_datetime": "2026-01-13 08:00:00", "sbp": "135", "dbp": "",
            "height_cm": "", "weight_kg": ""}  # fmt: skip
    obs = list(mp.map_table("vital", iter([wide])))
    assert [o["code"]["coding"][0]["code"] for o in obs] == ["8480-6"]  # systolic alone, not a half panel
    assert obs[0]["valueQuantity"]["value"] == 135
    both = list(mp.map_table("vital", iter([{**wide, "dbp": "82"}])))
    assert [o["code"]["coding"][0]["code"] for o in both] == ["85354-9"]


@pytest.mark.parametrize("bad", [{"keys": []}, {"item": ""}, {"columns": {}}, {"columns": {"SBP": ""}}])
def test_a_pivot_stated_badly_is_refused_at_load(tmp_path: Path, bad: dict[str, Any]) -> None:
    with pytest.raises(MappingError):
        Mapping.load(_site(tmp_path, {**PIVOT, **bad}))


def test_the_night_pivots_the_table_and_reads_it_whole_on_a_delta_night(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.mapping_path = _site(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    with (feed / "patient.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mrn", "name", "id_no", "birth_date", "sex", "death_date"])
        w.writeheader()
        w.writerow({"mrn": "10000001", "name": "a", "id_no": "b", "birth_date": "1960-01-01", "sex": "F",
                    "death_date": ""})  # fmt: skip
    cols = ["mrn", "measure_datetime", "item_code", "item_value", "updated_at"]
    with (feed / "vital_items.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerow({**_item("10000001", "2026-01-13 08:00:00", "SBP", "128"), "updated_at": "2026-01-13"})
        w.writerow({**_item("10000001", "2026-01-13 08:00:00", "DBP", "82"), "updated_at": "2026-01-14"})
    run_ingest(cfg, "csv", str(feed), snapshot="2026-01-14", load_fhir=False, validate=False)
    run_ingest(cfg, "csv", str(feed), since="2026-01-14", snapshot="2026-01-15", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-01-15")
    codes = sorted(o["code"]["coding"][0]["code"] for o in read_type(folder, "Observation"))
    assert codes == ["85354-9"]  # one panel, even though only the diastolic row changed on the delta night
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["vital"]["rows"] == 1


def test_the_mapping_check_asks_for_the_item_and_value_and_pivots_what_it_reads(tmp_path: Path) -> None:
    from tools.mapping_check import _wanted, check

    m = Mapping.load(_site(tmp_path))
    specs = [r for r in m.resources if r.table == "vital"]
    _need, _optional, local = _wanted(m, "vital", m.tables["vital"], specs)
    assert {"item_code", "item_value", "mrn", "measure_datetime"} <= set(local)
    assert not {"sbp", "dbp", "height_cm", "weight_kg"} & set(local)
    feed = tmp_path / "feed"
    feed.mkdir()
    with (feed / "vital_items.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mrn", "measure_datetime", "item_code", "item_value"])
        w.writeheader()
        w.writerow(_item("10000001", "2026-01-13 08:00:00", "SBP", "128"))
        w.writerow(_item("10000001", "2026-01-13 08:00:00", "DBP", "82"))
    (tmp_path / "s2").mkdir()
    rep = check(_site(tmp_path / "s2"), "csv", str(feed), 100)
    assert rep["tables"]["vital"]["rows_read"] == 1
