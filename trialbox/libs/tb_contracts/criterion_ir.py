"""Criterion IR v3 (spec v4 §6.2) and the criterion-library record (§6.3) as pydantic v2 models.

IR 3.0.0 is a strict superset of the v1 IR (``schemas/criterion_ir.schema.json``): every v1 field keeps its meaning,
and :func:`upgrade_v1` / :func:`downgrade_to_v1` convert losslessly for everything v1 can express (DM-02). The v3
additions are:

* atoms as a flat, id-addressed list with ``logic`` referencing them (``{"op": "and", "args": ["a1", "m1"]}``);
* ``line_of_therapy`` atoms (§6.2.2), ``attribute`` with ``source_priority`` (§6.2.1), ``value.ref`` (ULN/LLN
  multiples), pinned ``derived`` calculators (§6.2.3), ``screening`` / ``randomization`` anchors (§6.2.4), the
  organ-function macro (§6.2.5) and human checklists (§6.2.6);
* the atoms the v1 format could not express (HANDOFF trap 5): a relative or absolute change from a baseline
  (creatinine rise), a windowed aggregate normalised by weight (urine output in mL/kg over 12 h), medication dose
  and route with per-ingredient equivalents, the diagnosis role (primary diagnosis), and thresholds that depend on
  another atom (NT-proBNP / BNP cut-offs that differ with atrial fibrillation).

The JSON Schema in ``schemas/v4/criterion_ir.schema.json`` is generated from these models::

    python -m tb_contracts.criterion_ir            # rewrite the committed schemas
    python -m tb_contracts.criterion_ir --check    # exit 1 when they are stale

``canonical_hash`` follows §6.2.7: sha256 over the RFC 8785 canonical JSON of the normalised criterion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

IR_VERSION: Literal["3.0.0"] = "3.0.0"
LIBRARY_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "v4"
SCHEMA_BASE = "https://trialbox.local/schemas/v4/"

_SEMVER = r"\d+\.\d+\.\d+"
CALC_ID = rf"^[a-z][a-z0-9_]*@{_SEMVER}$"
MACRO_ID = rf"^[a-z][a-z0-9_]*@[a-z0-9-]+-{_SEMVER}$"
LOT_RULES_ID = rf"^lot_rules@[a-z0-9-]+-{_SEMVER}$"
CRITERION_ID = r"^[A-Z0-9]+(-[A-Z0-9]+)*-(INC|EXC|REN|DOC)-[0-9]{2,3}$"
ATOM_ID = r"^[a-z][a-z0-9_]*$"

Op = Literal[">", ">=", "<", "<=", "=", "between", "in"]
CmpOp = Literal[">", ">=", "<", "<=", "="]
V1Domain = Literal["condition", "observation", "medication", "procedure", "encounter", "demographic", "claim", "report"]
Domain = Literal[
    "condition",
    "observation",
    "medication",
    "procedure",
    "encounter",
    "demographic",
    "claim",
    "report",
    "line_of_therapy",
    "registry",
    "specimen",
    "genomic",
]
Num = int | float  # ints stay ints so that v1 -> v3 -> v1 is byte-identical JSON
SourceKind = Literal["registry", "structured_pathology", "structured_form", "report_span", "note"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ------------------------------------------------------------------------------------------------- shared parts
class LangText(_Model):
    """Text in several languages. ``und`` (BCP 47 "undetermined") holds v1 strings whose language was not recorded."""

    en: str | None = None
    zh_TW: str | None = Field(default=None, alias="zh-TW")
    ja: str | None = None
    und: str | None = None

    def first(self) -> str | None:
        return self.und or self.en or self.zh_TW or self.ja


class CriterionText(_Model):
    source: str = Field(description="the criterion text as written in the source document")
    lang: str | None = Field(default=None, description="BCP 47 tag of `source`; absent when not recorded (v1)")
    source_ref: str | None = Field(default=None, description="section/page in the source document")


class Review(_Model):
    """v1 ``CriterionReview``, unchanged."""

    status: Literal["draft", "approved", "rejected"] | None = None
    by: str | None = None
    at: str | None = Field(default=None, json_schema_extra={"format": "date-time"})
    comment: str | None = None


class RefRange(_Model):
    """Compare against a multiple of the observation's own reference range (OBX-7), else the site default table."""

    kind: Literal["uln", "lln"]
    multiple: Num


