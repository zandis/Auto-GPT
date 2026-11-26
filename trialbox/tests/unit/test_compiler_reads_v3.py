"""The compiler reads CriterionIRv3 (RULES-ARCH §2.3, R3 item 2): a v1 criterion is upgraded at load, and the 8 live
rulesets compile to the committed SQL and CQL byte for byte, whether they are given as v1 or as v3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import CompileError, lower
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from tb_contracts import CriterionIR
from tb_contracts.criterion_ir import CriterionIRv3, upgrade_v1

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
LIVE = sorted(p.parent for p in (ROOT / "rulesets").glob("*/manifest.yaml"))


def _load(rdir: Path) -> tuple[dict[str, Any], list[CriterionIR], ValueSets, int]:
    m = yaml.safe_load((rdir / "manifest.yaml").read_text("utf-8"))
    crit = [CriterionIR.model_validate_json((rdir / "ir" / f"{cid}.json").read_text("utf-8")) for cid in m["criteria"]]
    vs = {p.stem: json.loads(p.read_text("utf-8")) for p in (rdir / "valuesets").glob("*.json")}
    lookback = int(((m.get("scopes") or {}).get("feas") or {}).get("lookback_months") or 36)
    return m, crit, ValueSets(m["id"], vs, Terminology()), lookback


def test_the_eight_live_rulesets_are_here() -> None:
    assert [d.name for d in LIVE] == ["AD-MAB", "GOUT-COH", "GZQO", "NEUR-COH", "ONC-OSI", "RA-BIO", "RA-COH", "RA-JAK"]


@pytest.mark.parametrize("rdir", LIVE, ids=lambda d: d.name)
def test_live_ruleset_compiles_byte_identical_from_v1_and_v3(rdir: Path) -> None:
    m, crit, vsi, lookback = _load(rdir)
    v3 = [upgrade_v1(c) for c in crit]
    sql_v1 = SqlGenerator(m["id"], m["version"], vsi).render(crit)
    sql_v3 = SqlGenerator(m["id"], m["version"], vsi).render(v3)
    assert sql_v1 == sql_v3 == (rdir / "sql" / f"{m['id']}.sql").read_text("utf-8")
    gen = CqlGenerator(m["id"], m["version"], vsi, lookback)
    cql_v1 = gen.render(crit)
    cql_v3 = CqlGenerator(m["id"], m["version"], vsi, lookback).render(v3)
    assert cql_v1 == cql_v3 == (rdir / "cql" / f"{gen.library}.cql").read_text("utf-8")
    assert "GENERATED" in cql_v1 and '"C_' in sql_v1  # compiled, not refused


def _crit(**atom: Any) -> dict[str, Any]:
    return {
        "id": "SYN-EXC-01",
        "ruleset": "SYN",
        "kind": "exclusion",
        "class": "structured",
        "text": {"source": "Synthetic ALT above a limit"},
        "logic": "a1",
        "atoms": [{"id": "a1", "domain": "observation", "valueset": "VS_X", "quantifier": "latest",
                   "value": {"op": ">", "num": 120, "unit": "U/L"},
                   "window": {"from_days": -180, "to_days": 0}, **atom}],
    }  # fmt: skip


def _both(doc: dict[str, Any]) -> tuple[str, str]:
    vs = {
        "VS_X": {
            "url": "urn:tb:vs:VS_X",
            "compose": {"include": [{"system": "http://loinc.org", "concept": [{"code": "1742-6"}]}]},
        }
    }
    vsi = ValueSets("SYN", vs, Terminology())
    ir = CriterionIRv3.model_validate(doc)
    return SqlGenerator("SYN", "1.0.0", vsi).render([ir]), CqlGenerator("SYN", "1.0.0", vsi).render([ir])


def test_card_ref_and_written_out_defaults_compile_as_their_absence() -> None:
    plain = _both(_crit())
    carded = _crit(on_hit="exclude")
    carded["atoms"][0]["window"]["unit"] = "d"
    carded.update(ir_version="3.1.0", card_ref={"card_id": "lab.alt", "card_version": "1.0.0", "params": {"x": 1}})
    assert _both(carded) == plain


def test_a_window_in_hours_goes_to_a_person_in_both_engines() -> None:
    doc = _crit()
    doc["atoms"][0]["window"]["unit"] = "h"
    doc["ir_version"] = "3.1.0"
    ir = CriterionIRv3.model_validate(doc)
    with pytest.raises(CompileError, match="hours"):
        lower(ir)
    vsi = ValueSets("SYN", {}, Terminology())
    for gen in (SqlGenerator("SYN", "1.0.0", vsi), CqlGenerator("SYN", "1.0.0", vsi)):
        with pytest.raises(CompileError):
            gen.render([ir])


def test_cql_refuses_what_only_the_sql_compiles() -> None:
    doc = _crit(domain="medication", value=None, quantifier="any", medication={"route": ["4132161"]})
    doc["atoms"][0] = {k: v for k, v in doc["atoms"][0].items() if v is not None}
    ir = CriterionIRv3.model_validate(doc)
    vsi = ValueSets("SYN", {"VS_X": {"compose": {"include": []}}}, Terminology())
    assert '"C_SYN-EXC-01"' in SqlGenerator("SYN", "1.0.0", vsi).render([ir])
    with pytest.raises(CompileError, match="not compiled to CQL"):
        CqlGenerator("SYN", "1.0.0", vsi).render([ir])


def test_v1_input_is_upgraded_at_load() -> None:
    v1 = CriterionIR.model_validate(
        {"id": "SYN-EXC-01", "ruleset": "SYN", "kind": "exclusion", "class": "structured", "text": "t",
         "logic": {"domain": "condition", "valueset": "VS_X"}}
    )  # fmt: skip
    low, ext = lower(v1)
    assert low.id == v1.id and low.text == "t" and low.logic == v1.logic
    assert [a.id for a in ext.values()] == ["a1"]  # the upgraded v3 atom rides beside the lowered one
