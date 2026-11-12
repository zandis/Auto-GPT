"""D-275 (safety review S-1, S-4, S-5, S-9; MR-002 / R-31): missing or unusable data never excludes a patient.

Every case is a synthetic record that was a hard exclusion (or a silent "not applicable") before the fix. The rows
go through the real path: FHIR NDJSON -> the lake's flattener -> the compiled SQL -> the SQL engine of NAV /
MICROBATCH / CASE and the SCREEN cascade. The shipped GZQO ruleset is run with its SQL as approved (compiled before
the fix), guarded by the current rules (``compile_sql.overlay``).
"""

from __future__ import annotations

import json
from datetime import UTC, date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import MARK, SqlGenerator
from criteria_compiler.compile_sql.overlay import safe_sql
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.flatten import Flattener
from lake.store import Lake
from matching.cascade.engine import CascadeConfig, run_cascade
from orchestrator.scenarios.evaluate import SqlEngine, structured_verdict
from orchestrator.scenarios.screen_cascade import verdicts_of
from tb_common import labunit
from tb_common.reasons import LABELS, Reason, code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
IDX = date(2026, 10, 5)

CREAT, HBA1C, PREG_TEST, EGFR_STORED = "2160-0", "4548-4", "2106-3", "33914-3"
ULT, GLP1 = "M04AA01", "A10BJ02"


NOT_RECORDED_TAG = {"tag": [{"system": "urn:trialbox:status-source", "code": "not-recorded"}]}


def _pat(pid: str, gender: str | None = "female") -> dict[str, Any]:
    p: dict[str, Any] = {"resourceType": "Patient", "id": pid, "birthDate": "1971-03-01"}
    if gender is not None:
        p["gender"] = gender
    return p


def _obs(
    pid: str, n: int, code: str, value: float, unit: str | None, day: str = "2026-09-20", status: str | None = "final"
) -> dict[str, Any]:
    q: dict[str, Any] = {"value": value}
    if unit is not None:
        q["unit"] = unit
    o: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"o-{pid}-{n}",
        "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": LOINC, "code": code}]},
        "effectiveDateTime": f"{day}T09:00:00+08:00",
        "valueQuantity": q,
    }
    if status is not None:
        o["status"] = status
    return o


def _coded_obs(pid: str, n: int, code: str, answer: str, day: str = "2026-09-25") -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": f"o-{pid}-{n}",
        "status": "final",
        "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": LOINC, "code": code}]},
        "effectiveDateTime": f"{day}T09:00:00+08:00",
        "valueCodeableConcept": {"coding": [{"system": LOINC, "code": answer}]},
    }


def _med(
    pid: str,
    n: int,
    atc: str,
    authored: str | None,
    start: str | None = None,
    end: str | None = None,
    status: str = "active",
) -> dict[str, Any]:
    m: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": f"m-{pid}-{n}",
        "status": status,
        "intent": "order",
        "subject": {"reference": f"Patient/{pid}"},
        "medicationCodeableConcept": {"coding": [{"system": ATC, "code": atc}]},
    }
    if authored:
        m["authoredOn"] = authored
    period = {k: v for k, v in (("start", start), ("end", end)) if v}
    if period:
        m["dispenseRequest"] = {"validityPeriod": period}
    return m


# pid -> (gender, [resources]); every pid is a case named in the assertions below
CASES: dict[str, tuple[str | None, list[dict[str, Any]]]] = {
    # ---- S-1: creatinine against "<= 1.5 mg/dL"
    "U-OK": ("female", [_obs("U-OK", 1, CREAT, 1.0, "mg/dL")]),
    "U-HIGH": ("female", [_obs("U-HIGH", 1, CREAT, 2.0, "mg/dL")]),
    "U-UMOL": ("female", [_obs("U-UMOL", 1, CREAT, 90, "umol/L")]),  # 1.02 mg/dL: was FALSE -> excluded
    "U-UMOL-MICRO": ("female", [_obs("U-UMOL-MICRO", 1, CREAT, 90, "µmol/L")]),
    "U-UMOL-HIGH": ("female", [_obs("U-UMOL-HIGH", 1, CREAT, 200, "umol/L")]),  # 2.26 mg/dL: a true failure
    "U-NOUNIT": ("female", [_obs("U-NOUNIT", 1, CREAT, 90, None)]),  # no unit: was FALSE -> excluded
    "U-ODD": ("female", [_obs("U-ODD", 1, CREAT, 90, "nmol/mL")]),  # a unit nobody converts: unknown
    # a text result ("2.0 H") has no unit: read as a number (D-142), not compared with mg/dL (was FALSE)
    "U-TEXT": (
        "female",
        [
            {k: v for k, v in _obs("U-TEXT", 1, CREAT, 0, None).items() if k != "valueQuantity"}
            | {"valueString": "2.0 H"}
        ],
    ),
    # ---- S-1: HbA1c against the exclusion "> 10 %"
    "H-IFCC": ("female", [_obs("H-IFCC", 1, HBA1C, 53, "mmol/mol")]),  # 7.0 % NGSP: was TRUE -> excluded
    "H-PCT-HIGH": ("female", [_obs("H-PCT-HIGH", 1, HBA1C, 11.0, "%")]),
    "H-PCT-OK": ("female", [_obs("H-PCT-OK", 1, HBA1C, 7.0, "%")]),
    # ---- S-4: a result entered in error (9.0, five days ago) after a valid 1.0
    "V-ERR": (
        "female",
        [
            _obs("V-ERR", 1, CREAT, 1.0, "mg/dL", day="2026-09-15"),
            _obs("V-ERR", 2, CREAT, 9.0, "mg/dL", day="2026-09-30", status="entered-in-error"),
        ],
    ),
    "V-CANCELLED-RX": ("female", [_med("V-CANCELLED-RX", 1, GLP1, "2026-09-20", status="cancelled")]),
    "V-ERROR-RX": ("female", [_med("V-ERROR-RX", 1, GLP1, "2026-09-20", status="entered-in-error")]),
    "V-ACTIVE-RX": ("female", [_med("V-ACTIVE-RX", 1, GLP1, "2026-09-20")]),
    "V-STOPPED-RX": ("female", [_med("V-STOPPED-RX", 1, GLP1, "2026-09-20", status="stopped")]),  # history counts
    # ---- S-5: sex
    "X-F": ("female", [_obs("X-F", 1, CREAT, 1.0, "mg/dL"), _coded_obs("X-F", 2, PREG_TEST, "LA6576-8")]),
    "X-M": ("male", [_obs("X-M", 1, CREAT, 1.0, "mg/dL"), _coded_obs("X-M", 2, PREG_TEST, "LA6576-8")]),
    "X-UNK": ("unknown", [_obs("X-UNK", 1, CREAT, 1.0, "mg/dL"), _coded_obs("X-UNK", 2, PREG_TEST, "LA6576-8")]),
    "X-OTHER": ("other", [_obs("X-OTHER", 1, CREAT, 1.0, "mg/dL"), _coded_obs("X-OTHER", 2, PREG_TEST, "LA6576-8")]),
    "X-NONE": (None, [_obs("X-NONE", 1, CREAT, 1.0, "mg/dL"), _coded_obs("X-NONE", 2, PREG_TEST, "LA6576-8")]),
    # ---- S-9: urate-lowering therapy for at least 90 days in the last 180
    "M-FULL": ("female", [_med("M-FULL", 1, ULT, "2026-05-01", "2026-05-01", "2026-09-30")]),
    "M-SHORT": ("female", [_med("M-SHORT", 1, ULT, "2026-09-01", "2026-09-01", "2026-09-10")]),
    "M-OPEN": ("female", [_med("M-OPEN", 1, ULT, "2026-06-01")]),  # no end date: was "1 day" -> FALSE -> excluded
    "M-UNDATED": ("female", [_med("M-UNDATED", 1, ULT, None)]),  # no date at all: was dropped at ingest
    "M-NONE": ("female", []),
}