class Value(_Model):
    """v1 ``AtomValue`` plus ``ref`` (§6.2.1)."""

    op: Op | None = None
    num: Num | None = None
    num2: Num | None = None
    unit: str | None = None
    codes: list[str] | None = None
    ref: RefRange | None = None


class ConditionalValue(_Model):
    """A threshold that replaces ``value`` when atom ``if_atom`` holds (first match wins), e.g. NT-proBNP >= 2400
    pg/mL instead of >= 1600 pg/mL in atrial fibrillation."""

    if_atom: str = Field(pattern=ATOM_ID)
    value: Value


Anchor = Literal["index", "event", "screening", "randomization"]


class Window(_Model):
    """Days relative to ``anchor``; v1 windows are the ``index`` / ``event`` subset (§6.2.4)."""

    from_days: int | None = None
    to_days: int | None = None
    anchor: Anchor | None = None
    event_atom: str | None = Field(default=None, pattern=ATOM_ID, description="anchor=event: the atom giving events")
    event_pick: Literal["first", "last", "each"] | None = None


class Duration(_Model):
    min_days: int | None = None
    gap_days: int | None = None


class AgeRange(_Model):
    min: Num | None = None
    max: Num | None = None


class Attribute(_Model):
    """A value resolved from several sources in priority order (§6.2.1, DM-04)."""

    path: str = Field(description="e.g. ecog, nyha, biomarker:EGFR, stage")
    op: Op
    codes: list[str] | None = None
    num: Num | None = None
    source_priority: list[SourceKind] = Field(min_length=1)
    conflict: Literal["highest_priority", "most_recent", "any_pass", "all_pass"] = "highest_priority"
    max_age_days: int | None = None


class Derived(_Model):
    """A pinned calculator version (§6.2.3). Without ``op`` the atom's ``value`` holds the comparison (v1 form)."""

    calc: str = Field(pattern=CALC_ID)
    op: CmpOp | Literal["between"] | None = None
    num: Num | None = None
    num2: Num | None = None
    inputs_window_days: int | None = None


class RegimenClass(_Model):
    label: str
    atc: list[str] = Field(default_factory=list)


class LineNumber(_Model):
    op: CmpOp
    num: int


class LineOfTherapy(_Model):
    """Evaluated against the SI table ``episode_lot`` derived by a versioned ``lot_rules`` artefact (§6.2.2)."""

    regimen_classes: list[RegimenClass] = Field(min_length=1)
    match: Literal["any", "all"] = "any"
    line_number: LineNumber | None = None
    setting: Literal["metastatic", "adjuvant", "neoadjuvant", "maintenance", "unknown", "any"] | None = None
    ended_by: list[Literal["progression", "toxicity", "completion", "death", "unknown"]] | None = None
    progression_sources: list[Literal["registry", "report_span", "note"]] | None = None
    rules: str = Field(pattern=LOT_RULES_ID)


class Baseline(_Model):
    pick: Literal["min", "max", "first", "last", "median"]
    window: Window


class Change(_Model):
    """Change of the atom's observation against a baseline value (trap 5: "≥ 2-fold rise in creatinine from
    baseline", "+27 µmol/L from the pre-morbid value"). ``ratio`` = current / baseline, ``absolute`` = current −
    baseline (in ``unit``), ``percent`` = 100 · (current − baseline) / baseline."""

    kind: Literal["ratio", "absolute", "percent"]
    op: CmpOp
    num: Num
    unit: str | None = None
    baseline: Baseline


