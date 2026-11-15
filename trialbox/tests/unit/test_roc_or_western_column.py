"""F8 (D-807): a date column a site declares ``roc_or_western`` reads both.

An export may write a column as a western date (``2026-01-13 00:00:00``) where the database writes it in the ROC
calendar. Declared ``roc``, every such value is refused (D-589, unchanged: nothing is detected from values) and the
whole table is lost. Declared ``roc_or_western``, a ROC value is read as ROC, and a western value that cannot be ROC
(a four-digit year with separators, or 8, 12 or 14 digits) is read as western and counted per table and column.
Anything else is still refused. Synthetic values only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapper, Mapping, MappingError

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"

SITE = f"""
version: 1
name: export_site
extends: {BASE}
tz: Asia/Taipei
tables:
  lab: {{source: lab, key: lab_no, dates: {{sample_datetime: roc_or_western}}}}
  diagnosis: {{source: diagnosis, key: diag_no, dates: {{diag_date: roc}}}}
"""


@pytest.fixture
def m(tmp_path: Path) -> Mapping:
    p = tmp_path / "site.yaml"
    p.write_text(SITE, encoding="utf-8")
    return Mapping.load(p)


def _lab(when: Any) -> dict[str, Any]:
    return {"lab_no": "L1", "mrn": "P1", "local_code": "CRE", "item_name": "x", "result_value": "1.1",
            "unit": "mg/dL", "sample_datetime": when}  # fmt: skip


def _effective(m: Mapping, when: Any) -> str:
    (res,) = Mapper(m, b"k" * 32, "s").map_table("lab", iter([m.normalize("lab", _lab(when))]))
    return str(res["effectiveDateTime"])


@pytest.mark.parametrize(("raw", "want"), [
    ("1150113", "2026-01-13T00:00:00+08:00"),             # ROC, compact
    ("115/01/13 08:30", "2026-01-13T08:30:00+08:00"),     # ROC, written
    ("民國115年1月13日", "2026-01-13T00:00:00+08:00"),
    ("2026-01-13 00:00:00", "2026-01-13T00:00:00+08:00"),  # western, as an export writes a DATE
    ("2026-01-13", "2026-01-13T00:00:00+08:00"),
    ("2026/1/13 08:30", "2026-01-13T08:30:00+08:00"),
    ("20260113", "2026-01-13T00:00:00+08:00"),
    ("202601130830", "2026-01-13T08:30:00+08:00"),
    ("20260113083015", "2026-01-13T08:30:15+08:00"),
])  # fmt: skip
def test_a_roc_or_western_column_reads_both(m: Mapping, raw: str, want: str) -> None:
    assert _effective(m, raw) == want


@pytest.mark.parametrize("raw", ["260113", "15-01-13", "2026-13-01", "20261301", "Jan 13 2026", "2026-01-13 25:00",
                                 "1150113X"])  # fmt: skip
def test_what_is_neither_is_still_refused(m: Mapping, raw: str) -> None:
    with pytest.raises(MappingError, match="roc_or_western"):
        _effective(m, raw)


def test_each_western_value_read_is_counted_per_table_and_column(m: Mapping) -> None:
    for v in ("1150113", "2026-01-13 00:00:00", "20260114", "115/01/15"):
        m.normalize("lab", _lab(v))
    assert m.read_as_western() == {"lab": {"sample_datetime": 2}}


def test_a_column_declared_roc_still_refuses_a_western_date(m: Mapping) -> None:
    """D-589 is unchanged: only the site's declaration makes a western value acceptable."""
    row = m.normalize("diagnosis", {"diag_no": "D1", "mrn": "P1", "icd10": "M10.9", "diag_date": "2026-01-13",
                                    "recorded_date": "", "status": "A", "enc_no": "E1"})  # fmt: skip
    with pytest.raises(MappingError, match=r"not a roc calendar date"):
        list(Mapper(m, b"k" * 32, "s").map_table("diagnosis", iter([row])))
    assert m.read_as_western() == {}


def test_the_night_reports_the_western_values_read_and_maps_the_table(m: Mapping, tmp_path: Path) -> None:
    import csv
    import json

    from adapter.ndjson import read_type, snapshot_dir
    from adapter.pipeline import run_ingest

    from tests.unit.test_dataflow_lake_p0 import _cfg

    cfg = _cfg(tmp_path)
    cfg.mapping_path = m.path
    feed = tmp_path / "feed"
    feed.mkdir()
    cols = ["lab_no", "enc_no", "mrn", "local_code", "item_name", "sample_datetime", "result_value", "unit",
            "result_status", "updated_at"]  # fmt: skip
    with (feed / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for n, when in enumerate(["2026-01-13 00:00:00", "1150113", "20260113"]):
            w.writerow({"lab_no": f"L{n}", "enc_no": "E1", "mrn": "10000001", "local_code": "CRE",
                        "item_name": "creatinine", "sample_datetime": when, "result_value": "0.9", "unit": "mg/dL",
                        "result_status": "final", "updated_at": "2026-01-13"})  # fmt: skip
    run_ingest(cfg, "csv", str(feed), snapshot="2026-01-14", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-01-14")
    assert len(list(read_type(folder, "Observation"))) == 3  # none refused
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["lab"]["read_as_western"] == {"sample_datetime": 2}
