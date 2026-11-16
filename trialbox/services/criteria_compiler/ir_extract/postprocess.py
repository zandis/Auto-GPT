"""Post-processing of ``ir_extract`` output (SPEC §7.1) into Criterion IR + ValueSets.

* ids ``<RULESET>-INC-01`` ... per kind, in source order;
* concept names -> ``VS_<NAME>`` ids; each concept mapped through the terminology tables (§4.3.1);
* derived atoms reference ``VS_<DERIVED>_COMPONENTS`` built from the shared constants; demographic atoms ``NONE``;
* classification sanity: a ``structured`` (or ``mixed``) criterion whose logic cannot be compiled, or whose concepts
  did not map, is flagged ``needs_review`` (never silently dropped);
* units (D-418): a numeric lab atom with no unit, or with a unit its analyte's usual unit cannot convert to, is
  flagged ``value_unit_missing`` / ``value_unit_unconvertible`` (``criteria_compiler.unit_check``);
* clinical status (D-917): a criterion whose line says the condition is active or current ("active tuberculosis",
  活動性結核, 現在治療中) and not that it is past ("history of") counts only conditions recorded as active, recurrent or
  relapsed, or recorded with no status (``clinical_status`` on its condition atoms, ``clinical_status_from_text``): a
  condition recorded as resolved or in remission then makes the answer unknown, never a silent "active";
* polarity (D-98): an exclusion ``note_question`` in the negative is rewritten to its positive form when a safe
  English rewrite exists (``negated_question_rewritten``, original kept in ``note_question_source``), else flagged
  ``negated_question`` for the reviewer. Either way the criterion needs review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from tb_common.derived import CODES, COMPONENTS
from tb_contracts import Atom, BoolExpr, CriterionIR, LlmExtractOutput, dump
from tb_contracts.criterion_ir import ACTIVE_STATUSES

from criteria_compiler import unit_check
from criteria_compiler.ir_extract.polarity import is_negated, positive
from criteria_compiler.semantics import FILTERED, JUDGED, CompileError, atoms, check_bool, kind
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


# red of 2026-11-15 (tcga): a diagnosis the model filed under ``procedure`` ("invasive breast carcinoma") is re-filed
# under ``condition``; a name with an operation word stays a procedure
_DIAGNOSIS = re.compile(
    r"carcinoma|cancer|neoplas|tumou?r|lymphoma|leuka?emia|melanoma|sarcoma|myeloma|glioma|blastoma|disease|"
    r"syndrome|disorder|infection|failure|diabetes|hypertension|\w+itis\b|がん|癌|腫瘍|肉腫|病|症候群|炎",
    re.IGNORECASE,
)
_OPERATION = re.compile(
    r"\w+ectomy|\w+otomy|\w+ostomy|\w+plasty|resection|surgery|surgical|operation|biopsy|transplant|x-ray|scan|"
    r"imaging|therapy|radiation|手術|切除|摘出|術|移植|生検|照射",
    re.IGNORECASE,
)


# D-917: the line says the condition is active or current, and does not say it is past
_ACTIVE = re.compile(
    r"\b(?:active|current|currently|ongoing)\b|活動性|活動期|現在|治療中|進行中|目前|現患", re.IGNORECASE
)
# the line says it is past, over or ever (review of D-917: "in remission", "non-active", "no longer", 非活動性,
# 活動性のない, 現在までに "so far, ever", "cured"): no restriction, every row counts as before
_PAST = re.compile(
    r"\b(?:history|previous|previously|prior|past|former|ever|remission|resolved|cured|healed|no longer|"
    r"non-?active|inactive|not active)\b|既往|過去|以前|病史|曾|寛解|治癒|緩解|痊癒|非活動|活動性のない|"
    r"活動性でない|現在まで",
    re.IGNORECASE,
)


def says_active(text: str) -> bool:
    """The criterion's line says its condition is active or current and not that it is past (D-917)."""
    return bool(_ACTIVE.search(text)) and not _PAST.search(text)


def _active_only(logic: Any) -> tuple[Any, bool]:
    """``logic`` with ``clinical_status`` set to the active statuses on every condition atom that has none, and
    whether any changed."""
    if isinstance(logic, BoolExpr):
        parts = [_active_only(a) for a in logic.args]
        return logic.model_copy(update={"args": [p for p, _ in parts]}), any(c for _, c in parts)
    if isinstance(logic, Atom) and logic.domain == "condition" and logic.clinical_status is None:
        return logic.model_copy(update={"clinical_status": list(ACTIVE_STATUSES)}), True
    return logic, False


def is_diagnosis_name(name: str) -> bool:
    """The concept's name names a diagnosis and no operation (the test of a mis-filed procedure)."""
    return bool(_DIAGNOSIS.search(name)) and not _OPERATION.search(name)