class Aggregate(_Model):
    """A windowed aggregate of the atom's observations before the comparison (trap 5: "urine output < 6.0 mL/kg
    over the preceding 12 hours" = sum over 12 h divided by body weight in kg)."""

    fn: Literal["sum", "mean", "min", "max", "count"]
    over_hours: int = Field(gt=0)
    per_weight_kg: bool = False
    per_hour: bool = False
    weight_valueset: str | None = Field(default=None, description="body-weight codes when per_weight_kg")


class IngredientDose(_Model):
    code: str = Field(description="ingredient code (RxNorm, ATC or local)")
    system: str | None = None
    num: Num = Field(description="threshold dose of this ingredient, in the parent dose's unit")


class Dose(_Model):
    op: Op
    num: Num | None = None
    num2: Num | None = None
    unit: str
    basis: Literal["single", "daily", "cumulative"] = "single"
    per_ingredient: list[IngredientDose] | None = Field(
        default=None, description="equivalent thresholds, e.g. 40 mg furosemide = 20 mg torasemide = 1 mg bumetanide"
    )


class MedicationDetail(_Model):
    """Dose and route of a medication atom (trap 5: "a single dose of ≥ 40 mg i.v. furosemide or equivalent")."""

    route: list[str] | None = Field(default=None, description="route codes (e.g. SNOMED 47625008 intravenous)")
    dose: Dose | None = None
    status: list[Literal["ordered", "administered", "dispensed"]] | None = None


DiagnosisRole = Literal["primary", "principal", "admitting", "discharge", "secondary", "any"]


class Atom(_Model):
    """One machine-evaluable fact. The v1 atom fields keep their v1 meaning."""

    id: str = Field(pattern=ATOM_ID)
    domain: Domain
    valueset: str | None = Field(default=None, description="ValueSet id; reserved 'NONE' for demographic atoms")
    quantifier: Literal["any", "none", "count>=", "latest", "all"] | None = None
    count: int | None = None
    value: Value | None = None
    value_if: list[ConditionalValue] | None = None
    window: Window | None = None
    duration: Duration | None = None
    age: AgeRange | None = None
    sex: Literal["male", "female"] | None = None
    derived: Derived | None = None
    attribute: Attribute | None = None
    lot: LineOfTherapy | None = None
    change: Change | None = None
    aggregate: Aggregate | None = None
    medication: MedicationDetail | None = None
    diagnosis_role: DiagnosisRole | None = None

    @model_validator(mode="after")
    def _shape(self) -> Atom:
        if self.domain == "line_of_therapy" and self.lot is None:
            raise ValueError("a line_of_therapy atom needs `lot`")
        if self.lot is not None and self.domain != "line_of_therapy":
            raise ValueError("`lot` is only allowed on line_of_therapy atoms")
        if self.medication is not None and self.domain != "medication":
            raise ValueError("`medication` is only allowed on medication atoms")
        if (self.change is not None or self.aggregate is not None) and self.domain not in ("observation", "specimen"):
            raise ValueError("`change` and `aggregate` apply to observation atoms")
        if self.change is not None and self.aggregate is not None:
            raise ValueError("an atom has either `change` or `aggregate`, not both")
        if self.diagnosis_role is not None and self.domain not in ("condition", "encounter", "claim"):
            raise ValueError("`diagnosis_role` applies to condition, encounter and claim atoms")
        return self


class RenalParam(_Model):
    calc: str = Field(pattern=CALC_ID)
    op: CmpOp
    num: Num


class OrganFunctionParams(_Model):
    """Parameters of ``organ_function@<panel>-<semver>``; unset ones take the panel defaults (§6.2.5)."""

    anc_min: float | None = None
    plt_min: float | None = None
    hgb_min: float | None = None
    alt_ast_max_uln: float | None = None
    alt_ast_max_uln_if: dict[str, float] | None = None
    tbil_max_uln: float | None = None
    tbil_max_uln_if: dict[str, float] | None = None
    inr_max: float | None = None
    renal: RenalParam | None = None


