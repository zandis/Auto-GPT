"""T-731 (D-688): a window of `mapping_check` that read nothing does not pass, and `--day` reads a day however a
character column writes it.

CGRD writes its change times as compact character days (`20261110`, `20261110093000`). `--day` compared them with
`2026-11-10 00:00:00` as text: no row matched, every table read nothing, and the report said passed. The owner is
about to run this check against the real connection. The databases here are synthetic SQLite files."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tools import mapping_check

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
DAY, NEXT = "2026-11-10", "2026-11-11"

MAPPING = f"""
version: 1
name: SYN_window
extends: {BASE}
tz: Asia/Taipei
tables:
  encounter:
    source: VISIT_VIEW
    key: enc_no
    delta: updated_at
    rename: {{UPD: updated_at, VISIT_NO: enc_no, CHART_NO: mrn, VISIT_TIME: visit_datetime, DEPT: dept_code, DOC_ID: staff_id, VISIT_TYPE: enc_type}}
    values: {{enc_type: {{O: OPD, I: IPD, E: ER}}}}
"""


def _site(tmp_path: Path, upd_type: str, stamps: list[str]) -> tuple[Path, str]:
    """One visit table whose change-time column is of ``upd_type`` and holds ``stamps`` (one visit each)."""
    path = tmp_path / "w.db"
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE VISIT_VIEW (UPD {upd_type}, VISIT_NO TEXT, CHART_NO TEXT, VISIT_TIME TEXT, DEPT TEXT, "
                "DOC_ID TEXT, VISIT_TYPE TEXT)")  # fmt: skip
    con.executemany(
        "INSERT INTO VISIT_VIEW VALUES (?,?,?,?,?,?,?)",
        [(s, f"V{i}", "10000002", f"{DAY} 08:30:00", "RHEU", "S1", "O") for i, s in enumerate(stamps)],
    )
    con.commit()
    con.close()
    mp = tmp_path / "w.yaml"
    mp.write_text(MAPPING, encoding="utf-8")
    return mp, f"sqlite:///{path}"


def _day(site: tuple[Path, str], tmp_path: Path) -> tuple[int, dict[str, Any]]:
    out = tmp_path / "day.json"
    rc = mapping_check.main(["--mapping", str(site[0]), "--source", "cgrd_sql", "--dsn", site[1], "--day", DAY,
                             "--rows", "0", "--share", str(out)])  # fmt: skip
    return rc, json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("stamps", "form"),
    [
        (["20261110", "20261110093000", "20261111", "20261109235959"], "YYYYMMDD"),
        (["2026/11/10", "2026/11/10 09:30:00", "2026/11/11 00:00:00", "2026/11/09"], "YYYY/MM/DD"),
        (["2026-11-10", "2026-11-10 09:30:00", "2026-11-11", "2026-11-09 23:59:59"], "YYYY-MM-DD"),
    ],
)
def test_a_day_is_read_however_a_character_column_writes_it(
    tmp_path: Path, stamps: list[str], form: str, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, rep = _day(_site(tmp_path, "VARCHAR(20)", stamps), tmp_path)
    enc = rep["tables"]["encounter"]
    assert enc["rows_read"] == 2, enc  # the day's two rows, not the day before or after
    assert enc["window_form"] == form and "read_nothing_in_window" not in enc
    assert rc == 0 and rep["passed"] is True


def test_a_date_type_column_is_given_the_day_as_a_date(tmp_path: Path) -> None:
    rc, rep = _day(
        _site(tmp_path, "DATETIME", [f"{DAY} 09:30:00", f"{NEXT} 00:00:00", "2026-11-09 23:59:59"]), tmp_path
    )
    enc = rep["tables"]["encounter"]
    assert enc["rows_read"] == 1 and enc["window_form"] == "a date type", enc
    assert rc == 0 and rep["passed"] is True


@pytest.mark.parametrize("stamps", [["1151110", "115/11/10"], ["10/11/2026"], ["20261109", "20261112"]])
def test_a_window_that_read_nothing_is_said_and_does_not_pass(tmp_path: Path, stamps: list[str]) -> None:
    """A day in the ROC calendar, a day-month-year text, or simply no row of that day: nothing read. That is said
    for the table, and a run whose every table read nothing in its window fails (it said passed)."""
    rc, rep = _day(_site(tmp_path, "VARCHAR(20)", stamps), tmp_path)
    enc = rep["tables"]["encounter"]
    assert enc["rows_read"] == 0 and enc["read_nothing_in_window"] is True
    assert "YYYYMMDD" in enc["note"] and "ROC" in enc["note"]  # the forms tried, and the one that is not
    assert rep["passed"] is False and rc == 1
    assert rep["tables_that_read_nothing"] == 1


def test_one_table_that_read_nothing_is_said_while_the_others_read(tmp_path: Path) -> None:
    """A table with no change on that day is ordinary (a patient table): said for it, the run judged on the rest."""
    mp, dsn = _site(tmp_path, "VARCHAR(20)", ["20261110"])
    con = sqlite3.connect(dsn.removeprefix("sqlite:///"))
    con.execute("CREATE TABLE VISIT2 AS SELECT * FROM VISIT_VIEW WHERE 0")
    con.commit()
    con.close()
    mp.write_text(MAPPING + MAPPING.split("tables:\n", 1)[1].replace("encounter:", "encounter2:").replace(
        "VISIT_VIEW", "VISIT2"), encoding="utf-8")  # fmt: skip
    rep = mapping_check.check(mp, "cgrd_sql", dsn, rows=0, day=DAY)
    assert rep["tables"]["encounter"]["rows_read"] == 1
    assert rep["tables"]["encounter2"]["read_nothing_in_window"] is True
    assert rep["share"]["tables_that_read_nothing"] == 1


def test_an_explicit_window_is_used_as_given_and_still_said_when_it_read_nothing(tmp_path: Path) -> None:
    site = _site(tmp_path, "VARCHAR(20)", ["20261110"])
    rep = mapping_check.check(site[0], "cgrd_sql", site[1], rows=0, since="20261110", until="20261111")
    assert rep["tables"]["encounter"]["rows_read"] == 1 and rep["passed"] is True
    rep = mapping_check.check(site[0], "cgrd_sql", site[1], rows=0, since="2026-11-10", until="2026-11-11")
    assert rep["tables"]["encounter"]["read_nothing_in_window"] is True and rep["passed"] is False