def _convert_logic(
    node: dict[str, Any], concept_vs: dict[str, str], egfr: str = "egfr", refiled: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if "op" in node and "args" in node:
        return {"op": node["op"], "args": [_convert_logic(a, concept_vs, egfr, refiled) for a in node["args"]]}
    atom = {k: v for k, v in node.items() if k != "concept" and v is not None}
    if atom.get("domain") == "procedure" and str(node.get("concept") or "").strip().lower() in refiled:
        atom["domain"] = "condition"
    if atom.get("derived") == "egfr" and egfr != "egfr":  # D-149: the site's equation, named in the ruleset
        atom["derived"] = egfr
    if node.get("domain") == "demographic":
        atom["valueset"] = "NONE"
    elif atom.get("derived"):
        atom["valueset"] = f"VS_{str(atom['derived']).upper()}_COMPONENTS"
    else:
        concept = node.get("concept")
        if not concept:
            raise CompileError(f"{node.get('domain')} atom has no concept")
        atom["valueset"] = concept_vs.get(concept.strip().lower()) or vs_name_for(concept)
    return atom


def _question(text: str) -> str:
    return f"Does the patient meet this criterion: {text.strip()}?"


def _for_a_person(cid: str, ruleset: str, kind_: str, text: str, source_ref: Any) -> CriterionIR:
    """A criterion the compiler could not build, kept as a person's check (D-910): its line, its kind, no logic."""
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": ruleset, "kind": kind_, "class": "human", "text": text or cid,
         "human_question": _question(text or cid), "logic": {"domain": "demographic", "valueset": "NONE"},
         "review": {"status": "draft"}, **({"source_ref": source_ref} if source_ref else {})}
    )  # fmt: skip


# red of lane G's P1b run (#639, 2026-11-16): "Age outside of range specified", an exclusion, was compiled as the
# inclusion's range itself (min 18, max 35), so it excluded every patient inside the range. An exclusion's age line
# says which side is excluded; its words are read against the atom's bounds
# an outside word counts only beside the range or an age word ("not in remission" is not one); review of D-945
_OUTSIDE = re.compile(
    r"\boutside\s+(?:of\s+)?(?:the\s+)?(?:(?:specified|stated|given|above|protocol)\s+)?(?:age|range|\d)"
    r"|\bnot\s+(?:with)?in\s+(?:the\s+)?(?:age|range|\d)|\bnot\s+between\s+\d|\bbeyond\s+(?:the\s+)?(?:age|range|\d)"
    r"|範囲外|範囲以外|範圍外|範圍以外|(?:歳|才|歲|以下|以上)以外|不在\s*\d|不在.{0,3}範圍",
    re.IGNORECASE,
)
# ≤ ≦ ⩽ and ≥ ≧ ⩾ "75+" are bounds too; 以下の is "the following"; 超 only after a number or 歳 (not 超音波)
_BELOW = re.compile(
    r"\b(?:under|below|younger|less\s+than|fewer\s+than)\b|[<≤≦⩽]|未満|以下(?!の)|未滿|不足|小於|低於",
    re.IGNORECASE,
)
_ABOVE = re.compile(
    r"\b(?:over|above|older|more\s+than|greater\s+than)\b|[>≥≧⩾]|\d\s*\+|超え|超過|(?<=\d)超|(?<=[歳才歲])超"
    r"|以上|大於|高於|逾",
    re.IGNORECASE,
)


def _age_atom(logic: Any) -> Atom | None:
    """The logic when it is one age atom (no sex): the case the age rules read."""
    if isinstance(logic, Atom) and logic.domain == "demographic" and logic.age is not None and logic.sex is None:
        return logic
    return None


Bounds = tuple[float | None, float | None]


def _num_in(text: str, x: float) -> bool:
    """The number is written in the line (18 or 18.0 as "18")."""
    n = f"{x:g}"
    return re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", text) is not None


def inclusion_ages(logics: list[Any]) -> set[Bounds]:
    """The age bounds of every demographic age atom in the inclusions' raw logic (the ruleset's own range)."""
    out: set[Bounds] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "args" in node:
                for x in node["args"] or []:
                    walk(x)
            elif node.get("domain") == "demographic" and isinstance(node.get("age"), dict):
                out.add((node["age"].get("min"), node["age"].get("max")))

    for lg in logics:
        walk(lg)
    return out


