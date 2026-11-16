"""CGRD-SQL (D-814): a mapped table the database does not have is absent, counted and named; the night goes on.

The SQL source had no ``has_table``. A mapping that names a table the database lacks (a site with no drug-order
table) stopped the whole night at the first query. A table is now absent only when reading it fails **and** the
database's own catalogue has no table or view by that name: then it yields no rows and the night's report says it is
absent, as for a csv export without the file (T-611). Any other failure (a lost connection, no right to read) still
stops the night: an outage must never read as "every table is absent". Synthetic SQLite databases only."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import run_ingest
from adapter.sources.cgrd_sql.source import SqlSource

from tests.unit.test_dataflow_lake_p0 import _cfg


def _db(tmp_path: Path) -> str:
    path = tmp_path / "his.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE patient (mrn TEXT, name TEXT, id_no TEXT, birth_date TEXT, sex TEXT, death_date TEXT)")
    con.execute("INSERT INTO patient VALUES ('10000001', 'a', 'b', '1960-01-01', 'F', '')")
    con.execute("CREATE TABLE diagnosis (diag_no TEXT, enc_no TEXT, mrn TEXT, icd10 TEXT, diag_date TEXT, "
                "recorded_date TEXT, status TEXT, updated_at TEXT)")  # fmt: skip
    con.execute("INSERT INTO diagnosis VALUES ('D1', 'E1', '10000001', 'M10.9', '2026-01-13', '2026-01-13', 'A', "
                "'2026-01-13')")  # fmt: skip
    con.execute("CREATE VIEW vital AS SELECT mrn FROM patient WHERE 1 = 0")  # a view is a table the source has
    con.commit()
    con.close()
    return f"sqlite:///{path}"


def test_the_source_says_which_tables_it_has(tmp_path: Path) -> None:
    src = SqlSource(_db(tmp_path))
    assert src.has_table("patient") and src.has_table("vital")
    assert not src.has_table("medication")
    assert list(src.rows("medication", "medication", "updated_at", "2026-01-01")) == []


def test_a_night_with_a_mapped_table_the_database_lacks_goes_on_and_names_it(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    rep = run_ingest(cfg, "cgrd_sql", _db(tmp_path), snapshot="2026-01-14", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-01-14")
    assert len(list(read_type(folder, "Condition"))) == 1
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["medication"]["present"] is False and comp["tables"]["patient"]["present"] is True
    assert rep is not None


def test_a_failure_on_a_table_the_database_has_still_stops_the_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalogue says the table is there, yet reading it fails (no right to read it, a lost connection): never
    taken for an absent table."""
    src = SqlSource(_db(tmp_path))
    real = src.engine.connect

    def broken() -> object:
        raise RuntimeError("the connection was lost")

    monkeypatch.setattr(src.engine, "connect", broken)
    with pytest.raises(RuntimeError):
        src.has_table("patient")
    monkeypatch.setattr(src.engine, "connect", real)
    assert src.has_table("patient")


def test_the_mapping_check_says_a_table_the_database_lacks_is_absent(tmp_path: Path) -> None:
    from tools import mapping_check

    base = Path(__file__).resolve().parents[2] / "services/adapter/mapping/tw_core/demo_his.yaml"
    rep = mapping_check.check(base, "cgrd_sql", _db(tmp_path), 100, None, None, None, None)
    assert rep["tables"]["medication"]["cannot_be_read"] == "OperationalError"  # its kind, never its text
    assert rep["tables"]["diagnosis"]["rows_read"] == 1