def _crit(cid: str, kind: str, logic: dict[str, Any]) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "SAFE", "kind": kind, "class": "structured", "text": cid, "logic": logic}
    )


def _w(days: int) -> dict[str, Any]:
    return {"anchor": "index", "from_days": -days, "to_days": 0}


def _creat(quantifier: str = "latest") -> CriterionIR:
    extra = {"count": 1} if quantifier == "count>=" else {}
    return _crit(
        "SAFE-INC-01",
        "inclusion",
        {
            "domain": "observation",
            "quantifier": quantifier,
            **extra,
            "valueset": "VS_CREAT",
            "value": {"op": "<=", "num": 1.5, "unit": "mg/dL"},
            "window": _w(365),
        },
    )


HBA1C_EXC = _crit(
    "SAFE-EXC-01",
    "exclusion",
    {
        "domain": "observation",
        "quantifier": "latest",
        "valueset": "VS_HBA1C",
        "value": {"op": ">", "num": 10, "unit": "%"},
        "window": _w(180),
    },
)
SEX_INC = _crit(
    "SAFE-INC-02",
    "inclusion",
    {"domain": "demographic", "quantifier": "any", "valueset": "NONE", "sex": "female", "age": {"min": 18}},
)
EGFR_INC = _crit(
    "SAFE-INC-03",
    "inclusion",
    {
        "domain": "observation",
        "quantifier": "latest",
        "valueset": "VS_EGFR_COMPONENTS",
        "derived": "egfr_jsn",
        "value": {"op": ">=", "num": 45},
    },
)
PREG_EXC = _crit(  # the pregnancy-test arm of GZQO-EXC-08
    "SAFE-EXC-02",
    "exclusion",
    {
        "op": "and",
        "args": [
            {"domain": "demographic", "quantifier": "any", "valueset": "NONE", "sex": "female"},
            {
                "domain": "observation",
                "quantifier": "latest",
                "valueset": "VS_PREG_TEST",
                "value": {"op": "in", "codes": ["LA6576-8"]},
                "window": _w(30),
            },
        ],
    },
)
ULT_INC = _crit(
    "SAFE-INC-04",
    "inclusion",
    {
        "domain": "medication",
        "quantifier": "any",
        "valueset": "VS_ULT",
        "duration": {"min_days": 90, "gap_days": 30},
        "window": _w(180),
    },
)
ULT_ANY_INC = _crit(
    "SAFE-INC-05", "inclusion", {"domain": "medication", "quantifier": "any", "valueset": "VS_ULT", "window": _w(180)}
)
GLP1_EXC = _crit(
    "SAFE-EXC-03", "exclusion", {"domain": "medication", "quantifier": "any", "valueset": "VS_GLP1", "window": _w(90)}
)
GLP1_INC = _crit(
    "SAFE-INC-06", "inclusion", {"domain": "medication", "quantifier": "any", "valueset": "VS_GLP1", "window": _w(90)}
)

VS = {
    "VS_CREAT": valueset("SAFE", "VS_CREAT", "creatinine", [Concept(LOINC, CREAT, "creatinine")], "1.0.0"),
    "VS_HBA1C": valueset("SAFE", "VS_HBA1C", "HbA1c", [Concept(LOINC, HBA1C, "HbA1c")], "1.0.0"),
    "VS_PREG_TEST": valueset("SAFE", "VS_PREG_TEST", "pregnancy test", [Concept(LOINC, PREG_TEST, "hCG")], "1.0.0"),
    "VS_EGFR_COMPONENTS": valueset("SAFE", "VS_EGFR_COMPONENTS", "eGFR", [Concept(LOINC, CREAT, "creat")], "1.0.0"),
    "VS_ULT": valueset("SAFE", "VS_ULT", "urate lowering", [Concept(ATC, ULT, "allopurinol")], "1.0.0"),
    "VS_GLP1": valueset("SAFE", "VS_GLP1", "GLP-1 RA", [Concept(ATC, GLP1, "liraglutide")], "1.0.0"),
}


def _ruleset(*crits: CriterionIR) -> Ruleset:
    sql = SqlGenerator("SAFE", "1.0.0", ValueSets("SAFE", VS, Terminology())).render(list(crits))
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "SAFE", "library": None, "criteria": [c.id for c in crits]})
    return Ruleset(manifest=manifest, criteria=list(crits), valuesets=VS, sql=sql)


def _write(nd: Path, name: str, rows: list[dict[str, Any]]) -> None:
    (nd / f"{name}.ndjson").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    tmp = tmp_path_factory.mktemp("criteria-safety")
    nd = tmp / "ndjson"
    nd.mkdir()
    res = [r for _g, rows in CASES.values() for r in rows]
    _write(nd, "Patient", [_pat(pid, g) for pid, (g, _rows) in CASES.items()])
    _write(nd, "Observation", [r for r in res if r["resourceType"] == "Observation"])
    _write(nd, "MedicationRequest", [r for r in res if r["resourceType"] == "MedicationRequest"])
    _write(nd, "Condition", [])
    Lake(tmp / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder())


def _sql(lake: LakeLocal, rs: Ruleset, sql: str | None = None) -> dict[str, dict[str, Any]]:
    rows = lake.query(sql or rs.sql, [[IDX.isoformat()], list(CASES)]).to_pylist()
    return {r["pid"]: r for r in rows}


def _verdicts(lake: LakeLocal, rs: Ruleset, crit: CriterionIR) -> dict[str, tuple[str, str | None]]:
    ev = SqlEngine(lake).evaluate(rs, list(CASES), IDX, [crit.id])
    out: dict[str, tuple[str, str | None]] = {}
    for pid, e in ev.items():
        v = structured_verdict(crit, e)
        out[pid] = (v.verdict, v.evidence.reason if v.evidence else None)
    return out


def _why(v: Any) -> str | None:
    """The reason code of a criterion verdict (None when it has no evidence)."""
    return v.evidence.reason if v.evidence is not None else None