class MacroUse(_Model):
    id: str = Field(pattern=ATOM_ID)
    macro: str = Field(pattern=MACRO_ID)
    params: OrganFunctionParams = Field(default_factory=OrganFunctionParams)
    window: Window | None = None
    expanded: list[str] | None = Field(default=None, description="ids of the atoms the compiler expanded into")


class ChecklistItem(_Model):
    key: str | None = Field(default=None, pattern=r"^hq_[a-z0-9_]+$", description="language-independent item id")
    item: LangText
    who: Literal["investigator", "crc"] | None = None
    when: Literal["prescreen_call", "screening_visit"] | None = None
    evidence_hint: str | None = None
    blocks_enrollment: bool | None = None


class HumanSpec(_Model):
    checklist: list[ChecklistItem] = Field(min_length=1)


class NoteQuestion(LangText):
    key: str = Field(pattern=r"^nq_[a-z0-9_]+$")


class LibraryRef(_Model):
    lib_id: str | None = Field(default=None, description="absent when match is new")
    match: Literal["exact", "variant", "new"]
    diff: list[str] | None = None


class LexiconKey(_Model):
    entry_id: str
    surface: str | None = None


class Computability(_Model):
    score: float = Field(ge=0, le=1)
    basis: str | None = None
    inexact_map_share: float | None = Field(default=None, ge=0, le=1)


class Provenance(_Model):
    drafted_by: str | None = None
    model_route: str | None = None
    agreement: str | None = None


class FlipRule(_Model):
    kind: Literal["window_slide", "value_change"]
    flip_date: str | None = Field(default=None, json_schema_extra={"format": "date"})
    detail: str | None = None


class BoolNode(_Model):
    op: Literal["and", "or", "not"]
    args: list[Logic] = Field(min_length=1)


Logic = Annotated[str | BoolNode, Field(description="an atom/macro id, or a boolean node over them")]
BoolNode.model_rebuild()


class CriterionIRv3(_Model):
    """One eligibility criterion, IR 3.0.0 (spec v4 §6.2)."""

    ir_version: Literal["3.0.0"] = IR_VERSION
    id: str = Field(pattern=CRITERION_ID)
    ruleset: str
    kind: Literal["inclusion", "exclusion", "renewal", "documentation"]
    class_: Literal["structured", "note", "human", "mixed"] = Field(alias="class")
    text: CriterionText
    label: str | None = Field(default=None, description="short display label for funnels and spreadsheets")
    time_sensitive: bool | None = None
    library_ref: LibraryRef | None = None
    logic: Logic
    atoms: list[Atom] = Field(default_factory=list)
    macros: list[MacroUse] | None = None
    canonical_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    filter_class: Literal["hard", "soft"] | None = None
    depends_on: list[str] | None = None
    flip_rule: FlipRule | None = None
    fallback: str | None = None
    note_question: NoteQuestion | None = None
    lexicon_keys: list[LexiconKey] | None = None
    computability: Computability | None = None
    human: HumanSpec | None = None
    action: str | None = Field(default=None, description="suggested action when unknown/pending")
    suggested_order: str | None = None
    flags: list[str] | None = None
    review: Review | None = None
    safety_critical: bool | None = None
    index: bool | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _refs(self) -> CriterionIRv3:
        ids = [a.id for a in self.atoms] + [m.id for m in self.macros or []]
        if len(ids) != len(set(ids)):
            raise ValueError("atom and macro ids must be unique")
        known = set(ids)
        missing = sorted(set(_logic_refs(self.logic)) - known)
        if missing:
            raise ValueError(f"logic references unknown atoms: {', '.join(missing)}")
        for a in self.atoms:
            refs = [c.if_atom for c in a.value_if or []]
            if a.window and a.window.event_atom:
                refs.append(a.window.event_atom)
            bad = sorted(r for r in refs if r not in known or r == a.id)
            if bad:
                raise ValueError(f"atom {a.id} references unknown atoms: {', '.join(bad)}")
        return self


def _logic_refs(node: str | BoolNode) -> list[str]:
    if isinstance(node, str):
        return [node]
    return [r for arg in node.args for r in _logic_refs(arg)]


