"""R3 item 3 (RULES-ARCH §5): value.ref against the result's range, else the signed site table, else no answer with
the reason no_reference_range; study anchors, value_if and on_hit in the SQL and the CQL. The SQL runs in DuckDB on
synthetic rows; the CQL is read as text (no FHIR store here; the translator check is in the pull request)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

import duckdb
import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import NO_REFERENCE_RANGE, CompileError, RefRangeRow, SiteRefRanges
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from tb_contracts.criterion_ir import CriterionIRv3

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
INDEX = date(2026, 10, 5)
LOINC = "http://loinc.org"
ICD = "http://hl7.org/fhir/sid/icd-10"
VS = {
    "VS_ALT": {"url": "urn:tb:vs:VS_ALT", "compose": {"include": [{"system": LOINC, "concept": [{"code": "1742-6"}]}]}},
    "VS_BNP": {"url": "urn:tb:vs:VS_BNP", "compose": {"include": [{"system": LOINC, "concept": [{"code": "33762-6"}]}]}},
    "VS_AF": {"url": "urn:tb:vs:VS_AF", "compose": {"include": [{"system": ICD, "concept": [{"code": "I48"}]}]}},
}  # fmt: skip


def table(*rows: tuple[Literal["male", "female"] | None, float]) -> SiteRefRanges:
    """A signed synthetic table for ALT in U/L: (sex, high) per row."""
    return SiteRefRanges("pi@site.test", "2026-11-27", tuple(RefRangeRow(LOINC, "1742-6", "U/L", s, None, h)
                                                               for s, h in rows))  # fmt: skip


def crit(atoms: list[dict[str, Any]], logic: Any = "a1", kind: str = "exclusion") -> CriterionIRv3:
    return CriterionIRv3.model_validate({
        "ir_version": "3.1.0", "id": "SYN-EXC-01", "ruleset": "SYN", "kind": kind, "class": "structured",
        "text": {"source": "synthetic"}, "logic": logic, "atoms": atoms,
    })  # fmt: skip


def alt_uln(multiple: float = 3, **extra: Any) -> dict[str, Any]:
    return {"id": "a1", "domain": "observation", "valueset": "VS_ALT", "quantifier": "latest",
            "value": {"op": ">", "ref": {"kind": "uln", "multiple": multiple}},
            "window": {"from_days": -180, "to_days": 0}, **extra}  # fmt: skip


def sql(c: CriterionIRv3, ref: SiteRefRanges | None = None) -> str:
    return SqlGenerator("SYN", "1.0.0", ValueSets("SYN", VS, Terminology()), ref).render([c])


def cql(c: CriterionIRv3, ref: SiteRefRanges | None = None) -> str:
    return CqlGenerator("SYN", "1.0.0", ValueSets("SYN", VS, Terminology()), 36, ref).render([c])


@pytest.fixture
def db() -> Any:
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE patient AS SELECT 'p' pid, DATE '1970-01-01' birth_date, 'female' sex,
            NULL::DATE deceased_date, false deceased;
        CREATE TABLE observation (oid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, effective TIMESTAMP,
            value_num DOUBLE, unit VARCHAR, value_code VARCHAR, value_cmp VARCHAR);
        CREATE TABLE condition (cid VARCHAR, pid VARCHAR, system VARCHAR, code VARCHAR, onset DATE, recorded DATE,
            status VARCHAR);
        CREATE TABLE measurement (measurement_id INTEGER, person_id INTEGER, measurement_source_value VARCHAR,
            value_as_number DOUBLE, range_high DOUBLE, range_low DOUBLE);
        CREATE TABLE tb_id_map (id_kind VARCHAR, omop_id INTEGER, source_id VARCHAR);
        CREATE TABLE tb_record (cdm_table VARCHAR, record_id INTEGER, source_record_id VARCHAR, part INTEGER,
            status VARCHAR);
    """)
    yield con
    con.close()


def obs(db: Any, value: float, unit: str = "U/L", code: str = "1742-6", oid: str = "o1") -> None:
    db.execute("INSERT INTO observation VALUES (?, 'p', ?, ?, TIMESTAMP '2026-10-01', ?, ?, NULL, NULL)",
               [oid, code, LOINC, value, unit])  # fmt: skip


def run(db: Any, text: str) -> tuple[bool | None, str | None]:
    row = db.execute(text, [[INDEX], None]).fetchone()
    return row[2], row[3]


# ------------------------------------------------------------------ value.ref
def test_the_signed_site_table_decides_when_the_result_has_no_range(db: Any) -> None:
    c = crit([alt_uln()])
    obs(db, 150)
    assert run(db, sql(c, table((None, 40)))) == (True, "o1|2026-10-01")  # 150 > 3 x 40
    db.execute("UPDATE observation SET value_num = 100")
    assert run(db, sql(c, table((None, 40))))[0] is False  # 100 <= 120
    db.execute("UPDATE observation SET value_num = 121, unit = 'u/l'")  # another spelling of the same unit key
    assert run(db, sql(c, table((None, 40))))[0] is True