def _cascade(lake: LakeLocal, rs: Ruleset, pids: list[str]) -> Any:
    cfg = CascadeConfig(
        study_id=rs.id,
        run_date=IDX,
        lookback_months=36,
        index_mode="single",
        purpose="screening",
        step_id="safety",
        snapshot=None,
        population=pids,
        note_block=False,
        absence_semantics=False,
    )
    return run_cascade(lake, rs, cfg, judge=None, embedder=HashEmbedder(), reviewer=None)


# ------------------------------------------------------------------------------------------------ S-1: units
def test_unit_key_and_conversion_table() -> None:
    assert labunit.key("mL/min/{1.73_m2}") == labunit.key("mL/min/1.73m2") == "ml/min/1.73m2"
    assert labunit.key("mm[Hg]") == labunit.key("mmHg") and labunit.key("10^9/L") == labunit.key("10*9/L")
    assert labunit.key(" µmol/L ") == labunit.key("μmol/l") == "umol/l"
    # the criterion's own unit: used as it is
    assert labunit.convert(1.2, "mg/dL", "mg/dL") == 1.2 and labunit.convert(7.0, "%", "%") == 7.0
    # a known analyte with both units in its table: converted, both ways
    assert labunit.convert(88.4, "umol/L", "mg/dL", LOINC, CREAT) == pytest.approx(1.0)
    assert labunit.convert(1.0, "mg/dL", "umol/L", LOINC, CREAT) == pytest.approx(88.4)
    assert labunit.convert(1.0, "mg/dL", "mg/L", LOINC, "1988-5") == pytest.approx(10.0)
    assert labunit.convert(170, "cm", "m", LOINC, "8302-2") == pytest.approx(1.7)
    # never across analytes, never without a table, never a row with no unit
    assert labunit.convert(88.4, "umol/L", "mg/dL", LOINC, "3084-1") is None  # urate is not creatinine
    assert labunit.convert(88.4, "umol/L", "mg/dL") is None
    assert labunit.convert(53, "mmol/mol", "%", LOINC, HBA1C) is None
    # units of one kind convert by definition, whatever the analyte (D-418, DATA-016)
    assert labunit.convert(15.0, "10*4/uL", "10*9/L", LOINC, "777-3") == pytest.approx(150.0)
    assert labunit.convert(5.6, "mmol/L", "mg/dL", LOINC, "2345-7") is None  # mass and substance need a molar mass
    assert labunit.convert(1.0, None, "mg/dL", LOINC, CREAT) is None and labunit.convert(1.0, "", "%") is None
    # a criterion with no unit (a count, a score) reads rows with no unit only
    assert labunit.convert(6, None, None) == 6 and labunit.convert(6, "{count}", "") == 6
    assert labunit.convert(6, "mg/dL", None) is None
    assert labunit.reason_of(["unit_mismatch", "o-1|2026-09-20"]) == ("unit_mismatch", ["o-1|2026-09-20"])
    assert labunit.reason_of(["derived_unit:crp", "o-1|2026-09-20"]) == ("derived_unit", ["o-1|2026-09-20"])
    for code in (Reason.UNIT_MISMATCH.value, Reason.ORDER_DATES_MISSING.value):
        assert code_of(code) == code and set(LABELS[code]) == {"en", "ja", "zh-TW"}


def test_sql_conversion_is_the_python_conversion(lake: LakeLocal) -> None:
    """The SQL twin gives the number the reference gives, for every unit of every analyte table and a few others."""
    units = sorted({u for t in labunit.ANALYTES.values() for u in t} | {"", "%", "mmol/mol", "MG/DL", "mg / dL"})
    for (system, code), table in labunit.ANALYTES.items():
        for want in [*sorted(table), "%", None]:
            expr = labunit.value_sql("v", "u", "s", "c", want)
            for have in units:
                got = lake.query(
                    f"SELECT {expr} AS x FROM (SELECT CAST(2.5 AS DOUBLE) AS v, CAST($1 AS VARCHAR) AS u, $2 AS s, $3 AS c)",
                    [have or None, system, code],
                ).to_pylist()[0]["x"]
                ref = labunit.convert(2.5, have, want, system, code)
                assert (got is None) == (ref is None), (code, want, have, got, ref)
                if ref is not None:
                    assert got == pytest.approx(ref), (code, want, have)


CREAT_EXPECTED: dict[str, bool | None] = {
    "U-OK": True,
    "U-HIGH": False,
    "U-UMOL": True,
    "U-UMOL-MICRO": True,
    "U-UMOL-HIGH": False,
    "U-NOUNIT": None,
    "U-ODD": None,
    "U-TEXT": None,
}


@pytest.mark.parametrize("quantifier", ["latest", "any", "all", "count>="])
def test_a_lab_value_is_compared_in_the_criterions_unit_or_not_at_all(lake: LakeLocal, quantifier: str) -> None:
    rs = _ruleset(_creat(quantifier))
    got = _sql(lake, rs)
    assert {p: got[p]["C_SAFE-INC-01"] for p in CREAT_EXPECTED} == CREAT_EXPECTED
    for pid in ("U-NOUNIT", "U-ODD"):
        assert got[pid]["E_SAFE-INC-01"].split(";")[0] == "unit_mismatch"
        assert f"o-{pid}-1|2026-09-20" in got[pid]["E_SAFE-INC-01"]


def test_none_quantifier_is_unknown_on_an_unreadable_unit(lake: LakeLocal) -> None:
    got = _sql(lake, _ruleset(_creat("none")))
    assert {p: got[p]["C_SAFE-INC-01"] for p in CREAT_EXPECTED} == {
        p: (None if v is None else not v) for p, v in CREAT_EXPECTED.items()
    }


def test_unit_mismatch_never_excludes_in_either_engine(lake: LakeLocal) -> None:
    inc, exc = _creat("latest"), HBA1C_EXC
    rs = _ruleset(inc, exc)
    v_inc, v_exc = _verdicts(lake, rs, inc), _verdicts(lake, rs, exc)
    assert v_inc["U-UMOL"][0] == "pass" and v_inc["U-HIGH"][0] == "fail" and v_inc["U-UMOL-HIGH"][0] == "fail"
    assert v_inc["U-NOUNIT"] == ("unknown", "unit_mismatch") and v_inc["U-ODD"] == ("unknown", "unit_mismatch")
    # the shipped GZQO-EXC-06 case: 53 mmol/mol is 7.0 %, not "> 10 %"
    assert v_exc["H-IFCC"] == ("unknown", "unit_mismatch")
    assert v_exc["H-PCT-HIGH"][0] == "fail" and v_exc["H-PCT-OK"][0] == "pass"
    pids = ["U-OK", "U-HIGH", "U-UMOL", "U-UMOL-HIGH", "U-NOUNIT", "U-ODD"]
    res = _cascade(lake, _ruleset(inc), pids)
    tiers = {pid: verdicts_of(_ruleset(inc), res.traces[pid]).tier for pid in pids}
    assert tiers["U-HIGH"] == "excluded" and tiers["U-UMOL-HIGH"] == "excluded"
    for pid in ("U-OK", "U-UMOL", "U-NOUNIT", "U-ODD"):
        assert tiers[pid] != "excluded", (pid, tiers[pid])
    for pid in ("U-NOUNIT", "U-ODD"):
        o = res.traces[pid].outcomes[inc.id]
        assert o.status == "unknown" and not o.hard and o.reason == "unit_mismatch"
    pids = ["H-IFCC", "H-PCT-HIGH", "H-PCT-OK"]
    res = _cascade(lake, _ruleset(_creat("none"), exc), pids)  # "none" passes: no creatinine row
    out = {pid: res.traces[pid].outcomes[exc.id] for pid in pids}
    assert out["H-PCT-HIGH"].status == "fail" and out["H-PCT-HIGH"].hard
    assert out["H-IFCC"].status == "pass" and not out["H-IFCC"].hard and out["H-IFCC"].reason == "unit_mismatch"
    assert out["H-IFCC"].unknown_kind == "data_gap"  # kept, and shown as a point to check


