"""inv-j5 (the battery's metamorphic ``duplicate`` relation): a diagnosis row written twice in one encounter counted as a
second visit, so GOUT-COH-INC-04 ("seen for gout twice in a year") passed 197 of 2,000 patients who were seen once.

A condition ``count>=`` atom now counts visits: the row's encounter, and a row without one counts alone. The SQL
(runtime), the CQL (the approval's equivalence gate) and the shipped GOUT-COH ruleset say the same. Synthetic FHIR
conditions; the lake in-process; the local CQL engine where it is fetched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
IDX = date(2026, 10, 5)
GOUT = "M10.9"

pytestmark = pytest.mark.nodb  # the lake is in-process


def _cond(pid: str, cid: str, enc: str | None, onset: str = "2026-03-10") -> dict[str, Any]:
    c: dict[str, Any] = {"resourceType": "Condition", "id": cid, "subject": {"reference": f"Patient/{pid}"},
                         "code": {"coding": [{"system": ICD, "code": GOUT}]}, "onsetDateTime": onset}  # fmt: skip
    if enc:
        c["encounter"] = {"reference": f"Encounter/{enc}"}
    return c


CONDITIONS = [
    _cond("P-DUP", "c1", "e1"),
    _cond("P-DUP", "c2", "e1"),  # the same diagnosis written twice in one visit: one visit
    _cond("P-TWO", "c3", "e2"),
    _cond("P-TWO", "c4", "e3", onset="2026-06-01"),  # two visits
    _cond("P-NOENC", "c5", None),
    _cond("P-NOENC", "c6", None, onset="2026-06-01"),  # no encounter on either row: each counts alone
    _cond("P-ONE", "c7", "e4"),
]
PIDS = ["P-DUP", "P-TWO", "P-NOENC", "P-ONE"]
EXPECTED = {"P-DUP": False, "P-TWO": True, "P-NOENC": True, "P-ONE": False}
VS = {"VS_GOUT": valueset("VC", "VS_GOUT", "gout", [Concept(ICD, GOUT, "gout")], "1.0.0")}
CRIT = [
    CriterionIR.model_validate(
        {
            "id": "VC-INC-01",
            "ruleset": "VC",
            "kind": "inclusion",
            "class": "structured",
            "text": "seen twice for gout",
            "logic": {
                "domain": "condition",
                "quantifier": "count>=",
                "count": 2,
                "valueset": "VS_GOUT",
                "window": {"anchor": "index", "from_days": -365, "to_days": 0},
            },
        }
    )
]


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> tuple[LakeLocal, Path]:
    tmp = tmp_path_factory.mktemp("visits")
    nd = tmp / "ndjson"
    nd.mkdir()
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "male"} for p in PIDS]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "Condition.ndjson").write_text("\n".join(json.dumps(c) for c in CONDITIONS) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text("", encoding="utf-8")
    Lake(tmp / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder()), nd


def _answers(lake: LakeLocal, sql: str, cid: str) -> dict[str, Any]:
    rows = lake.query(sql, [[IDX.isoformat()], None]).to_pylist()
    return {r["pid"]: r[f"C_{cid}"] for r in rows if r["pid"] in EXPECTED}


def test_the_sql_counts_a_visit_once(lake: tuple[LakeLocal, Path]) -> None:
    sql = SqlGenerator("VC", "1.0.0", ValueSets("VC", VS, Terminology())).render(CRIT)
    assert _answers(lake[0], sql, "VC-INC-01") == EXPECTED


def test_the_shipped_gout_ruleset_counts_a_visit_once(lake: tuple[LakeLocal, Path]) -> None:
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    got = _answers(lake[0], rs.sql, "GOUT-COH-INC-04")
    assert got == EXPECTED or {p: got[p] for p in ("P-DUP", "P-ONE")} == {"P-DUP": False, "P-ONE": False}, got
    assert got["P-DUP"] is False  # the battery's case: one visit is never "seen twice"


def test_the_cql_says_the_same(lake: tuple[LakeLocal, Path]) -> None:
    gen = CqlGenerator("VC", "1.0.0", ValueSets("VC", VS, Terminology()))
    cql = gen.render(CRIT)
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source
    from tb_common.fhir import FhirEvaluator, library_resource

    from tools import cql_eval

    if not (available() and cql_eval.available()):
        pytest.skip("CQL translator or local CQL engine not available (python -m tools.cql_eval --fetch)")
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    head = next(x for x in cql.splitlines() if x.startswith("library "))
    version = head.split(" version ")[1].strip().strip("'")
    libs = [library_resource("TB_Common", "1.0.0", render_common(), tr.elm.get("TB_Common")),
            library_resource(gen.library, version, cql, tr.elm.get(gen.library))]  # fmt: skip
    pats = (lake[1] / "Patient.ndjson").read_text(encoding="utf-8").splitlines()
    lines = [*pats, *map(json.dumps, CONDITIONS), *(json.dumps(v) for v in VS.values()), *map(json.dumps, libs)]
    exprs = CqlGenerator.expression_names(CRIT)
    bodies = cql_eval.run(lines, gen.library, version, IDX, exprs, PIDS)
    got = {}
    for body in bodies:
        pid = str(body.get("id"))
        got[pid] = FhirEvaluator.parse(pid, IDX, body, exprs).results["VC-INC-01"]
    assert got == EXPECTED
