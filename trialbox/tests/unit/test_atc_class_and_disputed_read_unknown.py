"""Lane E's CGRD-A2 (#711, D-813), lane A2's side: a drug whose ATC is only a level-4 class, or whose two ATC codes
disagree, never answers a drug criterion yes or no.

The mapping writes a class-only answer under ``urn:trialbox:atc-class`` and two disagreeing codes under
``urn:trialbox:atc-disputed``; neither is the ATC system. The lake keeps only an ATC-system code in its ``atc`` column
(``lake.flatten.is_atc_system``), so such a row reaches matching with no ATC, and D-130's coverage rule turns an
inclusion's FALSE into unknown (``unknown_code_system``) on the SQL engine and on the cascade. A criterion on the class
(the value set's ATC family) reads the row the same way: unknown, never a guessed match, until the lake carries the
class. A drug with its ATC answers as before. Synthetic fixture (the off-list one) plus three NHI-shaped drug lines.
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
from tb_common import id_rule
from tb_common.ruleset import Ruleset

from tests.offlist_fixture import FIX, SNAPSHOT, index_date, offlist_ruleset

ROOT = Path(__file__).resolve().parents[2]
CLASS = "urn:trialbox:atc-class"
DISPUTED = "urn:trialbox:atc-disputed"
NHI = "https://trialbox.local/fhir/CodeSystem/nhi-drug"
DRUG = "OFFL-INC-02"  # urate-lowering therapy in the last 180 days: level-5 codes and the M04AA family

# (patient, codings): the class only (no level 5 in the list); two codes that disagree; the hospital's own ATC
EXTRA = {
    "ATC-CLASS": [(NHI, "AC00000100"), (CLASS, "M04AA")],
    "ATC-DISPUTED": [(NHI, "AC00000200"), (DISPUTED, "M04AA01"), (DISPUTED, "C10AA05")],
    "ATC-AGREED": [(NHI, "AC00000300"), ("http://www.whocc.no/atc", "M04AA01")],
}


def _lake(tmp: Path) -> LakeLocal:
    from lake.store import Lake

    src = tmp / "src"
    shutil.copytree(FIX, src, ignore=shutil.ignore_patterns("*.json"))
    with (src / "Patient.ndjson").open("a", encoding="utf-8") as f:
        for pid in EXTRA:
            f.write(
                json.dumps({"resourceType": "Patient", "id": pid, "birthDate": "1960-01-01", "gender": "male"}) + "\n"
            )
    with (src / "MedicationRequest.ndjson").open("a", encoding="utf-8") as f:
        for pid, codings in EXTRA.items():
            f.write(json.dumps({
                "resourceType": "MedicationRequest", "id": f"m-{pid.lower()}", "status": "active", "intent": "order",
                "subject": {"reference": f"Patient/{pid}"}, "authoredOn": "2026-08-01",
                "medicationCodeableConcept": {"coding": [{"system": s, "code": c} for s, c in codings]},
            }) + "\n")  # fmt: skip
    id_rule.write_snapshot_record(src)  # D-1253: a snapshot of this release
    Lake(tmp / "lake").rebuild(SNAPSHOT, HashEmbedder(), src)
    return LakeLocal(tmp / "lake", HashEmbedder())


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    crit, vs, vsi, expected = offlist_ruleset()
    sql = SqlGenerator("OFFL", "1.0.0", vsi).render(crit)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "OFFL", "library": None, "criteria": [c.id for c in crit]})
    rs = Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql)
    return {"rs": rs, "day": index_date(expected), "lake": _lake(tmp_path_factory.mktemp("atc-class"))}


def test_the_lake_keeps_no_atc_for_a_class_or_a_dispute(world: dict[str, Any]) -> None:
    rows = world["lake"].query("SELECT pid, atc, nhi_code FROM medication", None, SNAPSHOT).to_pylist()
    atc = {r["pid"]: r["atc"] for r in rows if r["pid"] in EXTRA}
    assert atc == {"ATC-CLASS": None, "ATC-DISPUTED": None, "ATC-AGREED": "M04AA01"}


def test_the_sql_engine_reads_a_class_or_a_dispute_as_unknown(world: dict[str, Any]) -> None:
    rs, day = world["rs"], world["day"]
    got = SqlEngine(world["lake"], SNAPSHOT).evaluate(rs, sorted(EXTRA), day, [DRUG])
    for pid in ("ATC-CLASS", "ATC-DISPUTED"):
        assert got[pid].results[DRUG] is None and (got[pid].reasons or {}).get(DRUG) == UNKNOWN_CODE_SYSTEM, pid
    assert got["ATC-AGREED"].results[DRUG] is True


def test_the_cascade_never_excludes_on_a_class_or_a_dispute(world: dict[str, Any]) -> None:
    rs, day = world["rs"], world["day"]
    cfg = CascadeConfig(
        study_id="OFFL", run_date=day, index_mode="single", population=sorted(EXTRA), semantics="v1", snapshot=None
    )  # fmt: skip  (v1: an inclusion's FALSE would be a hard exclusion)
    res = run_cascade(world["lake"], rs, cfg)
    for pid in ("ATC-CLASS", "ATC-DISPUTED"):
        o = res.traces[pid].outcomes[DRUG]
        assert (o.status, o.hard, o.reason) == ("unknown", False, UNKNOWN_CODE_SYSTEM), pid
    assert res.traces["ATC-AGREED"].outcomes[DRUG].status == "pass"