# ------------------------------------------------------------------------------------------------ S-4: status
def test_a_void_record_reaches_no_lake_table() -> None:
    fl = Flattener()
    pid = "P1"
    by_type = {
        "Patient": [_pat(pid)],
        "Observation": [
            _obs(pid, 1, CREAT, 1.0, "mg/dL"),
            _obs(pid, 2, CREAT, 9.0, "mg/dL", status="entered-in-error"),
            _obs(pid, 3, CREAT, 9.0, "mg/dL", status="cancelled"),
            _obs(pid, 4, CREAT, 1.1, "mg/dL", status="preliminary"),
            _obs(pid, 5, CREAT, 1.2, "mg/dL", status=None),
        ],
        "MedicationRequest": [
            _med(pid, 1, GLP1, "2026-09-01"),
            _med(pid, 2, GLP1, "2026-09-01", status="cancelled"),
            _med(pid, 3, GLP1, "2026-09-01", status="entered-in-error"),
            _med(pid, 4, GLP1, "2026-09-01", status="draft"),
            _med(pid, 5, GLP1, "2026-09-01", status="stopped"),
            _med(pid, 6, GLP1, "2026-09-01", status="completed"),
        ],
        "Procedure": [
            {
                "resourceType": "Procedure",
                "id": "pr-1",
                "status": "completed",
                "subject": {"reference": f"Patient/{pid}"},
            },
            {
                "resourceType": "Procedure",
                "id": "pr-2",
                "status": "not-done",
                "subject": {"reference": f"Patient/{pid}"},
            },
            {
                "resourceType": "Procedure",
                "id": "pr-3",
                "status": "entered-in-error",
                "subject": {"reference": f"Patient/{pid}"},
            },
        ],
        "DiagnosticReport": [
            {
                "resourceType": "DiagnosticReport",
                "id": "r-1",
                "status": "final",
                "subject": {"reference": f"Patient/{pid}"},
            },
            {
                "resourceType": "DiagnosticReport",
                "id": "r-2",
                "status": "entered-in-error",
                "subject": {"reference": f"Patient/{pid}"},
            },
        ],
        "DocumentReference": [
            {
                "resourceType": "DocumentReference",
                "id": "d-1",
                "status": "current",
                "subject": {"reference": f"Patient/{pid}"},
            },
            {
                "resourceType": "DocumentReference",
                "id": "d-2",
                "status": "entered-in-error",
                "subject": {"reference": f"Patient/{pid}"},
            },
            {
                "resourceType": "DocumentReference",
                "id": "d-3",
                "status": "current",
                "docStatus": "entered-in-error",
                "subject": {"reference": f"Patient/{pid}"},
            },
        ],
    }
    out = fl.flatten(by_type)
    assert [r["oid"] for r in out["observation"]] == ["o-P1-1", "o-P1-4", "o-P1-5"]
    assert [r["mid"] for r in out["medication"]] == ["m-P1-1", "m-P1-5", "m-P1-6"]
    assert [r["prid"] for r in out["procedure"]] == ["pr-1"]
    assert [r["rid"] for r in out["report"]] == ["r-1"]
    assert [r["did"] for r in out["document"]] == ["d-1"]
    assert out["site_fact"] == []


def test_an_entered_in_error_result_and_a_cancelled_order_decide_nothing(lake: LakeLocal) -> None:
    inc, exc, on_drug = _creat("latest"), GLP1_EXC, GLP1_INC
    rs = _ruleset(inc, exc, on_drug)
    got = _sql(lake, rs)
    # the newest row (9.0, entered in error) is not a fact: the valid 1.0 decides
    assert got["V-ERR"]["C_SAFE-INC-01"] is True and got["V-ERR"]["E_SAFE-INC-01"] == "o-V-ERR-1|2026-09-15"
    assert _verdicts(lake, rs, inc)["V-ERR"][0] == "pass"
    # a cancelled or mistaken order neither excludes ("prior GLP-1 RA") nor includes ("on a GLP-1 RA")
    for pid in ("V-CANCELLED-RX", "V-ERROR-RX"):
        assert got[pid]["C_SAFE-EXC-03"] is False and got[pid]["C_SAFE-INC-06"] is False, pid
    for pid in ("V-ACTIVE-RX", "V-STOPPED-RX"):
        assert got[pid]["C_SAFE-EXC-03"] is True and got[pid]["C_SAFE-INC-06"] is True, pid
    v = _verdicts(lake, rs, exc)
    assert v["V-CANCELLED-RX"][0] == "pass" and v["V-ERROR-RX"][0] == "pass" and v["V-ACTIVE-RX"][0] == "fail"
    res = _cascade(lake, _ruleset(inc), ["V-ERR"])
    assert verdicts_of(_ruleset(inc), res.traces["V-ERR"]).tier != "excluded"


def test_ssmix2_cancelled_order_is_cancelled_not_stopped() -> None:
    from adapter.sources.ssmix2.source import _RX_STATUS
    from lake.flatten import VOID

    assert _RX_STATUS["CA"] == "cancelled" and _RX_STATUS["CA"] in VOID["MedicationRequest"]
    assert _RX_STATUS["DC"] == "stopped" and _RX_STATUS["DC"] not in VOID["MedicationRequest"]


