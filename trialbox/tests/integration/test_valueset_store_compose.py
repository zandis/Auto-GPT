"""The compile's equivalence check on a fresh FHIR store, with a ValueSet whose concept mapped to no code.

The MVP walk stopped at step 3 (protocol import) on a fresh box: every compile failed its equivalence check with
"the FHIR server refused it (FhirEvalError) ... Failed to expand ValueSet". The store holds no code system, and a
compiled ValueSet with no code (a concept the model named in words no table has) has no ``compose`` its CQL engine can
fall back to. The compiler now gives the store each ValueSet expanded already (``tb_common.fhir.store_valueset``), so
the check runs with nothing loaded into the store but the patients, the ValueSets and the libraries.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from tb_contracts import CriterionIR

from tests.stack import url

pytestmark = pytest.mark.integration
FHIR = url("FHIR", "/fhir")
UNMAPPED = "synthetic qwerty zxcv syndrome"  # in no shipped table: the mapper finds no code for it


def test_a_value_set_with_no_code_does_not_stop_the_equivalence_check(tmp_path: Path) -> None:
    from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.equivalence.gate import run_gate
    from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from tb_common.fhir import FhirEvaluator, library_resource

    from tests.offlist_fixture import build_lake, index_date, offlist_ruleset, resources

    if not available():
        pytest.skip("cql-translator jars not available on the host (.cache/jvm)")
    term = Terminology()
    crit, vs, _, expected = offlist_ruleset(term)
    res = term.map("condition", UNMAPPED)
    assert res.method == "none" and not res.concepts
    # a fresh id, so no earlier run left this ValueSet in the store
    rid = f"OFFL{uuid.uuid4().hex[:8].upper()}"
    vs["VS_UNMAPPED"] = valueset(rid, "VS_UNMAPPED", UNMAPPED, res.concepts, "1.0.0", res.needs_review)
    crit.append(CriterionIR.model_validate({
        "id": "OFFL-INC-09", "ruleset": "OFFL", "kind": "inclusion", "class": "structured", "text": UNMAPPED,
        "logic": {"domain": "condition", "quantifier": "any", "valueset": "VS_UNMAPPED"},
    }))  # fmt: skip
    vsi = ValueSets("OFFL", vs, term)
    gen = CqlGenerator("OFFL", "1.0.0", vsi)
    cql = gen.render(crit)
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    fh = FhirEvaluator(FHIR)
    fh.load(
        [
            library_resource("FHIRHelpers", "4.0.1", fhirhelpers_source(), tr.elm["FHIRHelpers"]),
            library_resource("TB_Common", "1.0.0", render_common(), tr.elm["TB_Common"]),
            library_resource(gen.library, gen.library_version, cql, tr.elm[gen.library]),
        ],
        vs.values(),
    )
    for r in resources():
        fh.put(r)
    lake = LakeLocal(build_lake(tmp_path / "lake"), HashEmbedder())
    rep = run_gate(crit, SqlGenerator("OFFL", "1.0.0", vsi).render(crit), gen.library, lake, fh,
                   index_date(expected), "OFFL|1.0.0")  # fmt: skip
    assert rep.failing == [] and rep.overall_pct == 100.0, [d.model_dump() for d in (rep.disagreements or [])[:5]]
    assert rep.sample_size == len(expected["compiled"]) and rep.per_criterion["OFFL-INC-09"] == 100.0
    got = fh.evaluate_many(gen.library, sorted(expected["compiled"]), index_date(expected),
                           CqlGenerator.expression_names(crit))  # fmt: skip
    # no record is coded with a code the ValueSet lists: no patient has the concept
    assert {e.pid: e.results["OFFL-INC-09"] for e in got} == dict.fromkeys(expected["compiled"], False)
