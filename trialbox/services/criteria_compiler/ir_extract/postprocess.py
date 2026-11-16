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


# D-948 (F4 and G10 of the P1b reviews, #639): sigir's 1,032 extracted criteria carried fields their atoms cannot use,
# which the compile ignored or refused: on demographic atoms 111 quantifiers (every "none" an age or sex line such as
# "Aged 40 years or older"), 134 values (64 "Aged N years or older" with the number in ``value``, not ``age``),
# 8 derived (NCT00606840 EXC-02: quantifier all, derived egfr); on other atoms 35 ages (28 of them numbers not in the
# line, such as the prompt's 0-150) and 29 derived names (the prompt's "asdas"). Holding them all for a person would
# demote more lines (G9); a field is dropped, flagged, and only a line whose words may give it meaning goes to a person
_NOT_DEMOGRAPHIC = ("derived", "quantifier", "value", "count", "window", "duration")
HOLD = ("demographic_negated", "age_on_non_demographic")  # these go to a person: their meaning is unsure
_NEGATION = re.compile(r"\b(?:not|no|non|never|without|except|other\s+than)\b|以外|除く|ではない|でない|不是|非", re.I)
_AGE_WORD = re.compile(r"\bage[ds]?\b|\byears?\s+old\b|\bbefore\b|\bonset\b|diagnos|歳|才|歲|発症|發病|发病", re.I)
_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])")
_AGE_CONCEPTS = (None, "", "age")
_YEARS = (None, "", "y", "yr", "yrs", "year", "years", "歳", "才", "歲")


_YEARS_SAID = re.compile(r"\b(?:years?|yrs?|y/?o|aged?)\b|歳|才|歲|岁|年齢|年齡", re.I)
_SHORT_SAID = re.compile(
    r"\b(?:months?|mos?|weeks?|wks?|days?|gestation\w*)\b|か月|ヵ月|ヶ月|カ月|週|日齢|個月|个月|天", re.I
)


def _value_as_age(n: dict[str, Any], text: str) -> dict[str, Any] | None:
    """G10: an age written in ``value`` ("18 and over" as ``value >= 18``) as ``age``, only when unambiguous: an age
    concept, years, ``>=`` / ``<=`` / ``between``, and the line's numbers are exactly the value's ("Age 50 to 89
    years" as ``value >= 50`` is not repaired: its 89 would be lost)."""
    v = n.get("value")
    if not isinstance(v, dict) or n.get("age") is not None or n.get("concept") not in _AGE_CONCEPTS:
        return None
    if str(v.get("unit") or "").strip().lower() not in _YEARS or v.get("codes"):
        return None
    if not _YEARS_SAID.search(text) or _SHORT_SAID.search(text):  # review: "Body weight >= 40", "6 months", "32 weeks"
        return None
    op, x, y = v.get("op"), v.get("num"), v.get("num2")
    age = {">=": {"min": x}, "<=": {"max": x}, "between": {"min": x, "max": y}}.get(str(op))
    if age is None or any(b is None for b in age.values()):
        return None
    if {float(m) for m in _NUMBER.findall(text)} != {float(b) for b in age.values() if b is not None}:
        return None
    return age


def strip_stray(node: Any, text: str = "", kind_: str = "inclusion") -> tuple[Any, list[str]]:
    """The raw logic without the fields its atom's domain cannot use, and a flag for each kind repaired, dropped or
    held (D-948). The compile ignored every field dropped here: dropping one changes no answer.

    * A demographic atom of an inclusion: an unambiguous age in ``value`` becomes ``age`` (``value_read_as_age``,
      only when the line says years or age and no shorter unit). Any demographic atom: derived /
      quantifier / value / count / window / duration are dropped (``stray_field``). A ``quantifier: none`` on a line
      with a negation word is held for a person (``demographic_negated``): the age compare never read the "not".
    * Any other atom: an age is dropped when the line does not write its numbers (or one past them: "before the
      age of 40" as at most 39) beside an age word, "before", "onset" or "diagnosed", else held for a person
      (``age_on_non_demographic``: an age at onset, which dropping would widen). A ``derived`` name off an
      observation atom is left for ``kind`` to refuse: its review found that the prompt's placeholder names ride on
      atoms carrying other junk, which compiling would put in front of patients."""
    flags: list[str] = []

    def walk(n: Any) -> Any:
        if not isinstance(n, dict):
            return n
        if "op" in n and "args" in n:
            return {**n, "args": [walk(a) for a in n["args"] or []]}
        if n.get("domain") == "demographic":
            n = dict(n)
            age = _value_as_age(n, text) if kind_ == "inclusion" else None  # review: never widen an exclusion
            if age is not None:
                n["age"] = age
                flags.append("value_read_as_age")
            if n.get("quantifier") == "none" and _NEGATION.search(text):
                flags.append("demographic_negated")
            if any(n.get(k) is not None and not (k == "quantifier" and n[k] == "any") for k in _NOT_DEMOGRAPHIC):
                flags.append("stray_field")
            return {k: v for k, v in n.items() if k not in _NOT_DEMOGRAPHIC}
        out = dict(n)
        if out.get("age") is not None:
            nums = [float(b) for b in (out["age"].get("min"), out["age"].get("max")) if b is not None]
            written = {float(m) for m in _NUMBER.findall(text)}
            if (
                nums
                and _AGE_WORD.search(text)
                and all(b in written or b + 1 in written or b - 1 in written for b in nums)
            ):
                flags.append("age_on_non_demographic")
            else:
                out.pop("age")
                flags.append("stray_field")
        return out

    return walk(node), sorted(set(flags))


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
    for ec in extracted.criteria:
        code = KIND_CODE[ec.kind]
        counters[code] = counters.get(code, 0) + 1
        cid = f"{ruleset}-{code}-{counters[code]:02d}"
        flags: list[str] = []
        raw = dump(ec)
        logic_raw, stray = strip_stray(
            raw.get("logic") or {"domain": "demographic"}, str(raw.get("text") or ""), str(ec.kind)
        )
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
        if stray:
            flags.extend(stray)
            warnings.append(f"{cid}: fields its atoms cannot use ({', '.join(stray)})")
        if ir.class_ in FILTERED and set(stray) & set(HOLD):
            if ir.class_ == "mixed" and ir.note_question:  # as demote_uncompilable keeps it (D-98): the notes decide
                ir = ir.model_copy(update={"class_": "note", "logic": Atom(domain="demographic", valueset="NONE")})
                warnings.append(f"{cid}: its logic's meaning is unsure; the notes decide")
            else:
                ir = ir.model_copy(update={"class_": "human", "human_question": ir.human_question or _question(ir.text),
                                           "logic": Atom(domain="demographic", valueset="NONE")})  # fmt: skip
                warnings.append(f"{cid}: its logic's meaning is unsure; kept for a person to check")
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
