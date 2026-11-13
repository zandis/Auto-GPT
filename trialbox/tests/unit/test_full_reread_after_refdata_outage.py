"""NEW-B-18 (D-538): after an outage of the reference data, the next delta night reads that table whole.

D-530 left it to the operator: a row that met the outage keeps its unmapped code until it changes or a full load
runs, and a delta night reads only rows that changed. The night before says which tables met the outage
(``unmapped_codes.json``: ``<map>:unavailable``); the next delta night reads those tables whole, by itself."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import UNMAPPED_CODES, AdapterConfig, reread_whole, run_ingest
from tb_common import refdata

from tests.unit.test_dataflow_lake_p0 import _cfg
from tests.unit.test_icd9_map_at_night import BASE, I9, I10

DIAG = ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status", "updated_at"]
DOWN = "map:icd9cm->icd10cm:unavailable"


def _site(tmp_path: Path) -> AdapterConfig:
    """The demo mapping with the ICD-9-CM rule on (D-593): a diagnosis before 2016 is ICD-9-CM."""
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    doc["params"] = {"icd9cm_before": "2016-01-01"}
    for name, spec in (doc.get("lookups") or {}).items():
        spec["file"] = str(BASE.parent / spec["file"])
        doc["lookups"][name] = spec
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    cfg = _cfg(tmp_path)
    cfg.mapping_path = path
    return cfg


def _feed(path: Path, rows: list[dict[str, str]]) -> str:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DIAG)
        w.writeheader()
        w.writerows(rows)
    return str(path)


def _diag(no: str, code: str, updated: str) -> dict[str, str]:
    return {"diag_no": no, "enc_no": "E1", "mrn": "10000001", "icd10": code, "diag_date": "2014-03-02",
            "recorded_date": "2014-03-02", "status": "A", "updated_at": updated}  # fmt: skip


def _refdata(monkeypatch: pytest.MonkeyPatch, up: bool) -> None:
    def ask(system: str, code: str, url: str | None = None) -> list[dict[str, Any]] | None:
        if not up:
            return None
        return [{"target_system": I10, "target_code": {"042": "B20", "585.3": "N18.3"}[code], "relation": "equivalent"}]

    monkeypatch.setattr(refdata, "map_targets_or_none", ask)


def _codes(cfg: AdapterConfig, snap: str) -> list[list[str]]:
    """Each diagnosis' codes, in order: the ICD-10-CM one first when the map answered."""
    out = []
    for r in read_type(snapshot_dir(cfg.lake_dir, snap), "Condition"):
        out.append([f"{'10' if c['system'] == I10 else '9' if c['system'] == I9 else '?'}:{c['code']}"
                    for c in r["code"]["coding"]])  # fmt: skip
    return sorted(out)


def _night(cfg: AdapterConfig, feed: str, snap: str, since: str | None = None) -> Any:
    return run_ingest(cfg, "csv", feed, since=since, snapshot=snap, load_fhir=False, validate=False)


def test_the_delta_night_after_an_outage_maps_the_rows_that_did_not_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = _site(tmp_path)
    feed = _feed(tmp_path / "feed", [_diag("D1", "042", "2026-09-30"), _diag("D2", "585.3", "2026-09-30")])
    _refdata(monkeypatch, up=False)
    assert _night(cfg, feed, "2026-10-01").passed  # D-530: not held
    assert _codes(cfg, "2026-10-01") == [["9:042"], ["9:585.3"]]
    said = json.loads((snapshot_dir(cfg.lake_dir, "2026-10-01") / UNMAPPED_CODES).read_text())
    assert said == {"diagnosis": {DOWN: {"042": 1, "585.3": 1}}}
    # the next night is a delta night; no diagnosis changed at the source; the reference data answers again
    _refdata(monkeypatch, up=True)
    with caplog.at_level(logging.INFO):
        rep = _night(cfg, feed, "2026-10-02", since="2026-10-01")
    assert rep.passed and not rep.held
    assert _codes(cfg, "2026-10-02") == [["10:B20", "9:042"], ["10:N18.3", "9:585.3"]]
    assert not (snapshot_dir(cfg.lake_dir, "2026-10-02") / UNMAPPED_CODES).exists()
    assert (
        "diagnosis: read whole on this delta night: the reference data did not answer for it on 2026-10-01 (D-538)"
        in caplog.text
    )
    assert "042" not in caplog.text and "585.3" not in caplog.text  # a table and a night, never a code
    # healed: the night after is a delta night like any other (an unchanged row is not read)
    feed = _feed(tmp_path / "feed", [_diag("D1", "585.3", "2026-09-30"), _diag("D2", "585.3", "2026-09-30")])
    caplog.clear()
    with caplog.at_level(logging.INFO):
        _night(cfg, feed, "2026-10-03", since="2026-10-02")
    assert _codes(cfg, "2026-10-03") == [["10:B20", "9:042"], ["10:N18.3", "9:585.3"]]
    assert "read whole" not in caplog.text


def test_an_outage_that_lasts_is_read_whole_each_delta_night_until_it_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _site(tmp_path)
    feed = _feed(tmp_path / "feed", [_diag("D1", "042", "2026-09-30")])
    _refdata(monkeypatch, up=False)
    _night(cfg, feed, "2026-10-01")
    _night(cfg, feed, "2026-10-02", since="2026-10-01")  # still down: read whole, still not mapped, said again
    assert _codes(cfg, "2026-10-02") == [["9:042"]]
    assert reread_whole(cfg.lake_dir, "2026-10-02") == ({"diagnosis"}, "2026-10-02")
    _refdata(monkeypatch, up=True)
    _night(cfg, feed, "2026-10-03", since="2026-10-02")
    assert _codes(cfg, "2026-10-03") == [["10:B20", "9:042"]]


def test_only_the_tables_of_the_outage_and_only_from_the_night_merged_over(tmp_path: Path) -> None:
    nd = snapshot_dir(tmp_path, "2026-10-01")
    nd.mkdir(parents=True)
    assert reread_whole(tmp_path, None) == (set(), None)  # no night to merge over
    assert reread_whole(tmp_path, "2026-10-01") == (set(), "2026-10-01")  # a night that counted nothing
    (nd / UNMAPPED_CODES).write_text(json.dumps({
        "lab": {"lab": {"X1": 3}},  # a code no look-up knows: a fault of the feed, a full read changes nothing
        "diagnosis": {"map:icd9cm->icd10cm": {"7140": 2}, DOWN: {"042": 1}},
    }))  # fmt: skip
    assert reread_whole(tmp_path, "2026-10-01") == ({"diagnosis"}, "2026-10-01")
    (nd / UNMAPPED_CODES).write_text("not json")  # unreadable: nothing is read whole, the night goes on as a delta
    assert reread_whole(tmp_path, "2026-10-01") == (set(), "2026-10-01")
