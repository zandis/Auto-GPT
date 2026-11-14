"""Deep review 2026-11-13 (screening, SCR-03): an undated lab result is unknown where the dated ones do not settle it.

DUMP-01 (D-142) made an undated diagnosis leave its criterion unknown. A lab result without a date (a value read
from a chart line with no date, a PI's sheet row without a day, an old system's import) fell out of every window
test instead: "any HbA1c above 10 %" read as clear from a dated 6.1 % with an undated 11.2 % on file, and "the latest urate at least
7.0" read as not met from a dated 6.5 although an undated 8.8 may be newer. Synthetic data only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from embed_service.embedder import HashEmbedder
from lake.store import Lake
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
LOINC = "http://loinc.org"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"


def _obs(oid: str, pid: str, code: str, value: float, unit: str, day: str | None) -> dict[str, Any]:
    r: dict[str, Any] = {
        "resourceType": "Observation", "id": oid, "status": "final", "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": LOINC, "code": code}]},
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
    }  # fmt: skip
    if day:
        r["effectiveDateTime"] = day
    return r


PATIENTS = {
    # pid: (hba1c rows, urate rows)
    "P-UNDATED-HIGH": ([(6.1, "2026-08-01"), (11.2, None)], [(6.5, "2026-08-01"), (8.8, None)]),
    "P-DATED-HIGH": ([(11.2, "2026-09-01")], [(8.8, "2026-09-01")]),
    "P-DATED-LOW": ([(6.1, "2026-09-01")], [(6.5, "2026-09-01")]),
}


def _rules(tmp: Path) -> tuple[Ruleset, Lake]:
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
    from tb_contracts import CriterionIR

    feed = tmp / "feed"
    feed.mkdir()
    pts, obs = [], []
    for pid, (a1c, ua) in PATIENTS.items():
        pts.append({"resourceType": "Patient", "id": pid, "birthDate": "1960-01-01", "gender": "male"})
        obs += [_obs(f"a-{pid}-{i}", pid, "4548-4", v, "%", d) for i, (v, d) in enumerate(a1c)]
        obs += [_obs(f"u-{pid}-{i}", pid, "3084-1", v, "mg/dL", d) for i, (v, d) in enumerate(ua)]
    for rtype, items in (("Patient", pts), ("Observation", obs)):
        (feed / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in items), "utf-8")
    lake = Lake(tmp / "lake", tz="Asia/Tokyo")
    lake.rebuild("2026-11-09", HashEmbedder(), ndjson_dir=feed)

    def crit(cid: str, kind: str, vs: str, quant: str, op: str, num: float, unit: str) -> Any:
        logic = {"domain": "observation", "quantifier": quant, "valueset": vs,
                 "value": {"op": op, "num": num, "unit": unit},
                 "window": {"anchor": "index", "from_days": -365, "to_days": 0}}  # fmt: skip
        return CriterionIR.model_validate(
            {"id": cid, "ruleset": "UNL", "kind": kind, "class": "structured", "text": cid, "logic": logic}
        )

    cs = [
        crit("UNL-EXC-01", "exclusion", "VS_HBA1C", "any", ">", 10.0, "%"),
        crit("UNL-INC-01", "inclusion", "VS_URATE", "latest", ">=", 7.0, "mg/dL"),
    ]
    term = Terminology()
    vs = {}
    for name, concept in (("VS_HBA1C", "hba1c"), ("VS_URATE", "uric acid")):
        res = term.map("observation", concept)
        vs[name] = valueset("UNL", name, concept, res.concepts, "1.0.0", families=res.families)
    sql = SqlGenerator("UNL", "1.0.0", ValueSets("UNL", vs, term)).render(cs)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    rs = Ruleset(manifest=base.model_copy(update={"id": "UNL", "library": None, "criteria": [c.id for c in cs]}),
                 criteria=cs, valuesets=vs, sql=sql)  # fmt: skip
    return rs, lake


def _results(tmp: Path) -> dict[str, dict[str, Any]]:
    from datetime import date

    from lake.client import LakeLocal
    from orchestrator.scenarios.evaluate import SqlEngine

    rs, _ = _rules(tmp)
    lake = LakeLocal(tmp / "lake", HashEmbedder())
    ev = SqlEngine(lake).evaluate(rs, sorted(PATIENTS), date(2026, 11, 9), ["UNL-EXC-01", "UNL-INC-01"])
    return {p: dict(ev[p].results) for p in PATIENTS}


def test_dated_results_still_decide(tmp_path: Path) -> None:
    got = _results(tmp_path)
    assert got["P-DATED-HIGH"] == {"UNL-EXC-01": True, "UNL-INC-01": True}
    assert got["P-DATED-LOW"] == {"UNL-EXC-01": False, "UNL-INC-01": False}


def test_an_undated_result_leaves_the_criterion_unknown_where_the_dated_ones_do_not_settle_it(tmp_path: Path) -> None:
    got = _results(tmp_path)["P-UNDATED-HIGH"]
    assert got["UNL-EXC-01"] is None  # an undated 11.2 % may lie in the window: never a silent "clear"
    assert got["UNL-INC-01"] is None  # an undated 8.8 may be newer than the dated 6.5: never a silent "not met"
