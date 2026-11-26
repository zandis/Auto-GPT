"""M2 (9h-4): a licensed vocabulary the hospital has not loaded (SNOMED CT here) makes the DECISION unknown, never no.

A diagnosis the lake holds only as a SNOMED CT code cannot match an ICD-10-CM value set. Asserted at the decision
(``SqlEngine.evaluate`` and the cascade), not at the value-set lookup: the criterion reads unknown with the reason
``unknown_code_system``, a hard exclusion never follows, and a patient with an ICD-10-CM code still answers.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.coverage import UNKNOWN_CODE_SYSTEM
from orchestrator.scenarios.evaluate import SqlEngine
from tb_common.ruleset import Ruleset

from tests.offlist_fixture import FIX, SNAPSHOT, index_date, offlist_ruleset

ROOT = Path(__file__).resolve().parents[2]
SNOMED = "http://snomed.info/sct"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
CRIT = "OFFL-INC-01"


def _lake(tmp: Path) -> Any:
    from lake.store import Lake

    src = tmp / "src"
    shutil.copytree(FIX, src, ignore=shutil.ignore_patterns("*.json"))
    first = next(json.loads(ln) for ln in (src / "Condition.ndjson").read_text("utf-8").splitlines() if ln.strip())
    for pid, system, code in (("SNO-ONLY", SNOMED, "190268003"), ("ICD-GOUT", ICD, "M10.9")):
        with (src / "Patient.ndjson").open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"resourceType": "Patient", "id": pid, "birthDate": "1960-01-01", "gender": "male"}) + "\n"
            )
        c = {**first, "id": f"c-{pid.lower()}", "subject": {"reference": f"Patient/{pid}"},
             "code": {"coding": [{"system": system, "code": code}]}}  # fmt: skip
        with (src / "Condition.ndjson").open("a", encoding="utf-8") as f:
            f.write(json.dumps(c) + "\n")
    Lake(tmp / "lake").rebuild(SNAPSHOT, HashEmbedder(), src)
    return LakeLocal(tmp / "lake", HashEmbedder())


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    crit, vs, vsi, expected = offlist_ruleset()
    sql = SqlGenerator("OFFL", "1.0.0", vsi).render(crit)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "OFFL", "library": None, "criteria": [c.id for c in crit]})
    rs = Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql)
    return {"rs": rs, "day": index_date(expected), "lake": _lake(tmp_path_factory.mktemp("absent"))}


def test_a_diagnosis_only_in_an_absent_licensed_system_reads_unknown_at_the_decision(world: dict[str, Any]) -> None:
    got = SqlEngine(world["lake"], SNAPSHOT).evaluate(world["rs"], ["SNO-ONLY", "ICD-GOUT"], world["day"], [CRIT])
    assert got["SNO-ONLY"].results[CRIT] is None and (got["SNO-ONLY"].reasons or {}).get(CRIT) == UNKNOWN_CODE_SYSTEM
    assert (got["ICD-GOUT"].reasons or {}).get(CRIT) != UNKNOWN_CODE_SYSTEM


def test_the_cascade_never_excludes_on_it(world: dict[str, Any]) -> None:
    cfg = CascadeConfig(study_id="OFFL", run_date=world["day"], index_mode="single", population=["SNO-ONLY"],
                        semantics="v1", snapshot=None)  # fmt: skip
    o = run_cascade(world["lake"], world["rs"], cfg).traces["SNO-ONLY"].outcomes[CRIT]
    assert (o.status, o.hard, o.reason) == ("unknown", False, UNKNOWN_CODE_SYSTEM)
