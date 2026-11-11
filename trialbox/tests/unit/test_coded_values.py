"""T-514 (D-362, review UX-008): a coded answer carries the record's own value, unit, date and code.

The matching output record: ``matching.coded_values.attach`` reads, after every answer is decided, the records a
coded answer rests on and puts them on ``evidence.coded`` (latest first, at most three). It never changes a verdict.
The pages that show it are tested in ``tests/console/test_coded_criterion_row.py``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from lake.client import LakeLocal
from lake.flatten import SCHEMAS
from matching import coded_values as cv
from matching.cascade.engine import CascadeConfig, run_cascade
from orchestrator.scenarios.screen_cascade import verdicts_of
from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow, CriterionIR, CriterionVerdict, Evidence

from tests.offlist_fixture import build_lake, index_date, offlist_ruleset

ROOT = Path(__file__).resolve().parents[2]
RUN = date(2026, 10, 5)


class DuckLake:
    """The lake's query interface over an in-memory DuckDB holding the lake tables (``lake.flatten.SCHEMAS``)."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.con = duckdb.connect()
        self.calls = 0
        for table, cols in SCHEMAS.items():
            self.con.execute(f'CREATE TABLE "{table}" ({", ".join(f'"{n}" {t}' for n, t in cols)})')
            for r in rows.get(table, []):
                names = list(r)
                self.con.execute(
                    f'INSERT INTO "{table}" ({", ".join(f'"{n}"' for n in names)}) VALUES ({", ".join("?" for _ in names)})',
                    [r[n] for n in names],
                )

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        self.calls += 1
        return self.con.execute(sql, params or []).to_arrow_table()


def crit(cid: str, logic: dict[str, Any], kind: str = "inclusion", cls: str = "structured") -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "T", "kind": kind, "class": cls, "text": cid, "logic": logic}
    )


BMI = crit("T-INC-01", {"domain": "observation", "quantifier": "latest", "valueset": "VS_BMI",
                        "value": {"op": ">=", "num": 27, "unit": "kg/m2"}})  # fmt: skip
GOUT = crit("T-INC-02", {"domain": "condition", "quantifier": "any", "valueset": "VS_GOUT"})
AGE = crit("T-INC-03", {"domain": "demographic", "quantifier": "any", "valueset": "NONE", "age": {"min": 18}})
CANCER = crit("T-EXC-01", {"domain": "condition", "quantifier": "any", "valueset": "VS_MAL"}, kind="exclusion")
NOTE = crit("T-INC-04", {"domain": "condition", "quantifier": "any", "valueset": "VS_GOUT"}, cls="note")
ULT = crit("T-INC-05", {"domain": "medication", "quantifier": "any", "valueset": "VS_ULT"})
CREA = crit("T-EXC-02", {"domain": "observation", "quantifier": "latest", "valueset": "VS_CREA",
                         "value": {"op": ">", "num": 2, "unit": "mg/dL"}}, kind="exclusion")  # fmt: skip

LAKE: dict[str, list[dict[str, Any]]] = {
    "patient": [{"pid": "P1", "birth_date": date(1961, 11, 20), "sex": "female"}],
    "observation": [
        {"oid": "o-bmi-1", "pid": "P1", "code": "39156-5", "system": "http://loinc.org",
         "effective": "2025-04-01 09:00:00", "value_num": 26.0, "unit": "kg/m2"},
        {"oid": "o-bmi-2", "pid": "P1", "code": "39156-5", "system": "http://loinc.org",
         "effective": "2026-09-12 09:00:00", "value_num": 29.4, "unit": "kg/m2"},
        # the record's own unit (µmol/L), never a converted number (STD-001); a censored result keeps "<"
        {"oid": "o-crea", "pid": "P1", "code": "14682-9", "system": "http://loinc.org",
         "effective": "2026-10-01 08:00:00", "value_num": 88.0, "unit": "umol/L"},
        {"oid": "o-crp", "pid": "P1", "code": "1988-5", "system": "http://loinc.org",
         "effective": "2026-10-01 08:00:00", "value_num": 0.3, "unit": "mg/dL", "value_cmp": "<"},
    ],
    "condition": [
        {"cid": f"c-{i}", "pid": "P1", "code": "M10.9", "system": "http://hl7.org/fhir/sid/icd-10-cm",
         "onset": date(2025, 10, i), "recorded": None}
        for i in range(1, 6)
    ],
    "medication": [{"mid": "m-1", "pid": "P1", "atc": "M04AA01", "nhi_code": "AC00001", "authored": date(2026, 8, 1)}],
}  # fmt: skip