def exclusion_age(text: str, logic: Any, inclusion: set[Bounds] | None = None) -> tuple[Any, str | None]:
    """An exclusion that is one age atom, read against its line and the inclusions' ages: ``(logic, flag)``.

    * A range (a minimum and a maximum) whose line says outside / not within / 範囲外 / 以外 is the range's
      complement, ``not(range)``, flagged ``age_range_inverted``, only when the range is known: both its numbers are
      in the line, or it is an inclusion's range exactly ("Age outside of range specified", NCT00606840, copied the
      inclusion's 18-35; its complement then decides as the inclusion does). An outside range from nowhere goes to a
      person (``age_range_exclusion``), as does a range whose line does not say outside: an exclusion of the patients
      inside a range is rare, and a model that copied an inclusion's range is not.
    * One bound equal to an inclusion's ("aged 18 or older" as an exclusion, ``min 18`` as the inclusion) restates
      the inclusion and goes to a person (``exclusion_restates_inclusion``); one bound inside it (an exclusion of
      over-75s under an 18+ inclusion) is ordinary and stays.
    * One bound whose line points the other way ("under 18" as ``min 18``; "≥ 75" as ``max 75``), or both ways
      ("< 18 or > 65" as ``min 65``), goes to a person (``age_direction``).
    A patient with no birth date is unknown either way (the age is NULL)."""
    atom = _age_atom(logic)
    if atom is None or atom.age is None:
        return logic, None
    inclusion = inclusion or set()
    lo, hi = atom.age.min, atom.age.max
    if lo is not None and hi is not None:
        if (lo, hi) in inclusion and not _OUTSIDE.search(text):
            return logic, "exclusion_restates_inclusion"
        if _OUTSIDE.search(text) and ((_num_in(text, lo) and _num_in(text, hi)) or (lo, hi) in inclusion):
            return BoolExpr(op="not", args=[atom]), "age_range_inverted"
        return logic, "age_range_exclusion"
    if (lo, hi) in inclusion:
        return logic, "exclusion_restates_inclusion"
    below, above = bool(_BELOW.search(text)), bool(_ABOVE.search(text))
    if (lo is not None and below and not above) or (hi is not None and above and not below) or (below and above):
        return logic, "age_direction"  # one bound for a line that points both ways ("< 18 or > 65") also goes
    return logic, None


