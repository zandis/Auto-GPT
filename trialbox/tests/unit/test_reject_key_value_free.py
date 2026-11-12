"""NEW-B-1 (D-520): the key a rejected row is counted under holds no feed value.

The key was the mapper's message with quoted text replaced by a regex. ``repr`` of a value that holds both quote
marks escapes one of them, the regex then ends the "quoted value" early, and a fragment of the feed's value stayed in
the key: in ``completeness.json``, in the night's error and in the log."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import reject_key, run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _Lakes, _row

SECRET = "CHART-7731"  # stands for a feed value that must never be written outside the store


def test_a_value_with_both_quote_marks_leaves_nothing_in_the_key_or_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    bad = f"""it's "{SECRET}" on 2026"""  # in the date column: the mapping cannot read it
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01"), _row("D2", bad)])
    with caplog.at_level(logging.WARNING):
        rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-10-01")
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    (table,) = [t for t, facts in comp["tables"].items() if facts.get("rejected")]
    keys = list(comp["tables"][table]["rejected"])
    assert keys == ["MappingError: unparseable date <value>"], keys
    written = json.dumps(comp) + "\n".join(rep.errors or []) + caplog.text
    written += (folder / "ingest_report.json").read_text(encoding="utf-8")
    for fragment in (SECRET, "7731", "it's", "on 2026"):
        assert fragment not in written, fragment


@pytest.mark.nodb
@pytest.mark.parametrize(
    ("exc", "key"),
    [
        (ValueError("could not convert string to float: 'abc'"), "ValueError: could not convert string to float: <value>"),
        (ValueError('bad code "X\'Y" in column dx'), "ValueError: bad code <value>"),
        (ValueError("value 12345678 is out of range"), "ValueError: value <n> is out of range"),
        (ValueError("invalid literal for int() with base 10: '0012a'"),
         "ValueError: invalid literal for int() with base <n>: <value>"),
        (ValueError(""), "ValueError"),
        (ValueError("'everything is the value'"), "ValueError: <value>"),
    ],
)  # fmt: skip
def test_the_key_is_the_type_and_the_message_up_to_its_first_value(exc: ValueError, key: str) -> None:
    assert reject_key(exc) == key