# ------------------------------------------------------------------------------------------------- v1 <-> v3
class NotV1Expressible(ValueError):
    """The v3 criterion uses a construct the v1 IR cannot express."""


# v1 ``derived`` names -> pinned calculators of §6.2.3 (the v1 constants are re-exported unchanged).
V1_DERIVED_CALC: dict[str, str] = {
    "bmi": "bmi@1.0.0",
    "egfr": "egfr_ckd_epi_2021@1.0.0",
    "das28": "das28@1.0.0",  # v1: DAS28-ESR when an ESR exists in the window, else DAS28-CRP
    "basdai": "basdai@1.0.0",
    "asdas": "asdas_crp@1.0.0",
}
_CALC_V1 = {v: k for k, v in V1_DERIVED_CALC.items()}
_V1_ATOM_KEYS = ("domain", "valueset", "quantifier", "count", "value", "window", "duration", "age", "sex")
_V1_VALUE_KEYS = ("op", "num", "num2", "unit", "codes")
_V1_WINDOW_KEYS = ("from_days", "to_days", "anchor")
_V1_TOP_PASSTHROUGH = (
    "id",
    "ruleset",
    "kind",
    "class",
    "label",
    "time_sensitive",
    "fallback",
    "action",
    "suggested_order",
    "flags",
    "review",
)


