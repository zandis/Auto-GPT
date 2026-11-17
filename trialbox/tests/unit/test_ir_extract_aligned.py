"""Red of lane G's frozen-commit run (#639, 2026-11-16): "model returned N criteria for M lines" (HTTP 422), twice, a
hard refusal of the whole compile (D-912).

Each answer is matched to its line by the line's text (the prompt has the model copy it verbatim), in order:

* a line the model left out is asked once more, alone; answered then, the compile goes on as if nothing happened;
* a line still without an answer, or one the model answered twice (it split the line), is kept as a person's check,
  flagged ``not_extracted`` or ``split_by_model`` with ``needs_review``, and said in the review's warnings;
* a count that agrees but an answer in the model's own words is read by position, as before.

Nothing is dropped or merged in silence. (Naming the mismatch to the model in the retry would need a new prompt
version: the template shows the lines only, as data.) Synthetic protocols; a scripted model client.
"""

from __future__ import annotations

from typing import Any

from criteria_compiler import service
from criteria_compiler.ir_extract.postprocess import postprocess
from criteria_compiler.service import flag_unread
from criteria_compiler.terminology.mapper import Terminology
from tb_common.llm import LlmResult

LINES = [
    {"text": "Age 18 years or older", "kind": "inclusion", "source_ref": "Inclusion #1"},
    {"text": "Signed consent", "kind": "inclusion", "source_ref": "Inclusion #2"},
    {"text": "Active tuberculosis", "kind": "exclusion", "source_ref": "Exclusion #1"},
    {"text": "Pregnancy or breastfeeding", "kind": "exclusion", "source_ref": "Exclusion #2"},
]


def _crit(ln: dict[str, Any], text: str | None = None) -> dict[str, Any]:
    return {"kind": ln["kind"], "class": "human", "text": text or ln["text"], "human_question": "?",
            "concept_candidates": []}  # fmt: skip


class _Model:
    """Answers each call from ``script`` (a list of functions of the lines asked), recording what was asked."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.asked: list[list[str]] = []

    def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
        lines = variables["criteria"]
        self.asked.append([ln["text"] for ln in lines])
        fn = self.script.pop(0) if self.script else (lambda ls: [_crit(x) for x in ls])
        return LlmResult({"criteria": fn(lines)}, prompt_id, 3, "m", "local", "i", "o", 1, 1, 1)


def _run(model: _Model) -> tuple[Any, dict[int, str]]:
    comp = object.__new__(service.Compiler)
    comp.d = type("D", (), {"llm": model, "mrn_regex": None})()
    out, _guard, unread, _calls = comp._extract("J", "T", "en", LINES)
    return out, unread


def test_a_line_left_out_is_asked_again_alone() -> None:
    model = _Model(lambda ls: [_crit(x) for x in ls if x["text"] != "Signed consent"])
    out, unread = _run(model)
    assert model.asked[1] == ["Signed consent"]  # the retry asks that line only
    assert [c.text for c in out.criteria] == [ln["text"] for ln in LINES] and unread == {}


def test_a_line_still_left_out_or_split_is_a_flagged_persons_check() -> None:
    def first(ls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = [_crit(x) for x in ls if x["text"] != "Signed consent"]
        return [*out, _crit(LINES[3])]  # "Pregnancy or breastfeeding" twice: the model split it

    model = _Model(first, lambda ls: [])  # the retry answers nothing either
    out, unread = _run(model)
    assert unread == {1: "not_extracted", 3: "split_by_model"}
    assert [c.text for c in out.criteria] == [ln["text"] for ln in LINES]  # every line, in order, once
    assert out.criteria[1].class_ == "human" and "no criterion" in str(out.criteria[1].human_question)
    assert out.criteria[3].class_ == "human" and "more than one" in str(out.criteria[3].human_question)
    post = postprocess("T", out, Terminology(), "1.0.0")
    warnings: list[str] = []
    flagged = flag_unread(post.criteria, unread, warnings)
    assert {"not_extracted", "needs_review"} <= set(flagged[1].flags or [])
    assert {"split_by_model", "needs_review"} <= set(flagged[3].flags or [])
    assert len(warnings) == 2 and all("person" in w for w in warnings)
    assert not flagged[0].flags or "not_extracted" not in flagged[0].flags


def test_an_answer_in_the_models_own_words_is_read_by_position_when_the_count_agrees() -> None:
    model = _Model(lambda ls: [_crit(x, f"Reworded: {x['text']}") for x in ls])
    out, unread = _run(model)
    assert unread == {} and len(model.asked) == 1
    assert [c.text for c in out.criteria] == [f"Reworded: {ln['text']}" for ln in LINES]
