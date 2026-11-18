"""Card 10A-1 (review 15, finding 2.3.1; plan 10 Track A): a negated inclusion never compiles as its opposite.

The P2b launch stored two coded inclusions whose line negates what their logic asks: ``SM3NCT00002897-INC-03``
"PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy" compiled to ``any of VS_CHEMOTHERAPY``
(structured), and ``SM3NCT00256529-INC-03`` "No significant cardiopulmonary disease, or other contraindication to
EGD" the same way (mixed). An inclusion is met when its logic is true, so once the code list loads the first would
exclude every patient who never had chemotherapy, the eligible ones. The compiler never compared a coded
inclusion's logic with its line. Now an inclusion whose logic asks the presence of a concept that a negation in its
line governs (``negation_scope``) is held for a person (``negated_inclusion_presence``): never run, it answers
unknown, and unknown never excludes. The same holds for an approved inclusion an incremental compile reuses.

The cases are the committed synthetic table ``tests/fixtures/negated_inclusion/lines.json`` (three languages; the
review lines, this card's own, and lines written after the rule was tuned, ``source: fresh``). Public protocol text
and synthetic lines; no patients.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.semantics import FILTERED, JUDGED
from criteria_compiler.terminology.mapper import Terminology
from doc_parser.parser import parse
from tb_contracts import Atom, LlmExtractOutput

from tests.unit.test_compiler_service import PDF, _approve, _compile, _decisions, env  # noqa: F401 (env: a fixture)

FLAG = "negated_inclusion_presence"
ROWS: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/negated_inclusion/lines.json").read_text(encoding="utf-8")
)["rows"]
CHEMO = {"domain": "procedure", "quantifier": "any", "concept": "chemotherapy"}  # VS_CHEMOTHERAPY once compiled
CHEMO_CAND = [{"domain": "procedure", "name": "chemotherapy", "synonyms": ["化学療法", "化學治療"]}]
_TERM: list[Terminology] = []


def _term() -> Terminology:
    """One empty terminology for the module (each takes about a second to build; the table runs hundreds of lines)."""
    if not _TERM:
        _TERM.append(Terminology())
    return _TERM[0]


def _logic(row: dict[str, Any]) -> dict[str, Any]:
    atom = {"domain": row["domain"], "concept": row["concept"]}
    if row["logic"] == "value":  # a bound read off the latest result ("no greater than 1.5 mg/dL")
        return {**atom, "quantifier": "latest", "value": {"op": "<=", "num": 2}}
    return {**atom, "quantifier": "any"}


def _cand(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"domain": row["domain"], "name": row["concept"], "synonyms": row["synonyms"]}]


def _post(crits: list[dict[str, Any]]) -> Any:
    return pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": crits}), _term(), "1.0.0")


def _one(text: str, logic: dict[str, Any], kind: str = "inclusion", cls: str = "structured",
         concepts: list[dict[str, Any]] | None = None, question: str | None = None) -> Any:  # fmt: skip
    crit: dict[str, Any] = {"kind": kind, "class": cls, "text": text, "logic": logic,
                            "concept_candidates": concepts if concepts is not None else CHEMO_CAND}  # fmt: skip
    if question:
        crit["note_question"] = question
    (out,) = _post([crit]).criteria
    return out


def _held(x: Any) -> None:
    assert x.class_ == "human" and x.human_question, (x.class_, x.text)
    assert FLAG in (x.flags or []), x.flags
    assert getattr(x.logic, "valueset", None) == "NONE"  # the presence logic is never run


def test_the_two_p2b_lines_are_held() -> None:
    _held(_one("PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy", CHEMO))
    _held(_one("No significant cardiopulmonary disease, or other contraindication to EGD",
               {"domain": "condition", "quantifier": "any", "concept": "cardiopulmonary disease"},
               cls="mixed", concepts=[{"domain": "condition", "name": "cardiopulmonary disease"}],
               question="Does the patient have significant cardiopulmonary disease?"))  # fmt: skip


@pytest.mark.parametrize("cls", ["structured", "mixed"])
@pytest.mark.parametrize("row", ROWS, ids=[f"{r['source']}-{r['lang']}-{i}" for i, r in enumerate(ROWS)])
def test_property_each_line_of_the_table_is_held_or_runs_as_expected(row: dict[str, Any], cls: str) -> None:
    q = "Does the patient meet it?" if cls == "mixed" else None
    x = _one(row["text"], _logic(row), cls=cls, concepts=_cand(row), question=q)
    if row["expect"] == "held":
        _held(x)
    else:
        assert FLAG not in (x.flags or []), (row["text"], x.class_, x.flags)


def test_the_table_counts() -> None:
    """The figures the pull request reports: every negated line held, every line that should run runs."""
    out = _post([{"kind": "inclusion", "class": "structured", "text": r["text"], "logic": _logic(r),
                  "concept_candidates": _cand(r)} for r in ROWS]).criteria  # fmt: skip
    held = [r for r, x in zip(ROWS, out, strict=True) if r["expect"] == "held" and x.class_ == "human"]
    over = [r["text"] for r, x in zip(ROWS, out, strict=True) if r["expect"] == "runs" and x.class_ == "human"]
    assert len(held) == sum(r["expect"] == "held" for r in ROWS) and not over, over
    assert {r["lang"] for r in ROWS} == {"en", "ja", "zh"} and len(ROWS) >= 150


NEGATED = [r for r in ROWS if r["expect"] == "held" and r["logic"] == "presence"]
AGE18 = {"domain": "demographic", "age": {"min": 18}}
PRESENCE: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
    lambda a: {"op": "and", "args": [AGE18, a]},
    lambda a: {"op": "not", "args": [{"op": "not", "args": [a]}]},
    lambda a: {**a, "quantifier": "all"},
]
ABSENCE: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
    lambda a: {**a, "quantifier": "none"},
    lambda a: {"op": "not", "args": [a]},
    lambda a: {"op": "and", "args": [AGE18, {**a, "quantifier": "none"}]},
]


def _shaped(shape: Callable[[dict[str, Any]], dict[str, Any]]) -> list[Any]:
    crits = [{"kind": "inclusion", "class": "structured", "text": r["text"], "logic": shape(_logic(r)),
              "concept_candidates": _cand(r)} for r in NEGATED]  # fmt: skip
    return list(_post(crits).criteria)


@pytest.mark.parametrize("shape", range(len(PRESENCE)))
def test_property_presence_inside_other_logic_is_held(shape: int) -> None:
    out = _shaped(PRESENCE[shape])
    assert not [x.text for x in out if x.class_ != "human" or FLAG not in (x.flags or [])]


@pytest.mark.parametrize("shape", range(len(ABSENCE)))
def test_property_a_negated_line_already_coded_negative_runs(shape: int) -> None:
    assert not [x.text for x in _shaped(ABSENCE[shape]) if FLAG in (x.flags or [])]


def test_an_age_or_sex_alone_and_an_exclusion_are_not_this_rule() -> None:
    age = _one("No younger than 18 years", {"domain": "demographic", "age": {"min": 18}}, concepts=[])
    assert age.class_ in FILTERED and FLAG not in (age.flags or [])
    exc = _one("No prior chemotherapy", CHEMO, kind="exclusion")  # an exclusion's own rules decide it, not this one
    assert FLAG not in (exc.flags or [])


def test_a_negated_mixed_line_is_held_before_another_rule_hands_it_to_the_notes() -> None:
    """The age-at-onset rule hands a mixed line to the notes; a negated inclusion must not get there first, where a
    model would answer the presence question."""
    x = _one("No chemotherapy before age 18", {**CHEMO, "age": {"max": 18}}, cls="mixed",
             question="Did the patient receive chemotherapy before age 18?")  # fmt: skip
    _held(x)


def test_the_reason_is_said_to_the_reviewer() -> None:
    post = _post([{"kind": "inclusion", "class": "structured", "text": "No prior chemotherapy", "logic": CHEMO,
                   "concept_candidates": CHEMO_CAND}])  # fmt: skip
    assert any("T-INC-01" in w and "negates" in w and "person" in w for w in post.warnings), post.warnings


def test_held_it_answers_unknown_and_never_excludes() -> None:
    """Unknown never excludes: the held line is neither compiled for S1 nor asked of a model; it reaches the engine
    as a person's question, which never excludes (``test_safety_properties.py``, P1's tier table)."""
    x = _one("No prior chemotherapy", CHEMO)
    assert x.class_ == "human" and x.class_ not in FILTERED and x.class_ not in JUDGED
    assert isinstance(x.logic, Atom) and x.logic.domain == "demographic" and x.logic.valueset == "NONE"
    assert x.logic.age is None and x.logic.sex is None


def test_an_approved_negated_inclusion_reused_by_an_incremental_compile_goes_to_a_person(
    env: dict[str, Any],  # noqa: F811 (the compiler-service fixture)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An approved version compiled before this card (the rule off) has "No history of gout." as ``any of VS_GOUT``.
    The next compile reuses the approved line verbatim and skips postprocess: the rule must still see it, flag it,
    say so, and give it to a person, never run it."""
    doc = parse(PDF.read_bytes(), PDF.name)
    inc = list(doc.ie_block.inclusion)
    inc[1] = "No history of gout."
    doc = doc.model_copy(update={"ie_block": doc.ie_block.model_copy(update={"inclusion": inc})})
    env["store"].put("attachments/J/neg.json", c.dump_json(doc).encode())
    real = pp.postprocess

    def before_this_card(*a: Any, **kw: Any) -> Any:  # the compiler as it was: the line kept as presence
        out = real(*a, **kw)
        for i, x in enumerate(out.criteria):
            if x.text == "No history of gout.":
                gout = Atom(domain="condition", valueset="VS_GOUT", quantifier="any")
                out.criteria[i] = x.model_copy(update={"class_": "structured", "logic": gout, "flags": []})
        return out

    monkeypatch.setattr("criteria_compiler.ir_extract.postprocess.negated_presence", lambda *a, **kw: False)
    monkeypatch.setattr("criteria_compiler.service.postprocess", before_this_card)
    res = _compile(env, key="attachments/J/neg.json")
    first = next(x for x in res.criteria if x.text == "No history of gout.")
    assert first.class_ == "structured"  # the old compiler's mistake, approved as it was
    assert _approve(env, _decisions(env["store"], res.review_xlsx_key)).status == "approved"

    monkeypatch.undo()
    res2 = _compile(env, key="attachments/J/neg.json")
    again = next(x for x in res2.criteria if x.text == "No history of gout.")
    assert again.id == first.id  # the approved criterion, reused
    assert again.class_ == "human" and again.human_question and FLAG in (again.flags or [])
    assert isinstance(again.logic, Atom) and again.logic.valueset == "NONE"
    assert any(first.id in w and "approved before" in w for w in res2.warnings or []), res2.warnings
