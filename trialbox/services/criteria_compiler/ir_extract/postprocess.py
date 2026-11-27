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
from tb_contracts import Atom, BoolExpr, CriterionIR, CriterionReview, LlmExtractOutput, dump
from tb_contracts.criterion_ir import ACTIVE_STATUSES

from criteria_compiler import unit_check
from criteria_compiler.ir_extract.negation_scope import negated_presence
from criteria_compiler.ir_extract.polarity import is_negated, positive
from criteria_compiler.semantics import FILTERED, JUDGED, CompileError, atoms, check_bool, demographic_alone, kind
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


def _one_age(c: CriterionIR) -> tuple[float | None, float | None] | None:
    """The age bounds of a coded criterion whose whole logic is one age atom (no sex), else None."""
    a = c.logic
    if c.class_ not in FILTERED or not isinstance(a, Atom) or a.domain != "demographic" or a.age is None or a.sex:
        return None
    return a.age.min, a.age.max


def decided_once(criteria: list[CriterionIR], warnings: list[str]) -> list[CriterionIR]:
    """F5 of the P1b review (D-982): one age fact decided twice in 5 of sigir's rulesets (NCT01790477: INC age >= 18,
    EXC age <= 17), so a minor failed two criteria and the counts and the reasons said it twice. An exclusion whose
    age is the exact complement of an inclusion's (``max m-1`` against ``min m``; ``min M+1`` against ``max M``)
    decides nothing the inclusion does not: it is kept, marked rejected with a comment naming the inclusion
    (``restates_inclusion``), so the inclusion alone decides; the review sheet shows it as "reject", which the
    reviewer may change. No patient's answer changes."""
    bounds = {c.id: _one_age(c) for c in criteria if c.kind == "inclusion"}
    out: list[CriterionIR] = []
    for c in criteria:
        ages = _one_age(c) if c.kind == "exclusion" and not (c.review and c.review.status == "rejected") else None
        same = None
        if ages is not None:
            lo, hi = ages
            for iid, inc in bounds.items():
                if inc is None:
                    continue
                if (lo is None and hi is not None and inc == (hi + 1, None)) or (
                    hi is None and lo is not None and inc == (None, lo - 1)
                ):
                    same = iid
                    break
        if same is None:
            out.append(c)
            continue
        note = f"the complement of {same}: the inclusion decides it alone (approve this to keep both)"
        flags = sorted({*(c.flags or []), "restates_inclusion", "needs_review"})
        out.append(c.model_copy(update={"review": CriterionReview(status="rejected", comment=note), "flags": flags}))
        warnings.append(f"{c.id}: {note}")
    return out


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


# D-947 (F3 of the P1b review, NCT01260883): "2-18 months" came out as age 2 to 18 (years) and "<36 weeks gestation"
# as age.max 36. The age is complete years; an age the line writes in months, weeks or days is not one
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "eighteen": 18, "twenty-four": 24, "thirty-six": 36}  # fmt: skip
_N = r"(\d+(?:\.\d+)?|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_SHORT = (r"(?:months?\b|mos?\b|mths?\b|m\b|weeks?\b|wks?\b|days?\b|か月|ヵ月|ヶ月|カ月|ケ月|箇月|週|日齢|"
          r"(?<![月第年])日(?!本|以内|間|前|後|目)|個月|个月|天)")  # fmt: skip