def verdict(c: CriterionIR, v: str, refs: list[str] | None = None, **ev: Any) -> CriterionVerdict:
    return CriterionVerdict(id=c.id, verdict=v, evidence=Evidence(resource_refs=refs or [], reason="coded", **ev))  # type: ignore[arg-type]


def coded(v: CriterionVerdict) -> list[dict[str, Any]] | None:
    assert v.evidence is not None
    return None if v.evidence.coded is None else [x.model_dump(exclude_none=True) for x in v.evidence.coded]


def test_a_coded_answer_carries_the_records_value_unit_date_and_code() -> None:
    lake = DuckLake(LAKE)
    vs = [
        verdict(BMI, "pass", ["o-bmi-2|2026-09-12"]),
        verdict(GOUT, "pass", [f"Condition/c-{i}|2025-10-0{i}" for i in range(1, 6)]),  # v1 refs: type/id|date
        verdict(ULT, "pass", ["m-1"]),  # cascade refs: the bare id
        verdict(CREA, "pass", ["o-crea"]),
    ]
    before = [v.verdict for v in vs]
    assert cv.attach(lake, [BMI, GOUT, ULT, CREA], {"P1": vs}, RUN, None) == 4
    assert [v.verdict for v in vs] == before  # display only: no verdict moves
    assert lake.calls == 1  # one read for the whole run
    assert coded(vs[0]) == [{"record": "o-bmi-2", "domain": "observation", "code": "39156-5",
                             "system": "http://loinc.org", "date": "2026-09-12", "value": 29.4, "unit": "kg/m2"}]  # fmt: skip
    gout = coded(vs[1]) or []
    assert [x["record"] for x in gout] == ["c-5", "c-4", "c-3"]  # latest first, at most three
    assert gout[0] == {"record": "c-5", "domain": "condition", "code": "M10.9",
                       "system": "http://hl7.org/fhir/sid/icd-10-cm", "date": "2025-10-05"}  # fmt: skip
    assert coded(vs[2]) == [{"record": "m-1", "domain": "medication", "code": "M04AA01",
                             "system": "http://www.whocc.no/atc", "date": "2026-08-01"}]  # fmt: skip
    assert (coded(vs[3]) or [])[0]["value"] == 88.0 and (coded(vs[3]) or [])[0]["unit"] == "umol/L"


def test_a_censored_result_keeps_its_comparator() -> None:
    vs = {"P1": [verdict(CREA, "pass", ["o-crp"])]}
    cv.attach(DuckLake(LAKE), [CREA], vs, RUN, None)
    assert (coded(vs["P1"][0]) or [])[0]["comparator"] == "<"


def test_age_and_sex_come_from_the_patient_row_on_the_run_date() -> None:
    sex = crit("T-INC-06", {"domain": "demographic", "quantifier": "any", "valueset": "NONE", "sex": "female"})
    vs = [verdict(AGE, "pass"), verdict(sex, "pass")]
    cv.attach(DuckLake(LAKE), [AGE, sex], {"P1": vs}, RUN, None)
    # born 1961-11-20: 64 on 2026-10-05, 65 in November
    assert coded(vs[0]) == [{"record": "patient", "domain": "demographic", "code": "age", "date": "2026-10-05",
                             "value": 64.0}]  # fmt: skip
    assert coded(vs[1]) == [{"record": "patient", "domain": "demographic", "code": "sex", "value_code": "female"}]
    assert cv.age_on(date(1961, 11, 20), date(2026, 11, 20)) == 65


