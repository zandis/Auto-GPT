"""Post-processing of ``ir_extract`` output (SPEC §7.1) into Criterion IR + ValueSets.

* ids ``<RULESET>-INC-01`` ... per kind, in source order;
* concept names -> ``VS_<NAME>`` ids; each concept mapped through the terminology tables (§4.3.1);
* derived atoms reference ``VS_<DERIVED>_COMPONENTS`` built from the shared constants; demographic atoms ``NONE``;
* classification sanity: a ``structured`` criterion whose logic cannot be compiled, or whose concepts did not map,
  is flagged ``needs_review`` (never silently dropped).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tb_common.derived import CODES, COMPONENTS
from tb_contracts import CriterionIR, LlmExtractOutput, dump

from criteria_compiler.semantics import CompileError, atoms, check_bool, kind
from criteria_compiler.terminology.mapper import (
    Concept,
    ConceptMapLLM,
    MappingResult,
    Terminology,
    ValueSets,
    valueset,
    vs_name_for,
)

KIND_CODE = {"inclusion": "INC", "exclusion": "EXC", "renewal": "REN", "documentation": "DOC"}


@dataclass
class PostResult:
    criteria: list[CriterionIR]
    valuesets: dict[str, dict[str, Any]]
    mappings: dict[str, MappingResult] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def vs_index(self, ruleset: str, term: Terminology | None) -> ValueSets:
        return ValueSets(ruleset, self.valuesets, term)


def _convert_logic(node: dict[str, Any], concept_vs: dict[str, str]) -> dict[str, Any]:
    if "op" in node and "args" in node:
        return {"op": node["op"], "args": [_convert_logic(a, concept_vs) for a in node["args"]]}
    atom = {k: v for k, v in node.items() if k != "concept" and v is not None}
    if node.get("domain") == "demographic":
        atom["valueset"] = "NONE"
    elif node.get("derived"):
        atom["valueset"] = f"VS_{str(node['derived']).upper()}_COMPONENTS"
    else:
        concept = node.get("concept")
        if not concept:
            raise CompileError(f"{node.get('domain')} atom has no concept")
        atom["valueset"] = concept_vs.get(concept.strip().lower()) or vs_name_for(concept)
    return atom


def derived_valueset(ruleset: str, derived: str, version: str, term: Terminology) -> dict[str, Any]:
    concepts = []
    for comp in COMPONENTS[derived]:
        system, code = CODES[comp]
        hit = term.concept(system, code)
        concepts.append(hit or Concept(system, code, comp))
    return valueset(ruleset, f"VS_{derived.upper()}_COMPONENTS", f"{derived.upper()} components", concepts, version)


def postprocess(
    ruleset: str,
    extracted: LlmExtractOutput,
    term: Terminology,
    version: str = "1.0.0",
    llm_map: ConceptMapLLM | None = None,
    id_offset: dict[str, int] | None = None,
) -> PostResult:
    counters = dict(id_offset or {})
    concept_vs: dict[str, str] = {}
    valuesets: dict[str, dict[str, Any]] = {}
    mappings: dict[str, MappingResult] = {}
    warnings: list[str] = []
    criteria: list[CriterionIR] = []
    # 1. concepts -> ValueSets
    for ec in extracted.criteria:
        for cand in ec.concept_candidates:
            key = cand.name.strip().lower()
            if key in concept_vs or cand.domain == "demographic":
                continue
            vs_name = vs_name_for(cand.name)
            if vs_name in valuesets:  # another concept with the same slug: never overwrite its ValueSet
                vs_name = vs_name_for(cand.name, unique=True)
            res = term.map(cand.domain, cand.name, cand.synonyms or [], llm_map)
            mappings[vs_name] = res
            concept_vs[key] = vs_name
            valuesets[vs_name] = valueset(ruleset, vs_name, cand.name, res.concepts, version, res.needs_review)
            if res.method == "none":
                warnings.append(f"concept '{cand.name}' ({cand.domain}) could not be mapped")
    # 2. criteria -> IR
    for ec in extracted.criteria:
        code = KIND_CODE[ec.kind]
        counters[code] = counters.get(code, 0) + 1
        cid = f"{ruleset}-{code}-{counters[code]:02d}"
        flags: list[str] = []
        raw = dump(ec)
        logic_raw = raw.get("logic") or {"domain": "demographic"}
        try:
            logic = _convert_logic(logic_raw, concept_vs)
        except CompileError as exc:
            warnings.append(f"{cid}: {exc}")
            logic, flags = {"domain": "demographic", "valueset": "NONE"}, ["needs_review", "logic_invalid"]
        ir_dict = {k: v for k, v in raw.items() if k not in ("concept_candidates", "logic") and v is not None}
        ir_dict.update({"id": cid, "ruleset": ruleset, "logic": logic, "review": {"status": "draft"}})
        ir = CriterionIR.model_validate(ir_dict)
        if ir.class_ == "structured":
            try:
                check_bool(ir.logic)
                for a in atoms(ir.logic):
                    kind(a)
                    if a.derived and a.valueset not in valuesets:
                        valuesets[a.valueset] = derived_valueset(ruleset, a.derived, version, term)
                    if a.valueset not in ("NONE",) and a.valueset not in valuesets:
                        raise CompileError(f"ValueSet {a.valueset} has no concept candidate")
                    m = mappings.get(a.valueset)
                    if m is not None and (m.needs_review or not m.concepts):
                        flags.append("concept_unmapped" if not m.concepts else "concept_needs_review")
            except CompileError as exc:
                warnings.append(f"{cid}: {exc}")
                flags.append("logic_invalid")
        if ir.class_ == "note" and not ir.note_question:
            flags.append("missing_note_question")
        if ir.class_ == "human" and not ir.human_question:
            flags.append("missing_human_question")
        if flags:
            ir = ir.model_copy(update={"flags": sorted(set(flags) | {"needs_review"})})
        criteria.append(ir)
    return PostResult(criteria, dict(sorted(valuesets.items())), mappings, warnings)