def _positive_logic(logic: Any) -> Any:
    """The positive form of a wholly negated logic (an atom with quantifier ``none``, or ``not(x)``); None otherwise."""
    if isinstance(logic, BoolExpr):
        return logic.args[0] if logic.op == "not" and len(logic.args) == 1 else None
    if isinstance(logic, Atom) and logic.quantifier == "none":
        return logic.model_copy(update={"quantifier": "any"})
    return None


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
    egfr: str = "egfr",
) -> PostResult:
    """``egfr``: what a criterion that says only "eGFR" becomes at this site (D-149): ``egfr`` (CKD-EPI 2021, the
    meaning it always had) or ``egfr_jsn`` at a Japanese site; a protocol that names its equation keeps it."""
    counters = dict(id_offset or {})
    concept_vs: dict[str, str] = {}
    valuesets: dict[str, dict[str, Any]] = {}
    mappings: dict[str, MappingResult] = {}
    warnings: list[str] = []
    criteria: list[CriterionIR] = []
    # 1. concepts -> ValueSets
    refiled: set[str] = set()
    for ec in extracted.criteria:
        for cand in ec.concept_candidates:
            key = cand.name.strip().lower()
            if cand.domain == "procedure" and is_diagnosis_name(cand.name):
                refiled.add(key)
                cand = cand.model_copy(update={"domain": "condition"})
            if key in concept_vs or cand.domain == "demographic":
                continue
            vs_name = vs_name_for(cand.name)
            if vs_name in valuesets:  # another concept with the same slug: never overwrite its ValueSet
                vs_name = vs_name_for(cand.name, unique=True)
            res = term.map(cand.domain, cand.name, cand.synonyms or [], llm_map)
            mappings[vs_name] = res
            concept_vs[key] = vs_name
            valuesets[vs_name] = valueset(
                ruleset,
                vs_name,
                cand.name,
                res.concepts,
                version,
                res.needs_review,
                families=res.families,
                ingredients=getattr(term, "ingredients", None) if cand.domain == "medication" else None,
            )
            if res.method == "none":
                warnings.append(f"concept '{cand.name}' ({cand.domain}) could not be mapped")
    # 2. criteria -> IR
    incl_ages = inclusion_ages([dump(ec).get("logic") for ec in extracted.criteria if ec.kind == "inclusion"])
    for ec in extracted.criteria:
        code = KIND_CODE[ec.kind]
        counters[code] = counters.get(code, 0) + 1
        cid = f"{ruleset}-{code}-{counters[code]:02d}"
        flags: list[str] = []
        raw = dump(ec)
        logic_raw = raw.get("logic") or {"domain": "demographic"}
        try:
            logic = _convert_logic(logic_raw, concept_vs, egfr, frozenset(refiled))
        except CompileError as exc:
            warnings.append(f"{cid}: {exc}")
            logic, flags = {"domain": "demographic", "valueset": "NONE"}, ["needs_review", "logic_invalid"]
        ir_dict = {k: v for k, v in raw.items() if k not in ("concept_candidates", "logic") and v is not None}
        ir_dict.update({"id": cid, "ruleset": ruleset, "logic": logic, "review": {"status": "draft"}})
        try:
            ir = CriterionIR.model_validate(ir_dict)
        except ValidationError as exc:
            # D-910: one criterion the model wrote outside the IR (a public protocol is messier than the shipped
            # ones) failed the whole compile with an HTTP 500. It is kept as a person's check, flagged, with where
            # the IR refused it (never the refused value)
            where = ", ".join(".".join(str(x) for x in e["loc"]) or "criterion" for e in exc.errors()[:3])
            warnings.append(f"{cid}: not a valid criterion ({where}); kept for a person to check")
            ir = _for_a_person(cid, ruleset, ec.kind, str(raw.get("text") or ""), raw.get("source_ref"))
            flags = [*flags, "ir_invalid"]
        moved = sorted({str(c.name) for c in ec.concept_candidates if c.name.strip().lower() in refiled})
        if moved and ir.logic is not None and any(a.domain == "condition" for a in atoms(ir.logic)):
            flags.append("domain_refiled")
            warnings.append(f"{cid}: {', '.join(moved)} filed as a procedure; read as a condition (check it)")
        # red of 2026-11-15 (jmed): an exclusion whose whole logic is negated ("none of diabetes" for "history of
        # diabetes") excluded everyone with no such record. Exclusions are positive (ir_extract_v3): the logic is
        # rewritten to the positive form and flagged, as a negated question is; a negation inside it is left alone
        pos = _positive_logic(ir.logic) if ir.kind == "exclusion" and ir.class_ in FILTERED else None
        if pos is not None:
            ir = ir.model_copy(update={"logic": pos})
            flags.append("negated_logic_rewritten")
            warnings.append(f"{cid}: exclusion logic was negated; rewritten to the positive form (check it)")
        if ir.class_ in FILTERED and ir.logic is not None and says_active(ir.text):
            active, changed = _active_only(ir.logic)
            if changed:
                ir = ir.model_copy(update={"logic": active})
                flags.append("clinical_status_from_text")
                warnings.append(f"{cid}: counts only conditions recorded as active or with no status (check it)")
        if ir.kind == "exclusion" and ir.class_ in FILTERED and ir.logic is not None:
            fixed, age_flag = exclusion_age(ir.text, ir.logic, incl_ages)
            if age_flag == "age_range_inverted":
                ir = ir.model_copy(update={"logic": fixed})
                flags.append(age_flag)
                warnings.append(f"{cid}: an age range excluded its own patients; read as outside the range (check it)")
            elif age_flag is not None:
                flags.append(age_flag)
                ir = ir.model_copy(update={"class_": "human", "human_question": ir.human_question or _question(ir.text),
                                           "logic": Atom(domain="demographic", valueset="NONE")})  # fmt: skip
                warnings.append(f"{cid}: its age line may exclude the wrong side; kept for a person to check")
        if ir.class_ in FILTERED:
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
                    unit = unit_check.check(a, valuesets.get(a.valueset))
                    if unit is not None:  # D-418: a lab number that would read every result as unknown
                        flags.append(unit[0])
                        warnings.append(f"{cid}: {unit[1]}")
            except CompileError as exc:
                warnings.append(f"{cid}: {exc}")
                flags.append("logic_invalid")
        if "logic_invalid" in flags and ir.class_ in FILTERED:
            # D-910: logic the compiler cannot run (an age-or-sex atom with neither, an atom of no kind) went into
            # the SQL as written ("()") and failed later, at approval, with an HTTP 500. A person checks it instead
            ir = ir.model_copy(update={"class_": "human", "human_question": ir.human_question or _question(ir.text),
                                       "logic": Atom(domain="demographic", valueset="NONE")})  # fmt: skip
            warnings.append(f"{cid}: its logic cannot be run; kept for a person to check")
        if ir.class_ in JUDGED and not ir.note_question:
            flags.append("missing_note_question")
        if ir.class_ == "human" and not ir.human_question:
            flags.append("missing_human_question")
        if ir.class_ in JUDGED and ir.kind == "exclusion" and ir.note_question and is_negated(ir.note_question):
            fixed = positive(ir.note_question)
            if fixed is not None:
                ir = ir.model_copy(update={"note_question": fixed, "note_question_source": ir.note_question})
                flags.append("negated_question_rewritten")
                warnings.append(f"{cid}: exclusion question was negated; rewritten to {fixed!r} (check it)")
            else:
                flags.append("negated_question")
                warnings.append(f"{cid}: exclusion question is negated and could not be rewritten; edit it")
        if flags:
            ir = ir.model_copy(update={"flags": sorted(set(flags) | {"needs_review"})})
        criteria.append(ir)
    return PostResult(criteria, dict(sorted(valuesets.items())), mappings, warnings)