# ------------------------------------------------------------------------------------------------ S-5: sex
def test_sex_other_or_unknown_is_unknown_not_male(lake: LakeLocal) -> None:
    rs = _ruleset(SEX_INC, EGFR_INC, PREG_EXC)
    rows = lake.query("SELECT pid, sex FROM patient WHERE starts_with(pid, 'X-') ORDER BY pid").to_pylist()
    assert {r["pid"]: r["sex"] for r in rows} == {
        "X-F": "female",
        "X-M": "male",
        "X-NONE": None,
        "X-OTHER": None,
        "X-UNK": None,
    }
    got = _sql(lake, rs)
    assert got["X-F"]["C_SAFE-INC-02"] is True and got["X-M"]["C_SAFE-INC-02"] is False
    for pid in ("X-UNK", "X-OTHER", "X-NONE"):
        assert got[pid]["C_SAFE-INC-02"] is None, pid  # was FALSE -> excluded
        # eGFR needs the sex: no value and the reason, never the male constants (was TRUE with them)
        assert got[pid]["C_SAFE-INC-03"] is None and got[pid]["E_SAFE-INC-03"] == "derived_missing_input:sex", pid
        # a positive pregnancy test: unknown (a person checks), never "not applicable" (was FALSE)
        assert got[pid]["C_SAFE-EXC-02"] is None, pid
    assert got["X-F"]["C_SAFE-EXC-02"] is True and got["X-M"]["C_SAFE-EXC-02"] is False
    assert got["X-F"]["C_SAFE-INC-03"] is not None and got["X-M"]["C_SAFE-INC-03"] is not None
    v_sex, v_egfr, v_preg = (_verdicts(lake, rs, c) for c in (SEX_INC, EGFR_INC, PREG_EXC))
    for pid in ("X-UNK", "X-OTHER", "X-NONE"):
        assert v_sex[pid][0] == "unknown" and v_preg[pid][0] == "unknown", pid
        assert v_egfr[pid] == ("unknown", "derived_missing_input"), pid
    assert v_preg["X-F"][0] == "fail" and v_preg["X-M"][0] == "pass"
    pids = ["X-F", "X-M", "X-UNK", "X-OTHER", "X-NONE"]
    res = _cascade(lake, _ruleset(SEX_INC), pids)
    tiers = {pid: verdicts_of(_ruleset(SEX_INC), res.traces[pid]).tier for pid in pids}
    assert tiers["X-M"] == "excluded"
    for pid in ("X-F", "X-UNK", "X-OTHER", "X-NONE"):
        assert tiers[pid] != "excluded", (pid, tiers[pid])


def test_the_generator_does_not_trust_the_sex_column(lake: LakeLocal) -> None:
    """A lake built before D-275 still holds ``unknown`` / ``other`` in ``patient.sex``: the SQL reads them as no
    value by itself."""
    rs = _ruleset(SEX_INC, EGFR_INC)
    sql = rs.sql.replace(
        "SELECT p.pid, p.birth_date, p.sex, i.index_date FROM patient p",
        "SELECT p.pid, p.birth_date, CASE p.pid WHEN 'X-UNK' THEN 'unknown' WHEN 'X-OTHER' THEN 'other' "
        "ELSE p.sex END AS sex, i.index_date FROM patient p",
    )
    assert sql != rs.sql
    got = _sql(lake, rs, sql)
    for pid in ("X-UNK", "X-OTHER"):
        assert got[pid]["C_SAFE-INC-02"] is None and got[pid]["C_SAFE-INC-03"] is None, pid


# ------------------------------------------------------------------------------------------------ S-9: order dates
def test_an_order_without_an_end_date_or_any_date_is_unknown_not_one_day(lake: LakeLocal) -> None:
    rs = _ruleset(ULT_INC, ULT_ANY_INC)
    got = _sql(lake, rs)
    dur = {p: got[p]["C_SAFE-INC-04"] for p in ("M-FULL", "M-SHORT", "M-OPEN", "M-UNDATED", "M-NONE")}
    assert dur == {"M-FULL": True, "M-SHORT": False, "M-OPEN": None, "M-UNDATED": None, "M-NONE": False}
    assert got["M-OPEN"]["E_SAFE-INC-04"] == "order_dates_missing;m-M-OPEN-1"
    assert got["M-UNDATED"]["E_SAFE-INC-04"] == "order_dates_missing;m-M-UNDATED-1"
    # "any order in the window": the undated one cannot be placed, so unknown (it was dropped at ingest: FALSE)
    assert got["M-UNDATED"]["C_SAFE-INC-05"] is None and got["M-OPEN"]["C_SAFE-INC-05"] is True
    assert got["M-NONE"]["C_SAFE-INC-05"] is False
    v = _verdicts(lake, rs, ULT_INC)
    assert v["M-OPEN"] == ("unknown", "order_dates_missing") and v["M-UNDATED"] == ("unknown", "order_dates_missing")
    assert v["M-SHORT"][0] == "fail" and v["M-FULL"][0] == "pass"
    pids = ["M-FULL", "M-SHORT", "M-OPEN", "M-UNDATED", "M-NONE"]
    res = _cascade(lake, _ruleset(ULT_INC), pids)
    tiers = {pid: verdicts_of(_ruleset(ULT_INC), res.traces[pid]).tier for pid in pids}
    assert tiers["M-SHORT"] == "excluded" and tiers["M-NONE"] == "excluded"
    for pid in ("M-FULL", "M-OPEN", "M-UNDATED"):
        assert tiers[pid] != "excluded", (pid, tiers[pid])
    for pid in ("M-OPEN", "M-UNDATED"):
        o = res.traces[pid].outcomes[ULT_INC.id]
        assert o.status == "unknown" and not o.hard and o.reason == "order_dates_missing"


def test_the_adapter_keeps_an_undated_order(tmp_path: Path) -> None:
    """The ingest step no longer deletes an order with no date (it reported it as "dropped")."""
    import inspect

    from adapter import ndjson

    from adapter import pipeline

    # run_ingest wraps _run_ingest (T-615b); since T-692 each resource passes _NightPass as it is written: it counts
    # an undated order and returns False only for a Patient merged into another (its chart number), never for an order
    src = inspect.getsource(pipeline._run_ingest) + inspect.getsource(pipeline._NightPass)
    assert "if not _undated_order(r)" not in src and "kept, read as unknown" in src
    assert "transform=night" in src  # the pass is the snapshot's transform
    night = pipeline._NightPass(UTC, {}, False, pipeline._Aliases({}, []), {"MedicationRequest": 1}, None, None)
    assert night(_med("P", 1, ULT, None)) is True and night.undated == 1
    assert night.missing_counts()["MedicationRequest.authoredOn (no date at all: kept, read as unknown)"] == 1
    # behaviour: through the spool and the night's pass, the undated order is in the written snapshot
    sp = ndjson.Spool(tmp_path / "spool")
    sp.add(_med("P", 1, ULT, None))
    sp.add(_med("P", 2, ULT, "2026-01-01"))
    night = pipeline._NightPass(UTC, {}, False, pipeline._Aliases({}, []), sp.counts(), None, None)
    assert ndjson.write_snapshot(tmp_path / "out", sp, None, transform=night) == {"MedicationRequest": 2}
    sp.close()
    assert night.undated == 1
    assert pipeline._undated_order(_med("P", 1, ULT, None)) and not pipeline._undated_order(
        _med("P", 2, ULT, "2026-01-01")
    )


