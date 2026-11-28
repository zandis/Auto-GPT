"""The verifier demotes, it never vetoes a keep (BENCH-2 §2, integrator ruling 2026-11-28).

On the product's pair (``NoteJudge.judge_excerpts(..., demote=True)``: SCREEN on the cascade through
``OrchestratorJudge`` and SCREEN/NAV/CASE/MICROBATCH on v1), a decided judge answer the verifier does not confirm:

* stands when it KEEPS the patient (an inclusion met, an exclusion stated absent), flagged ``second_opinion_differs``
  with both opinions on the page;
* stays ``unknown`` / ``disagree`` when it would not keep the patient (unchanged: a person looks, never an exclusion).

A verifier that did not answer, or the judge's own model answering twice, is no opinion: unchanged. Tools that measure
the pair (qualify, bake-off, injection) keep the plain rule (``demote`` off by default).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from console.studies import second_opinion_differs, worklist_sorted
from orchestrator.scenarios.evaluate import NoteJudge, note_verdict, tier
from orchestrator.scenarios.screen_cascade import OrchestratorJudge
from tb_common.llm import LlmError, LlmResult
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

from tests.judge_kit import ruleset

QUOTE = "No history of HIV; HIV test negative in 2025."
EXCERPTS = [{"date": "2026-01-10", "note_type": "progress", "text": QUOTE, "did": "D1"}]
IDX = date(2026, 2, 1)
_n = 0


class Model:
    """One model of the pair answering every judge call with one verdict (or down)."""

    def __init__(self, verdict: str, error: bool = False) -> None:
        global _n
        _n += 1
        self.model = f"m{_n}-{verdict}"
        self.verdict, self.error = verdict, error

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        if self.error:
            raise LlmError("model down")
        cert = {"pass": "affirmed", "fail": "negated"}.get(self.verdict)
        data = {"verdict": self.verdict, "reason": "r", "confidence": 0.9,
                "quote": QUOTE if cert else None, "quote_date": "2026-01-10" if cert else None,
                "certainty": cert, "experiencer": "patient" if cert else None, "time": "current" if cert else None}  # fmt: skip
        return LlmResult(data, prompt_id, 6, self.model, "local", "i" * 64, "o" * 64, 100, 20, 1)


def crit(kind: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": f"T-{kind[:3].upper()}-01", "ruleset": "T", "text": "Known HIV infection", "kind": kind,
         "class": "note", "note_question": "Does the patient have HIV infection?",
         "logic": {"domain": "condition", "valueset": "VS_T"}}
    )  # fmt: skip


def ask(kind: str, first: str, second: str, *, demote: bool = True, down: bool = False) -> Any:
    c = crit(kind)
    nj = NoteJudge(lake=None, llm=Model(first), verifier=Model(second, error=down))  # type: ignore[arg-type]
    r = nj.judge_excerpts(c.text, c.note_question or c.text, IDX, EXCERPTS, demote=demote)
    return c, note_verdict(c, r, pair=True)


@pytest.mark.parametrize(("kind", "first", "second", "verdict"), [
    ("inclusion", "pass", "fail", "pass"),  # met, the verifier says not met: met stands, flagged
    ("inclusion", "pass", "unknown", "pass"),
    ("exclusion", "fail", "pass", "pass"),  # stated absent, the verifier says present: the patient stays, flagged
])  # fmt: skip
def test_a_keep_the_verifier_does_not_confirm_stands_flagged(kind: str, first: str, second: str, verdict: str) -> None:
    _, v = ask(kind, first, second)
    assert v.verdict == verdict
    assert v.evidence.reason == "second_opinion_differs"
    assert v.evidence.quote == QUOTE and v.evidence.resource_refs == ["DocumentReference/D1"]
    assert [o.role for o in v.evidence.opinions or []] == ["judge", "verifier"]
    assert v.affirmed is None  # a disputed answer never affirms an exclusion


@pytest.mark.parametrize(("kind", "first", "second"), [
    ("exclusion", "pass", "fail"),  # present by the judge only: never an exclusion
    ("exclusion", "pass", "unknown"),
    ("inclusion", "fail", "pass"),  # not met by the judge only: a person looks, as before
])  # fmt: skip
def test_a_disputed_answer_that_does_not_keep_is_unknown_as_before(kind: str, first: str, second: str) -> None:
    c, v = ask(kind, first, second)
    assert v.verdict == "unknown" and v.evidence.reason == "disagree"
    assert [o.role for o in v.evidence.opinions or []] == ["judge", "verifier"]
    rs: Ruleset = ruleset([c])
    assert tier(rs, [v], 0.75, note_block=True)[0] != "excluded"


def test_no_opinion_is_no_demotion() -> None:
    _, v = ask("inclusion", "pass", "pass", down=True)
    assert v.verdict == "unknown" and v.evidence.reason == "model_down"


def test_measuring_tools_keep_the_plain_rule() -> None:
    _, v = ask("inclusion", "pass", "fail", demote=False)
    assert v.verdict == "unknown" and v.evidence.reason == "disagree"


def test_a_flagged_keep_sorts_below_the_unflagged_of_its_tier() -> None:
    flagged = {"evidence": {"reason": "second_opinion_differs"}}
    rows = [{"pid": p, "visit": None, "visit_text": "", "tier": "high", "fit": None, "criteria": c}
            for p, c in (("a", [flagged]), ("b", [{"evidence": {"reason": "coded"}}]))]  # fmt: skip
    assert [r["pid"] for r in worklist_sorted(rows, "all")] == ["b", "a"]
    assert second_opinion_differs([flagged]) and not second_opinion_differs([])


def test_screen_asks_the_product_rule() -> None:
    c = crit("exclusion")
    oj = OrchestratorJudge(lake=None, llm=Model("fail"), verifier=Model("pass"))  # type: ignore[arg-type]
    reply = oj.judge(role="judge", criterion_text=c.text, note_question=c.note_question or c.text, index_date=IDX,
                     excerpts=EXCERPTS, study_id="T", data_class="D3", step_id="s", purpose="screening")  # fmt: skip
    # the pair's reply is the plain rule's (every reader of it unchanged); the judge's own answer rides along
    assert reply.verdict == "unknown" and reply.reason == "disagree" and len(reply.opinions) == 2
    assert reply.kept is not None and reply.kept.verdict == "fail" and reply.kept.affirmed is False
