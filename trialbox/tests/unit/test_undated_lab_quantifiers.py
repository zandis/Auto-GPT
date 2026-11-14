"""SCR-03 (D-656), every quantifier, both directions: an undated lab result leaves a value criterion unknown only where
it could change the dated results' answer; where it cannot, the answer stands. Synthetic data only.

HbA1c in %, the comparison "above 10", a window of the year before the screening date. ``None`` is unknown.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.store import Lake
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
LOINC = "http://loinc.org"

# pid: [(value, day or None for an undated result)]
PATIENTS: dict[str, list[tuple[float, str | None]]] = {
    "P-LOW-UND-HIGH": [(6.1, "2026-08-01"), (11.2, None)],
    "P-LOW-UND-LOW": [(6.1, "2026-08-01"), (5.0, None)],
    "P-HIGH-UND-LOW": [(11.2, "2026-08-01"), (5.0, None)],
    "P-HIGH-UND-HIGH": [(11.2, "2026-08-01"), (12.0, None)],
    "P-UND-ONLY": [(11.2, None)],
    "P-2HIGH-UND-LOW": [(11.2, "2026-07-01"), (12.0, "2026-08-01"), (5.0, None)],
    "P-OLD-HIGH-UND-HIGH": [(11.2, "2024-01-01"), (6.1, "2026-08-01"), (12.0, None)],
}

# key: (quantifier, count, criterion number)
QUANTS = {
    "ANY": ("any", None, 1), "ALL": ("all", None, 2), "NONE": ("none", None, 3), "CNT": ("count>=", 2, 4),
    "LAST": ("latest", None, 5),
}  # fmt: skip

WANT: dict[str, dict[str, bool | None]] = {
    # an undated 11.2 % may lie in the window: never a silent "clear"
    "P-LOW-UND-HIGH": {"ANY": None, "ALL": False, "NONE": None, "CNT": False, "LAST": None},
    # an undated 5.0 % meets nothing: the dated answers stand
    "P-LOW-UND-LOW": {"ANY": False, "ALL": False, "NONE": True, "CNT": False, "LAST": False},
    "P-HIGH-UND-LOW": {"ANY": True, "ALL": None, "NONE": False, "CNT": False, "LAST": None},
    "P-HIGH-UND-HIGH": {"ANY": True, "ALL": True, "NONE": False, "CNT": None, "LAST": True},
    # no dated result: unknown, as before
    "P-UND-ONLY": {"ANY": None, "ALL": None, "NONE": None, "CNT": None, "LAST": None},
    "P-2HIGH-UND-LOW": {"ANY": True, "ALL": None, "NONE": False, "CNT": True, "LAST": None},
    # a dated row outside the window still does not count; the undated one may be inside
    "P-OLD-HIGH-UND-HIGH": {"ANY": None, "ALL": False, "NONE": None, "CNT": False, "LAST": None},
}


def _results(tmp: Path) -> dict[str, dict[str, Any]]:
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
    from lake.client import LakeLocal
    from orchestrator.scenarios.evaluate import SqlEngine
    from tb_contracts import CriterionIR

    feed = tmp / "feed"
    feed.mkdir()
    pts, obs = [], []
    for pid, rows in PATIENTS.items():
        pts.append({"resourceType": "Patient", "id": pid, "birthDate": "1960-01-01", "gender": "male"})
        for i, (v, day) in enumerate(rows):
            r: dict[str, Any] = {
                "resourceType": "Observation", "id": f"a-{pid}-{i}", "status": "final",
                "subject": {"reference": f"Patient/{pid}"}, "code": {"coding": [{"system": LOINC, "code": "4548-4"}]},
                "valueQuantity": {"value": v, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
            }  # fmt: skip
            if day:
                r["effectiveDateTime"] = day
            obs.append(r)
    for rtype, items in (("Patient", pts), ("Observation", obs)):
        (feed / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in items), "utf-8")
    Lake(tmp / "lake", tz="Asia/Tokyo").rebuild("2026-11-09", HashEmbedder(), ndjson_dir=feed)

    cs = []
    for key, (quant, count, num) in QUANTS.items():
        logic: dict[str, Any] = {"domain": "observation", "quantifier": quant, "valueset": "VS_HBA1C",
                                 "value": {"op": ">", "num": 10.0, "unit": "%"},
                                 "window": {"anchor": "index", "from_days": -365, "to_days": 0}}  # fmt: skip
        if count is not None:
            logic["count"] = count
        cs.append(CriterionIR.model_validate(
            {"id": f"UNQ-INC-0{num}", "ruleset": "UNQ", "kind": "inclusion", "class": "structured", "text": key,
             "logic": logic}))  # fmt: skip
    term = Terminology()
    res = term.map("observation", "hba1c")
    vs = {"VS_HBA1C": valueset("UNQ", "VS_HBA1C", "hba1c", res.concepts, "1.0.0", families=res.families)}
    sql = SqlGenerator("UNQ", "1.0.0", ValueSets("UNQ", vs, term)).render(cs)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    rs = Ruleset(manifest=base.model_copy(update={"id": "UNQ", "library": None, "criteria": [c.id for c in cs]}),
                 criteria=cs, valuesets=vs, sql=sql)  # fmt: skip
    ids = [c.id for c in cs]
    ev = SqlEngine(LakeLocal(tmp / "lake", HashEmbedder())).evaluate(rs, sorted(PATIENTS), date(2026, 11, 9), ids)
    key_of = {f"UNQ-INC-0{n}": k for k, (_, _, n) in QUANTS.items()}
    return {p: {key_of[k]: v for k, v in ev[p].results.items()} for p in PATIENTS}


@pytest.fixture(scope="module")
def got(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    return _results(tmp_path_factory.mktemp("undq"))


@pytest.mark.parametrize("pid", sorted(PATIENTS))
def test_an_undated_result_changes_the_answer_only_where_it_could(got: dict[str, dict[str, Any]], pid: str) -> None:
    assert got[pid] == WANT[pid]


def test_the_cql_carries_the_undated_records_for_every_value_quantifier() -> None:
    """The CQL twin (the equivalence gate holds the two engines equal): each value atom defines its undated records
    and every quantifier's answer consults them."""
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
    from tb_contracts import CriterionIR

    term = Terminology()
    res = term.map("observation", "hba1c")
    vs = {"VS_HBA1C": valueset("UNQ", "VS_HBA1C", "hba1c", res.concepts, "1.0.0", families=res.families)}
    for key, (quant, count, num) in QUANTS.items():
        logic: dict[str, Any] = {"domain": "observation", "quantifier": quant, "valueset": "VS_HBA1C",
                                 "value": {"op": ">", "num": 10.0, "unit": "%"},
                                 "window": {"anchor": "index", "from_days": -365, "to_days": 0}}  # fmt: skip
        if count is not None:
            logic["count"] = count
        c = CriterionIR.model_validate({"id": f"UNQ-INC-0{num}", "ruleset": "UNQ", "kind": "inclusion",
                                        "class": "structured", "text": key, "logic": logic})  # fmt: skip
        cql = CqlGenerator("UNQ", "1.0.0", ValueSets("UNQ", vs, term)).render([c])
        undated = f'define "U_UNQ-INC-0{num}_1":\n  [Observation: "VS_HBA1C"] X where TB.ObsDate(X) is null'
        assert undated in cql, key
        answer = cql.split(f'define "A_UNQ-INC-0{num}_1":', 1)[1].split("\ndefine ", 1)[0]
        assert f'exists ("U_UNQ-INC-0{num}_1" X where' in answer or f'Count("U_UNQ-INC-0{num}_1" X where' in answer, key