# ------------------------------------------------------------------------------------------------ approved SQL
def test_missing_data_never_makes_an_inclusion_false(lake: LakeLocal) -> None:
    """The v1 point of S-9: every shipped ruleset reads a FALSE structured inclusion as a hard exclusion, so no
    inclusion may be FALSE for a patient whose data is missing, void or unreadable rather than failing."""
    incs = [_creat("latest"), SEX_INC, EGFR_INC, ULT_INC, ULT_ANY_INC]
    rs = _ruleset(*incs)
    got = _sql(lake, rs)
    unreadable = {
        "SAFE-INC-01": ["U-NOUNIT", "U-ODD"],
        "SAFE-INC-02": ["X-UNK", "X-OTHER", "X-NONE"],
        "SAFE-INC-03": ["X-UNK", "X-OTHER", "X-NONE", "U-NOUNIT", "U-ODD"],
        "SAFE-INC-04": ["M-OPEN", "M-UNDATED"],
        "SAFE-INC-05": ["M-UNDATED"],
    }
    for cid, pids in unreadable.items():
        for pid in pids:
            assert got[pid][f"C_{cid}"] is None, (cid, pid)


def test_shipped_gzqo_as_approved_no_longer_excludes_on_unreadable_data(tmp_path: Path) -> None:
    """GZQO's SQL as it was approved before D-275 (kept as a fixture: the shipped ruleset is now recompiled). Run as
    stored it excludes these patients; the runtime runs it guarded by the current rules and they stay on the list as
    points to check."""
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    rs.sql = (ROOT / "tests" / "fixtures" / "pre_d275" / "GZQO.sql").read_text(encoding="utf-8")
    assert MARK not in rs.sql and rs.sql in safe_sql(rs)  # the approved text is embedded unchanged
    pats = {
        "G-IFCC": "female",  # HbA1c 53 mmol/mol (7.0 %) against GZQO-EXC-06 "> 10 %"
        "G-PCT": "female",  # HbA1c 11 %: a true exclusion, kept
        "G-PREG": "unknown",  # sex unknown, positive pregnancy test: GZQO-EXC-08
        "G-OPEN": "female",  # one urate-lowering order, no end date: GZQO-INC-06 (>= 90 days)
        "G-FULL": "female",  # 150 days of therapy: met, kept
        "G-NOUNIT": "female",  # serum urate 8.2 with no unit: GZQO-INC-04
        "G-CANCELLED": "female",  # a cancelled GLP-1 RA order: GZQO-EXC-04
    }
    obs = [
        _obs("G-IFCC", 1, HBA1C, 53, "mmol/mol"),
        _obs("G-PCT", 1, HBA1C, 11.0, "%"),
        _coded_obs("G-PREG", 1, PREG_TEST, "LA6576-8"),
        _obs("G-NOUNIT", 1, "3084-1", 8.2, None),
        _obs("G-FULL", 1, "3084-1", 8.2, "mg/dL"),
    ]
    meds = [
        _med("G-OPEN", 1, ULT, "2026-06-01"),
        _med("G-FULL", 1, ULT, "2026-05-01", "2026-05-01", "2026-09-30"),
        _med("G-CANCELLED", 1, GLP1, "2026-09-20", status="cancelled"),
    ]
    nd = tmp_path / "ndjson"
    nd.mkdir()
    _write(nd, "Patient", [_pat(p, g) for p, g in pats.items()])
    _write(nd, "Observation", obs)
    _write(nd, "MedicationRequest", meds)
    _write(nd, "Condition", [])
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    lk = LakeLocal(tmp_path / "lake", HashEmbedder())
    stored = {r["pid"]: r for r in lk.query(rs.sql, [[IDX.isoformat()], list(pats)]).to_pylist()}
    # what the approved SQL says on its own (the findings as the reviewers ran them)
    assert stored["G-IFCC"]["C_GZQO-EXC-06"] is True
    assert stored["G-OPEN"]["C_GZQO-INC-06"] is False
    assert stored["G-NOUNIT"]["C_GZQO-INC-04"] is True  # a bare number compared with mg/dL
    ids = ["GZQO-EXC-04", "GZQO-EXC-06", "GZQO-EXC-08", "GZQO-INC-04", "GZQO-INC-06"]
    by = rs.by_id()
    ev = SqlEngine(lk).evaluate(rs, list(pats), IDX, ids)
    v = {pid: {cid: structured_verdict(by[cid], e) for cid in ids} for pid, e in ev.items()}
    assert v["G-IFCC"]["GZQO-EXC-06"].verdict == "unknown"
    assert _why(v["G-IFCC"]["GZQO-EXC-06"]) == "unit_mismatch"
    assert v["G-PCT"]["GZQO-EXC-06"].verdict == "fail"
    assert v["G-PREG"]["GZQO-EXC-08"].verdict == "unknown"
    assert v["G-OPEN"]["GZQO-INC-06"].verdict == "unknown"
    assert _why(v["G-OPEN"]["GZQO-INC-06"]) == "order_dates_missing"
    assert v["G-FULL"]["GZQO-INC-06"].verdict == "pass" and v["G-FULL"]["GZQO-INC-04"].verdict == "pass"
    assert v["G-NOUNIT"]["GZQO-INC-04"].verdict == "unknown"
    assert v["G-CANCELLED"]["GZQO-EXC-04"].verdict == "pass"
    # the SCREEN cascade reads the same guarded SQL
    res = _cascade(lk, rs, list(pats))
    o = res.traces["G-IFCC"].outcomes["GZQO-EXC-06"]
    assert o.status == "pass" and not o.hard and o.reason == "unit_mismatch" and o.unknown_kind == "data_gap"
    assert res.traces["G-PCT"].outcomes["GZQO-EXC-06"].hard
    o = res.traces["G-OPEN"].outcomes["GZQO-INC-06"]
    assert o.status == "unknown" and not o.hard and o.reason == "order_dates_missing"
    o = res.traces["G-PREG"].outcomes["GZQO-EXC-08"]
    assert o.status == "pass" and not o.hard and o.unknown_kind == "data_gap"


def test_guarded_sql_only_ever_turns_an_answer_into_unknown(lake: LakeLocal) -> None:
    """The overlay keeps a stored answer where the current rules agree and gives NULL where they differ; SQL that
    carries the D-275 mark runs alone."""
    crits = [_creat("latest"), HBA1C_EXC, SEX_INC, ULT_INC]
    rs = _ruleset(*crits)
    assert MARK in rs.sql and safe_sql(rs) == rs.sql
    # the same criteria as SQL compiled before D-275 would answer them: bare numbers, no order-date rule
    old = rs.sql.replace(MARK, "-- (compiled before D-275)")
    old = old.replace("(coalesce(a_safe_inc_04_1_o.n, 0) > 0)", "FALSE").replace(
        "coalesce(a_safe_inc_04_1_o.n, 0) > 0", "FALSE"
    )
    stale = Ruleset(manifest=rs.manifest, criteria=rs.criteria, valuesets=rs.valuesets, sql=old)
    guarded = safe_sql(stale)
    assert guarded != old and old in guarded
    a, b, fresh = _sql(lake, stale, old), _sql(lake, stale, guarded), _sql(lake, rs)
    assert a["M-OPEN"]["C_SAFE-INC-04"] is False and b["M-OPEN"]["C_SAFE-INC-04"] is None
    assert list(a["U-OK"]) == list(b["U-OK"])  # same columns, same order
    for pid in CASES:
        for c in crits:
            col = f"C_{c.id}"
            if a[pid][col] == fresh[pid][col]:
                assert b[pid][col] == a[pid][col], (pid, col)
            else:
                assert b[pid][col] is None, (pid, col)


