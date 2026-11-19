"""Lane G's accuracy run on the real pair (#639, 2026-11-15): jmed's diabetes protocol wrongly excluded every patient.

Two faults met. (1) The compiler kept a negated exclusion: "history of diabetes" came back from the model as a
structured exclusion whose atom says "none of diabetes" (the prompt forbids it: exclusions are positive). Only a
negated note question was caught. Now an exclusion whose whole logic is negated (an atom with quantifier ``none``, or
``not(...)``) is rewritten to the positive form and flagged for review, as the question is; a negation inside the
logic ("diabetes and no insulin") and any inclusion are left alone. The review page says what was rewritten.
(2) Its value set mapped to no code (generic "diabetes mellitus" is not in the terminology), and an empty list still
answered: "none of" an empty list is TRUE for everyone, "any of" it FALSE. A list with no code cannot answer: the
runtime reads it as unknown (``code_system_not_carried``, D-795), on the SQL engine and the cascade. Synthetic data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ir_extract.postprocess import postprocess
from criteria_compiler.review import rows
from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.carried import NOT_CARRIED, Carried
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.coverage import UNKNOWN_CODE_SYSTEM
from orchestrator.scenarios.evaluate import SqlEngine
from tb_common import id_rule
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, LlmExtractOutput

from tests.offlist_fixture import FIX, SNAPSHOT, index_date, offlist_ruleset

ROOT = Path(__file__).resolve().parents[2]


def _crit(kind: str, logic: dict[str, Any], text: str) -> dict[str, Any]:
    return {"text": text, "kind": kind, "class": "structured", "logic": logic,
            "concept_candidates": [{"domain": "condition", "name": "diabetes mellitus"}]}  # fmt: skip


DM = {"domain": "condition", "concept": "diabetes mellitus"}


def test_a_negated_exclusion_is_rewritten_positive_and_flagged() -> None:
    post = postprocess(
        "MJMED-DM",
        LlmExtractOutput.model_validate(
            {
                "criteria": [
                    _crit(
                        "exclusion", {**DM, "quantifier": "none"}, "History of diabetes"
                    ),  # jmed's EXC-01, as compiled
                    _crit("exclusion", {"op": "not", "args": [{**DM, "quantifier": "any"}]}, "History of diabetes"),
                    _crit(
                        "exclusion",
                        {"op": "and", "args": [{**DM, "quantifier": "any"}, {**DM, "quantifier": "none"}]},
                        "Diabetes, and no other",
                    ),
                    _crit("inclusion", {**DM, "quantifier": "none"}, "No history of diabetes"),
                    _crit("exclusion", {**DM, "quantifier": "any"}, "History of diabetes"),
                ]
            }
        ),
        Terminology(),
    )
    c1, c2, c3, c4, c5 = post.criteria
    assert c1.logic is not None and getattr(c1.logic, "quantifier", None) == "any"
    assert c1.flags is not None and {"negated_logic_rewritten", "needs_review"} <= set(c1.flags)
    assert getattr(c2.logic, "domain", None) == "condition" and getattr(c2.logic, "quantifier", None) == "any"
    assert c2.flags is not None and "negated_logic_rewritten" in c2.flags
    for c in (c3, c4, c5):  # a negation inside the logic, an inclusion, a positive exclusion: untouched
        assert "negated_logic_rewritten" not in (c.flags or []), c.id
    assert getattr(c4.logic, "quantifier", None) == "none"
    assert any("MJMED-DM-EXC-01" in w and "negated" in w for w in post.warnings)
    summary = rows(post.criteria, post.valuesets, None)[0]["summary"]
    assert "rewritten from the negated form: No diagnosis of diabetes" in summary  # the reviewer sees both


def _empty(rs_id: str) -> dict[str, Any]:
    return valueset(rs_id, "VS_DIABETES_MELLITUS", "diabetes mellitus", [], "1.0.0", True)


def _ir(cid: str, kind: str, quantifier: str) -> CriterionIR:
    return CriterionIR.model_validate({"id": cid, "ruleset": "OFFL", "kind": kind, "class": "structured", "text": cid,
        "logic": {"domain": "condition", "quantifier": quantifier, "valueset": "VS_DIABETES_MELLITUS"}})  # fmt: skip


def test_a_list_with_no_code_never_answers() -> None:
    vs = {"VS_DIABETES_MELLITUS": _empty("OFFL")}
    carried = Carried({"condition": frozenset({"http://hl7.org/fhir/sid/icd-10-cm"})})
    none_exc, any_inc = _ir("OFFL-EXC-09", "exclusion", "none"), _ir("OFFL-INC-09", "inclusion", "any")
    assert carried.doubt(none_exc, vs, True) and not carried.doubt(none_exc, vs, False)
    assert carried.doubt(any_inc, vs, False) and not carried.doubt(any_inc, vs, True)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from lake.store import Lake

    crit, vs, _vsi, expected = offlist_ruleset()
    extra = [_ir("OFFL-EXC-09", "exclusion", "none"), _ir("OFFL-INC-09", "inclusion", "any")]
    crit = [*crit, *extra]
    vs = {**vs, "VS_DIABETES_MELLITUS": _empty("OFFL")}
    sql = SqlGenerator("OFFL", "1.0.0", ValueSets("OFFL", vs, Terminology())).render(crit)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "OFFL", "library": None, "criteria": [c.id for c in crit]})
    tmp = tmp_path_factory.mktemp("empty-list")
    id_rule.write_snapshot_record(FIX)  # D-1253: a snapshot of this release
    Lake(tmp / "lake").rebuild(SNAPSHOT, HashEmbedder(), FIX)
    lake = LakeLocal(tmp / "lake", HashEmbedder())
    pids = sorted({r["pid"] for r in lake.query("SELECT pid FROM patient", None, SNAPSHOT).to_pylist()})
    rs = Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql)
    return {"rs": rs, "lake": lake, "pids": pids, "day": index_date(expected)}


def test_the_engines_read_an_empty_list_as_unknown(world: dict[str, Any]) -> None:
    rs, lake, pids, day = world["rs"], world["lake"], world["pids"], world["day"]
    got = SqlEngine(lake, SNAPSHOT).evaluate(rs, pids, day, ["OFFL-EXC-09", "OFFL-INC-09"])
    for pid, ev in got.items():
        why = ev.reasons or {}
        assert ev.results["OFFL-EXC-09"] is None and why.get("OFFL-EXC-09") == NOT_CARRIED, pid
        # an inclusion beside an unreadable record is already unknown by D-130; either way it never answers
        assert ev.results["OFFL-INC-09"] is None and why.get("OFFL-INC-09") in (NOT_CARRIED, UNKNOWN_CODE_SYSTEM), pid
    cfg = CascadeConfig(study_id="OFFL", run_date=day, index_mode="single", population=pids, semantics="v1",
                        snapshot=None)  # fmt: skip
    res = run_cascade(lake, rs, cfg)
    for pid in pids:
        t = res.traces[pid]
        assert t.exit_criterion not in ("OFFL-EXC-09", "OFFL-INC-09"), pid  # jmed: 297 of 297 excluded here
        if "OFFL-EXC-09" in t.outcomes:
            assert t.outcomes["OFFL-EXC-09"].reason == NOT_CARRIED and not t.outcomes["OFFL-EXC-09"].hard, pid