_RANGE = r"(?:\s*(?:-|–|~|〜|to|and|から|至)\s*" + _N + r")?"
_SHORT_UNIT = re.compile(_N + _RANGE + r"[\s-]*" + _SHORT, re.IGNORECASE)
_YEARS_AGE = re.compile(
    r"(?:\bage[ds]?\b\s*(?:of\s*)?[:=≥≤<>]*\s*|年齢|年齡)" + _N + _RANGE + r"(?![\s-]*" + _SHORT + ")"
    r"|" + _N + r"(?:\s*(?:-|–|~|〜|to|から|至)\s*" + _N + r")?\s*(?:years?\b|yrs?\b|y/?o\b|歳|才|歲|岁)",
    re.IGNORECASE,
)
# a short-unit age said to be one: "6-month-old", "aged 6 months", "生後6か月", "月齢", "1 year 6 months"
_SHORT_AGE = re.compile(
    _N
    + r"[\s-]*(?:months?|weeks?|days?)[\s-]*(?:old|of\s+age)\b|\bage[ds]?\s*(?:of\s*)?"
    + _N
    + r"(?:\s*(?:-|–|~|〜|to)\s*"
    + _N
    + r")?[\s-]*"
    + _SHORT
    + r"|生後|月齢|週齢|日齢|出生後"
    + r"|\d+\s*(?:years?|y|歳|才|歲|岁)\s*\d+\s*(?:months?|か月|ヵ月|ヶ月|カ月|個月|个月)",
    re.IGNORECASE,
)  # fmt: skip


def _num(x: str | None) -> float | None:
    if x is None:
        return None
    return float(_WORDS[x.lower()]) if x.lower() in _WORDS else float(x)


def age_in_short_units(text: str, logic: Any) -> bool:
    """An age bound of the logic is an age the line writes in months, weeks or days (D-947): the line says so outright
    ("6-month-old", "aged 6 months", 生後, 月齢, "1 year 6 months"), or a bound is a number (or one past it, "<36
    weeks" as at most 35) the line writes in a short unit and never as an age in years ("Aged 18-75; 18 days washout"
    is not one)."""
    if logic is None:
        return False
    bounds = [float(b) for a in atoms(logic) if a.age is not None for b in (a.age.min, a.age.max) if b is not None]
    if not bounds:
        return False
    text = text or ""
    if _SHORT_AGE.search(text):
        return True
    short = {n for m in _SHORT_UNIT.finditer(text) for n in map(_num, m.groups()) if n is not None}
    years = {n for m in _YEARS_AGE.finditer(text) for n in map(_num, m.groups()) if n is not None}
    near = short - years
    return any(b in near or b + 1 in near or b - 1 in near for b in bounds)