# ------------------------------------------------------------------------------------------------ CQL twin
def test_cql_carries_the_same_rules_and_translates() -> None:
    from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source

    crits = [_creat("latest"), _creat("any").model_copy(update={"id": "SAFE-INC-11"}), HBA1C_EXC, SEX_INC, ULT_INC]
    gen = CqlGenerator("SAFE", "1.0.0", ValueSets("SAFE", VS, Terminology()))
    cql, common = gen.render(crits), render_common()
    assert "when TB.UnitKey(Q) = 'mg/dl' then Q.value.value" in cql
    assert "and TB.UnitKey(Q) = 'umol/l' then Round(Q.value.value / 88.4, 6)" in cql
    assert "when TB.UnitKey(Q) = '%' then Q.value.value" in cql
    assert "TB.ObsValue(" not in cql  # no bare number in a value comparison
    assert "Patient.gender.value in { 'male', 'female' }" in cql
    assert "X.dispenseRequest.validityPeriod.end is null" in cql and "then null as Boolean else false" in cql
    assert "P.gender.value in { 'male', 'female' }" in common and 'define function "UnitKey"' in common
    if not available():
        pytest.skip("cql-translator jars not available on the host (.cache/jvm)")
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": common, gen.library: cql})
    assert gen.library in tr.elm and "TB_Common" in tr.elm


# ------------------------------------------------------------------------------------------------ OMOP path
def test_the_omop_lake_reads_status_sex_and_undated_orders_as_the_legacy_lake(db_url: str) -> None:
    """Both lake sources give the same rows for the D-275 cases: a void record in no table, ``other`` / ``unknown``
    sex as no value, an undated or open-ended order kept with its missing dates."""
    from lake.flatten import SCHEMAS
    from lake.source import lake_rows
    from omop import schema
    from omop.export import export_rows
    from omop.load import load_batch

    pids = [p for p in CASES if p[:2] in ("V-", "X-", "M-")]
    res = [r for p in pids for r in CASES[p][1]]
    subject = {"reference": "Patient/V-ERR"}
    feed: dict[str, list[dict[str, Any]]] = {
        "Patient": [_pat(p, CASES[p][0]) for p in pids],
        # review F3 / F7: a result not yet final, one of a status nobody reads, one with no status recorded
        "Observation": [r for r in res if r["resourceType"] == "Observation"]
        + [
            _obs("V-ERR", 7, CREAT, 1.3, "mg/dL", status="preliminary"),
            _obs("V-ERR", 8, CREAT, 1.4, "mg/dL", status="unknown"),
            _obs("V-ERR", 9, CREAT, 1.5, "mg/dL", status="unknown") | {"meta": NOT_RECORDED_TAG},
        ],
        # review F1: an order of a status nobody reads is kept undated
        "MedicationRequest": [r for r in res if r["resourceType"] == "MedicationRequest"]
        + [
            _med("V-ERR", 9, GLP1, "2026-09-01", status="draft"),
            _med("V-ERR", 10, GLP1, "2026-09-01", status="unknown"),
        ],
        "Encounter": [
            {
                "resourceType": "Encounter",
                "id": f"e-{status}",
                "status": status,
                "subject": subject,
                "period": {"start": "2026-09-01T09:00:00+08:00"},
                "class": {"code": "AMB"},
            }
            for status in ("finished", "cancelled", "entered-in-error")
        ],
        "Procedure": [
            {
                "resourceType": "Procedure",
                "id": f"pr-{n}",
                "status": status,
                "subject": subject,
                "code": {"coding": [{"system": ICD, "code": "0DB64Z3"}]},
                "performedDateTime": "2026-01-10",
            }
            for n, status in enumerate(("completed", "not-done", "entered-in-error"), start=1)
        ],
        "DiagnosticReport": [
            {
                "resourceType": "DiagnosticReport",
                "id": f"r-{n}",
                "status": status,
                "subject": subject,
                "code": {"coding": [{"system": LOINC, "code": "24627-2"}]},
                "effectiveDateTime": "2026-01-10",
                "conclusion": "synthetic",
            }
            for n, status in enumerate(("final", "entered-in-error", "cancelled"), start=1)
        ],
    }
    legacy = lake_rows(feed, {}, tz="Asia/Taipei", snapshot="2026-10-05", source="legacy")
    assert [r["oid"] for r in legacy["observation"] if r["pid"] == "V-ERR"][:1] == ["o-V-ERR-1"]
    assert {r["mid"] for r in legacy["medication"] if r["pid"].startswith("V-")} == {
        "m-V-ACTIVE-RX-1",
        "m-V-STOPPED-RX-1",
        "m-V-ERR-10",  # unknown status: kept, undated (review F1)
    }
    assert [r["prid"] for r in legacy["procedure"]] == ["pr-1"] and [r["rid"] for r in legacy["report"]] == ["r-1"]
    assert [r["eid"] for r in legacy["encounter"]] == ["e-finished"]
    unread = next(r for r in legacy["medication"] if r["mid"] == "m-V-ERR-10")
    assert unread["status"] == "unknown" and unread["authored"] is None
    values = {r["oid"]: r["value_num"] for r in legacy["observation"] if r["pid"] == "V-ERR"}
    assert values == {"o-V-ERR-1": 1.0, "o-V-ERR-7": None, "o-V-ERR-8": None, "o-V-ERR-9": 1.5}
    undated = next(r for r in legacy["medication"] if r["mid"] == "m-M-UNDATED-1")
    assert undated["authored"] is None and undated["start"] is None and undated["end"] is None
    assert {r["pid"]: r["sex"] for r in legacy["patient"] if r["pid"].startswith("X-")} == {
        "X-F": "female",
        "X-M": "male",
        "X-UNK": None,
        "X-OTHER": None,
        "X-NONE": None,
    }
    db = schema.connect(db_url)
    try:
        load_batch(db, "feed", "2026-10-05", feed, tz="Asia/Taipei")
        out = export_rows(db)
        # a person row written before D-275 keeps "unknown" as its source value: the export still reads no value
        db.execute("UPDATE person SET gender_source_value = 'unknown' WHERE gender_source_value IS NULL")
        again = export_rows(db)
    finally:
        db.close()
    key = {"patient": "pid", "observation": "oid", "medication": "mid", "procedure": "prid", "report": "rid",
           "encounter": "eid"}  # fmt: skip
    for name in SCHEMAS:
        k = key.get(name)
        a, b = out[name], legacy[name]
        if k:
            a, b = sorted(a, key=lambda r: str(r[k])), sorted(b, key=lambda r: str(r[k]))
        assert a == b, name
    assert sorted(again["patient"], key=lambda r: r["pid"]) == sorted(legacy["patient"], key=lambda r: r["pid"])