def test_a_coded_answer_with_no_record_says_so_and_notes_are_left_alone() -> None:
    vs = [
        verdict(CANCER, "pass"),  # no record carries the exclusion's codes
        verdict(GOUT, "fail"),  # an inclusion not met for lack of a record
        verdict(NOTE, "pass", ["DocumentReference/d1"], quote="gout flare", quote_date="2026-04-02"),
        verdict(GOUT, "unknown"),  # nothing decided: nothing to say
    ]
    assert cv.attach(DuckLake(LAKE), [CANCER, GOUT, NOTE], {"P1": vs}, RUN, None) == 0
    assert coded(vs[0]) == [] and coded(vs[1]) == []  # looked: nothing behind it
    assert coded(vs[2]) is None and coded(vs[3]) is None


def test_a_failing_lake_read_changes_nothing() -> None:
    class Down:
        def query(self, *a: Any, **k: Any) -> Any:
            raise OSError("lake down")

    vs = [verdict(BMI, "pass", ["o-bmi-2"])]
    assert cv.attach(Down(), [BMI], {"P1": vs}, RUN, None) == 0
    assert coded(vs[0]) is None


def test_the_record_ids_of_both_engines() -> None:
    assert cv.record_id("Observation/o-1|2026-09-12") == "o-1"
    assert cv.record_id("o-1|2026-09-12") == "o-1" and cv.record_id("c-old|") == "c-old" and cv.record_id("m") == "m"


def test_the_candidate_row_keeps_the_values() -> None:
    vs = [verdict(BMI, "pass", ["o-bmi-2"])]
    cv.attach(DuckLake(LAKE), [BMI], {"P1": vs}, RUN, None)
    row = CandidateRow(pid="P1", tier="high", criteria=vs, actions=[])
    again = CandidateRow.model_validate_json(row.model_dump_json())
    assert again.criteria[0].evidence is not None and again.criteria[0].evidence.coded is not None
    assert again.criteria[0].evidence.coded[0].value == 29.4


# ---------------------------------------------------------------------------------------------- on a real lake
@pytest.fixture(scope="module")
def offlist(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from embed_service.embedder import HashEmbedder

    crit_, vs, vsi, expected = offlist_ruleset()
    sql = SqlGenerator("OFFL", "1.0.0", vsi).render(crit_)
    lake = LakeLocal(build_lake(tmp_path_factory.mktemp("coded-lake")), HashEmbedder())
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "OFFL", "library": None, "criteria": [c.id for c in crit_]})
    return {"rs": Ruleset(manifest=manifest, criteria=crit_, valuesets=vs, sql=sql), "lake": lake, "exp": expected}


def test_the_cascade_answers_carry_codes_and_dates_on_a_real_lake(offlist: dict[str, Any]) -> None:
    rs, lake, exp = offlist["rs"], offlist["lake"], offlist["exp"]
    cfg = CascadeConfig(study_id="OFFL", run_date=index_date(exp), index_mode="single",
                        population=sorted(exp["compiled"]), semantics="v1", snapshot=None)  # fmt: skip
    res = run_cascade(lake, rs, cfg)
    results = {pid: verdicts_of(rs, t) for pid, t in res.traces.items() if t.in_scope}
    verdicts = {pid: pv.verdicts for pid, pv in results.items()}
    before = {pid: [v.verdict for v in vs] for pid, vs in verdicts.items()}
    assert cv.attach(lake, rs.active(), verdicts, index_date(exp), None) > 0
    assert {pid: [v.verdict for v in vs] for pid, vs in verdicts.items()} == before
    decided = [v for vs in verdicts.values() for v in vs if v.verdict in ("pass", "fail")]
    assert decided
    for v in decided:  # the acceptance of T-514: no met / not met row without a value (here: a code) or a quote
        assert v.evidence is not None
        assert v.evidence.quote or v.evidence.coded is not None, v
        for x in v.evidence.coded or []:
            assert x.code and x.system and x.domain in ("condition", "medication"), x
    with_codes = [x for v in decided for x in v.evidence.coded or []]  # type: ignore[union-attr]
    assert with_codes and all(x.date for x in with_codes if x.domain == "medication")