def _convert_logic(
    node: dict[str, Any], concept_vs: dict[str, str], egfr: str = "egfr", refiled: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if "op" in node and "args" in node:
        return {"op": node["op"], "args": [_convert_logic(a, concept_vs, egfr, refiled) for a in node["args"]]}
    atom = {k: v for k, v in node.items() if k != "concept" and v is not None}
    refilable = atom.get("domain") in ("procedure", "encounter")  # G2 (D-957): a diagnosis filed as an encounter too
    if refilable and str(node.get("concept") or "").strip().lower() in refiled:
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


# D-954's review (the run's 173 moved criteria, judged by hand against the physicians' gold): 74 were risky to give
# the models. The rules below are its general ones (not the phrases particular to that run): a line or question the
# notes cannot settle, or that the models would answer wider than the line, stays with a person
_LACK = re.compile(r"\b(?:lack|lacks|lacking)\b", re.I)
_UNOBSERVABLE = re.compile(
    r"consent|willing|desire|plann?ed|plans?\b|likely|expected|agree|particip|investigator|physician|cardiologist|"
    r"contracept|birth\s+control|complian|refus|childbearing|pregnan\w*\s+(?:test|during)|study\s+(?:drug|period)|"
    r"judg(?:e?ment)|opinion|prognos|life\s+expectancy|passing\s+away|able\s+to|eligible|switch|"
    r"同意|意思|予定|治験|試験への参加|研究者",
    re.I,
)
_INFERRED = re.compile(
    r"\bscore\b|\bcriteria\b|\bone\s+or\s+more\b|\b\d+\s+(?:of|out\s+of)\s+\d+\b|\bINR\b|creatinine|"
    r"blood\s+tests?|drug\s+screen|immunocompromis|performance\s+status|\bASA\b|such\s+as|e\.g\.",
    re.I,
)
_FRAGMENT = re.compile(r"(?:,|;)?\s*\bor\s*[:.]?\s*$|^\s*(?:and/or|or)\b|will\s+be\s+(?:included|eligible)", re.I)
_PLAIN_HAVE = re.compile(r"^(?:does|did|has|is)\s+the\s+(?:patient|subject)\s+(?:have|had|has|been|a)\b", re.I)
# an exclusion's question with a severity or an organ-level word is wider than its line's qualifiers ("serious
# cardiac failure" for one that the line limits); a number is a threshold the models would read off the notes
_VAGUE = re.compile(
    r"\b(?:serious|severe|significant|uncontrolled|major|any|other|medical|problems?|impairment|insufficiency|"
    r"dysfunction|failure|illness(?:es)?|condition|disorder|abnormalit\w*)\b",
    re.I,
)
_NUMBER_ASKED = re.compile(r"\d|\b(?:less|more|greater|fewer)\s+than\b", re.I)


def notes_can_decide(kind_: str, text: str, question: str) -> str | None:
    """None when the notes may decide a mixed criterion whose coded part cannot run (D-954); else why a person keeps
    it: the question is negated (the polarity rewrite does not cover "lack"), an inclusion line is a negation ("No
    significant cardiopulmonary disease" asked as "Does the patient have…"), the subject is not in the notes (consent,
    plans, contraception, an investigator's judgement), the answer would be inferred (a score, a count of criteria,
    an INR, "such as metformin"), the line is a fragment of an "or", the question asks a number, or an exclusion is
    not a plain "Does the patient have …" of a named condition (a vague "any serious illness" excludes everyone)."""
    both = f"{text} {question}"
    if is_negated(question) or _LACK.search(question):
        return "negated_question"
    if kind_ == "inclusion" and is_negated(text):
        return "negated_line"
    if _UNOBSERVABLE.search(both):
        return "not_in_notes"
    if _INFERRED.search(both):
        return "inferred"
    if _FRAGMENT.search(text):
        return "fragment"
    if _NUMBER_ASKED.search(question):
        return "threshold"
    if kind_ == "exclusion" and (not _PLAIN_HAVE.search(question.strip()) or _VAGUE.search(question)):
        return "broad_exclusion"
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
    * Any other atom: an age whose numbers the line never writes (a placeholder, the prompt's 0-150) is dropped; one
      it writes (or one past: "before the age of 40" as at most 39) beside an age word, "before", "onset" or
      "diagnosed" is held for a person (``age_on_non_demographic``: an age at onset, which dropping would widen); one
      it writes otherwise ("<36 weeks gestation") is left as it was, for the rule of ages in short units (D-947).
      A ``derived`` name off an observation atom is left for ``kind`` to refuse: its review found that the prompt's
      placeholder names ride on atoms carrying other junk, which compiling would put in front of patients."""
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
            said = bool(nums) and all(b in written or b + 1 in written or b - 1 in written for b in nums)
            if said and _AGE_WORD.search(text):
                flags.append("age_on_non_demographic")
            elif not said:  # a placeholder (the prompt's 0-150): the line never writes it
                out.pop("age")
                flags.append("stray_field")
            # else the line writes it without an age word ("<36 weeks gestation"): left as it was, for D-947
        return out

    return walk(node), sorted(set(flags))


def approved_negated(c: CriterionIR, valuesets: dict[str, dict[str, Any]]) -> bool:
    """Card 10A-1 for a criterion already compiled (an approved ruleset): whether it is an inclusion whose line may
    negate what its coded logic asks the presence of. The concept's names are its ValueSet's title and its codes'
    displays (an approved ruleset keeps no concept candidates). The line's other concepts are the titles of the
    ruleset's ValueSets (each the name of a concept candidate the extractor emitted, card 10A-1b): a cue that governs
    one of them, not listed with this concept, is explained as it is at the first compile."""
    if c.kind != "inclusion" or c.class_ not in FILTERED:
        return False

    def terms_for(vs: str) -> list[str]:
        v = valuesets.get(vs) or {}
        shown = [str(x.get("display")) for inc in (v.get("compose") or {}).get("include") or []
                 for x in inc.get("concept") or [] if x.get("display")]  # fmt: skip
        return [str(v["title"])] * bool(v.get("title")) + shown

    titles = [str(v["title"]) for v in valuesets.values() if v.get("title")]
    return negated_presence(c.text, c.logic, terms_for, titles)


def hold_reused_negated(c: CriterionIR, valuesets: dict[str, dict[str, Any]]) -> tuple[CriterionIR, str | None]:
    """Card 10A-1 for a criterion reused from the approved version (an incremental compile skips ``postprocess``):
    an inclusion whose line may negate what its logic asks the presence of goes to a person, flagged, with a warning.
    The approved line is never changed silently: its reviewer sees why it came back. ``(criterion, warning)``."""
    if not approved_negated(c, valuesets):
        return c, None
    flags = sorted({*(c.flags or []), "negated_inclusion_presence", "needs_review"})
    held = c.model_copy(update={"class_": "human", "human_question": c.human_question or _question(c.text),
                                "logic": Atom(domain="demographic", valueset="NONE"), "flags": flags})  # fmt: skip
    return held, (f"{c.id}: approved before, but its line may negate what its logic asks the presence of; kept for "
                  "a person to check")  # fmt: skip


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
    vs_terms: dict[str, list[str]] = {}  # a ValueSet's concept names and synonyms (card 10A-1)
    valuesets: dict[str, dict[str, Any]] = {}
    mappings: dict[str, MappingResult] = {}
    warnings: list[str] = []
    criteria: list[CriterionIR] = []
    # 1. concepts -> ValueSets
    refiled: set[str] = set()
    for ec in extracted.criteria:
        for cand in ec.concept_candidates:
            key = cand.name.strip().lower()
            if cand.domain in ("procedure", "encounter") and is_diagnosis_name(cand.name):
                refiled.add(key)
                cand = cand.model_copy(update={"domain": "condition"})
            if key in concept_vs and cand.domain != "demographic":  # card 10A-1: every name and synonym of it
                vs_terms.setdefault(concept_vs[key], []).extend([cand.name, *(cand.synonyms or [])])
            if key in concept_vs or cand.domain == "demographic":
                continue
            vs_name = vs_name_for(cand.name)
            if vs_name in valuesets:  # another concept with the same slug: never overwrite its ValueSet
                vs_name = vs_name_for(cand.name, unique=True)
            res = term.map(cand.domain, cand.name, cand.synonyms or [], llm_map)
            mappings[vs_name] = res
            concept_vs[key] = vs_name
            vs_terms.setdefault(vs_name, []).extend([cand.name, *(cand.synonyms or [])])
            valuesets[vs_name] = valueset(
                ruleset,
                vs_name,
                cand.name,
                res.concepts,
                version,
                res.needs_review,
                families=res.families,
                ingredients=getattr(term, "ingredients", None) if cand.domain == "medication" else None,
                open_families=res.open_families,
            )
            if res.method == "none":
                warnings.append(f"concept '{cand.name}' ({cand.domain}) could not be mapped")

    def terms_for(vs: str) -> list[str]:
        return vs_terms.get(vs, [])

    # 2. criteria -> IR
    incl_ages = inclusion_ages([dump(ec).get("logic") for ec in extracted.criteria if ec.kind == "inclusion"])
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
        # card 10A-1 (review 15, P2b): "No prior chemotherapy" (inclusion) compiled to "any of chemotherapy", which
        # meets the line only for the patients it should exclude. An inclusion whose logic asks the presence of a
        # concept that a negation in its line governs (negation_scope) is never run: a person checks it (rewriting it
        # could be wrong as well). It comes first: a later rule that hands a mixed line to the notes would have a
        # model answer the presence
        named_terms = [x for cand in ec.concept_candidates if cand.domain != "demographic"
                       for x in (cand.name, *(cand.synonyms or []))]  # fmt: skip
        if ir.kind == "inclusion" and ir.class_ in FILTERED and negated_presence(ir.text, ir.logic, terms_for,
                                                                                  named_terms):  # fmt: skip
            flags.append("negated_inclusion_presence")
            why = notes_can_decide(ir.kind, ir.text, ir.note_question or "") if ir.class_ == "mixed" else None
            if ir.note_question and why is not None:  # the reviewer sees why the notes cannot decide it either
                flags.append(f"notes_cannot_decide_{why}")
            ir = ir.model_copy(update={"class_": "human", "human_question": ir.human_question or _question(ir.text),
                                       "logic": Atom(domain="demographic", valueset="NONE")})  # fmt: skip
            warnings.append(f"{cid}: its line negates what its logic asks the presence of; kept for a person to "
                            "check")  # fmt: skip
        if ir.class_ in FILTERED and set(stray) & set(HOLD):
            if ir.class_ == "mixed" and ir.note_question:  # as demote_uncompilable keeps it (D-98): the notes decide
                ir = ir.model_copy(update={"class_": "note", "logic": Atom(domain="demographic", valueset="NONE")})
                warnings.append(f"{cid}: its logic's meaning is unsure; the notes decide")
            else:
                ir = ir.model_copy(update={"class_": "human", "human_question": ir.human_question or _question(ir.text),
                                           "logic": Atom(domain="demographic", valueset="NONE")})  # fmt: skip
                warnings.append(f"{cid}: its logic's meaning is unsure; kept for a person to check")
        named = sorted({str(c.name) for c in ec.concept_candidates if c.domain != "demographic"})
        if ir.kind == "exclusion" and ir.class_ in FILTERED and named and demographic_alone(ir.logic):
            # P2b (lane H's trace, 2026-11-17): "women with pregnant or lactation" compiled to sex: female alone and
            # excluded every woman at S1, with no model asked. An exclusion whose coded part keeps only an age or a
            # sex while its line names more (here pregnancy, lactation) has lost its qualifier: the coded part never
            # excludes on its own. The notes decide (a mixed line with its question), else a person
            flags.append("qualifier_dropped")
            if ir.class_ == "mixed" and ir.note_question:
                ir = ir.model_copy(update={"class_": "note", "logic": Atom(domain="demographic", valueset="NONE")})
                warnings.append(f"{cid}: its coded part keeps only an age or sex of {', '.join(named)}; the notes "
                                "decide it (check it)")  # fmt: skip
            else:
                ir = ir.model_copy(update={"class_": "human", "human_question": ir.human_question or _question(ir.text),
                                           "logic": Atom(domain="demographic", valueset="NONE")})  # fmt: skip
                warnings.append(f"{cid}: its coded part keeps only an age or sex of {', '.join(named)}; kept for a "
                                "person to check")  # fmt: skip
        moved = sorted({str(c.name) for c in ec.concept_candidates if c.name.strip().lower() in refiled})
        if moved and ir.logic is not None and any(a.domain == "condition" for a in atoms(ir.logic)):
            flags.append("domain_refiled")
            warnings.append(f"{cid}: {', '.join(moved)} filed as a procedure; read as a condition (check it)")
        if ir.class_ in FILTERED and age_in_short_units(ir.text, ir.logic):
            flags.append("age_unit_not_years")
            if ir.class_ == "mixed" and ir.note_question:  # as demote_uncompilable keeps it (D-98): the notes decide
                ir = ir.model_copy(update={"class_": "note", "logic": Atom(domain="demographic", valueset="NONE")})
                warnings.append(f"{cid}: an age written in months, weeks or days was read as years; the notes decide")
            else:
                ir = ir.model_copy(update={"class_": "human", "human_question": ir.human_question or _question(ir.text),
                                           "logic": Atom(domain="demographic", valueset="NONE")})  # fmt: skip
                warnings.append(f"{cid}: an age written in months, weeks or days was read as years; kept for a person")
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
                    if a.derived and not derived_said(a.derived, ir.text):
                        raise CompileError(f"derived value {a.derived} is not what its line measures")
                    if a.derived and a.valueset not in valuesets:
                        valuesets[a.valueset] = derived_valueset(ruleset, a.derived, version, term)
                    if a.valueset not in ("NONE",) and a.valueset not in valuesets:
                        raise CompileError(f"ValueSet {a.valueset} has no concept candidate")
                    m = mappings.get(a.valueset)
                    if a.domain == "encounter" and (m is None or not m.concepts):
                        # G2 of the P1b review (D-957): an encounter type no code was found for compiled as
                        # ``X.serviceType in`` an empty ValueSet, which the FHIR server refused (four protocols)
                        raise CompileError(f"encounter type {a.valueset} has no code on this box")
                    if m is not None and (m.needs_review or not m.concepts):
                        flags.append("concept_unmapped" if not m.concepts else "concept_needs_review")
                    unit = unit_check.check(a, valuesets.get(a.valueset))
                    if unit is not None:  # D-418: a lab number that would read every result as unknown
                        flags.append(unit[0])
                        warnings.append(f"{cid}: {unit[1]}")
            except CompileError as exc:
                warnings.append(f"{cid}: {exc}")
                flags.append("logic_invalid")
        held = notes_can_decide(ir.kind, ir.text, ir.note_question or "") if ir.class_ == "mixed" else "no_question"
        if "logic_invalid" in flags and ir.class_ == "mixed" and ir.note_question and held is None:
            # G9 of the P1b review (D-954): 111 of sigir's mixed criteria had a note question and went to a person
            # only because their coded part could not run, while ``demote_uncompilable`` keeps such a criterion as
            # note (D-98); this is what made the all-human and notes-only rulesets. The notes decide it, as there
            flags.append("coded_part_dropped")
            ir = ir.model_copy(update={"class_": "note", "logic": Atom(domain="demographic", valueset="NONE")})
            warnings.append(f"{cid}: its coded part cannot be run; the notes decide it (check it)")
        elif "logic_invalid" in flags and ir.class_ in FILTERED:
            if ir.class_ == "mixed" and ir.note_question:
                flags.append(f"notes_cannot_decide_{held}")
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
    criteria = decided_once(criteria, warnings)
    return PostResult(criteria, dict(sorted(valuesets.items())), mappings, warnings)


# G5 of the P1b review (D-956): the model copies the prompt's example derived names onto atoms that are not those
# scores ("sdai" on a brain injury, "egfr" on an FEV1/FVC ratio, which would compile as eGFR < 0.7). A derived value
# runs only when its line names that score
_L, _R = r"(?<![A-Za-z])", r"(?![A-Za-z])"  # ASCII edges: "eGFRが" names eGFR (が is a word character to \b)
# D-986: capitals "EGFR" is the growth factor receptor ("EGFR mutation"); the kidney's only beside a kidney word or a
# comparison with a number, and never when an oncology word follows it
_EGFR_SAID = (
    _L
    + r"(?:(?-i:eGFR|egfr|e-GFR|Egfr)|gfr)"
    + _R
    + r"|glomerular\s+filtration|糸球体濾過|腎絲球過濾|肾小球滤过|"
    + _L
    + r"(?-i:EGFR)"
    + _R
    + r"(?!\W{0,3}(?:tki|mutat|exon|tyrosine|amplif|positive|negative|變異|変異|突變))"
    r"(?=.*(?:ml\s*/\s*min|creatinine|renal|kidney|ckd|腎))|"
    + _L
    + r"(?-i:EGFR)\s*(?:[<>≤≥≦≧=]|of|below|above|under|over)\s*\d"
)
_DERIVED_SAID = {
    "bmi": _L + r"bmi" + _R + r"|body\s*mass\s*index|身體質量指數|体格指数|ボディマス",
    "egfr": _EGFR_SAID,
    "das28": _L + r"das\s*-?\s*28",
    "basdai": _L + r"basdai" + _R,
    "asdas": _L + r"asdas" + _R,
    "cdai": _L + r"cdai" + _R,
    "sdai": _L + r"sdai" + _R,
}


def derived_said(derived: str, text: str) -> bool:
    """The line names the derived score its atom computes (``egfr_jsn`` and ``das28_crp`` by their family)."""
    family = next((f for f in _DERIVED_SAID if derived == f or derived.startswith(f + "_")), None)
    return family is not None and re.search(_DERIVED_SAID[family], text or "", re.IGNORECASE) is not None
