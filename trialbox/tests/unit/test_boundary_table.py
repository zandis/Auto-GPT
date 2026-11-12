"""The three-engine boundary table (T-711, D-480): the Python reference, the generated SQL and CQL on the edges.

The unit job runs the reference against SQL (an in-process lake, no JDK). The CQL third runs here when the local
engine is fetched, and always in the CI job ``differential`` (``python -m tools.boundary_check``).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from criteria_compiler.equivalence import boundary
from criteria_compiler.equivalence.boundary import Case, Table
from tb_common import derived

from tools import boundary_check, cql_eval


@pytest.fixture(scope="module")
def table() -> Table:
    return boundary_check.table()


def test_the_table_covers_every_kind_of_edge(table: Table) -> None:
    """Not vacuous: every group has cases, every answer occurs, and the edges the card names are there."""
    groups = Counter(c.group for c in table.cases)
    assert set(groups) == set(boundary.GROUPS) and min(groups.values()) >= 3
    assert {c.expected for c in table.cases} == {True, False, None}
    for g in ("age", "window", "score", "unit"):
        assert {True, False} <= {c.expected for c in table.cases if c.group == g}, g
    assert {c.expected for c in table.cases if c.group == "impossible"} <= {None, False}
    assert {c.ruleset for c in table.cases} == set(boundary.RULESETS)
    by = {c.key: c for c in table.cases}
    assert len(by) == len(table.cases) >= 70  # one case per patient, criterion and index date
    # the birthday and the day before; 29 February in a common and in a leap year
    assert by["GZQO/GZQO-INC-01/b-age-18-today@2026-10-05"].expected is True
    assert by["GZQO/GZQO-INC-01/b-age-18-tomorrow@2026-10-05"].expected is False
    assert by["GZQO/GZQO-INC-01/b-age-feb29-common@2026-02-28"].expected is False
    assert by["GZQO/GZQO-INC-01/b-age-feb29-common@2026-03-01"].expected is True
    assert by["RA-JAK/RA-JAK-INC-01/b-age-feb29-76-leap@2028-02-28"].expected is True
    assert by["RA-JAK/RA-JAK-INC-01/b-age-feb29-76-leap@2028-02-29"].expected is False
    # both ends of a window, and the day boundary in the site's zone
    assert by["GZQO/GZQO-EXC-13/b-win-first-day@2026-10-05"].expected is True
    assert by["GZQO/GZQO-EXC-13/b-win-day-before@2026-10-05"].expected is None
    assert by["GZQO/GZQO-EXC-13/b-win-last-day@2026-10-05"].expected is True
    assert by["GZQO/GZQO-EXC-13/b-win-day-after@2026-10-05"].expected is None
    assert by["GZQO/GZQO-EXC-13/b-zone-open-utc@2026-10-05"].expected is True
    assert by["GZQO/GZQO-EXC-13/b-zone-after-utc@2026-10-05"].expected is None
    scores = {c.criterion for c in table.cases if c.group == "score"}
    assert {"GZQO-INC-03", "GZQO-INC-08", "RA-JAK-EXC-11", "AD-MAB-EXC-04", "RA-BIO-INC-05"} <= scores


def test_the_cases_are_synthetic_and_each_patient_is_one_case_subject(table: Table) -> None:
    for rid, res in table.resources.items():
        pids = [r["id"] for r in res if r["resourceType"] == "Patient"]
        assert len(pids) == len(set(pids)) and all(p.startswith("b-") for p in pids), rid
        assert {c.pid for c in table.of(rid)} == set(pids)
        assert not any("name" in r or "identifier" in r or "telecom" in r for r in res)


def test_the_utc_cases_are_another_day_in_the_site_zone(table: Table) -> None:
    """The zone cases are real edges: the UTC calendar day of the instant is not the site's."""
    alt = [r for r in table.resources["GZQO"] if r["resourceType"] == "Observation" and "b-zone-" in r["id"]]
    assert len(alt) == 3 and all(r["effectiveDateTime"].endswith("Z") for r in alt)
    other_day = {r["id"] for r in alt if date.fromisoformat(r["effectiveDateTime"][:10])
                 != boundary._site_day(r["effectiveDateTime"])}  # fmt: skip
    assert other_day == {"b-zone-open-utc-o1", "b-zone-after-utc-o1"}  # the third is late on the index date


