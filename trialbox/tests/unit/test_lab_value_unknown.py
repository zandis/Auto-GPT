"""Review B-01 (D-142): a lab result that is not a plain number never makes a structured criterion FALSE.

"75 H" is 75 with a flag; "<0.3" and ">1000" are censored and decide a comparison only when every value on that side
of the bound gives the same answer; "検出せず" (not detected) and other text are no number: unknown, never a failed
test. Both runtime engines read the compiled SQL: the SQL engine of NAV / MICROBATCH / CASE and the SCREEN cascade.
The patients and criterion follow the review's repro (``scratch-02/repro_lake.py`` part A).

D-275: a text result (``valueString``) carries no unit, and a row with no unit is not compared with a criterion that
names one (``tests/unit/test_criteria_safety.py``). So this file's criterion and its Quantity rows have no unit: what
is tested here is the reading of the text, as before.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from matching.cascade.engine import CascadeConfig, run_cascade
from orchestrator.scenarios.evaluate import SqlEngine, structured_verdict
from orchestrator.scenarios.screen_cascade import verdicts_of
from tb_common import id_rule, labvalue
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
LOINC = "http://loinc.org"
IDX = date(2026, 10, 5)

# pid -> one eGFR result (valueQuantity number, or the text a source sent); criterion "eGFR >= 60"
RESULTS: dict[str, Any] = {
    "P-NUM": 75,  # met
    "P-LOW": 40,  # not met
    "P-TEXT": "75 H",  # 75 with a high flag: met
    "P-FW": "７５　Ｌ",  # full width: met
    "P-CENS-LO": "<0.3",  # below 0.3: certainly below 60, a decided FALSE
    "P-CENS-HI": ">1000",  # above 1000: certainly met
    "P-CENS-MID": "<90",  # below 90: could be 50 or 80, unknown
    "P-JA-MIBAN": "30未満",  # below 30: not met
    "P-NOTDET": "検出せず",  # not detected: no number, unknown
    "P-QCOMP": {"value": 1000, "comparator": ">"},  # a FHIR censored quantity: met
    "P-QCOMP-MID": {"value": 70, "comparator": "<"},  # below 70: unknown (was read as 70: met)
    "P-NOLAB": None,  # no result: unknown (as before)
}
EXPECTED: dict[str, bool | None] = {
    "P-NUM": True,
    "P-LOW": False,
    "P-TEXT": True,
    "P-FW": True,
    "P-CENS-LO": False,
    "P-CENS-HI": True,
    "P-CENS-MID": None,
    "P-JA-MIBAN": False,
    "P-NOTDET": None,
    "P-QCOMP": True,
    "P-QCOMP-MID": None,
    "P-NOLAB": None,
}


def test_parser_reads_flags_and_censoring_and_nothing_else() -> None:
    assert labvalue.parse("75 H") == (75.0, None) and labvalue.parse("75H") == (75.0, None)
    assert labvalue.parse("3.2 L") == (3.2, None) and labvalue.parse("H 120") == (120.0, None)
    assert labvalue.parse("<0.3") == (0.3, "<") and labvalue.parse("≦0.3") == (0.3, "<=")
    assert labvalue.parse(">1000") == (1000.0, ">") and labvalue.parse(">=1,000") == (1000.0, ">=")
    assert labvalue.parse("0.3未満") == (0.3, "<") and labvalue.parse("100以上") == (100.0, ">=")
    assert labvalue.parse("１２．５") == (12.5, None)
    for text in ("検出せず", "陰性", "(-)", "see note", "", "1-2", "<0.3未満", "75 mg/dL H x", None):
        assert labvalue.parse(text) is None, text


def _obs(pid: str, value: Any, unit: str | None = None) -> dict[str, Any]:
    o: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"o-{pid}",
        "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": LOINC, "code": "33914-3"}]},
        "effectiveDateTime": "2026-09-01T09:00:00+09:00",
    }
    if isinstance(value, dict):
        o["valueQuantity"] = dict(value)
    elif isinstance(value, int | float):
        o["valueQuantity"] = {"value": value}
    if "valueQuantity" in o and unit is not None:
        o["valueQuantity"]["unit"] = unit
    if "valueQuantity" not in o:
        o["valueString"] = value
    return o


def _ruleset(quantifier: str, kind: str = "inclusion", unit: str | None = None) -> tuple[Ruleset, CriterionIR]:
    extra = {"count": 1} if quantifier == "count>=" else {}
    crit = CriterionIR.model_validate(
        {
            "id": "REPRO-INC-01",
            "ruleset": "REPRO",
            "kind": kind,
            "class": "structured",
            "text": "eGFR >= 60",
            "logic": {
                "domain": "observation",
                "quantifier": quantifier,
                **extra,
                "valueset": "VS_EGFR",
                "value": {"op": ">=", "num": 60, **({"unit": unit} if unit else {})},
                "window": {"anchor": "index", "from_days": -365, "to_days": 0},
            },
        }
    )
    vs = {"VS_EGFR": valueset("REPRO", "VS_EGFR", "eGFR", [Concept(LOINC, "33914-3", "eGFR")], "1.0.0")}
    sql = SqlGenerator("REPRO", "1.0.0", ValueSets("REPRO", vs, Terminology())).render([crit])
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "REPRO", "library": None, "criteria": [crit.id]})
    return Ruleset(manifest=manifest, criteria=[crit], valuesets=vs, sql=sql), crit


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    tmp = tmp_path_factory.mktemp("labtext")
    nd = tmp / "ndjson"
    nd.mkdir()
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "female"} for p in RESULTS]
    obs = [_obs(p, v) for p, v in RESULTS.items() if v is not None]
    obs.append(_obs("P-NUM", 70) | {"id": "o-P-NUM-2", "effectiveDateTime": "2026-08-01T09:00:00+09:00"})
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in obs) + "\n", encoding="utf-8"
    )
    (nd / "Condition.ndjson").write_text("", encoding="utf-8")
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder())


@pytest.mark.parametrize("quantifier", ["any", "latest", "all", "count>="])
def test_compiled_sql_reads_text_results_as_numbers_or_unknown(lake: LakeLocal, quantifier: str) -> None:
    rs, _crit = _ruleset(quantifier)
    rows = lake.query(rs.sql, [[IDX.isoformat()], list(RESULTS)]).to_pylist()
    got = {r["pid"]: r["C_REPRO-INC-01"] for r in rows}
    assert got == EXPECTED


def test_none_quantifier_is_unknown_not_true_on_text(lake: LakeLocal) -> None:
    rs, _ = _ruleset("none")
    rows = lake.query(rs.sql, [[IDX.isoformat()], list(RESULTS)]).to_pylist()
    got = {r["pid"]: r["C_REPRO-INC-01"] for r in rows}
    assert got == {p: (None if v is None else not v) for p, v in EXPECTED.items()}


def test_sql_engine_lists_the_text_result_patient_never_excludes(lake: LakeLocal) -> None:
    rs, crit = _ruleset("any")
    ev = SqlEngine(lake).evaluate(rs, list(RESULTS), IDX, [crit.id])
    verdicts = {pid: structured_verdict(crit, e).verdict for pid, e in ev.items()}
    assert verdicts["P-TEXT"] == "pass" and verdicts["P-CENS-HI"] == "pass"
    assert verdicts["P-NOTDET"] == "unknown" and verdicts["P-CENS-MID"] == "unknown"
    assert verdicts["P-LOW"] == "fail" and verdicts["P-CENS-LO"] == "fail"


def test_cascade_keeps_the_text_result_patient(lake: LakeLocal) -> None:
    rs, crit = _ruleset("any")
    pids = list(RESULTS)
    cfg = CascadeConfig(
        study_id="REPRO",
        run_date=IDX,
        lookback_months=36,
        index_mode="single",
        purpose="screening",
        step_id="repro",
        snapshot=None,
        population=pids,
        note_block=False,
        absence_semantics=False,
    )
    res = run_cascade(lake, rs, cfg, judge=None, embedder=HashEmbedder(), reviewer=None)
    tiers = {pid: verdicts_of(rs, res.traces[pid]).tier for pid in pids}
    for pid in ("P-TEXT", "P-FW", "P-CENS-HI", "P-QCOMP", "P-NOTDET", "P-CENS-MID", "P-QCOMP-MID"):
        assert tiers[pid] != "excluded", (pid, tiers[pid])
    assert tiers["P-LOW"] == "excluded" and tiers["P-CENS-LO"] == "excluded"
    for pid in ("P-NOTDET", "P-CENS-MID"):
        o = res.traces[pid].outcomes[crit.id]
        assert o.status == "unknown" and not o.hard


# review F11 (D-275): the realistic case, a criterion with a unit. A Quantity in that unit (spelled either way) is
# decided as above; a text result carries no unit, so it is unknown, never a failed test
TEXT = {"P-TEXT", "P-FW", "P-CENS-LO", "P-CENS-HI", "P-CENS-MID", "P-JA-MIBAN", "P-NOTDET"}


@pytest.fixture(scope="module")
def lake_units(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    tmp = tmp_path_factory.mktemp("labunits")
    nd = tmp / "ndjson"
    nd.mkdir()
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "female"} for p in RESULTS]
    obs = [_obs(p, v, "mL/min/{1.73_m2}") for p, v in RESULTS.items() if v is not None]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in obs) + "\n", encoding="utf-8"
    )
    (nd / "Condition.ndjson").write_text("", encoding="utf-8")
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder())


def test_with_a_unit_quantities_are_decided_and_text_is_unknown(lake_units: LakeLocal) -> None:
    rs, _crit = _ruleset("latest", unit="mL/min/1.73m2")
    rows = lake_units.query(rs.sql, [[IDX.isoformat()], list(RESULTS)]).to_pylist()
    got = {r["pid"]: r["C_REPRO-INC-01"] for r in rows}
    assert got == {p: (None if p in TEXT else v) for p, v in EXPECTED.items()}
    assert got["P-NUM"] is True and got["P-LOW"] is False and got["P-QCOMP"] is True
