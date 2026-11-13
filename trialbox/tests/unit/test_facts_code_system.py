"""The facts of an NHI draft match a record by its code AND its code system (D-643).

``orchestrator.scenarios.facts.collect`` read "the data the criteria were evaluated on" by the ValueSet's codes
alone. The compiled SQL of the same ruleset matches the system too (``vs.system = x.system AND vs.code = x.code``).
So a record whose code string is in the ValueSet under another system (an ICD-9-CM or a house code that looks like
an ICD-10-CM one, a local lab code that looks like a LOINC one) was shown in the draft as the diagnosis, its date
as the date of diagnosis, though the criteria never counted it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
from orchestrator.scenarios import facts
from tb_common import derived
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
RA_BIO = Ruleset.load(ROOT / "rulesets" / "RA-BIO")
RUN = date(2026, 10, 5)
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
HOUSE = "http://hospa.test/codes"  # synthetic: a site's own code list


class _Lake:
    def __init__(self) -> None:
        self.con = duckdb.connect(":memory:")
        for ddl in (
            "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR)",
            "CREATE TABLE condition (cid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, onset DATE, recorded DATE)",
            'CREATE TABLE medication (mid VARCHAR, pid VARCHAR, name VARCHAR, atc VARCHAR, dose VARCHAR, start DATE, "end" DATE)',
            "CREATE TABLE observation (oid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, value_code VARCHAR, "
            "value_num DOUBLE, unit VARCHAR, effective TIMESTAMP)",
            "CREATE TABLE report (rid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, effective DATE, conclusion VARCHAR)",
            "CREATE TABLE claim (pid VARCHAR, product VARCHAR, outcome VARCHAR, approval_end DATE)",
        ):
            self.con.execute(ddl)
        self.con.execute("INSERT INTO patient VALUES ('P1', DATE '1970-01-01', 'female')")

    def add(self, table: str, *row: Any) -> None:
        self.con.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", list(row))

    def query(self, sql: str, params: list[Any] | None = None, *a: Any, **kw: Any) -> Any:
        return self.con.execute(sql, params or []).fetch_arrow_table()


def test_the_diagnosis_of_the_draft_is_the_one_the_criteria_count() -> None:
    lake = _Lake()
    lake.add("condition", "c-house", "P1", "M05.9", HOUSE, date(2011, 3, 1), None)  # the same string, a house code
    lake.add("condition", "c-icd", "P1", "M05.9", ICD10CM, date(2020, 6, 1), None)
    f = facts.collect(lake, RA_BIO, "P1", RUN)  # type: ignore[arg-type]
    assert (f.get("diagnosis_code"), f.get("diagnosis_date")) == ("M05.9", "2020-06-01")


def test_a_code_under_another_system_alone_is_no_diagnosis() -> None:
    lake = _Lake()
    lake.add("condition", "c-house", "P1", "M05.9", HOUSE, date(2011, 3, 1), None)
    f = facts.collect(lake, RA_BIO, "P1", RUN)  # type: ignore[arg-type]
    assert f.get("diagnosis_code") is None and f.get("diagnosis_date") is None


def test_a_screening_result_and_a_report_are_matched_with_their_system() -> None:
    lake = _Lake()
    # the newest row under each code string is a house code; the LOINC rows are older
    lake.add("observation", "o1", "P1", "5196-1", LOINC, "LA6577-6", None, None, "2026-08-01 09:00:00")
    lake.add("observation", "o2", "P1", "5196-1", HOUSE, "LA6576-8", None, None, "2026-09-01 09:00:00")
    lake.add("report", "r1", "P1", "36643-5", LOINC, date(2026, 8, 2), "no active lesion")
    lake.add("report", "r2", "P1", "36643-5", HOUSE, date(2026, 9, 2), "another examination")
    f = facts.collect(lake, RA_BIO, "P1", RUN)  # type: ignore[arg-type]
    assert f.get("hbsag") == "陰性（2026-08-01）"
    assert f.get("cxr") == "胸部X光 2026-08-02：no active lesion"


def test_a_das28_component_is_read_with_its_system() -> None:
    lake = _Lake()
    for oid, code, system, value in (
        ("o1", "4537-7", LOINC, 30.0),
        ("o2", "TJC28", derived.CODES["tjc28"][0], 4.0),
        ("o3", "SJC28", derived.CODES["sjc28"][0], 3.0),
        ("o4", "PTGA", derived.CODES["ptga"][0], 50.0),
        ("o5", "TJC28", HOUSE, 28.0),  # the same string under a house system, newer: not a joint count
    ):
        when = "2026-09-20 09:00:00" if oid != "o5" else "2026-09-25 09:00:00"
        lake.add("observation", oid, "P1", code, system, None, value, "mm/h" if code == "4537-7" else None, when)
    f = facts.collect(lake, RA_BIO, "P1", RUN)  # type: ignore[arg-type]
    assert f.das28[0]["tjc"] == "4" and f.das28[0]["date"] == "2026-09-20"


# ------------------------------------------------------------------------------------------------ review of #426
def test_the_twpas_bundles_own_lookups_match_the_system_too() -> None:
    """H1: weight, height and the EGFR mutation result of a TWPAS bundle were read by code alone
    (``twpas._latest``). A newer house row with the code string of body weight gave 6.1 kg for 61 kg; a house
    "EGFR-MUT" alone gave "mutation present"."""
    from types import SimpleNamespace

    from orchestrator.scenarios import twpas

    onc = Ruleset.load(ROOT / "rulesets" / "ONC-OSI")
    egfr_system = onc.valuesets["VS_EGFR_MUTATION"]["compose"]["include"][0]["system"]
    lake = _Lake()
    lake.add("observation", "w1", "P1", "29463-7", LOINC, None, 61.0, "kg", "2026-08-01 09:00:00")
    lake.add("observation", "w2", "P1", "29463-7", HOUSE, None, 6.1, "kg", "2026-09-01 09:00:00")
    lake.add("observation", "e1", "P1", "EGFR-MUT", HOUSE, "LA9633-4", None, None, "2026-09-01 09:00:00")
    ctx = SimpleNamespace(services=SimpleNamespace(lake=lake))
    assert twpas._latest(ctx, "P1", LOINC, "29463-7", RUN) == (61.0, "2026-08-01")  # type: ignore[arg-type]
    assert twpas._latest(ctx, "P1", egfr_system, "EGFR-MUT", RUN, "value_code") == (None, None)  # type: ignore[arg-type]
    lake.add("observation", "e2", "P1", "EGFR-MUT", egfr_system, "LA9634-2", None, None, "2026-08-15 09:00:00")
    got = twpas._latest(ctx, "P1", egfr_system, "EGFR-MUT", RUN, "value_code")  # type: ignore[arg-type]
    assert got == ("LA9634-2", "2026-08-15")
    assert (egfr_system, "EGFR-MUT") == twpas.EGFR_MUT  # the bundle reads the result the criteria read


def test_a_value_set_include_with_no_system_matches_nothing() -> None:
    """L3: an include without a system gave the pair "|code", which a lake row with an empty system matched."""
    import copy

    rs = copy.deepcopy(RA_BIO)
    del rs.valuesets["VS_HBSAG"]["compose"]["include"][0]["system"]
    assert facts._pairs(rs, "VS_HBSAG") == []
