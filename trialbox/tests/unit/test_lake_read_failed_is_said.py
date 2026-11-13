"""A lake read that failed is said, never shown as "none" (D-652).

Four places caught any failure of a lake read and went on with an empty value that reads as a fact: "no confirmed
fact" behind an exclusion, a doctor's placeholder name, no value behind a coded answer, "no notes in the box". Each
now keeps the one case it was written for where that case can be asked of the lake (a snapshot with no such
table), and for every other failure writes into its output that the lake could not be read."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest
from matching import coded_values
from orchestrator.scenarios import feas_profile, screen
from orchestrator.scenarios.screen import ScreenRun, excluded_doc
from tb_common import lakeprobe
from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow, CriterionVerdict, Evidence

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
CODED_EXC = next(c.id for c in GZQO.active() if c.class_ == "structured" and c.kind == "exclusion")
DOWN = RuntimeError("lake query failed (503): upstream connect error")


class _Lake:
    """Answers the queries whose text holds a key of ``tables`` with those rows; ``fail``: raised for every other
    query. The question "is there such a table" is answered ``there`` (1) unless the table is in ``absent``."""

    def __init__(
        self, tables: dict[str, list[dict[str, Any]]], fail: Exception | None = None, absent: tuple[str, ...] = ()
    ):
        self.tables, self.fail, self.absent = tables, fail, absent
        self.asked: list[str] = []

    def query(self, sql: str, params: Any = None, snapshot: Any = None) -> Any:
        self.asked.append(sql)
        for table in ("site_fact", "practitioner", "document_chunk", "appointment"):
            if sql == lakeprobe.table_sql(table):
                return pa.table({"n": [0 if table in self.absent else 1]})
        for key, rows in self.tables.items():
            if key in sql and not any(a in sql for a in self.absent):
                return pa.Table.from_pylist(rows) if rows else pa.table({"fid": pa.array([], pa.string())})
        raise self.fail or RuntimeError("lake query failed (422): Catalog Error: Table does not exist!")


def _ctx(lake: Any, practitioners: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(
        services=SimpleNamespace(lake=lake),
        cfg=SimpleNamespace(settings=SimpleNamespace(practitioners=practitioners or {})),
    )


def _run() -> ScreenRun:
    coded = CriterionVerdict(id=CODED_EXC, verdict="fail", basis="coded", evidence=Evidence(resource_refs=["C/f-1"]))
    row = CandidateRow(pid="P1", tier="excluded", actions=[], criteria=[coded])
    return ScreenRun(GZQO, date(2026, 10, 5), "2026-10-05", [], {}, [row], [], [], 7, None)


# ----------------------------------------------------------------------- 1. where an exclusion's answer came from
def test_the_excluded_page_does_not_say_coded_records_when_the_confirmed_facts_could_not_be_read() -> None:
    """Shown to the person who decides: "the coded records" (the hospital's systems coded it) or "a confirmed fact"
    (a person typed or confirmed it from a chart). With the lake down every answer read "the coded records"."""
    doc = excluded_doc(_ctx(_Lake({}, fail=DOWN)), _run())
    assert doc["confirmed_facts"] == "not read"
    assert [c["source"] for r in doc["rows"] for c in r["criteria"]] == ["records"]
    read = excluded_doc(_ctx(_Lake({"site_fact": [{"fid": "f-1"}]})), _run())
    assert read["confirmed_facts"] == "read" and read["rows"][0]["criteria"][0]["source"] == "fact"
    none = excluded_doc(_ctx(_Lake({"site_fact": []})), _run())
    assert none["confirmed_facts"] == "read" and none["rows"][0]["criteria"][0]["source"] == "coded"


def test_a_snapshot_without_site_facts_has_no_confirmed_fact_and_that_is_asked_of_the_lake() -> None:
    lake = _Lake({}, absent=("site_fact",))
    doc = excluded_doc(_ctx(lake), _run())
    assert doc["confirmed_facts"] == "read" and doc["rows"][0]["criteria"][0]["source"] == "coded"
    assert lakeprobe.table_sql("site_fact") in lake.asked
    # the words of a missing table in another failure's text, on a lake that has the table: not read
    said = RuntimeError("lake query failed (503): Catalog busy; site_fact does not exist in the cache")
    assert excluded_doc(_ctx(_Lake({}, fail=said)), _run())["confirmed_facts"] == "not read"


# ------------------------------------------------------------------------------------- 2. a doctor's name on a list
def test_a_doctors_name_that_could_not_be_read_is_not_filled_from_the_settings_placeholder() -> None:
    settings = {"D1": SimpleNamespace(name="Dr. A (synthetic)"), "D2": SimpleNamespace(name="")}
    read = screen.practitioner_names(
        _ctx(_Lake({"practitioner": [{"practitioner_id": "D1", "name": "林 醫師"}]}), settings)
    )
    assert read == {"D1": "林 醫師 (D1)", "D2": "D2 (D2)"}
    down = screen.practitioner_names(_ctx(_Lake({}, fail=DOWN), settings))
    # the settings name is all there is, and it is said to be the settings' name; no name at all: "name not read"
    assert down == {"D1": "Dr. A (synthetic) (D1; name from settings)", "D2": "D2 (name not read)"}
    assert screen.practitioner_names(_ctx(_Lake({}, fail=DOWN), {})) == {}  # not in the settings: the bare id
    # the records hold no name for D1: the settings name fills it, as before (D-120)
    none = screen.practitioner_names(
        _ctx(_Lake({"practitioner": [{"practitioner_id": "D9", "name": "王 醫師"}]}), settings)
    )
    assert none["D1"] == "Dr. A (synthetic) (D1)" and none["D9"] == "王 醫師 (D9)"


# ----------------------------------------------------------------------------- 3. the values behind a coded answer
def test_coded_values_that_could_not_be_read_are_not_the_same_as_none_found() -> None:
    v = CriterionVerdict(id=CODED_EXC, verdict="fail", basis="coded", evidence=Evidence(resource_refs=["C/f-1"]))
    assert coded_values.attach(_Lake({}, fail=DOWN), GZQO.active(), {"P1": [v]}, date(2026, 10, 5), None) is None
    assert v.evidence is not None and v.evidence.coded is None  # no claim on the answer: not "no record"
    # the run's own step: False when the read failed, True when it was made (also when it found nothing)
    assert screen.attach_values(_Lake({}, fail=DOWN), GZQO, {"P1": [v]}, date(2026, 10, 5), None) is False
    assert screen.attach_values(_Lake({}, fail=DOWN), GZQO, {}, date(2026, 10, 5), None) is True  # nothing to read
    run = _run()
    assert run.coded_values_read is True
    run.coded_values_read = False
    assert excluded_doc(_ctx(_Lake({"site_fact": []})), run)["coded_values"] == "not read"
    assert excluded_doc(_ctx(_Lake({"site_fact": []})), _run())["coded_values"] == "read"


# -------------------------------------------------------------------------- 4. what the feasibility counts stand on
def test_the_feasibility_profile_says_its_data_facts_were_not_read() -> None:
    read = feas_profile.data_facts(_Lake({"appointment": [{"appts": 12, "chunks": 0}]}), "2026-10-05")
    assert read == {"appointment_rows": 12, "note_chunks": 0, "read": True}
    down = feas_profile.data_facts(_Lake({}, fail=DOWN), "2026-10-05")
    assert down == {"appointment_rows": None, "note_chunks": None, "read": False}


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), SystemExit(1)])
def test_none_of_them_swallows_the_process_being_stopped(exc: BaseException) -> None:
    lake = _Lake({})
    lake.fail = exc  # type: ignore[assignment]
    with pytest.raises(type(exc)):
        excluded_doc(_ctx(lake), _run())
    with pytest.raises(type(exc)):
        screen.practitioner_names(_ctx(lake))
    with pytest.raises(type(exc)):
        feas_profile.data_facts(lake, "2026-10-05")
