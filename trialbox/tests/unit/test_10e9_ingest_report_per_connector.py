"""10E-9 (plan 10, Track E; review 13-10): the ingest report says, per connector and per message, how long the read
took: messages, seconds and the 95th percentile per message, per table and for the whole source, with the histogram
the percentile is read from (review 13 §measurements: "per-message histogram in the ingest report").

A message is what the connector hands the night one at a time: a CSV or SQL row, an SS-MIX2 message, a FHIR
resource. The time is the connector's own (reading and parsing), not the mapping's. Counts and times only: never a
value of a row. Synthetic data.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest
from adapter.read_timing import BOUNDS_MS, ReadTimes

from tests.unit.test_dataflow_lake_p0 import _cfg, _Lakes
from tests.unit.test_number_too_long_is_a_rejected_row import _labs


@pytest.mark.nodb
def test_each_message_is_timed_from_the_connector_alone() -> None:
    now = [0.0]
    times = ReadTimes(clock=lambda: now[0])

    def rows() -> Iterator[dict[str, str]]:
        for ms in (0.2, 0.2, 0.2, 40.0):  # the connector's own time per message
            now[0] += ms / 1000
            yield {"n": "x"}

    got: list[dict[str, str]] = []
    for r in times.timed("lab", rows()):
        now[0] += 5.0  # the mapping's time after each message: never counted as the connector's
        got.append(r)
    s = times.summary("csv")
    assert len(got) == 4 and s["kind"] == "csv" and s["messages"] == 4
    lab = s["tables"]["lab"]
    assert lab["messages"] == 4 and lab["seconds"] == pytest.approx(0.0406)
    assert lab["p95_ms"] == 50.0  # the upper bound of the bucket the 95th message falls in, never under it
    assert sum(lab["histogram"].values()) == 4 and lab["histogram"]["<=0.25"] == 3 and lab["histogram"]["<=50"] == 1
    assert s["seconds"] == pytest.approx(0.0406) and s["p95_ms"] == 50.0


@pytest.mark.nodb
def test_a_table_with_no_message_has_no_percentile_and_the_buckets_cover_everything() -> None:
    times = ReadTimes(clock=iter([0.0, 9.0]).__next__)
    assert list(times.timed("empty", iter([]))) == []
    s = times.summary("cgrd_sql")
    assert s["tables"]["empty"] == {"messages": 0, "seconds": 0.0, "p95_ms": None,
                                    "histogram": {k: 0 for k in s["tables"]["empty"]["histogram"]}}  # fmt: skip
    assert list(s["tables"]["empty"]["histogram"])[-1] == f">{BOUNDS_MS[-1]:g}"  # a slow message is never lost


def test_the_night_reports_its_connector_per_table(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _labs(tmp_path / "n1", ["0.9"] * 120)
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed
    c = rep.connector
    assert c is not None and c.kind == "csv"
    assert c.tables["lab"].messages == 120 and sum(c.tables["lab"].histogram.values()) == 120
    assert c.tables["lab"].p95_ms is not None and c.tables["lab"].seconds >= 0
    assert c.messages == sum(t.messages for t in c.tables.values())
    written = json.loads((snapshot_dir(cfg.lake_dir, "2026-10-01") / "ingest_report.json").read_text("utf-8"))
    assert written["connector"]["tables"]["lab"]["messages"] == 120
    # counts and times only: the section's keys are these and no other, so no value of a row can be in it
    assert set(written["connector"]) == {"kind", "messages", "seconds", "p95_ms", "histogram", "tables"}
    assert set(written["connector"]["tables"]["lab"]) == {"messages", "seconds", "p95_ms", "histogram"}