def note_question_key(text: str, prefix: str = "nq_") -> str:
    """Key of a question upgraded from v1 (which has no keys): a hash of its text."""
    return prefix + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _as_dict(ir: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(ir, BaseModel):
        return ir.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return json.loads(json.dumps(dict(ir)))  # type: ignore[no-any-return]


def upgrade_v1(ir: BaseModel | Mapping[str, Any]) -> CriterionIRv3:
    """v1 criterion (dict or generated ``CriterionIR``) -> IR 3.0.0. Lossless: ``downgrade_to_v1`` restores it."""
    src = _as_dict(ir)
    out: dict[str, Any] = {k: src[k] for k in _V1_TOP_PASSTHROUGH if k in src}
    out["ir_version"] = IR_VERSION
    text: dict[str, Any] = {"source": src["text"]}
    if "source_ref" in src:
        text["source_ref"] = src["source_ref"]
    out["text"] = text
    if "note_question" in src:
        q = str(src["note_question"])
        out["note_question"] = {"key": note_question_key(q), "und": q}
    if "human_question" in src:
        q = str(src["human_question"])
        out["human"] = {"checklist": [{"key": note_question_key(q, "hq_"), "item": {"und": q}}]}
    atoms: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> str | dict[str, Any]:
        if "domain" in node:
            atom: dict[str, Any] = {"id": f"a{len(atoms) + 1}", **{k: v for k, v in node.items() if k != "derived"}}
            if "derived" in node:
                atom["derived"] = {"calc": V1_DERIVED_CALC[node["derived"]]}
            atoms.append(atom)
            return str(atom["id"])
        return {"op": node["op"], "args": [walk(a) for a in node["args"]]}

    out["logic"] = walk(src["logic"])
    out["atoms"] = atoms
    return CriterionIRv3.model_validate(out)


def _v1_atom(a: Atom) -> dict[str, Any]:
    d = a.model_dump(mode="json", by_alias=True, exclude_unset=True)
    extra = sorted(set(d) - {"id", "derived", *_V1_ATOM_KEYS})
    if extra:
        raise NotV1Expressible(f"atom {a.id}: {', '.join(extra)} have no v1 form")
    if a.domain not in get_args(V1Domain):
        raise NotV1Expressible(f"atom {a.id}: domain {a.domain} has no v1 form")
    if a.valueset is None:
        raise NotV1Expressible(f"atom {a.id}: v1 atoms need a valueset")
    if a.value is not None and a.value.ref is not None:
        raise NotV1Expressible(f"atom {a.id}: value.ref has no v1 form")
    if a.window is not None:
        w = a.window.model_dump(exclude_unset=True)
        if set(w) - set(_V1_WINDOW_KEYS) or w.get("anchor") not in (None, "index", "event"):
            raise NotV1Expressible(f"atom {a.id}: window {w} has no v1 form")
    out = {k: v for k, v in d.items() if k in _V1_ATOM_KEYS}
    if a.derived is not None:
        dd = a.derived.model_dump(exclude_unset=True)
        if set(dd) != {"calc"} or a.derived.calc not in _CALC_V1:
            raise NotV1Expressible(f"atom {a.id}: derived {dd} has no v1 form")
        out["derived"] = _CALC_V1[a.derived.calc]
    return out


def downgrade_to_v1(ir: CriterionIRv3) -> dict[str, Any]:
    """IR 3.0.0 -> v1 criterion dict (valid against ``schemas/criterion_ir.schema.json``).

    Raises :class:`NotV1Expressible` when the criterion uses a v3-only construct; v3 annotations with no v1 meaning
    (library_ref, canonical_hash, computability, provenance, ...) are reported the same way, so nothing is dropped
    silently."""
    d = ir.model_dump(mode="json", by_alias=True, exclude_unset=True)
    handled = {"ir_version", "text", "logic", "atoms", "note_question", "human", *_V1_TOP_PASSTHROUGH}
    extra = sorted(set(d) - handled)
    if extra:
        raise NotV1Expressible(f"{ir.id}: {', '.join(extra)} have no v1 form")
    out: dict[str, Any] = {k: d[k] for k in _V1_TOP_PASSTHROUGH if k in d}
    if ir.text.lang is not None:
        raise NotV1Expressible(f"{ir.id}: text.lang has no v1 form")
    out["text"] = ir.text.source
    if ir.text.source_ref is not None:
        out["source_ref"] = ir.text.source_ref
    if ir.note_question is not None:
        q = ir.note_question.first()
        if q is None:
            raise NotV1Expressible(f"{ir.id}: note_question has no text")
        out["note_question"] = q
    if ir.human is not None:
        items = ir.human.checklist
        only = items[0].model_dump(exclude_unset=True) if len(items) == 1 else {}
        if not {"item"} <= set(only) <= {"item", "key"} or items[0].item.first() is None:
            raise NotV1Expressible(f"{ir.id}: a structured human checklist has no v1 form")
        out["human_question"] = items[0].item.first()
    by_id = {a.id: a for a in ir.atoms}
    used: list[str] = []

    def walk(node: str | BoolNode) -> dict[str, Any]:
        if isinstance(node, str):
            if node not in by_id:
                raise NotV1Expressible(f"{ir.id}: {node} is a macro; expand it first")
            used.append(node)
            return _v1_atom(by_id[node])
        return {"op": node.op, "args": [walk(a) for a in node.args]}

    out["logic"] = walk(ir.logic)
    if sorted(used) != sorted(by_id) or len(used) != len(set(used)):
        raise NotV1Expressible(f"{ir.id}: v1 logic inlines each atom exactly once")
    return out


# ------------------------------------------------------------------------------------------------- canonical hash
def _jcs_number(x: float | int) -> str:
    if isinstance(x, bool):
        raise TypeError("bool is not a number")
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        raise ValueError("JCS forbids NaN and infinities")
    if x == 0:
        return "0"
    if x.is_integer() and abs(x) < 1e21:
        return str(int(x))
    r = repr(x)  # shortest round-trip digits, as ECMAScript Number::toString
    if "e" not in r:
        return r
    mant, exp = r.split("e")
    e = int(exp)
    if -7 < e < 21:
        s = format(Decimal(r), "f")
        return s.rstrip("0").rstrip(".") if "." in s else s
    return f"{mant}e{'+' if e > 0 else '-'}{abs(e)}"


def jcs(obj: Any) -> str:
    """RFC 8785 JSON Canonicalization Scheme (keys sorted by UTF-16 code units, ECMAScript number form)."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, int | float):
        return _jcs_number(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list | tuple):
        return "[" + ",".join(jcs(x) for x in obj) + "]"
    if isinstance(obj, dict):
        keys = sorted(obj, key=lambda k: str(k).encode("utf-16-be"))
        return "{" + ",".join(json.dumps(str(k), ensure_ascii=False) + ":" + jcs(obj[k]) for k in keys) + "}"
    raise TypeError(f"not JSON: {type(obj).__name__}")


_DROP_TOP = (
    "id",
    "ruleset",
    "text",
    "label",
    "library_ref",
    "canonical_hash",
    "fallback",
    "lexicon_keys",
    "computability",
    "action",
    "suggested_order",
    "flags",
    "review",
    "provenance",
    "filter_class",
    "depends_on",
    "flip_rule",
)


def normalise(ir: CriterionIRv3, valueset_hashes: Mapping[str, str] | None = None) -> dict[str, Any]:
    """§6.2.7: positional atom ids, ValueSet names -> content hashes, calculators/macros/LoT rules kept as
    ``id@version``, the note question and keyed checklist items -> their keys, and no free text, language variants,
    provenance or computability.

    ``valueset_hashes`` maps ValueSet names to content hashes (``sha256:…``); names without a hash are kept as
    ``name:<id>`` so two criteria only share a hash when they use the same ValueSet ids."""
    d = ir.model_dump(mode="json", by_alias=True, exclude_none=True)
    for k in _DROP_TOP:
        d.pop(k, None)
    vsh = dict(valueset_hashes or {})
    order = [a["id"] for a in d.get("atoms", [])] + [m["id"] for m in d.get("macros", [])]
    rename = {
        old: (f"a{i + 1}" if i < len(d.get("atoms", [])) else f"m{i + 1 - len(d['atoms'])}")
        for i, old in enumerate(order)
    }

    def vs(name: str) -> str:
        return name if name == "NONE" else vsh.get(name, f"name:{name}")

    def ren(node: Any) -> Any:
        if isinstance(node, str):
            return rename.get(node, node)
        return {"op": node["op"], "args": [ren(a) for a in node["args"]]}

    d["logic"] = ren(d["logic"])
    for a in d.get("atoms", []):
        a["id"] = rename[a["id"]]
        if "valueset" in a:
            a["valueset"] = vs(a["valueset"])
        for c in a.get("value_if", []):
            c["if_atom"] = rename[c["if_atom"]]
        if "window" in a and "event_atom" in a["window"]:
            a["window"]["event_atom"] = rename[a["window"]["event_atom"]]
        if "aggregate" in a and "weight_valueset" in a["aggregate"]:
            a["aggregate"]["weight_valueset"] = vs(a["aggregate"]["weight_valueset"])
        if "lot" in a:
            for rc in a["lot"]["regimen_classes"]:
                rc.pop("label", None)
    for m in d.get("macros", []):
        m["id"] = rename[m["id"]]
        m.pop("expanded", None)
    if "note_question" in d:
        d["note_question"] = d["note_question"]["key"]
    if "human" in d:
        # an item with a key is identified by it; an item without one only by its text
        drop = ("item", "evidence_hint")
        d["human"] = {
            "checklist": [
                {k: v for k, v in i.items() if "key" not in i or k not in drop} for i in d["human"]["checklist"]
            ]
        }
    return d


def canonical_hash(ir: CriterionIRv3, valueset_hashes: Mapping[str, str] | None = None) -> str:
    """``sha256:`` + hex sha256 of the JCS form of :func:`normalise` (DM-10)."""
    return "sha256:" + hashlib.sha256(jcs(normalise(ir, valueset_hashes)).encode("utf-8")).hexdigest()


def valueset_content_hash(valueset: Mapping[str, Any]) -> str:
    """Content hash of a FHIR ValueSet: the sorted (system, code) pairs of its compose, independent of name/url."""
    pairs = sorted(
        (str(inc.get("system", "")), str(c["code"]))
        for inc in (valueset.get("compose") or {}).get("include", [])
        for c in inc.get("concept", [])
    )
    return "sha256:" + hashlib.sha256(jcs([list(p) for p in pairs]).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------- library record
class LibraryText(_Model):
    lang: str
    text: str
    source: str


class LibraryValueSet(_Model):
    id: str
    sha: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    terminology_version: str | None = None


class LexiconRecall(_Model):
    n_judged: int = Field(ge=0)
    point: float = Field(ge=0, le=1)
    lower95: float = Field(ge=0, le=1)
    strata: dict[str, float] = Field(default_factory=dict)
    suite_run: str = Field(min_length=1, description="the eval run that measured it (DM-11)")
    zero_hit_exclusion_allowed: bool = False


class ComputabilityPoint(_Model):
    snapshot: str
    scope: str
    score: float = Field(ge=0, le=1)


class PrecisionPoint(_Model):
    period: str
    ppv_strong: float = Field(ge=0, le=1)
    n: int = Field(ge=0)


class LibraryApproval(_Model):
    gate: str
    approval: str


class CriterionLibraryRecord(_Model):
    """An approved, reusable criterion (§6.3). Holds no patient data: ``data_class`` is always D1 (DM-11)."""

    schema_version: Literal["1.0.0"] = LIBRARY_SCHEMA_VERSION
    lib_id: str = Field(pattern=r"^cl_[0-9A-Z]{26}$")
    canonical_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: Literal["draft", "approved", "deprecated"] = "draft"
    kind: Literal["inclusion", "exclusion", "renewal", "documentation"]
    class_: Literal["structured", "note", "human", "mixed"] = Field(alias="class")
    ir: CriterionIRv3
    texts: list[LibraryText] = Field(default_factory=list)
    valuesets: list[LibraryValueSet] = Field(default_factory=list)
    lexicon_keys: list[str] = Field(default_factory=list)
    note_question: NoteQuestion | None = None
    lexicon_recall: LexiconRecall | None = None
    computability_history: list[ComputabilityPoint] = Field(default_factory=list)
    precision_history: list[PrecisionPoint] = Field(default_factory=list)
    recall_ledger: str | None = None
    used_by: list[str] = Field(default_factory=list)
    seed_source: Literal["chia", "ctgov", "site"]
    approved: LibraryApproval | None = None
    supersedes: str | None = None
    data_class: Literal["D1"] = "D1"

    @model_validator(mode="after")
    def _consistent(self) -> CriterionLibraryRecord:
        if self.kind != self.ir.kind or self.class_ != self.ir.class_:
            raise ValueError("kind and class must match the IR")
        if self.status == "approved" and self.approved is None:
            raise ValueError("an approved record names its gate and approval")
        return self


# ------------------------------------------------------------------------------------------------- JSON Schema
def _schema(model: type[BaseModel], name: str, title: str, version: str, description: str) -> dict[str, Any]:
    body = model.model_json_schema(by_alias=True, mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_BASE}{name}.schema.json",
        **{k: v for k, v in body.items() if k not in ("title", "description")},
        "title": title,
        "description": f"{description} Schema version {version}. GENERATED from libs/tb_contracts/criterion_ir.py.",
    }


def json_schemas() -> dict[str, dict[str, Any]]:
    """File name -> generated JSON Schema 2020-12 for the v4 contracts defined here."""
    return {
        "criterion_ir.schema.json": _schema(
            CriterionIRv3, "criterion_ir", "CriterionIRv3", IR_VERSION, "One eligibility criterion (spec v4 §6.2)."
        ),
        "criterion_library_record.schema.json": _schema(
            CriterionLibraryRecord,
            "criterion_library_record",
            "CriterionLibraryRecord",
            LIBRARY_SCHEMA_VERSION,
            "An approved, reusable criterion (spec v4 §6.3).",
        ),
    }


def render_schema(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tb_contracts.criterion_ir")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    stale = []
    for fname, doc in json_schemas().items():
        path = SCHEMA_DIR / fname
        text = render_schema(doc)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(fname)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if stale:
        print(f"stale v4 schemas: {', '.join(stale)} (run python -m tb_contracts.criterion_ir)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