# ------------------------------------------------------------------------------------------------ score input domains
# D-275 (after D-189/190): an input the Python reference rejects as impossible (``derived.DOMAIN``: a joint count over
# 28, a negative CRP, a creatinine of 0) gives no value in the SQL and CQL engines too, never a number that decides


def _dobs(pid: str, comp: str, value: float, unit: str | None) -> dict[str, Any]:
    from tb_common import derived as d

    system, code = d.CODES[comp]
    o = _obs(pid, 0, code, value, unit, day="2026-09-20")
    o["id"] = f"o-{pid}-{comp}"
    o["code"] = {"coding": [{"system": system, "code": code}]}
    return o


# pid -> (score, the reason the Python reference gives or None, {component: (value, unit)})
DOMAIN_CASES: dict[str, tuple[str, str | None, dict[str, tuple[float, str | None]]]] = {
    "S-DAS-OK": ("das28", None, {"tjc28": (8, None), "sjc28": (6, None), "ptga": (70, "mm"), "esr": (40, "mm/h")}),
    "S-DAS-TJC40": (
        "das28",
        "derived_unit:tjc28",
        {"tjc28": (40, None), "sjc28": (6, None), "ptga": (70, "mm"), "esr": (40, "mm/h")},
    ),
    "S-DAS-CRPNEG": (
        "das28",
        "derived_unit:crp",
        {"tjc28": (8, None), "sjc28": (6, None), "ptga": (70, "mm"), "crp": (-0.5, "mg/L")},
    ),
    "S-CDAI-SJC30": (
        "cdai",
        "derived_unit:sjc28",
        {"tjc28": (4, None), "sjc28": (30, None), "ptga10": (5, None), "evga": (5, None)},
    ),
    "S-CDAI-OK": ("cdai", None, {"tjc28": (4, None), "sjc28": (3, None), "ptga10": (5, None), "evga": (5, None)}),
    "S-EGFR-CR0": ("egfr_ckd_epi", "derived_unit:creatinine", {"creatinine": (0, "mg/dL")}),
    "S-EGFR-OK": ("egfr_ckd_epi", None, {"creatinine": (1.0, "mg/dL")}),
}
# "score > threshold" inclusions: each impossible input would have met it with a number
DOMAIN_CRITS = {
    "das28": ("SAFE-INC-21", 5.1),
    "cdai": ("SAFE-INC-22", 22),
    "egfr_ckd_epi": ("SAFE-INC-23", 45),
}


def _score_crit(score: str) -> CriterionIR:
    cid, num = DOMAIN_CRITS[score]
    return _crit(
        cid,
        "inclusion",
        {
            "domain": "observation",
            "quantifier": "latest",
            "valueset": f"VS_{score.upper()}_COMPONENTS",
            "derived": score,
            "value": {"op": ">=" if score == "egfr_ckd_epi" else ">", "num": num},
            "window": _w(365),
        },
    )


def _score_vs() -> dict[str, Any]:
    from tb_common import derived as d

    return {
        f"VS_{s.upper()}_COMPONENTS": valueset(
            "SAFE", f"VS_{s.upper()}_COMPONENTS", s, [Concept(*d.CODES[c], c) for c in d.COMPONENTS[s]], "1.0.0"
        )
        for s in DOMAIN_CRITS
    }


def test_an_impossible_score_input_is_unknown_in_the_sql_engine(tmp_path: Path) -> None:
    from tb_common import derived as d

    nd = tmp_path / "ndjson"
    nd.mkdir()
    _write(nd, "Patient", [_pat(p, "female") for p in DOMAIN_CASES])
    _write(
        nd,
        "Observation",
        [_dobs(p, c, v, u) for p, (_s, _r, comps) in DOMAIN_CASES.items() for c, (v, u) in comps.items()],
    )
    _write(nd, "Condition", [])
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    lk = LakeLocal(tmp_path / "lake", HashEmbedder())
    crits = [_score_crit(s) for s in DOMAIN_CRITS]
    vs = _score_vs()
    sql = SqlGenerator("SAFE", "1.0.0", ValueSets("SAFE", vs, Terminology())).render(crits)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "SAFE", "library": None, "criteria": [c.id for c in crits]})
    rs = Ruleset(manifest=manifest, criteria=crits, valuesets=vs, sql=sql)
    rows = {r["pid"]: r for r in lk.query(sql, [[IDX.isoformat()], list(DOMAIN_CASES)]).to_pylist()}
    ev = SqlEngine(lk).evaluate(rs, list(DOMAIN_CASES), IDX, [c.id for c in crits])
    on = date(2026, 9, 20)
    for pid, (score, reason, comps) in DOMAIN_CASES.items():
        cid = DOMAIN_CRITS[score][0]
        ref = d.compute(
            score, {c: [d.Obs(v, u, on, f"o-{pid}-{c}")] for c, (v, u) in comps.items()}, age=55, female=True
        )
        assert ref.reason == reason, (pid, ref.reason)  # the Python reference, as #59 made it
        got = rows[pid]
        if reason is None:
            assert got[f"C_{cid}"] is not None, pid
            continue
        # was a decided TRUE (a DAS28 of 7.6, a CDAI of 44, an infinite eGFR): now no value, the same reason
        assert got[f"C_{cid}"] is None and got[f"E_{cid}"] == reason, (pid, got[f"C_{cid}"], got[f"E_{cid}"])
        v = structured_verdict(next(c for c in crits if c.id == cid), ev[pid])
        assert v.verdict == "unknown" and _why(v) == "derived_unit", pid


def test_an_impossible_score_input_is_null_in_the_cql_engine() -> None:
    from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source

    crits = [_score_crit(s) for s in DOMAIN_CRITS]
    gen = CqlGenerator("SAFE", "1.0.0", ValueSets("SAFE", _score_vs(), Terminology()))
    cql = gen.render(crits)
    # every score reads its inputs through the domain guard, never the converted value alone
    for cid, comp, guard in (
        ("SAFE-INC-21", "tjc28", "{v} >= 0.0 and {v} <= 28.0"),
        ("SAFE-INC-21", "crp", "{v} >= 0.0 then"),
        ("SAFE-INC-22", "sjc28", "{v} >= 0.0 and {v} <= 28.0"),
        ("SAFE-INC-23", "creatinine", "{v} > 0.0 then"),
    ):
        conv = f'TB."Conv_{comp}"("L_{cid}_1_{comp}")'
        assert f'define "K_{cid}_1_{comp}":\n  if {guard.format(v=conv)}' in cql, (cid, comp)
        assert f'TB."Conv_{comp}"("L_{cid}_1_{comp}"), ' not in cql  # not passed to a formula unguarded
    assert 'TB.DAS28("K_SAFE-INC-21_1_tjc28"' in cql
    assert 'TB.EGFR2021("K_SAFE-INC-23_1_creatinine"' in cql
    if not available():
        pytest.skip("cql-translator jars not available on the host (.cache/jvm)")
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    assert gen.library in tr.elm