@pytest.mark.parametrize("site", [None, "other_unit", "other_code"])
def test_no_bound_is_unknown_with_the_reason(db: Any, site: str | None) -> None:
    c = crit([alt_uln()])
    obs(db, 900, unit="mg/dL" if site == "other_unit" else "U/L")
    ref = None if site is None else table((None, 40))
    if site == "other_code":
        ref = SiteRefRanges("pi@site.test", "2026-11-27", (RefRangeRow(LOINC, "1920-8", "U/L", None, None, 40),))
    v, ev = run(db, sql(c, ref))
    assert v is None and ev is not None and ev.startswith(NO_REFERENCE_RANGE + ";")


def test_a_sex_specific_row_before_the_row_for_both(db: Any) -> None:
    c = crit([alt_uln()])
    obs(db, 110)
    sexed = table(("male", 45), ("female", 35))
    assert run(db, sql(c, sexed))[0] is True  # female: 110 > 105
    db.execute("UPDATE patient SET sex = 'male'")
    assert run(db, sql(c, sexed))[0] is False  # male: 110 <= 135
    db.execute("UPDATE patient SET sex = 'other'")
    assert run(db, sql(c, sexed))[0] is None  # no row for this sex and none for both
    assert run(db, sql(c, table(("male", 45), (None, 30))))[0] is True  # the row for both: 110 > 90


def test_the_results_own_range_comes_before_the_site_table(db: Any) -> None:
    c = crit([alt_uln()])
    obs(db, 150)
    db.execute("INSERT INTO tb_id_map VALUES ('person', 1, 'p')")
    db.execute("INSERT INTO tb_record VALUES ('measurement', 1, 'o1', 0, 'coded')")
    db.execute("INSERT INTO measurement VALUES (1, 1, '1742-6', 150, 60, 5)")
    assert run(db, sql(c, table((None, 40))))[0] is False  # its own ULN 60: 150 <= 180, the table's 40 not used
    db.execute("UPDATE measurement SET range_high = NULL")
    assert run(db, sql(c, table((None, 40))))[0] is True  # no range of its own: the table's 40


def test_the_lln_side_reads_low() -> None:
    lo = SiteRefRanges("pi@site.test", "2026-11-27", (RefRangeRow(LOINC, "1742-6", "U/L", None, 7, 40),))
    text = sql(crit([alt_uln() | {"value": {"op": "<", "ref": {"kind": "lln", "multiple": 0.5}}}]), lo)
    assert "THEN 7 END" in text and "(o.ref_bound * 0.5)" in text


def test_an_unsigned_or_malformed_table_is_refused(tmp_path: Path) -> None:
    good = {"signed": {"by": "pi@site.test", "at": "2026-11-27"},
            "ranges": [{"system": LOINC, "code": "1742-6", "unit": "U/L", "high": 40}]}  # fmt: skip
    p = tmp_path / "ranges.json"
    p.write_text(json.dumps(good), "utf-8")
    assert SiteRefRanges.load(p).rows == (RefRangeRow(LOINC, "1742-6", "U/L", None, None, 40),)
    for bad in (
        {**good, "signed": {"by": "pi@site.test"}},
        {**good, "signed": {"by": " ", "at": "2026-11-27"}},
        {**good, "ranges": [{"system": LOINC, "code": "1742-6", "unit": "U/L"}]},
        {**good, "ranges": [{"system": LOINC, "code": "1742-6", "unit": "U/L", "high": float("inf")}]},
        {**good, "ranges": [{"system": LOINC, "code": "1742-6", "unit": "U/L", "high": 40, "sex": "f"}]},
    ):
        p.write_text(json.dumps(bad), "utf-8")
        with pytest.raises(ValueError):
            SiteRefRanges.load(p)


def test_value_ref_in_cql_uses_the_same_table() -> None:
    c = crit([alt_uln()])
    text = cql(c, table(("female", 35), (None, 40)))
    assert "TB.UnitKey(X.value as FHIR.Quantity) = 'u/l' and Patient.gender.value = 'female' then 35.0" in text
    assert "then 40.0 else null end) * 3)" in text and "120" not in text
    assert "(X.value as FHIR.Quantity).value.value" in text  # the result's own number, no unit conversion
    assert "((null as Decimal) * 3)" in cql(c)  # no table: never a number


# ------------------------------------------------------------------ on_hit
def test_on_hit_review_sends_a_met_atom_to_a_person(db: Any) -> None:
    c = crit([{"id": "a1", "domain": "observation", "valueset": "VS_ALT", "quantifier": "latest",
               "value": {"op": ">", "num": 120, "unit": "U/L"}, "on_hit": "review"}])  # fmt: skip
    obs(db, 150)
    assert run(db, sql(c))[0] is None  # met: a person decides, never excluded by the box
    db.execute("UPDATE observation SET value_num = 100")
    assert run(db, sql(c))[0] is False
    assert ") and (null as Boolean)" in cql(c)