def test_the_generated_sql_answers_as_the_python_reference(
    table: Table, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half that needs no JDK, through the tool itself: every case through the ruleset's SQL on a lake built by
    the ingest's steps. The only differences are the known ones, by name."""
    out = tmp_path / "differential.json"
    assert boundary_check.main(["--no-cql", "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "differential: PASS" in printed and "known: GZQO/GZQO-INC-03/b-bmi-height-zero" in printed
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cases"] == len(table.cases) and report["engines"] == ["sql"] and not report["problems"]
    parted = {r["case"] for r in report["rows"] if r["sql"] != r["reference"]}
    assert parted == {k for k, engine in boundary_check.KNOWN if engine == "sql"}


@pytest.mark.skipif(not cql_eval.available(), reason="local CQL engine not fetched (python -m tools.cql_eval --fetch)")
def test_cql_answers_as_the_python_reference_and_sql(table: Table) -> None:
    rs = boundary_check.rulesets()
    engines = {"sql": boundary_check.run_sql(table, rs), "cql": boundary_check.run_cql(table, rs)}
    report = boundary_check.compare(table, engines)
    assert not report["problems"], report["problems"]


# ------------------------------------------------------------------------------------------------ the comparison
def _one() -> tuple[Table, Case]:
    c = Case("b-x", "GZQO", "GZQO-INC-01", boundary.INDEX, True, "age", "an edge")
    return Table(cases=[c]), c


def test_a_disagreement_fails_the_gate() -> None:
    t, c = _one()
    assert not boundary_check.compare(t, {"sql": {c.key: True}, "cql": {c.key: True}}, known={})["problems"]
    for wrong in (False, None):
        report = boundary_check.compare(t, {"sql": {c.key: True}, "cql": {c.key: wrong}}, known={})
        assert len(report["problems"]) == 1 and "cql says" in report["problems"][0]


def test_a_known_difference_is_reported_and_is_strict() -> None:
    t, c = _one()
    known = {(c.key, "cql"): "B-0: a finding"}
    still = boundary_check.compare(t, {"sql": {c.key: True}, "cql": {c.key: None}}, known=known)
    assert not still["problems"] and still["known"] == [f"{c.key} [cql]: B-0: a finding"]
    fixed = boundary_check.compare(t, {"sql": {c.key: True}, "cql": {c.key: True}}, known=known)
    assert len(fixed["problems"]) == 1 and "remove its KNOWN line" in fixed["problems"][0]
    stale = boundary_check.compare(t, {"cql": {c.key: True}}, known={("GZQO/none/b-y@2026-10-05", "cql"): "B-0"})
    assert any("matches no case" in p for p in stale["problems"])


def test_every_known_line_names_a_case_and_a_finding(table: Table) -> None:
    keys = {c.key for c in table.cases}
    for (key, engine), why in boundary_check.KNOWN.items():
        assert key in keys and engine in ("sql", "cql") and why.startswith("B-"), (key, engine)


def test_an_engine_that_gives_no_answer_is_an_error_not_an_agreement(table: Table) -> None:
    out: dict[str, bool | None] = {}
    with pytest.raises(RuntimeError, match="gave no answer"):
        boundary_check._collect(out, table, "GZQO", boundary.INDEX, {})


# ------------------------------------------------------------------------------------------------ the reference
def test_a_height_of_zero_is_no_value_in_the_reference() -> None:
    """Found by the table: ``compute`` raised ZeroDivisionError although no input may make it raise."""
    on = date(2026, 9, 25)
    got = derived.compute("bmi", {"weight": [derived.Obs(70.0, "kg", on)], "height": [derived.Obs(0.0, "cm", on)]})
    assert got.value is None and got.reason == "derived_unit:height"
    ok = derived.compute("bmi", {"weight": [derived.Obs(70.0, "kg", on)], "height": [derived.Obs(170.0, "cm", on)]})
    assert ok.value == pytest.approx(24.22, abs=0.01)