# ------------------------------------------------------------------ value_if
def _bnp() -> CriterionIRv3:
    return crit(
        [
            {"id": "a1", "domain": "observation", "valueset": "VS_BNP", "quantifier": "latest",
             "value": {"op": ">=", "num": 1600, "unit": "pg/mL"},
             "value_if": [{"if_atom": "af", "value": {"op": ">=", "num": 2400, "unit": "pg/mL"}}]},
            {"id": "af", "domain": "condition", "valueset": "VS_AF"},
        ],
        kind="inclusion",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("af", "value", "expected"),
    [
        ("dated", 2000, False),  # in atrial fibrillation the cut-off is 2400
        ("dated", 2500, True),
        ("none", 2000, True),  # without it, 1600
        ("none", 1500, False),
        ("undated", 3000, True),  # unknown AF: both cut-offs agree
        ("undated", 1000, False),
        ("undated", 2000, None),  # they disagree: unknown
    ],
)
def test_value_if_takes_the_conditional_threshold(db: Any, af: str, value: float, expected: bool | None) -> None:
    obs(db, value, unit="pg/mL", code="33762-6")
    if af != "none":
        onset = "DATE '2020-01-01'" if af == "dated" else "NULL"
        db.execute(f"INSERT INTO condition VALUES ('c1', 'p', '{ICD}', 'I48', {onset}, NULL, NULL)")
    assert run(db, sql(_bnp()))[0] is expected


def test_value_if_in_cql_is_the_same_logic() -> None:
    text = cql(_bnp())
    assert ">= 2400" in text and ">= 1600" in text
    assert text.count('[Condition: "VS_AF"]') >= 2 and " or " in text and "(not " in text


def test_value_if_that_refers_back_is_refused() -> None:
    loop = crit([
        {"id": "a1", "domain": "observation", "valueset": "VS_BNP", "value": {"op": ">", "num": 1},
         "value_if": [{"if_atom": "a2", "value": {"op": ">", "num": 2}}]},
        {"id": "a2", "domain": "observation", "valueset": "VS_BNP", "value": {"op": ">", "num": 1},
         "value_if": [{"if_atom": "a1", "value": {"op": ">", "num": 3}}]},
    ])  # fmt: skip
    for render in (sql, cql):
        with pytest.raises(CompileError, match="refer back"):
            render(loop)


def test_value_if_without_the_atoms_own_value_is_refused() -> None:
    bare = crit([
        {"id": "a1", "domain": "observation", "valueset": "VS_BNP", "quantifier": "latest",
         "value_if": [{"if_atom": "a2", "value": {"op": ">", "num": 2}}]},
        {"id": "a2", "domain": "condition", "valueset": "VS_AF"},
    ])  # fmt: skip
    for render in (sql, cql):
        with pytest.raises(CompileError, match="needs the atom's own value"):
            render(bare)


# ------------------------------------------------------------------ study anchors in CQL
@pytest.mark.parametrize(("anchor", "param"), [("screening", "ScreeningDate"), ("randomization", "RandomizationDate")])
def test_study_anchor_is_a_cql_parameter(anchor: str, param: str) -> None:
    c = crit([{"id": "a1", "domain": "condition", "valueset": "VS_AF",
               "window": {"from_days": -30, "to_days": 0, "anchor": anchor}}])  # fmt: skip
    text = cql(c)
    assert f"\nparameter {param} Date\n" in text
    assert f"Interval[{param} - 30 days, {param}]" in text and f"if {param} is null then null as Boolean" in text
    assert "IndexDate - 30 days" not in text
    assert f"b.{anchor}_date" in sql(c)  # the SQL reads the same date from criterion_anchors


def test_medication_detail_stays_sql_only() -> None:
    c = crit([{"id": "a1", "domain": "medication", "valueset": "VS_AF", "medication": {"route": ["4132161"]}}])
    assert '"C_SYN-EXC-01"' in sql(c)
    with pytest.raises(CompileError, match="medication route and dose are not compiled to CQL"):
        cql(c)


# ------------------------------------------------------------------ GZQO-EXC-13 in v3, the first use
def test_gzqo_exc_13_in_v3_compiles_against_the_reference_range(db: Any) -> None:
    """The v3 form of the approved criterion (docs/handover/cx-ir31): 3 x the ULN instead of the typed 120 U/L. Not
    the shipped ruleset, which stays v1 until its move is ruled (REPORT question)."""
    rdir = ROOT / "rulesets" / "GZQO"
    vs = {p.stem: json.loads(p.read_text("utf-8")) for p in (rdir / "valuesets").glob("*.json")}
    v3 = CriterionIRv3.model_validate_json((ROOT / "docs/handover/cx-ir31/GZQO-EXC-13-v3.json").read_text("utf-8"))
    vsi = ValueSets("GZQO", vs, Terminology())
    t = table((None, 40))
    text = SqlGenerator("GZQO", "3.0.0", vsi, t).render([v3])
    assert "(o.ref_bound * 3)" in text and "> 120" not in text
    assert "* 3)" in CqlGenerator("GZQO", "3.0.0", vsi, 36, t).render([v3])
    for value, expected in ((150, True), (120, False), (119, False)):  # with ULN 40 the typed 120 and 3 x ULN agree
        db.execute("DELETE FROM observation")
        obs(db, value)
        assert db.execute(text, [[INDEX], None]).fetchone()[2] is expected
